"""Deterministic text questions, server-side grading and SM-2-style scheduling."""
import json
import random
import re
import uuid
from datetime import timedelta

from .repository import decode, stamp, utcnow

STEP_TYPES = {
    'learning': [['en_to_zh'],['audio_to_zh','cloze_context'],['spelling','definition_match']],
    'relearning': [['en_to_zh'],['cloze_context']],
    'review': [['en_to_zh','zh_to_en','audio_to_zh','cloze_context','definition_match']],
}
INITIAL_INTERVAL_DAYS = {'hard':1,'medium':2,'easy':3}
INTERVAL_MULTIPLIERS = {'hard':0.7,'medium':1.0,'easy':1.3}

def edit_distance(left,right):
    previous = list(range(len(right)+1))
    for i,a in enumerate(left,1):
        current = [i]
        for j,b in enumerate(right,1):
            current.append(min(current[-1]+1,previous[j]+1,previous[j-1]+(a!=b)))
        previous = current
    return previous[-1]

def overlap(left,right):
    a,b = set(left or ''),set(right or '')
    return len(a & b) / max(1,len(a | b))

def build_question(word,others,qtype):
    prompt,answer,sentence = None,None,None
    pos = set(word['part_of_speech'])
    others = [item for item in others if item['id']!=word['id'] and pos.intersection(item['part_of_speech'])]
    others.sort(key=lambda item:(-overlap(word['definition_zh'],item['definition_zh']),item['word']))
    if qtype in {'en_to_zh','audio_to_zh'}:
        if not word['definition_zh'] or (qtype=='audio_to_zh' and not word['audio_url']):
            return None
        prompt = {'text': word['word'], 'phonetic':word['phonetic']} if qtype=='en_to_zh' else {'audio_url':word['audio_url']}
        answer = word['definition_zh']
        choices = [o['definition_zh'] for o in others if o['definition_zh'] and o['definition_zh']!=answer]
    elif qtype in {'zh_to_en','definition_match','cloze_context'}:
        answer = word['word']
        if qtype=='zh_to_en':
            if not word['definition_zh']:
                return None
            prompt = {'text':word['definition_zh']}
        elif qtype=='definition_match':
            if not word['definition_en'] or re.search(r'\b'+re.escape(answer)+r'\b',word['definition_en'],re.I):
                return None
            prompt = {'text':word['definition_en']}
        else:
            for example in word['example_sentences']:
                match = re.search(r'\b'+re.escape(answer)+r'\b',example,re.I)
                if match and len(example)-len(match.group())>=15:
                    sentence = example[:match.start()]+'____'+example[match.end():]
                    prompt = {'text':sentence}
                    break
            if prompt is None:
                return None
        choices = [o['word'] for o in others if edit_distance(o['word'],answer)>2]
    elif qtype=='spelling':
        if not word['definition_zh']:
            return None
        return {'prompt':{'text':word['definition_zh'],'first_letter':word['word'][0]},'options':[]},word['word']
    else:
        return None
    choices = list(dict.fromkeys(choices))[:3]
    if len(choices)!=3:
        return None
    choices.append(answer)
    random.Random(f"{word['id']}:{qtype}").shuffle(choices)
    return {'prompt':prompt,'options':choices,'sentence_with_blank':sentence},answer


class LearningService:
    def __init__(self,repository,daily_new_limit=10):
        self.repo = repository
        self.db = repository.db
        self.daily_new_limit = daily_new_limit

    def today(self):
        now = stamp()
        today = now[:10]
        with self.db.connect() as conn:
            due = conn.execute("SELECT count(*) FROM learning_states WHERE queue_state!='new' AND due_at<=?",(now,)).fetchone()[0]
            new = conn.execute("SELECT count(*) FROM learning_states WHERE queue_state='new'").fetchone()[0]
            completed = conn.execute('SELECT count(*) FROM review_events WHERE substr(created_at,1,10)=?',(today,)).fetchone()[0]
            stats = conn.execute('SELECT count(*),COALESCE(sum(is_correct),0) FROM review_events WHERE created_at>=?',(stamp(utcnow()-timedelta(days=7)),)).fetchone()
            days = {r[0] for r in conn.execute('SELECT DISTINCT substr(created_at,1,10) FROM review_events')}
            introduced = conn.execute("SELECT count(DISTINCT word_id) FROM learning_questions WHERE result_json IS NOT NULL AND substr(created_at,1,10)=? AND json_extract(payload_json,'$.queue_state')='new'",(today,)).fetchone()[0]
        streak,cursor = 0,utcnow().date()
        if cursor.isoformat() not in days:
            cursor -= timedelta(days=1)
        while cursor.isoformat() in days:
            streak += 1
            cursor -= timedelta(days=1)
        return {'due_count':due,'new_count':new,'new_remaining_today':max(0,self.daily_new_limit-introduced),
                'completed_today':completed,'streak_days':streak,'accuracy_7d':stats[1]/stats[0] if stats[0] else None}

    def next_question(self,question_type=None):
        now = stamp()
        with self.db.connect() as conn:
            pending = conn.execute('SELECT payload_json FROM learning_questions WHERE result_json IS NULL AND expires_at>? ORDER BY created_at LIMIT 1',(now,)).fetchone()
            if pending:
                return json.loads(pending['payload_json'])
            rows = conn.execute("SELECT w.*,s.queue_state,s.step_index,s.due_at FROM learning_states s JOIN words w ON w.id=s.word_id WHERE s.queue_state='new' OR s.due_at<=? ORDER BY CASE s.queue_state WHEN 'relearning' THEN 0 WHEN 'learning' THEN 1 WHEN 'review' THEN 2 WHEN 'mastered' THEN 2 ELSE 3 END,COALESCE(s.due_at,''),w.id",(now,)).fetchall()
            others = [decode(w) for w in conn.execute('SELECT * FROM words ORDER BY word')]
        remaining = self.today()['new_remaining_today']
        first_contact = None
        for row in rows:
            if row['queue_state']=='new' and remaining<=0:
                continue
            word = decode(row)
            state = row['queue_state']
            group = 'learning' if state=='new' else ('review' if state=='mastered' else state)
            options = STEP_TYPES[group][min(row['step_index'],len(STEP_TYPES[group])-1)]
            if question_type:
                options = [question_type]
            for qtype in options:
                built = build_question(word,others,qtype)
                if built:
                    payload,answer = built
                    question_id = 'q_'+uuid.uuid4().hex
                    payload.update({'question_id':question_id,'word':{'id':word['id']},'question_type':qtype,
                                    'queue_state':state,'step_index':row['step_index']})
                    with self.db.transaction() as conn:
                        conn.execute('INSERT INTO learning_questions(id,word_id,question_type,answer,payload_json,created_at,expires_at) VALUES(?,?,?,?,?,?,?)',
                                     (question_id,word['id'],qtype,answer,json.dumps(payload),now,stamp(utcnow()+timedelta(hours=1))))
                    return payload
            if first_contact is None:
                first_contact = {'question_type':'first_contact','word':{k:word[k] for k in ('id','word','phonetic','definition_en','definition_zh')},
                                 'queue_state':state,'step_index':row['step_index'],'options':[],
                                 'message':'More metadata or same-part-of-speech distractors are needed. No review state has changed.'}
        return first_contact

    def answer(self,question_id,answer,rating,duration_ms=None):
        if rating not in {0,2,3,5}:
            raise ValueError('rating must be 0, 2, 3, or 5')
        with self.db.transaction() as conn:
            question = conn.execute('SELECT * FROM learning_questions WHERE id=?',(question_id,)).fetchone()
            if not question:
                raise KeyError('Question not found')
            if question['result_json']:
                return json.loads(question['result_json'])
            if question['expires_at']<stamp():
                raise ValueError('Question has expired')
            correct = str(answer).strip().casefold()==question['answer'].strip().casefold()
            rating = rating if correct else 0
            word_id = question['word_id']
            word = conn.execute('SELECT learning_difficulty FROM words WHERE id=?',(word_id,)).fetchone()
            difficulty = word['learning_difficulty'] or 'medium'
            interval_multiplier = INTERVAL_MULTIPLIERS[difficulty]
            state = dict(conn.execute('SELECT * FROM learning_states WHERE word_id=?',(word_id,)).fetchone())
            if state['queue_state']=='mastered':
                state['queue_state']='review'
            current = state['queue_state']
            if rating==0:
                state['queue_state'] = 'relearning' if current in {'review','relearning'} else 'learning'
                state['step_index']=0
                state['lapses'] += int(current in {'review','relearning'})
                due = utcnow()+timedelta(minutes=1)
            elif current in {'new','learning','relearning'}:
                state['queue_state'] = 'learning' if current=='new' else current
                if rating>=3:
                    state['step_index'] += 1
                steps = 2 if state['queue_state']=='relearning' else 3
                if state['step_index']>=steps:
                    state['queue_state']='review'
                    if current in {'new','learning'}:
                        state['interval_days']=INITIAL_INTERVAL_DAYS[difficulty]
                    else:
                        state['interval_days']=max(1,round(state['interval_days']*interval_multiplier))
                    state['repetitions'] += 1
                    due = utcnow()+timedelta(days=state['interval_days'])
                else:
                    due = utcnow()+timedelta(minutes=1 if state['step_index']<=1 else 10)
            else:
                interval = state['interval_days']
                proposed = interval*(1.2 if rating==2 else state['ease_factor']*(1.3 if rating==5 else 1))
                state['interval_days'] = max(1,round(proposed*interval_multiplier))
                state['repetitions'] += 1
                due = utcnow()+timedelta(days=state['interval_days'])
            state['ease_factor'] = max(1.3,state['ease_factor']+(.1-(5-rating)*(.08+(5-rating)*.02)))
            state['due_at']=stamp(due)
            state['last_reviewed_at']=stamp()
            conn.execute('UPDATE learning_states SET queue_state=:queue_state,ease_factor=:ease_factor,interval_days=:interval_days,repetitions=:repetitions,lapses=:lapses,due_at=:due_at,step_index=:step_index,last_reviewed_at=:last_reviewed_at WHERE word_id=:word_id',state)
            conn.execute('INSERT INTO review_events(word_id,question_id,question_type,rating,is_correct,duration_ms) VALUES(?,?,?,?,?,?)',(word_id,question_id,question['question_type'],rating,int(correct),duration_ms))
            result = {'next_due':state['due_at'],'queue_state':state['queue_state'],'step_index':state['step_index'],'rating':rating,'is_correct':correct,'correct_answer':question['answer']}
            conn.execute('UPDATE learning_questions SET result_json=? WHERE id=?',(json.dumps(result),question_id))
            return result

    def master(self,word_id):
        due = stamp(utcnow()+timedelta(days=90))
        with self.db.transaction() as conn:
            if not conn.execute('UPDATE learning_states SET queue_state=\'mastered\',due_at=? WHERE word_id=?',(due,word_id)).rowcount:
                raise KeyError('Word not found')
            conn.execute('DELETE FROM learning_questions WHERE word_id=? AND result_json IS NULL',(word_id,))
        return {'queue_state':'mastered','due_at':due}
