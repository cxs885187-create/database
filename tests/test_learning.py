import sqlite3
from datetime import timedelta
import pytest

from app.db import Database
from app.repository import VocabularyRepository,decode,stamp,utcnow
from app.learning import LearningService,build_question

@pytest.fixture
def repo(tmp_path):
    repository = VocabularyRepository(Database(tmp_path/'learning.sqlite3'))
    for i,word in enumerate(['alpha','bravo','charlie','delta','echo']):
        repository.upsert_entries([{'word':word,'count':1,'part_of_speech':['noun'],
            'definition_en':f'A separate concept with numerical identity {i}.',
            'definition_zh':f'Meaning {i}',
            'audio_url':'https://example.com/pronunciation.mp3',
            'example_sentences':[f'The {word} concept is useful for this extended example sentence.']}],word)
    return repository

@pytest.mark.parametrize('qtype',['en_to_zh','zh_to_en','audio_to_zh','cloze_context','spelling','definition_match'])
def test_all_six_question_types(repo,qtype):
    with repo.db.connect() as conn:
        words = [decode(row) for row in conn.execute('SELECT * FROM words')]
    built,answer = build_question(words[0],words,qtype)
    assert built['prompt']
    assert answer == (words[0]['definition_zh'] if qtype in {'en_to_zh','audio_to_zh'} else words[0]['word'])
    if qtype!='spelling':
        assert len(built['options'])==len(set(built['options']))==4
        assert answer in built['options']
    if qtype=='cloze_context':
        assert 'alpha' not in built['prompt']['text']

def test_progression_review_failure_and_master(repo):
    service = LearningService(repo)
    for expected in [1,2,3]:
        q = service.next_question()
        with repo.db.connect() as conn:
            correct = conn.execute('SELECT answer FROM learning_questions WHERE id=?',(q['question_id'],)).fetchone()[0]
        result = service.answer(q['question_id'],correct,3)
        assert result['step_index']==expected
        with repo.db.transaction() as conn:
            conn.execute("UPDATE learning_states SET due_at='2000-01-01T00:00:00Z' WHERE word_id=?",(q['word']['id'],))
    assert result['queue_state']=='review'
    q = service.next_question()
    result = service.answer(q['question_id'],'wrong',5)
    assert result['queue_state']=='relearning'
    assert result['rating']==0
    assert repo.word_detail(q['word']['id'])
    mastered = service.master(q['word']['id'])
    assert mastered['queue_state']=='mastered'
    assert mastered['due_at']>stamp(utcnow()+timedelta(days=89))


def test_learning_difficulty_changes_review_intervals(repo):
    word_id = repo.list_words()[0]['id']
    intervals = {}
    for difficulty in ('easy', 'medium', 'hard'):
        question_id = f'q-{difficulty}'
        with repo.db.transaction() as conn:
            conn.execute('UPDATE words SET learning_difficulty=? WHERE id=?', (difficulty, word_id))
            conn.execute("UPDATE learning_states SET queue_state='review', interval_days=10, ease_factor=2, repetitions=1 WHERE word_id=?", (word_id,))
            conn.execute(
                'INSERT INTO learning_questions(id,word_id,question_type,answer,payload_json,created_at,expires_at) VALUES(?,?,?,?,?,?,?)',
                (question_id, word_id, 'en_to_zh', 'Meaning 0', '{}', stamp(), stamp(utcnow()+timedelta(hours=1)),),
            )
        LearningService(repo).answer(question_id, 'Meaning 0', 3)
        with repo.db.connect() as conn:
            intervals[difficulty] = conn.execute('SELECT interval_days FROM learning_states WHERE word_id=?', (word_id,)).fetchone()[0]

    assert intervals['easy'] > intervals['medium'] > intervals['hard']


@pytest.mark.parametrize(('difficulty', 'expected_days'), [('hard', 1), ('medium', 2), ('easy', 3)])
def test_learning_difficulty_sets_initial_review_date(repo, difficulty, expected_days):
    word_id = repo.list_words()[0]['id']
    question_id = f'q-initial-{difficulty}'
    with repo.db.transaction() as conn:
        conn.execute('UPDATE words SET learning_difficulty=? WHERE id=?', (difficulty, word_id))
        conn.execute("UPDATE learning_states SET queue_state='learning', step_index=2 WHERE word_id=?", (word_id,))
        conn.execute(
            'INSERT INTO learning_questions(id,word_id,question_type,answer,payload_json,created_at,expires_at) VALUES(?,?,?,?,?,?,?)',
            (question_id, word_id, 'en_to_zh', 'Meaning 0', '{}', stamp(), stamp(utcnow()+timedelta(hours=1)),),
        )

    LearningService(repo).answer(question_id, 'Meaning 0', 3)

    with repo.db.connect() as conn:
        interval = conn.execute('SELECT interval_days FROM learning_states WHERE word_id=?', (word_id,)).fetchone()[0]
    assert interval == expected_days


def test_unset_learning_difficulty_uses_medium_schedule(repo):
    word_id = repo.list_words()[0]['id']
    with repo.db.transaction() as conn:
        conn.execute("UPDATE learning_states SET queue_state='learning', step_index=2 WHERE word_id=?", (word_id,))
        conn.execute(
            'INSERT INTO learning_questions(id,word_id,question_type,answer,payload_json,created_at,expires_at) VALUES(?,?,?,?,?,?,?)',
            ('q-initial-unset', word_id, 'en_to_zh', 'Meaning 0', '{}', stamp(), stamp(utcnow()+timedelta(hours=1)),),
        )

    LearningService(repo).answer('q-initial-unset', 'Meaning 0', 3)

    with repo.db.connect() as conn:
        interval = conn.execute('SELECT interval_days FROM learning_states WHERE word_id=?', (word_id,)).fetchone()[0]
    assert interval == 2


def test_database_adds_learning_difficulty_to_existing_schema(tmp_path):
    legacy_path = tmp_path/'legacy.sqlite3'
    with sqlite3.connect(legacy_path) as conn:
        conn.execute(
            'CREATE TABLE words ('
            'id INTEGER PRIMARY KEY, word TEXT NOT NULL UNIQUE COLLATE NOCASE, '
            'phonetic TEXT, part_of_speech TEXT, definition_en TEXT, definition_zh TEXT, '
            'audio_url TEXT, example_sentences TEXT, usage_contexts TEXT, semantic_tag TEXT, '
            'difficulty TEXT, total_count INTEGER NOT NULL DEFAULT 0, first_seen_at TEXT, '
            'last_seen_at TEXT, created_at TEXT NOT NULL DEFAULT '
            "(strftime('%Y-%m-%dT%H:%M:%SZ','now')))"
        )
        conn.execute("INSERT INTO words (id,word,total_count) VALUES (1,'legacy',3)")
        conn.execute('PRAGMA user_version=1')

    migrated = Database(legacy_path)
    with migrated.connect() as conn:
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(words)')}
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        preserved_word = conn.execute('SELECT word,total_count,learning_difficulty FROM words WHERE id=1').fetchone()

    assert 'learning_difficulty' in columns
    assert version == 2
    assert tuple(preserved_word) == ('legacy', 3, None)

def test_daily_limit_and_question_expiry(repo):
    service = LearningService(repo,daily_new_limit=1)
    q = service.next_question()
    with repo.db.transaction() as conn:
        conn.execute("UPDATE learning_questions SET expires_at='2000-01-01T00:00:00Z' WHERE id=?",(q['question_id'],))
    with pytest.raises(ValueError,match='expired'):
        service.answer(q['question_id'],'wrong',3)
    q = service.next_question()
    service.answer(q['question_id'],'wrong',0)
    assert service.today()['new_remaining_today']==0
    assert service.next_question() is None

def test_missing_audio_and_invalid_cloze_fall_back(repo):
    with repo.db.connect() as conn:
        words = [decode(row) for row in conn.execute('SELECT * FROM words')]
    words[0]['audio_url']=None
    words[0]['example_sentences']=['ALPHABET is not the target.', 'alpha']
    assert build_question(words[0],words,'audio_to_zh') is None
    assert build_question(words[0],words,'cloze_context') is None
