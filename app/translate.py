"""Model-assisted Simplified Chinese glosses, batched and validated before writing."""
import logging
import re

log = logging.getLogger('vocabulary.translate')

CJK = re.compile(r'[\u4e00-\u9fff]')

class TranslationService:
    """Fill empty definition_zh values with a model gloss; user text is kept unless overwrite is asked."""

    def __init__(self,repository,model,batch_size=20):
        self.repo = repository
        self.model = model
        self.batch_size = batch_size

    @property
    def available(self):
        return callable(getattr(self.model,'translate',None))

    def _clean(self,batch,answer):
        wanted = {entry['word'].lower() for entry in batch}
        result = {}
        for word,gloss in (answer or {}).items():
            key = str(word).strip().lower()
            text = str(gloss or '').strip()
            if key not in wanted or not text or len(text)>40 or not CJK.search(text):
                continue
            result[key] = text
        return result

    def _entries(self,words,overwrite):
        if not words:
            return self.repo.missing_translations() if not overwrite else []
        if overwrite:
            known = self.repo.lookup(words)
            return [{'word':word,'definition_en':row.get('definition_en')} for word,row in known.items()]
        return self.repo.missing_translations(words)

    async def fill(self,words=None,limit=None,overwrite=False):
        """Translate words without a Chinese meaning; with overwrite, revisit the named words."""
        if not self.available:
            return {'requested':0,'updated':0,'skipped':0,'failed':0,'error':'translation_model_unavailable'}
        if overwrite and not words:
            return {'requested':0,'updated':0,'skipped':0,'failed':0,'error':'overwrite_needs_words'}
        entries = self._entries(words,overwrite)
        if limit:
            entries = entries[:limit]
        if not entries:
            return {'requested':0,'updated':0,'skipped':0,'failed':0}
        updated,failed,skipped,error = 0,0,0,None
        for offset in range(0,len(entries),self.batch_size):
            batch = entries[offset:offset+self.batch_size]
            try:
                answer = await self.model.translate(batch)
            except Exception as exc:
                failed += len(batch)
                error = type(exc).__name__
                log.warning('Translation batch failed (%s): %s',type(exc).__name__,str(exc)[:200])
                continue
            cleaned = self._clean(batch,answer)
            skipped += len(batch)-len(cleaned)
            if cleaned:
                updated += self.repo.update_translations(cleaned,overwrite=overwrite)
        result = {'requested':len(entries),'updated':updated,'skipped':skipped,'failed':failed}
        if error:
            result['error'] = error
        return result
