"""SQLite storage with genuinely read-only connections for the read MCP."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS words (
 id INTEGER PRIMARY KEY, word TEXT NOT NULL UNIQUE COLLATE NOCASE,
 phonetic TEXT, part_of_speech TEXT, definition_en TEXT, definition_zh TEXT,
 audio_url TEXT, example_sentences TEXT, usage_contexts TEXT,
 learning_difficulty TEXT CHECK(learning_difficulty IS NULL OR learning_difficulty IN ('easy','medium','hard')),
 semantic_tag TEXT, difficulty TEXT, total_count INTEGER NOT NULL DEFAULT 0,
 first_seen_at TEXT, last_seen_at TEXT,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_words_count ON words(total_count DESC);
CREATE INDEX IF NOT EXISTS idx_words_pos ON words(part_of_speech);
CREATE INDEX IF NOT EXISTS idx_words_letter ON words(substr(lower(word),1,1));
CREATE TABLE IF NOT EXISTS occurrences (
 id INTEGER PRIMARY KEY, word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
 source_id TEXT NOT NULL, count INTEGER NOT NULL CHECK(count>0),
 occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
 UNIQUE(word_id, source_id)
);
CREATE INDEX IF NOT EXISTS idx_occ_word ON occurrences(word_id);
CREATE INDEX IF NOT EXISTS idx_occ_time ON occurrences(occurred_at DESC);
CREATE TABLE IF NOT EXISTS ingestion_sources (source_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS words_fts USING fts5(
 word, phonetic, part_of_speech, definition_en, definition_zh, example_sentences,
 usage_contexts, semantic_tag, difficulty, note_body, tokenize='unicode61'
);
CREATE TABLE IF NOT EXISTS word_notes (
 id INTEGER PRIMARY KEY, word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
 title TEXT NOT NULL, body_md TEXT NOT NULL,
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE IF NOT EXISTS note_links (
 source_note_id INTEGER REFERENCES word_notes(id) ON DELETE CASCADE,
 target_word TEXT NOT NULL, target_word_id INTEGER REFERENCES words(id) ON DELETE SET NULL,
 PRIMARY KEY(source_note_id,target_word)
);
CREATE INDEX IF NOT EXISTS idx_links_target ON note_links(target_word_id);
CREATE TABLE IF NOT EXISTS learning_states (
 word_id INTEGER PRIMARY KEY REFERENCES words(id) ON DELETE CASCADE,
 queue_state TEXT NOT NULL DEFAULT 'new', ease_factor REAL NOT NULL DEFAULT 2.5,
 interval_days INTEGER NOT NULL DEFAULT 0, repetitions INTEGER NOT NULL DEFAULT 0,
 lapses INTEGER NOT NULL DEFAULT 0, due_at TEXT, step_index INTEGER NOT NULL DEFAULT 0,
 last_reviewed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ls_due ON learning_states(queue_state,due_at);
CREATE TABLE IF NOT EXISTS review_events (
 id INTEGER PRIMARY KEY, word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
 question_id TEXT UNIQUE, question_type TEXT NOT NULL, rating INTEGER NOT NULL,
 is_correct INTEGER NOT NULL, duration_ms INTEGER,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_re_word ON review_events(word_id,created_at DESC);
CREATE TABLE IF NOT EXISTS learning_questions (
 id TEXT PRIMARY KEY, word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
 question_type TEXT NOT NULL, answer TEXT NOT NULL, payload_json TEXT NOT NULL,
 result_json TEXT, created_at TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS logs (
 id TEXT PRIMARY KEY, intent TEXT NOT NULL, source_ref TEXT, stats_json TEXT NOT NULL,
 summary TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE IF NOT EXISTS agent_traces (
 id INTEGER PRIMARY KEY, log_id TEXT NOT NULL REFERENCES logs(id) ON DELETE CASCADE,
 step INTEGER NOT NULL, role TEXT NOT NULL, tool_name TEXT, payload TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_trace_log ON agent_traces(log_id,step);
"""

class Database:
    def __init__(self, path, read_only=False):
        self.path = Path(path).resolve()
        self.read_only = read_only
        if not read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.connect() as conn:
                version = conn.execute('PRAGMA user_version').fetchone()[0]
                if version not in {0,1,2}:
                    raise RuntimeError(f'Unsupported database schema version {version}; an explicit migration is required')
                conn.execute('PRAGMA journal_mode=WAL')
                conn.executescript(SCHEMA)
                columns = {row['name'] for row in conn.execute('PRAGMA table_info(words)')}
                if 'learning_difficulty' not in columns:
                    conn.execute(
                        "ALTER TABLE words ADD COLUMN learning_difficulty TEXT "
                        "CHECK(learning_difficulty IS NULL OR learning_difficulty IN ('easy','medium','hard'))"
                    )
                conn.execute('PRAGMA user_version=2')

    @contextmanager
    def connect(self):
        target = f'{self.path.as_uri()}?mode=ro' if self.read_only else str(self.path)
        conn = sqlite3.connect(target, uri=self.read_only, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        if self.read_only:
            conn.execute('PRAGMA query_only=ON')
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        with self.connect() as conn:
            try:
                conn.execute('BEGIN IMMEDIATE')
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
