"""Two stdio MCP processes: read-only database URI versus transactional writer."""
import argparse
import asyncio
from mcp.server.fastmcp import FastMCP
from .db import Database
from .repository import VocabularyRepository
from .dictionary import enrich_entries

def create_server(path,mode='read',dictionary_enabled=True):
    server = FastMCP('vocabulary-'+mode)
    repository = VocabularyRepository(Database(path,read_only=(mode=='read')))
    if mode=='read':
        @server.tool()
        def read_vocabulary(mode: str, payload: dict) -> dict:
            """Read vocabulary only. mode is lookup, top, or log. Never mutates storage."""
            if mode=='lookup':
                return {'matches':list(repository.lookup(payload.get('words',[])).values())}
            if mode=='top':
                return {'items':repository.top(max(1,min(int(payload.get('limit',20)),100)),payload.get('window','all'))}
            if mode=='log':
                return {'logs':repository.list_logs(max(1,min(int(payload.get('limit',10)),100)))}
            raise ValueError('Unsupported read mode')
    elif mode=='write':
        @server.tool()
        async def write_vocabulary(entries: list[dict], context: str) -> dict:
            """Ingest a code-selected batch. context is the stable source identifier for retry deduplication."""
            warnings = []
            if dictionary_enabled:
                existing = repository.lookup(e.get('word','') for e in entries)
                new = [e for e in entries if e.get('word','').lower() not in existing]
                enriched,warnings = await enrich_entries(new)
                by_word = {entry['word']:entry for entry in enriched}
                entries = [by_word.get(entry['word'],entry) for entry in entries]
            result = await asyncio.to_thread(repository.upsert_entries,entries,context)
            result['warnings'].extend(warnings)
            return result
    else:
        raise ValueError('MCP mode must be read or write')
    return server

if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--database',required=True)
    parser.add_argument('--mode',choices=['read','write'],required=True)
    parser.add_argument('--dictionary',choices=['true','false'],default='true')
    args = parser.parse_args()
    create_server(args.database,args.mode,args.dictionary=='true').run(transport='stdio')
