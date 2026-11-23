# Personal Vocabulary Management

A local vocabulary library with an embedded DeepSeek Agent, Wiki notes and backlinks, full-text search, and spaced-repetition practice. Earlier Excel releases remain in `version control/` and can be imported without changing them.

## Start on Windows

Python 3.13 and internet access are needed for the first dependency/model download. The project uses an isolated `.venv`.

```powershell
# First setup or a fresh clone:
Copy-Item .env.example .env
# Edit .env and set DEEPSEEK_API_KEY, or use an existing environment variable.
powershell -ExecutionPolicy Bypass -File .\run.ps1 -Setup

# Later starts:
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

Open [the local workspace](http://127.0.0.1:8000) or [the API documentation](http://127.0.0.1:8000/docs). Add `-Port 8001` if port 8000 is occupied. Stop with Ctrl+C.

Manual setup:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.venv\Scripts\python.exe -m spacy download en_core_web_sm
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Model and runtime configuration

The system Agent uses LangChain against DeepSeek's OpenAI-compatible chat API. It does not change the model running this Codex chat.

| Setting | Default |
| --- | --- |
| `DEEPSEEK_API_BASE` | `https://api.deepseek.com/v1` |
| `DEEPSEEK_MODEL_ALIAS` | `deepseekapiv41flash`, resolved to `deepseek-flash` |
| `DEEPSEEK_TEMPERATURE` | `0.3` |
| `DATABASE_PATH` | `data/vocabulary.sqlite3` |
| `SPACY_MODEL` | `en_core_web_sm` |
| `DICTIONARY_ENABLED` | `true` |
| `DAILY_NEW_LIMIT` | `10` |
| `SESSION_TTL_SECONDS` | `1800` |

`DEEPSEEK_API_KEY` comes from the environment or local `.env`; it is never committed or returned by the API. The cloud model receives instructions, analysis summaries, selected examples, and relevant tool results. SQLite data, notes, logs, and review history stay local. Wiki and learning work without a model key; Agent requests require a working key and report failures clearly.

## Import the existing Excel vocabulary

```powershell
.venv\Scripts\python.exe -m app.import_excel "version control/v0.3/v0.3.xlsx"
```

This imports the 30 v0.3 records, English definitions, examples, topics, and the matching Chinese meanings from the supplied glossary. Excel has no encounter counts, so each imported record starts with one encounter. A file-content-based source ID prevents the same workbook from incrementing counts on retry. The original workbook is read without being changed. A changed workbook counts as a distinct source.

To refresh only the Chinese meanings in an existing database:

```powershell
.venv\Scripts\python.exe -m app.import_glossary
```

This fills only currently empty translations and does not change occurrence counts. `Difficulty` is a separate verified metadata field; the glossary does not provide exam-level labels, so it remains empty until labels are assigned explicitly.

## Use the system

- **Import & ask:** paste an article and a filter such as "top 20 verbs." Larger ambiguous imports show scope choices. Retries of unchanged input keep the same source ID.
- **Vocabulary & Wiki:** search words, meanings, examples, tags, or notes. Edit definitions and Markdown notes; navigate `[[word]]` links.
- **Learn:** get the next due question and submit an answer. The backend grades correctness and schedules review. Missing metadata or distractors produce a first-contact card without advancing the state.
- **Activity:** inspect import results and tool traces using the log ID.

Free Dictionary API adds English definitions, IPA, and optional audio. It does not provide reliable Chinese translations or exam-difficulty labels; add those explicitly when needed. Difficulty filtering uses verified labels only. All six question types are implemented and require their respective metadata. Daily quotas currently use UTC calendar days.

## API contracts

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Model/runtime settings without secrets |
| POST | `/api/agent/stream` | Agent request, SSE response |
| POST | `/api/agent/respond` | Scope response, SSE continuation |
| GET / POST | `/api/words` | Frequency ranking / manual ingestion |
| GET / PATCH / DELETE | `/api/words/{id}` | Detail, metadata edit, deletion |
| GET | `/api/wiki/search?q=...` | Full-text/prefix/substring search |
| POST | `/api/wiki/notes` | Create Markdown note |
| PUT / DELETE | `/api/wiki/notes/{id}` | Edit/delete note and backlinks |
| GET | `/api/logs` and `/api/logs/{log_id}` | Activity and traces |
| GET | `/api/learn/today` | Daily queue and statistics |
| GET | `/api/learn/next` | Question ID, prompt, and choices |
| POST | `/api/learn/answer` | Server-graded answer and next due date |
| POST | `/api/learn/master/{id}` | Mark mastered for 90 days |

Example Agent request:

```json
{
  "user_input": "Import the top 20 vocabulary words",
  "text": "Paste an English article here.",
  "thread_id": "reading-session",
  "source_id": "article-unique-id"
}
```

`text` and `source_id` extend the supplied design's minimum request. For a read-only request, omit `text` and ask, for example, "Show my top 10 words from the last 7 days." Retry unchanged ingestion with the same source ID; use a new source ID for a genuinely new encounter.

SSE types are `step`, `token`, `scope_confirm`, `clarify`, `final`, and `error`. Scope responses must include the originating `thread_id`. Structured counts come from code and the actual MCP write result.

The learning answer contract strengthens the original design: send `{"question_id":"q_...","answer":"chosen answer","rating":3,"duration_ms":1200}`. The backend grades the answer instead of trusting client-supplied `is_correct`. Ratings are `0`, `2`, `3`, and `5`; duplicate answers never advance the schedule twice.

## Architecture and tests

```text
app/
  main.py          FastAPI routes and local contract client
  agent.py         Scope and bounded LangChain tool calling
  deepseek.py      DeepSeek cloud adapter
  analysis.py      spaCy lemmas, POS, counts and filters
  tools.py         Persistent LangChain MCP Adapter sessions
  mcp_server.py    Separate read-only and read/write processes
  repository.py    Transactions, FTS, Wiki and activity
  learning.py      Six question types and scheduling
  import_excel.py  Read-only historical workbook importer
  skills/          Read, write and scope instructions
  static/          Functional browser contract client
tests/             Unit and real local-MCP integration checks
```

```powershell
# No cloud calls:
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe -m compileall -q app tests

# Explicit live check: synthetic data only, consumes DeepSeek API usage:
.venv\Scripts\python.exe -m scripts.smoke_live
```

See [the system design](docs/system-design.md) for integrity rules and limitations. SQLite `user_version` records schema version 1. An incompatible older database requires a migration rather than overwriting user data. Keep the server on loopback; public deployment requires authentication. PDF/PPT parsing, vector search, accounts, cloud sync, native apps, generated images, and audio caching remain outside v1.

## Historical materials

| Version | Files | Contents |
| --- | --- | --- |
| v0.1 | `version control/v0.1/` | Six-word Excel prototype and design |
| v0.2 | `version control/v0.2/` | 18 words, seven fields, improved filtering/layout |
| v0.3 | `version control/v0.3/` | 30 words, eight fields, usage notes |

Earlier screenshots are in `pictures/`. Source code, examples, and documentation are in English. User-provided vocabulary content may contain other languages.
