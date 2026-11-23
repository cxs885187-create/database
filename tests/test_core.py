import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from app.analysis import Analyzer, apply_filter
from app.db import Database
from app.repository import VocabularyRepository


@pytest.fixture
def repo(tmp_path):
    return VocabularyRepository(Database(tmp_path / 'test.sqlite3'))


def test_source_retry_does_not_double_count(repo):
    entry = {'word': 'resilient', 'count': 3, 'definition_en': 'Able to recover quickly.', 'part_of_speech': ['adj']}
    first = repo.upsert_entries([entry], 'article-one')
    retry = repo.upsert_entries([entry], 'article-one')
    assert len(first['new_ids']) == 1
    assert retry['duplicates'] == 1
    assert repo.lookup(['resilient'])['resilient']['total_count'] == 3
    repo.upsert_entries([entry], 'article-two')
    assert repo.lookup(['resilient'])['resilient']['total_count'] == 6


def test_read_connection_is_physically_read_only(repo):
    read_db = Database(repo.db.path, read_only=True)
    with read_db.connect() as conn:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO words(word) VALUES('forbidden')")


def test_note_fts_and_late_backlink_resolution(repo):
    word_id = repo.upsert_entries([{'word': 'alpha', 'count': 1, 'semantic_tag': 'science'}], 's1')['new_ids'][0]
    note = repo.save_note(word_id, 'Connections', 'Useful concept: [[beta]].')
    assert repo.search('useful')[0]['word_id'] == word_id
    assert repo.search('science')[0]['word_id'] == word_id
    beta_id = repo.upsert_entries([{'word': 'beta', 'count': 1}], 's2')['new_ids'][0]
    assert repo.word_detail(beta_id)['backlinks'][0]['note_id'] == note['id']
    repo.delete_note(note['id'])
    assert repo.search('useful') == []
    assert repo.word_detail(beta_id)['backlinks'] == []


def test_frequency_windows_use_consistent_utc(repo):
    repo.upsert_entries([{'word': 'current', 'count': 4}], 'today')
    repo.upsert_entries([{'word': 'ancient', 'count': 9}], 'old')
    with repo.db.transaction() as conn:
        conn.execute("UPDATE occurrences SET occurred_at=? WHERE source_id='old'", ((datetime.now(UTC)-timedelta(days=60)).strftime('%Y-%m-%dT%H:%M:%SZ'),))
    assert repo.top(20, '7d') == [{'word': 'current', 'total_count': 4, 'rank': 1}]


def test_spacy_analysis_lemmas_and_pos():
    analyzer = Analyzer('en_core_web_sm')
    pool = analyzer.analyze('The researchers tested the systems. The researchers are testing the systems.', {})
    assert pool.candidates['researcher'] == 2
    assert pool.candidates['test'] == 2
    assert pool.pos_by_word['test'] == 'verb'
    verbs = apply_filter(pool, {'pos_include': ['verb']})
    assert [entry['word'] for entry in verbs] == ['test']


def test_unknown_difficulty_is_not_silently_included():
    pool = Analyzer('en_core_web_sm').analyze('Researchers test systems.', {})
    with pytest.raises(ValueError, match='difficulty'):
        apply_filter(pool, {'difficulty': 'cet6+'})


def test_question_answer_is_server_graded_and_idempotent(repo):
    from app.learning import LearningService
    for i, word in enumerate(['alpha', 'beta', 'gamma', 'delta']):
        repo.upsert_entries([{'word': word, 'count': 1, 'part_of_speech': ['noun'], 'definition_en': f'A distinct concept numbered {i}.', 'definition_zh': f'Meaning {i}', 'example_sentences': [f'The {word} concept provides enough context for this exercise.']}], word)
    service = LearningService(repo, daily_new_limit=10)
    question = service.next_question()
    assert question['question_id']
    assert len(question['options']) == 4
    assert 'word' not in question['word']
    assert 'correct_answer' not in question
    outcome = service.answer(question['question_id'], 'invalid option', 5, 120)
    assert outcome['is_correct'] is False
    assert outcome['rating'] == 0
    assert service.answer(question['question_id'], 'invalid option', 5, 120) == outcome
    with repo.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM review_events').fetchone()[0] == 1


def test_missing_question_data_does_not_start_learning(repo):
    from app.learning import LearningService
    repo.upsert_entries([{'word': 'unknown', 'count': 1}], 'no-metadata')
    question = LearningService(repo).next_question()
    assert question['question_type'] == 'first_contact'
    with repo.db.connect() as conn:
        assert conn.execute('SELECT queue_state FROM learning_states').fetchone()[0] == 'new'
