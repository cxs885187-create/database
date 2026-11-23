"""spaCy tokenization, lemmatization and filtering. No heuristic fallback."""
from collections import Counter
from dataclasses import dataclass, field
import spacy

POS_MAP = {'NOUN':'noun','PROPN':'noun','VERB':'verb','AUX':'verb','ADJ':'adj','ADV':'adv','ADP':'prep'}

@dataclass
class AnalysisPool:
    source_text: str
    candidates: Counter
    pos_by_word: dict
    existing_set: set = field(default_factory=set)
    difficulty_by_word: dict = field(default_factory=dict)
    sentences: dict = field(default_factory=dict)

    @property
    def unique_words(self):
        return len(self.candidates)

    def as_dict(self):
        return {'total_tokens':sum(self.candidates.values()),'unique_words':self.unique_words,
                'existing_words':len(self.existing_set),'new_words':self.unique_words-len(self.existing_set),
                'singleton_words':sum(c==1 for c in self.candidates.values()),
                'pos_distribution':dict(Counter(self.pos_by_word.values())),
                'top_frequency':[{'word':w,'count':c} for w,c in sorted(self.candidates.items(),key=lambda x:(-x[1],x[0]))[:30]]}

class Analyzer:
    def __init__(self,model='en_core_web_sm'):
        self.nlp = spacy.load(model,disable=['ner'])

    def analyze(self,text,existing):
        doc = self.nlp(text)
        counts,tags,sentences = Counter(),{},{}
        for token in doc:
            if not token.is_ascii or not token.is_alpha or token.is_stop or len(token.text)<2:
                continue
            lemma = token.lemma_.lower()
            counts[lemma] += 1
            tags.setdefault(lemma,Counter())[POS_MAP.get(token.pos_,'other')] += 1
            sentence = token.sent.text.strip()
            if len(sentence)>=15:
                sentences.setdefault(lemma,[])
                if sentence not in sentences[lemma] and len(sentences[lemma])<3:
                    sentences[lemma].append(sentence)
        return AnalysisPool(text,counts,{w:c.most_common(1)[0][0] for w,c in tags.items()},set(existing).intersection(counts),{w:r.get('difficulty') for w,r in existing.items()},sentences)

def apply_filter(pool,filter_spec=None):
    f = filter_spec or {}
    difficulty = f.get('difficulty','all')
    if difficulty!='all' and not any(pool.difficulty_by_word.values()):
        raise ValueError('No verified difficulty labels are available; choose all or label words first')
    ranks = {'cet4':1,'cet6':2,'toefl':3,'gre':4}
    items = []
    for word,count in pool.candidates.items():
        if f.get('exclude_existing') and word in pool.existing_set:
            continue
        if f.get('pos_include') and pool.pos_by_word.get(word) not in f['pos_include']:
            continue
        if count<f.get('min_occurrences',1):
            continue
        if difficulty!='all':
            label = pool.difficulty_by_word.get(word)
            if label is None or (ranks.get(label,0)<ranks.get(difficulty.rstrip('+'),99) if difficulty.endswith('+') else label!=difficulty):
                continue
        items.append((word,count))
    items.sort(key=(lambda pair:pair[0]) if f.get('sort_by')=='alphabetical' else (lambda pair:(-pair[1],pair[0])))
    if f.get('top_n'):
        items = items[:f['top_n']]
    return [{'word':w,'count':c,'part_of_speech':[pool.pos_by_word.get(w,'other')],'example_sentences':pool.sentences.get(w,[])} for w,c in items]
