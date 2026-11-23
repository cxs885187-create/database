"""Transactional vocabulary, Wiki and trace operations. No model-generated counts."""
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta

JSON_FIELDS = {'part_of_speech': [], 'example_sentences': [], 'usage_contexts': []}
METADATA = ('phonetic','part_of_speech','definition_en','definition_zh','audio_url',
            'example_sentences','usage_contexts','semantic_tag','difficulty')

def utcnow():
    return datetime.now(UTC)

def stamp(value=None):
    return (value or utcnow()).strftime('%Y-%m-%dT%H:%M:%SZ')

def decode(row):
    if row is None:
        return None
    result = dict(row)
    for key, default in JSON_FIELDS.items():
        if key in result:
            try:
                result[key] = json.loads(result[key]) if result[key] else list(default)
            except (ValueError, TypeError):
                result[key] = [result[key]] if result[key] else []
    return result

def encode_metadata(key,value):
    if key in JSON_FIELDS:
        return json.dumps([value] if isinstance(value,str) else value,ensure_ascii=True)
    return value

class VocabularyRepository:
    def __init__(self,db):
        self.db = db

    def lookup(self,words):
        words = sorted({word.strip().lower() for word in words if word.strip()})
        result = {}
        with self.db.connect() as conn:
            for offset in range(0,len(words),400):
                batch = words[offset:offset+400]
                rows = conn.execute(f"SELECT * FROM words WHERE word IN ({','.join('?' for _ in batch)})",batch)
                result.update({row['word']:decode(row) for row in rows})
        return result

    def upsert_entries(self,entries,source_id):
        if not source_id or len(source_id)>200:
            raise ValueError('A source_id of at most 200 characters is required')
        validated,warnings = {},[]
        for entry in entries:
            word = str(entry.get('word','')).strip().lower()
            count = entry.get('count',1)
            if not re.fullmatch(r"[a-z][a-z' _-]{0,80}",word) or type(count) is not int or count<1:
                warnings.append({'word':word,'reason':'invalid_word_or_count'})
                continue
            if word in validated:
                raise ValueError('Duplicate word in one ingestion batch')
            validated[word] = {**entry,'word':word,'count':count}
        fingerprint = hashlib.sha256(json.dumps(sorted((w,e['count']) for w,e in validated.items())).encode()).hexdigest()
        result = {'success':0,'failed':len(warnings),'duplicates':0,'new_ids':[],'updated_ids':[],
                  'new_entries':[],'updated_entries':[],'warnings':warnings}
        with self.db.transaction() as conn:
            prior = conn.execute('SELECT fingerprint FROM ingestion_sources WHERE source_id=?',(source_id,)).fetchone()
            if prior and prior['fingerprint']!=fingerprint:
                raise ValueError('source_id already exists with different content')
            conn.execute('INSERT OR IGNORE INTO ingestion_sources VALUES (?,?)',(source_id,fingerprint))
            for word,entry in validated.items():
                old = conn.execute('SELECT * FROM words WHERE word=?',(word,)).fetchone()
                if old and conn.execute('SELECT 1 FROM occurrences WHERE word_id=? AND source_id=?',(old['id'],source_id)).fetchone():
                    result['duplicates'] += 1
                    continue
                metadata = {k:encode_metadata(k,entry[k]) for k in METADATA if entry.get(k) not in (None,'',[])}
                if old:
                    word_id = old['id']
                    conn.execute('UPDATE words SET total_count=total_count+?,last_seen_at=? WHERE id=?',(entry['count'],stamp(),word_id))
                    for key,value in metadata.items():
                        conn.execute(f"UPDATE words SET {key}=? WHERE id=? AND ({key} IS NULL OR {key}='' OR {key}='[]')",(value,word_id))
                    result['updated_ids'].append(word_id)
                    result['updated_entries'].append({'word':word,'count_before':old['total_count'],'count_after':old['total_count']+entry['count']})
                else:
                    word_id = conn.execute('INSERT INTO words(word,total_count,first_seen_at,last_seen_at) VALUES(?,?,?,?)',(word,entry['count'],stamp(),stamp())).lastrowid
                    for key,value in metadata.items():
                        conn.execute(f'UPDATE words SET {key}=? WHERE id=?',(value,word_id))
                    conn.execute('INSERT INTO learning_states(word_id) VALUES(?)',(word_id,))
                    conn.execute('UPDATE note_links SET target_word_id=? WHERE target_word=?',(word_id,word))
                    result['new_ids'].append(word_id)
                    result['new_entries'].append({'id':word_id,'word':word,'count':entry['count'],'pos':entry.get('part_of_speech',[]),'definition_en':entry.get('definition_en')})
                conn.execute('INSERT INTO occurrences(word_id,source_id,count) VALUES(?,?,?)',(word_id,source_id,entry['count']))
                self._sync_fts(conn,word_id)
                result['success'] += 1
        return result

    def _sync_fts(self,conn,word_id):
        word = conn.execute('SELECT * FROM words WHERE id=?',(word_id,)).fetchone()
        conn.execute('DELETE FROM words_fts WHERE rowid=?',(word_id,))
        if word:
            notes = '\n'.join(f"{n['title']}\n{n['body_md']}" for n in conn.execute('SELECT title,body_md FROM word_notes WHERE word_id=?',(word_id,)))
            fields = ('word','phonetic','part_of_speech','definition_en','definition_zh','example_sentences','usage_contexts','semantic_tag','difficulty')
            conn.execute('INSERT INTO words_fts(rowid,word,phonetic,part_of_speech,definition_en,definition_zh,example_sentences,usage_contexts,semantic_tag,difficulty,note_body) VALUES(?,?,?,?,?,?,?,?,?,?,?)',[word_id]+[word[f] or '' for f in fields]+[notes])

    def update_metadata(self,word_id,metadata):
        with self.db.transaction() as conn:
            if not conn.execute('SELECT 1 FROM words WHERE id=?',(word_id,)).fetchone():
                raise KeyError('Word not found')
            for key,value in metadata.items():
                if key in METADATA:
                    conn.execute(f'UPDATE words SET {key}=? WHERE id=?',(encode_metadata(key,value) if value is not None else None,word_id))
            self._sync_fts(conn,word_id)
        return self.word_detail(word_id)

    def update_translations(self, translations):
        """Fill missing Chinese meanings and refresh FTS without changing counts."""
        changed = 0
        with self.db.transaction() as conn:
            for word, translation in translations.items():
                row = conn.execute('SELECT id, definition_zh FROM words WHERE lower(word)=?', (word.lower(),)).fetchone()
                if not row or row['definition_zh']:
                    continue
                conn.execute('UPDATE words SET definition_zh=? WHERE id=?', (translation, row['id']))
                self._sync_fts(conn, row['id'])
                changed += 1
        return changed

    def top(self,limit=20,window='all'):
        if window not in {'all','7d','30d'}:
            raise ValueError('Invalid ranking window')
        with self.db.connect() as conn:
            if window=='all':
                rows = conn.execute('SELECT word,total_count FROM words ORDER BY total_count DESC,word LIMIT ?',(limit,)).fetchall()
            else:
                rows = conn.execute('SELECT w.word,SUM(o.count) AS total_count FROM words w JOIN occurrences o ON w.id=o.word_id WHERE o.occurred_at>=? GROUP BY w.id ORDER BY total_count DESC,w.word LIMIT ?',(stamp(utcnow()-timedelta(days=int(window[:-1]))),limit)).fetchall()
        return [{**dict(row),'rank':i+1} for i,row in enumerate(rows)]

    def list_words(self, limit=1000):
        """Return the complete reader-facing vocabulary rows, ordered for scanning."""
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT id, word, part_of_speech, definition_en, definition_zh,
                          total_count, difficulty, last_seen_at
                   FROM words ORDER BY lower(word), id LIMIT ?""",
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
        return [decode(row) for row in rows]

    def search(self,query,limit=20):
        terms = re.findall(r"[\w'-]+",query)
        if not terms:
            return []
        q = ' AND '.join('"'+term.replace('"','')+'"*' for term in terms)
        with self.db.connect() as conn:
            rows = conn.execute("SELECT rowid AS word_id,word,snippet(words_fts,-1,'<b>','</b>','...',12) AS snippet,bm25(words_fts) AS rank FROM words_fts WHERE words_fts MATCH ? ORDER BY rank LIMIT ?",(q,limit)).fetchall()
            if not rows:
                literal = query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
                rows = conn.execute("SELECT id AS word_id,word,COALESCE(definition_en,'') AS snippet,0 AS rank FROM words WHERE word LIKE ? ESCAPE '\\' ORDER BY word LIMIT ?",('%'+literal+'%',limit)).fetchall()
        return [dict(row) for row in rows]

    def word_detail(self,word_id):
        with self.db.connect() as conn:
            word = conn.execute('SELECT * FROM words WHERE id=?',(word_id,)).fetchone()
            if not word:
                return None
            notes = [dict(n) for n in conn.execute('SELECT * FROM word_notes WHERE word_id=? ORDER BY id',(word_id,))]
            for note in notes:
                note['links'] = [dict(link) for link in conn.execute('SELECT target_word,target_word_id FROM note_links WHERE source_note_id=?',(note['id'],))]
            backlinks = [dict(n) for n in conn.execute('SELECT n.id AS note_id,n.title,substr(n.body_md,1,160) AS snippet FROM note_links l JOIN word_notes n ON n.id=l.source_note_id WHERE l.target_word_id=?',(word_id,))]
        return {'word':decode(word),'notes':notes,'backlinks':backlinks}

    def save_note(self,word_id,title,body_md,note_id=None):
        with self.db.transaction() as conn:
            if note_id is not None:
                note = conn.execute('SELECT * FROM word_notes WHERE id=?',(note_id,)).fetchone()
                if not note:
                    raise KeyError('Note not found')
                word_id = note['word_id']
                conn.execute('UPDATE word_notes SET title=?,body_md=?,updated_at=? WHERE id=?',(title,body_md,stamp(),note_id))
                conn.execute('DELETE FROM note_links WHERE source_note_id=?',(note_id,))
            else:
                if not conn.execute('SELECT 1 FROM words WHERE id=?',(word_id,)).fetchone():
                    raise KeyError('Word not found')
                note_id = conn.execute('INSERT INTO word_notes(word_id,title,body_md) VALUES(?,?,?)',(word_id,title,body_md)).lastrowid
            for target in sorted({t.strip().lower() for t in re.findall(r'\[\[([^\]]+)\]\]',body_md)}):
                found = conn.execute('SELECT id FROM words WHERE word=?',(target,)).fetchone()
                conn.execute('INSERT INTO note_links VALUES(?,?,?)',(note_id,target,found['id'] if found else None))
            self._sync_fts(conn,word_id)
            result = dict(conn.execute('SELECT * FROM word_notes WHERE id=?',(note_id,)).fetchone())
        return result

    def delete_note(self,note_id):
        with self.db.transaction() as conn:
            note = conn.execute('SELECT word_id FROM word_notes WHERE id=?',(note_id,)).fetchone()
            if not note:
                raise KeyError('Note not found')
            conn.execute('DELETE FROM word_notes WHERE id=?',(note_id,))
            self._sync_fts(conn,note['word_id'])

    def delete_word(self,word_id):
        with self.db.transaction() as conn:
            if not conn.execute('DELETE FROM words WHERE id=?',(word_id,)).rowcount:
                raise KeyError('Word not found')
            conn.execute('DELETE FROM words_fts WHERE rowid=?',(word_id,))

    def create_log(self,log_id,intent,source_ref,stats,summary,traces=()):
        with self.db.transaction() as conn:
            conn.execute('INSERT INTO logs(id,intent,source_ref,stats_json,summary) VALUES(?,?,?,?,?)',(log_id,intent,source_ref,json.dumps(stats,ensure_ascii=True),summary))
            for step,trace in enumerate(traces,1):
                conn.execute('INSERT INTO agent_traces(log_id,step,role,tool_name,payload) VALUES(?,?,?,?,?)',(log_id,step,trace.get('role','tool'),trace.get('tool_name'),json.dumps(trace.get('payload',{}),ensure_ascii=True)))

    def list_logs(self,limit=10):
        with self.db.connect() as conn:
            return [dict(row) for row in conn.execute('SELECT id AS log_id,intent,summary,created_at FROM logs ORDER BY created_at DESC,id DESC LIMIT ?',(limit,))]

    def log_detail(self,log_id):
        with self.db.connect() as conn:
            row = conn.execute('SELECT * FROM logs WHERE id=?',(log_id,)).fetchone()
            if not row:
                return None
            result = dict(row)
            result['stats'] = json.loads(result.pop('stats_json'))
            result['traces'] = [dict(t) for t in conn.execute('SELECT * FROM agent_traces WHERE log_id=? ORDER BY step',(log_id,))]
            for trace in result['traces']:
                trace['payload'] = json.loads(trace['payload'])
            ids = [r['word_id'] for r in conn.execute('SELECT word_id FROM occurrences WHERE source_id=?',(row['source_ref'],))]
            result['entries'] = [decode(conn.execute('SELECT * FROM words WHERE id=?',(i,)).fetchone()) for i in ids]
            return result
