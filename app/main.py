"""Local FastAPI server. Wiki and learning never depend on a model call."""
import asyncio
import base64
import binascii
import logging
import secrets
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .markdown import render_note

from .analysis import Analyzer
from .agent import VocabularyAgent
from .config import ROOT, Settings
from .db import Database
from .deepseek import DeepSeekClient
from .learning import LearningService
from .repository import VocabularyRepository
from .schemas import AgentStreamRequest, AgentRespondRequest, NoteCreateRequest, NoteUpdateRequest, WordCreateRequest, WordUpdateRequest, LearnAnswerRequest
from .tools import MCPGateway
from .translate import TranslationService


def configure_logging():
    """Record agent failures with their real exception instead of only the SSE hint."""
    logger = logging.getLogger('vocabulary')
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s')
    try:
        log_dir = ROOT/'logs'
        log_dir.mkdir(parents=True,exist_ok=True)
        file_handler = RotatingFileHandler(log_dir/'agent-errors.log',maxBytes=1_000_000,backupCount=3,encoding='utf-8')
    except OSError:
        file_handler = logging.StreamHandler()
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger

def create_app(settings=None,model=None):
    configure_logging()
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        repository = VocabularyRepository(Database(settings.database_path))
        analyzer = await asyncio.to_thread(Analyzer,settings.spacy_model)
        gateway = MCPGateway(settings)
        await gateway.start()
        agent_model = model or DeepSeekClient(settings)
        app.state.repo = repository
        app.state.learning = LearningService(repository,settings.daily_new_limit)
        app.state.translations = TranslationService(repository,agent_model)
        app.state.agent = VocabularyAgent(repository,analyzer,agent_model,gateway,settings,app.state.translations)
        app.state.gateway = gateway
        try:
            yield
        finally:
            await gateway.close()

    app = FastAPI(title='Personal Vocabulary Management',version='1.0.0',lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=settings.allowed_hosts)

    @app.exception_handler(KeyError)
    async def missing(request,exc):
        return JSONResponse(status_code=404,content={'detail':str(exc)})

    @app.exception_handler(ValueError)
    async def invalid(request,exc):
        return JSONResponse(status_code=422,content={'detail':str(exc)})

    @app.middleware('http')
    async def basic_auth(request,call_next):
        if settings.app_username and settings.app_password:
            authorization = request.headers.get('authorization', '')
            scheme, separator, encoded_credentials = authorization.partition(' ')
            credentials = None
            if separator and scheme.lower() == 'basic' and encoded_credentials:
                try:
                    credentials = base64.b64decode(encoded_credentials, validate=True).decode('utf-8')
                except (binascii.Error, UnicodeDecodeError, ValueError):
                    pass
            if credentials is not None:
                username, separator, password = credentials.partition(':')
                if separator:
                    username_matches = secrets.compare_digest(
                        username.encode('utf-8'), settings.app_username.encode('utf-8')
                    )
                    password_matches = secrets.compare_digest(
                        password.encode('utf-8'), settings.app_password.encode('utf-8')
                    )
                    if username_matches and password_matches:
                        return await call_next(request)
            return JSONResponse(
                status_code=401,
                content={'detail':'Authentication required'},
                headers={'WWW-Authenticate':'Basic realm="Vocabulary"'},
            )
        return await call_next(request)

    @app.middleware('http')
    async def local_boundary(request,call_next):
        # Loopback binding plus same-origin writes protects the single-user API from other websites.
        if request.method not in {'GET','HEAD','OPTIONS'}:
            origin = request.headers.get('origin')
            expected = str(request.base_url).rstrip('/')
            if origin and origin!=expected:
                return JSONResponse(status_code=403,content={'detail':'Cross-origin writes are disabled'})
        response = await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        return response

    @app.get('/api/health')
    def health():
        return {'status':'ok','model':settings.deepseek_model,'model_alias':settings.deepseek_model_alias,
                'temperature':settings.deepseek_temperature,'model_configured':bool(settings.deepseek_api_key),
                'spacy_model':settings.spacy_model,'mcp_ready':bool(app.state.gateway.tools)}

    @app.post('/api/agent/stream')
    async def stream(body: AgentStreamRequest):
        return StreamingResponse(app.state.agent.stream(body),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

    @app.post('/api/agent/respond')
    async def respond(body: AgentRespondRequest):
        return StreamingResponse(app.state.agent.respond(body),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

    @app.get('/api/wiki/search')
    def search(q: str = Query(min_length=1,max_length=200),limit: int = Query(default=20,ge=1,le=100)):
        return app.state.repo.search(q,limit)

    @app.get('/api/words')
    def words(limit: int = Query(default=20,ge=1,le=100),window: str = 'all'):
        return app.state.repo.top(limit,window)

    @app.get('/api/words/all')
    def all_words(limit: int = Query(default=1000,ge=1,le=1000)):
        return app.state.repo.list_words(limit)

    @app.post('/api/words/translate')
    async def translate_missing_words():
        if not app.state.translations.available:
            raise ValueError('Set DEEPSEEK_API_KEY to generate Chinese meanings')
        return await app.state.translations.fill()

    @app.get('/api/words/{word_id}')
    def word_detail(word_id: int):
        detail = app.state.repo.word_detail(word_id)
        if not detail:
            raise HTTPException(404,'Word not found')
        for note in detail['notes']:
            note['body_html'] = render_note(note['body_md'],{link['target_word']:link['target_word_id'] for link in note['links']})
        return detail

    @app.post('/api/words',status_code=201)
    def create_word(body: WordCreateRequest):
        entry = body.model_dump(exclude={'source_id'})
        result = app.state.repo.upsert_entries([entry],body.source_id)
        if result['failed']:
            raise ValueError('Invalid word')
        return result

    @app.patch('/api/words/{word_id}')
    def update_word(word_id: int,body: WordUpdateRequest):
        return app.state.repo.update_metadata(word_id,body.model_dump(exclude_unset=True))

    @app.delete('/api/words/{word_id}',status_code=204)
    def delete_word(word_id: int):
        app.state.repo.delete_word(word_id)

    @app.post('/api/wiki/notes',status_code=201)
    def create_note(body: NoteCreateRequest):
        return app.state.repo.save_note(body.word_id,body.title,body.body_md)

    @app.put('/api/wiki/notes/{note_id}')
    def update_note(note_id: int,body: NoteUpdateRequest):
        return app.state.repo.save_note(None,body.title,body.body_md,note_id)

    @app.delete('/api/wiki/notes/{note_id}',status_code=204)
    def delete_note(note_id: int):
        app.state.repo.delete_note(note_id)

    @app.get('/api/logs')
    def logs():
        return app.state.repo.list_logs()

    @app.get('/api/logs/{log_id}')
    def log_detail(log_id: str):
        detail = app.state.repo.log_detail(log_id)
        if not detail:
            raise HTTPException(404,'Log not found')
        return detail

    @app.get('/api/learn/today')
    def today():
        return app.state.learning.today()

    @app.get('/api/learn/next')
    def next_question(question_type: str | None = None):
        if question_type and question_type not in {'en_to_zh','zh_to_en','audio_to_zh','cloze_context','spelling','definition_match'}:
            raise ValueError('Unknown question type')
        return app.state.learning.next_question(question_type)

    @app.post('/api/learn/answer')
    def answer(body: LearnAnswerRequest):
        return app.state.learning.answer(body.question_id,body.answer,body.rating,body.duration_ms)

    @app.post('/api/learn/master/{word_id}')
    def master(word_id: int):
        return app.state.learning.master(word_id)

    static = ROOT/'app'/'static'
    if static.exists():
        app.mount('/static',StaticFiles(directory=static),name='static')
        @app.get('/')
        def index():
            return FileResponse(static/'index.html')
    return app

app = create_app()
