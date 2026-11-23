"""Explicit live integration check: synthetic data, real DeepSeek and two MCP servers."""
import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app

def main():
    if not os.getenv('DEEPSEEK_API_KEY'):
        raise SystemExit('Set DEEPSEEK_API_KEY before this explicit live check.')
    with tempfile.TemporaryDirectory(prefix='vocabulary-live-') as directory:
        settings = replace(Settings.from_env(),database_path=Path(directory)/'live.sqlite3',dictionary_enabled=True)
        with TestClient(create_app(settings)) as client:
            print('Health:',json.dumps(client.get('/api/health').json()))
            response = client.post('/api/agent/stream',json={
                'user_input':'Import only the top three most frequent vocabulary words in this article.',
                'text':'Researchers test systems. Researchers build reliable systems. Researchers improve reliable systems.',
                'thread_id':'live-test','source_id':'synthetic-live-test',
            })
            events=[]
            for chunk in response.text.strip().split('\n\n'):
                lines=chunk.splitlines()
                if len(lines)>=2:
                    events.append((lines[0][7:],json.loads(lines[1][6:])))
            print('Events:',[kind for kind,_ in events])
            print('Final:',json.dumps(events[-1][1]))
            assert events[-1][0]=='final',events
            final=events[-1][1]
            assert final['stats']['new_words']==3
            assert final['stats']['write_success']==3
            log=client.get('/api/logs/'+final['log_id']).json()
            assert log['traces'][0]['tool_name']=='write_vocabulary'
            assert len(log['entries'])==3
            print('PASS: real DeepSeek -> LangChain tool calling -> separate MCP writer -> SQLite -> SSE final.')

if __name__=='__main__':
    main()
