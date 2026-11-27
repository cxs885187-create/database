import json
from dataclasses import replace

from fastapi.testclient import TestClient
from app.config import Settings


class FakeModel:
    def __init__(self):
        self.round = 0

    async def decide(self,instruction,summary):
        from app.schemas import Decision, Filter
        if instruction.lower().startswith('top'):
            return Decision(intent='top',limit=3)
        return Decision(intent='ingest',filter=Filter(top_n=2) if 'two' in instruction else Filter())

    async def choose_tool(self,messages,tools):
        from langchain_core.messages import AIMessage
        request = messages[1].content
        name = 'read_vocabulary' if 'READ_ONLY_ACTION' in request else 'write_vocabulary'
        return AIMessage(content='',tool_calls=[{'name':name,'args':{'mode':'top','payload':{}} if name=='read_vocabulary' else {'entries':[], 'context':'model-cannot-override'},'id':'call-one'}])

    async def summarize(self,intent,result):
        return 'Vocabulary processing completed.'


def parse_sse(text):
    return [(chunk.splitlines()[0][7:],json.loads(chunk.splitlines()[1][6:])) for chunk in text.strip().split('\n\n')]


def test_api_ingestion_mcp_scope_and_learning_contract(tmp_path):
    from app.main import create_app
    settings = Settings(database_path=tmp_path/'api.sqlite3',dictionary_enabled=False)
    with TestClient(create_app(settings,model=FakeModel())) as client:
        assert client.get('/api/health').json()['mcp_ready'] is True
        response = client.post('/api/agent/stream',json={'user_input':'Import these words','text':'Researchers build systems. Researchers test systems.','thread_id':'demo','source_id':'stable'})
        events = parse_sse(response.text)
        assert events[-1][0]=='final',events
        final = events[-1][1]
        assert final['stats']['new_words']>0
        assert final['stats']['new_words']==final['stats']['write_success']
        again = parse_sse(client.post('/api/agent/stream',json={'user_input':'Import these words','text':'Researchers build systems. Researchers test systems.','thread_id':'demo','source_id':'stable'}).text)[-1][1]
        assert again['stats']['duplicates']==final['stats']['write_success']
        assert client.get('/api/logs/'+final['log_id']).json()['traces']
        matches = client.get('/api/wiki/search',params={'q':'research'}).json()
        assert matches
        all_words = client.get('/api/words/all').json()
        assert all_words
        assert {'word', 'part_of_speech', 'definition_en', 'total_count', 'last_seen_at'} <= set(all_words[0])
        assert 'learning_difficulty' in all_words[0]
        assert client.get('/api/words/all?limit=1').status_code == 200
        word_id = matches[0]['word_id']
        changed = client.patch(f'/api/words/{word_id}', json={'learning_difficulty':'hard'})
        assert changed.status_code == 200
        assert changed.json()['word']['learning_difficulty'] == 'hard'
        assert client.patch(f'/api/words/{word_id}', json={'learning_difficulty':'extreme'}).status_code == 422
        assert client.post('/api/wiki/notes',json={'word_id':word_id,'title':'Notes','body_md':'Related to [[system]].'}).status_code==201
        assert client.get('/api/words/'+str(word_id)).json()['notes']
        assert client.get('/api/learn/today').status_code==200
        assert client.get('/api/words/999999').status_code==404
        assert client.post('/api/learn/answer',json={'word_id':word_id,'question_type':'spelling','rating':5,'is_correct':True}).status_code==422


def test_missing_api_key_is_clear_and_does_not_write(tmp_path):
    from app.main import create_app
    with TestClient(create_app(Settings(database_path=tmp_path/'missing.sqlite3',dictionary_enabled=False))) as client:
        events = parse_sse(client.post('/api/agent/stream',json={'user_input':'Researchers build systems.'}).text)
        assert events[-1][0]=='error'
        assert events[-1][1]['code']=='model_unavailable'
        assert client.get('/api/wiki/search?q=research').json()==[]


def test_question_in_article_box_routes_to_read_query(tmp_path):
    from app.main import create_app
    from app.schemas import Decision

    class ChineseQuestionModel(FakeModel):
        async def decide(self, instruction, summary):
            if '最高频' in instruction:
                return Decision(intent='top', limit=1)
            return await super().decide(instruction, summary)

    with TestClient(create_app(Settings(database_path=tmp_path/'question.sqlite3',dictionary_enabled=False), model=ChineseQuestionModel())) as client:
        client.app.state.repo.upsert_entries([{'word':'debug','count':4}], 'seed')
        events = parse_sse(client.post('/api/agent/stream', json={
            'user_input':'Import the vocabulary in this article',
            'text':'当前最高频的词语是哪一个',
            'thread_id':'question',
        }).text)
        assert events[-1][0] == 'final'
        assert events[-1][1]['intent'] == 'top'
        assert events[-1][1]['highlights']['items'] == [{'word':'debug','total_count':4,'rank':1}]
