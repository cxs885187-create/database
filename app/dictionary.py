"""Optional, bounded metadata enrichment; provider errors never prevent ingestion."""
import asyncio
from urllib.parse import quote
import httpx

# spaCy tag -> dictionaryapi.dev partOfSpeech, so a noun does not inherit an adjective sense.
POS_ALIASES = {'noun':'noun','verb':'verb','adj':'adjective','adv':'adverb','prep':'preposition'}

def _ordered_meanings(meanings,entry):
    wanted = POS_ALIASES.get((entry.get('part_of_speech') or ['other'])[0])
    if not wanted:
        return meanings
    matching = [meaning for meaning in meanings if meaning.get('partOfSpeech')==wanted]
    others = [meaning for meaning in meanings if meaning.get('partOfSpeech')!=wanted]
    return matching+others

async def enrich_entries(entries):
    semaphore = asyncio.Semaphore(4)
    async with httpx.AsyncClient(timeout=8,follow_redirects=False) as client:
        async def enrich(entry):
            async with semaphore:
                try:
                    response = await client.get('https://api.dictionaryapi.dev/api/v2/entries/en/'+quote(entry['word'],safe=''))
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
