"""Optional, bounded metadata enrichment; provider errors never prevent ingestion."""
import asyncio
from urllib.parse import quote
import httpx

# spaCy tag -> dictionaryapi.dev partOfSpeech, so a noun does not inherit an adjective sense.
POS_ALIASES = {'noun':'noun','verb':'verb','adj':'adjective','adv':'adverb','prep':'preposition'}
REQUEST_INTERVAL_SECONDS = 0.4
MAX_RATE_LIMIT_RETRIES = 2
_request_lock = asyncio.Lock()
_next_request_at = 0.0


async def _get_dictionary_response(client, word):
    """Serialize and pace calls so the public dictionary API does not rate-limit bulk imports."""
    global _next_request_at
    url = 'https://api.dictionaryapi.dev/api/v2/entries/en/' + quote(word, safe='')
    loop = asyncio.get_running_loop()
    async with _request_lock:
        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            delay = _next_request_at - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            _next_request_at = loop.time() + REQUEST_INTERVAL_SECONDS
            response = await client.get(url)
            if response.status_code != 429 or attempt == MAX_RATE_LIMIT_RETRIES:
                return response
            retry_after = response.headers.get('Retry-After')
            try:
                backoff = max(float(retry_after), 0.5) if retry_after else 2 ** attempt
            except ValueError:
                backoff = 2 ** attempt
            await asyncio.sleep(min(backoff, 15))

def _ordered_meanings(meanings,entry):
    wanted = POS_ALIASES.get((entry.get('part_of_speech') or ['other'])[0])
    if not wanted:
        return meanings
    matching = [meaning for meaning in meanings if meaning.get('partOfSpeech')==wanted]
    others = [meaning for meaning in meanings if meaning.get('partOfSpeech')!=wanted]
    return matching+others

async def enrich_entries(entries):
    async with httpx.AsyncClient(timeout=8,follow_redirects=False) as client:
        async def enrich(entry):
            try:
                response = await _get_dictionary_response(client, entry['word'])
                response.raise_for_status()
                data = response.json()[0]
                metadata = {}
                phonetics = data.get('phonetics',[])
                metadata['phonetic'] = next((p['text'] for p in phonetics if p.get('text')),None)
                metadata['audio_url'] = next((p['audio'] for p in phonetics if p.get('audio','').startswith('https://')),None)
                meanings = _ordered_meanings(data.get('meanings',[]),entry)
                definitions = [d for meaning in meanings for d in meaning.get('definitions',[])]
                metadata['definition_en'] = next((d['definition'] for d in definitions if d.get('definition')),None)
                if not entry.get('example_sentences'):
                    metadata['example_sentences'] = [d['example'] for d in definitions if d.get('example')][:3]
                return {**entry,**{k:v for k,v in metadata.items() if v}},None
            except (httpx.HTTPError,ValueError,KeyError,IndexError,TypeError):
                return entry,{'word':entry['word'],'reason':'metadata_fetch_failed'}
        results = await asyncio.gather(*(enrich(entry) for entry in entries))
    return [entry for entry,_ in results],[warning for _,warning in results if warning]
