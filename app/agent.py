"""Bounded LangChain tool calling over real MCP sessions and deterministic scope."""
import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage
from .analysis import apply_filter
from .config import ROOT
from .deepseek import ModelProtocolError, ModelUnavailable
from .repository import stamp
from .schemas import Filter
from .translate import TranslationService

log = logging.getLogger('vocabulary.agent')

PRESETS = {
    'top20':{'top_n':20},'new_only':{'exclude_existing':True},
    'verb_only':{'pos_include':['verb']},'freq_2plus':{'min_occurrences':2},
    'cet6_up':{'difficulty':'cet6+'},
}

def event(kind,data):
    return f'event: {kind}\ndata: {json.dumps(data,ensure_ascii=True)}\n\n'

@dataclass
class PendingScope:
    pool: object
    source_ref: str
    thread_id: str
    filter: Filter
    created: float
    rounds: int = 1

class VocabularyAgent:
    def __init__(self,repository,analyzer,model,gateway,settings,translations=None):
        self.repo,self.analyzer,self.model,self.gateway,self.settings = repository,analyzer,model,gateway,settings
        self.translations = translations or TranslationService(repository,model)
        self.pending = {}
        self.locks = {}
        self.skills = '\n\n'.join((ROOT/'app'/'skills'/name).read_text(encoding='utf-8') for name in ('read.md','write.md','scope.md'))

    def cleanup(self):
        cutoff = time.monotonic()-self.settings.session_ttl_seconds
        for key in list(self.pending):
            if self.pending[key].created<cutoff:
                del self.pending[key]
        if len(self.pending)>=200:
            raise ValueError('Too many pending sessions; finish a scope selection first')

    async def _tool_call(self,name,arguments,traces):
        # The model selects the tool; code owns every executable argument.
        label = 'READ_ONLY_ACTION' if name=='read_vocabulary' else 'VERIFIED_INGESTION'
        messages = [SystemMessage(content=self.skills+'\nSelect the required tool now. Do not calculate counts. Max eight attempts.'),
                    HumanMessage(content=label+'\n'+json.dumps({'tool':name,'arguments':arguments},ensure_ascii=True))]
        for attempt in range(8):
            response = await self.model.choose_tool(messages,[self.gateway.tools[name]])
            calls = getattr(response,'tool_calls',[]) or []
            if len(calls)==1 and calls[0]['name']==name:
                result = await self.gateway.invoke(name,arguments)
                traces.append({'tool_name':name,'payload':{'arguments':arguments,'result':result}})
                return result
            # Do not append unmatched tool calls without ToolMessages to the model transcript.
            messages.append(HumanMessage(content='Call exactly '+name+' once; no other tool is permitted.'))
        raise ValueError('Agent reached the maximum of eight tool-call attempts')

    async def stream(self,request):
        lock = self.locks.setdefault(request.thread_id,asyncio.Lock())
        async with lock:
            try:
                self.cleanup()
                yield event('step',{'stage':'analysis','label':'Analyzing text with spaCy'})
                text = request.text if request.text is not None else request.user_input
                pool = await asyncio.to_thread(self.analyzer.analyze,text,{})
                decision = await self.model.decide(request.user_input,{**pool.as_dict(),'library':self.repo.stats()})
                # The second field accepts either an English article or a direct natural-language query.
                # If it has no English tokens and the instruction is still the default import label,
                # classify the actual query instead of forcing an ingest path.
                default_instruction = 'import the vocabulary in this article'
                if request.text and not pool.candidates and request.user_input.strip().lower() == default_instruction:
                    decision = await self.model.decide(request.text,{'non_english_input':True,'library':self.repo.stats()})
                if decision.intent=='clarify':
                    yield event('clarify',{'question':decision.question or 'Paste an English article or ask about your vocabulary.'})
                    return
                traces = [{'role':'agent','tool_name':None,'payload':{'decision':decision.model_dump()}}]
                if decision.intent in {'lookup','search','top','log'}:
                    mode = decision.intent
                    limit = decision.filter.top_n or decision.limit
                    if mode=='lookup':
                        payload = {'words':decision.lookup_words}
                    elif mode=='search':
                        payload = {'query':decision.search_query or request.user_input,'limit':limit}
                    else:
                        payload = {'limit':limit,'window':decision.window}
                    yield event('step',{'stage':'tool_call','tool':'read_vocabulary','label':'Reading vocabulary'})
                    result = await self._tool_call('read_vocabulary',{'mode':mode,'payload':payload},traces)
                    yield event('step',{'stage':'tool_result','tool':'read_vocabulary','summary':'Read completed'})
                    async for item in self._finish(mode,result,None,None,traces,None):
                        yield item
                    return
                if not pool.candidates:
                    yield event('clarify',{'question':'No English vocabulary was found. Paste an English article, or ask a direct vocabulary question in the instruction or text box.'})
                    return
                matches = self.repo.lookup(pool.candidates)
                pool.existing_set = set(matches)
                pool.difficulty_by_word = {w:r.get('difficulty') for w,r in matches.items()}
                source_ref = request.source_id or 'article_'+uuid.uuid4().hex
                explicit = decision.filter.model_dump()!=Filter().model_dump()
                if not explicit and pool.unique_words>20 and (pool.unique_words>=50 or len(matches)/pool.unique_words>.6):
                    confirm_id = 'scp_'+uuid.uuid4().hex
                    self.pending[confirm_id] = PendingScope(pool,source_ref,request.thread_id,decision.filter,time.monotonic())
                    yield event('scope_confirm',{'type':'scope_confirm','data':self._scope_payload(confirm_id)})
                    return
                async for item in self._ingest(pool,decision.filter,source_ref):
                    yield item
            except ModelUnavailable as exc:
                yield event('error',{'code':'model_unavailable','message':str(exc)})
            except Exception as exc:
                yield event('error',{'code':'agent_failed','message':self._safe_error(exc)})

    def _safe_error(self,exc):
        # Log the real exception; the SSE payload stays short but actionable.
        log.exception('Agent request failed (%s)',type(exc).__name__)
        if isinstance(exc,(ValueError,KeyError)):
            return str(exc)[:400]
        if isinstance(exc,ModelProtocolError):
            return str(exc)[:400]
        name, text = type(exc).__name__.lower(), str(exc).lower()
        if 'timeout' in name or 'timed out' in text:
            return ('The model call timed out. Retry with the same source_id; if it keeps failing, '
                    'check network or proxy access to DEEPSEEK_API_BASE.')
        if any(token in name for token in ('connect','proxy','transfer','protocol')):
            return ('The model endpoint could not be reached. Check the network, the proxy settings, and '
                    'DEEPSEEK_API_BASE, then retry with the same source_id.')
        return 'Agent request failed. Check model connectivity and retry using the same source_id.'

    def _scope_payload(self,confirm_id,message=None):
        pending = self.pending[confirm_id]
        pool = pending.pool
        return {'confirm_id':confirm_id,'message':message or 'Choose which vocabulary to import.',
                'pool_summary':pool.as_dict(),
                'presets':[{'id':key,'label':label,'filter':spec} for key,label,spec in [
                    ('top20','Top 20 by frequency',PRESETS['top20']),('new_only','New words only',PRESETS['new_only']),
                    ('verb_only','Verbs only',PRESETS['verb_only']),('freq_2plus','At least two occurrences',PRESETS['freq_2plus']),
                    ('cet6_up','CET6 and above (verified labels only)',PRESETS['cet6_up'])]],
                'advanced':{'top_n':{'type':'slider','min':5,'max':100,'default':20},
                            'exclude_existing':{'type':'toggle','default':False},
                            'pos_include':{'type':'multiselect','options':['noun','verb','adj','adv','prep','other']},
                            'difficulty':{'type':'select','options':['all','cet4','cet6','toefl','gre']},
                            'min_occurrences':{'type':'slider','min':1,'max':5,'default':1}},
                'allow_free_text':True,'round':pending.rounds,
                'preview':[{'word':w,'count':c,'pos':pool.pos_by_word[w],'exists':w in pool.existing_set} for w,c in pool.candidates.most_common(10)]}

    async def respond(self,request):
        async with self.locks.setdefault(request.thread_id,asyncio.Lock()):
            try:
                self.cleanup()
                pending = self.pending.get(request.confirm_id)
                if not pending or pending.thread_id!=request.thread_id:
                    yield event('error',{'code':'scope_expired','message':'Scope not found for this chat or expired.'})
                    return
                filter_spec = pending.filter.model_dump()
                ambiguous = not request.selection.preset_id and request.selection.filter is None and not request.free_text
                if request.selection.preset_id:
                    if request.selection.preset_id not in PRESETS:
                        raise ValueError('Unknown scope preset')
                    filter_spec.update(PRESETS[request.selection.preset_id])
                if request.selection.filter:
                    filter_spec.update(request.selection.filter.model_dump())
                if request.free_text:
                    decision = await self.model.decide(request.free_text,pending.pool.as_dict())
                    ambiguous = decision.intent=='clarify'
                    if not ambiguous:
                        filter_spec = decision.filter.model_dump()
                if ambiguous and pending.rounds<2:
                    pending.rounds += 1
                    yield event('scope_confirm',{'type':'scope_confirm','data':self._scope_payload(request.confirm_id,'Choose a preset or provide a specific filter.')})
                    return
                if ambiguous:
                    filter_spec = Filter(top_n=30).model_dump()
                try:
                    selected_filter = Filter.model_validate(filter_spec)
                    apply_filter(pending.pool,selected_filter.model_dump())
                except ValueError as exc:
                    if pending.rounds<2:
                        pending.rounds += 1
                        yield event('scope_confirm',{'type':'scope_confirm','data':self._scope_payload(request.confirm_id,str(exc))})
                        return
                    selected_filter = Filter(top_n=30)
                async for item in self._ingest(pending.pool,selected_filter,pending.source_ref):
                    yield item
                self.pending.pop(request.confirm_id,None)
            except Exception as exc:
                yield event('error',{'code':'scope_failed','message':self._safe_error(exc)})

    async def _ingest(self,pool,filter_spec,source_ref):
        entries = apply_filter(pool,filter_spec.model_dump())
        for entry in entries:
            entry['usage_contexts']=[source_ref]
        traces = []
        yield event('step',{'stage':'tool_call','tool':'write_vocabulary','label':'Importing selected vocabulary'})
        result = await self._tool_call('write_vocabulary',{'entries':entries,'context':source_ref},traces)
        yield event('step',{'stage':'tool_result','tool':'write_vocabulary','summary':f"Imported {result['success']} selected words"})
        translated = 0
        if self.settings.auto_translate and self.translations.available and result['success']:
            yield event('step',{'stage':'translation','label':'Adding Chinese meanings'})
            try:
                summary = await self.translations.fill([entry['word'] for entry in entries])
                translated = summary.get('updated',0)
                if summary.get('failed') or summary.get('error'):
                    traces.append({'tool_name':None,'payload':{'translation':summary}})
            except Exception as exc:
                log.warning('Automatic translation failed: %s',type(exc).__name__)
                traces.append({'tool_name':None,'payload':{'translation':{'error':type(exc).__name__}}})
        stats = {'tokens_processed':sum(pool.candidates.values()),'new_words':len(result['new_ids']),
                 'updated_words':len(result['updated_ids']),'skipped':pool.unique_words-len(entries),
                 'write_success':result['success'],'write_failed':result['failed'],'duplicates':result['duplicates'],
                 'translated_words':translated}
        async for item in self._finish('ingest_and_analyze',result,source_ref,stats,traces,filter_spec.model_dump()):
            yield item

    async def _finish(self,intent,result,source_ref,stats,traces,applied_filter):
        warnings = list(result.get('warnings',[]))
        try:
            prose = await self.model.summarize(intent,{k:v for k,v in result.items() if k not in {'new_entries','updated_entries'}})
            if not prose or re.search(r'\d',prose):
                prose = 'Vocabulary action completed.'
        except Exception:
            prose = 'Vocabulary action completed.'
            warnings.append({'reason':'summary_unavailable','word':''})
        # Authoritative numbers always come from code and are appended after the model prose.
        summary = prose
        if stats:
            summary += f" Imported {stats['write_success']} words: {stats['new_words']} new, {stats['updated_words']} updated; {stats['duplicates']} retries skipped."
        log_id = 'log_'+uuid.uuid4().hex
        self.repo.create_log(log_id,intent,source_ref,stats or {},summary,traces)
        highlights = {'applied_filter':applied_filter,'new_entries':result.get('new_entries',[]),
                      'updated_entries':result.get('updated_entries',[]),'filtered_out':stats['skipped'] if stats else 0}
        if intent in {'ingest','ingest_and_analyze'}:
            highlights['top_frequency']=self.repo.top()
        else:
            highlights.update(result)
            if intent in {'lookup','search'}:
                highlights['items']=[{'rank':index+1,'word':match.get('word'),
                                      'word_id':match.get('word_id'),
                                      'snippet':re.sub(r'</?b>','',str(match.get('snippet') or match.get('definition_en') or '')),
                                      'total_count':match.get('total_count')}
                                     for index,match in enumerate(result.get('matches',[]))]
        payload = {'intent':intent,'summary':summary,'stats':stats,'highlights':highlights,
                   'source':{'type':'text','ref':source_ref,'ingested_at':stamp()} if source_ref else None,
                   'log_id':log_id,'warnings':warnings,'question':None}
        yield event('token',{'text':summary})
        yield event('final',payload)
