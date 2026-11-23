from collections import Counter
from fastapi.testclient import TestClient
from app.analysis import AnalysisPool
from app.config import Settings
from app.main import create_app
from test_api import FakeModel,parse_sse

def test_scope_thread_binding_and_two_round_default(tmp_path):
    pool = AnalysisPool('source',Counter({'term'+chr(97+i//26)+chr(97+i%26):1 for i in range(120)}),{})
    pool.pos_by_word={w:'noun' for w in pool.candidates}
    with TestClient(create_app(Settings(database_path=tmp_path/'scope.sqlite3',dictionary_enabled=False),FakeModel())) as client:
        client.app.state.agent.analyzer.analyze=lambda *args:pool
        events = parse_sse(client.post('/api/agent/stream',json={'user_input':'Import this article','text':'source','thread_id':'owner'}).text)
        assert events[-1][0]=='scope_confirm'
        confirm = events[-1][1]['data']['confirm_id']
        with client.app.state.repo.db.connect() as conn:
            assert conn.execute('SELECT count(*) FROM words').fetchone()[0]==0
        denied = parse_sse(client.post('/api/agent/respond',json={'type':'scope_response','confirm_id':confirm,'thread_id':'wrong'}).text)
        assert denied[-1][1]['code']=='scope_expired'
        second = parse_sse(client.post('/api/agent/respond',json={'type':'scope_response','confirm_id':confirm,'thread_id':'owner'}).text)
        assert second[-1][0]=='scope_confirm'
        final = parse_sse(client.post('/api/agent/respond',json={'type':'scope_response','confirm_id':confirm,'thread_id':'owner'}).text)
        assert final[-1][0]=='final',final
        assert final[-1][1]['stats']['write_success']==30
        assert final[-1][1]['highlights']['applied_filter']['top_n']==30
        assert final[-1][1]['highlights']['applied_filter']['exclude_existing'] is False
        replay = parse_sse(client.post('/api/agent/respond',json={'type':'scope_response','confirm_id':confirm,'thread_id':'owner'}).text)
        assert replay[-1][1]['code']=='scope_expired'

def test_read_request_does_not_mutate_vocabulary(tmp_path):
    with TestClient(create_app(Settings(database_path=tmp_path/'read.sqlite3',dictionary_enabled=False),FakeModel())) as client:
        events = parse_sse(client.post('/api/agent/stream',json={'user_input':'Top vocabulary'}).text)
        assert events[-1][1]['intent']=='top'
        assert events[-1][1]['highlights']['items']==[]
        assert client.get('/api/words').json()==[]
        assert client.post('/api/words',headers={'Origin':'https://other.example'},json={'word':'intruder','source_id':'other-site'}).status_code==403

def test_top_filter_is_respected_even_if_model_uses_filter_top_n(tmp_path):
    from app.schemas import Decision, Filter
    class RankingModel(FakeModel):
        async def decide(self,instruction,summary):
            return Decision(intent='top',filter=Filter(top_n=5))
    with TestClient(create_app(Settings(database_path=tmp_path/'ranking.sqlite3',dictionary_enabled=False),RankingModel())) as client:
        client.app.state.repo.upsert_entries([{'word':'term'+chr(97+i),'count':1} for i in range(10)],'seed')
        events = parse_sse(client.post('/api/agent/stream',json={'user_input':'Show my top five words'}).text)
        assert len(events[-1][1]['highlights']['items'])==5

def test_excel_import_preserves_file_and_retry_deduplicates(tmp_path):
    import hashlib
    from pathlib import Path
    from app.db import Database
    from app.repository import VocabularyRepository
    from app.import_excel import import_workbook
    path = Path(__file__).resolve().parents[1]/'version control'/'v0.3'/'v0.3.xlsx'
    original = hashlib.sha256(path.read_bytes()).hexdigest()
    repository = VocabularyRepository(Database(tmp_path/'excel.sqlite3'))
    first = import_workbook(repository,path)
    assert len(first['new_ids'])==30
    assert import_workbook(repository,path)['duplicates']==30
    assert hashlib.sha256(path.read_bytes()).hexdigest()==original
