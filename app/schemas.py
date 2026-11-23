from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class Filter(BaseModel):
    model_config = ConfigDict(extra='forbid')
    top_n: int | None = Field(default=None,ge=1,le=100)
    exclude_existing: bool = False
    pos_include: list[Literal['noun','verb','adj','adv','prep','other']] = Field(default_factory=list)
    difficulty: Literal['all','cet4','cet6','cet6+','toefl','gre'] = 'all'
    min_occurrences: int = Field(default=1,ge=1,le=10000)
    sort_by: Literal['frequency_desc','alphabetical'] = 'frequency_desc'

class Decision(BaseModel):
    intent: Literal['ingest','ingest_and_analyze','lookup','top','log','clarify']
    filter: Filter = Field(default_factory=Filter)
    lookup_words: list[str] = Field(default_factory=list,max_length=100)
    limit: int = Field(default=20,ge=1,le=100)
    window: Literal['all','7d','30d'] = 'all'
    question: str | None = None

class AgentStreamRequest(BaseModel):
    user_input: str = Field(min_length=1,max_length=100000)
    text: str | None = Field(default=None,max_length=100000)
    source_type: Literal['text'] = 'text'
    thread_id: str = Field(default='default',min_length=1,max_length=100)
    source_id: str | None = Field(default=None,min_length=1,max_length=150)

class ScopeSelection(BaseModel):
    preset_id: str | None = None
    filter: Filter | None = None

class AgentRespondRequest(BaseModel):
    type: Literal['scope_response']
    confirm_id: str
    thread_id: str = 'default'
    selection: ScopeSelection = Field(default_factory=ScopeSelection)
    free_text: str | None = Field(default=None,max_length=2000)

class NoteCreateRequest(BaseModel):
    word_id: int
    title: str = Field(min_length=1,max_length=200)
    body_md: str = Field(default='',max_length=100000)

class NoteUpdateRequest(BaseModel):
    title: str = Field(min_length=1,max_length=200)
    body_md: str = Field(default='',max_length=100000)

class WordCreateRequest(BaseModel):
    word: str = Field(min_length=1,max_length=81)
    count: int = Field(default=1,ge=1,le=100000)
    source_id: str = Field(min_length=1,max_length=150)
    definition_en: str | None = None
    definition_zh: str | None = None
    part_of_speech: list[str] = Field(default_factory=list)
    example_sentences: list[str] = Field(default_factory=list)

class WordUpdateRequest(BaseModel):
    phonetic: str | None = None
    part_of_speech: list[str] | None = None
    definition_en: str | None = None
    definition_zh: str | None = None
    audio_url: str | None = None
    example_sentences: list[str] | None = None
    usage_contexts: list[str] | None = None
    semantic_tag: str | None = None
    difficulty: Literal['cet4','cet6','toefl','gre'] | None = None

class LearnAnswerRequest(BaseModel):
    question_id: str
    answer: str = Field(max_length=1000)
    rating: Literal[0,2,3,5] = 3
    duration_ms: int | None = Field(default=None,ge=0,le=3600000)
