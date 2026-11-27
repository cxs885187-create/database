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
| `AUTO_TRANSLATE` | `true` |

`DEEPSEEK_API_KEY` comes from the environment or local `.env`; it is never committed or returned by the API. The cloud model receives instructions, analysis summaries, selected examples, and relevant tool results. SQLite data, notes, logs, and review history stay on the machine running the app. Wiki and learning work without a model key; Agent requests require a working key and report failures clearly.

## Server demo

The server demo keeps its SQLite database at `/srv/database/data/vocabulary.sqlite3`. Its server-only `.env` sets `DATABASE_PATH`, `APP_USERNAME`, `APP_PASSWORD`, and `ALLOWED_HOSTS=82.156.102.68`. Keep the `.env` private and out of Git. The public demo uses HTTP on port 8088; its generated password is for this demo only because HTTP does not encrypt credentials or traffic.

## Import the existing Excel vocabulary

```powershell
.venv\Scripts\python.exe -m app.import_excel "version control/v0.3/v0.3.xlsx"
```

This imports the 30 v0.3 records, English definitions, examples, topics, and the matching Chinese meanings from the supplied glossary. Excel has no encounter counts, so each imported record starts with one encounter. A file-content-based source ID prevents the same workbook from incrementing counts on retry. The original workbook is read without being changed. A changed workbook counts as a distinct source.

To refresh only the Chinese meanings in an existing database:

```powershell
.venv\Scripts\python.exe -m app.import_glossary
```

### Chinese meanings

Free Dictionary API supplies English definitions only, so an imported word would otherwise show an empty `Translation` cell. Three mechanisms fill it:

1. **Automatic.** After a successful ingest the Agent translates the words it just wrote and stores the glosses. This is what `AUTO_TRANSLATE` controls; the count appears as `translated_words` in the result stats.
2. **On demand.** The **Add Chinese meanings** button in *Vocabulary & Wiki* translates every word that still has no meaning.
3. **From the command line.**

```powershell
# every word without a meaning
.venv\Scripts\python.exe -m app.fill_translations

# specific words, replacing an existing gloss
.venv\Scripts\python.exe -m app.fill_translations --words library,uni --overwrite
```

Generated meanings never overwrite text you typed, and `--overwrite` only touches the words you name. Glosses come back as one short Simplified Chinese phrase per word; the English definition is passed as a hint, and the model is told to prefer the common modern sense over an archaic dictionary entry.

This fills only currently empty translations and does not change occurrence counts. `Difficulty` is a separate verified metadata field; the glossary does not provide exam-level labels, so it remains empty until labels are assigned explicitly.

## Use the system

- **Import & ask:** paste an article and a filter such as "top 20 verbs." Larger ambiguous imports show scope choices. Retries of unchanged input keep the same source ID.
- **Vocabulary & Wiki:** search words, meanings, examples, tags, or notes. Edit definitions and Markdown notes; navigate `[[word]]` links. Set each word's study difficulty directly in the table.
- **Import & ask:** paste an article and a filter such as "top 20 verbs." Larger ambiguous imports show scope choices. Retries of unchanged input keep the same source ID. A topic request instead of an article, such as "和计算机相关的词语", is answered by searching the stored library rather than by inventing words; the Agent cannot create vocabulary that no article supplied.
- **Vocabulary & Wiki:** search words, meanings, examples, tags, or notes. Edit definitions and Markdown notes; navigate `[[word]]` links.
- **Learn:** get the next due question and submit an answer. The backend grades correctness and schedules review using the selected study difficulty. Missing metadata or distractors produce a first-contact card without advancing the state.
- **Activity:** inspect import results and tool traces using the log ID.

Free Dictionary API adds English definitions, IPA, and optional audio. Its Chinese translations are absent, so glosses come from the model as described above. Difficulty filtering uses verified labels only. All six question types are implemented and require their respective metadata. Daily quotas currently use UTC calendar days.

### Study difficulty and review schedule

Study difficulty is separate from the exam-level `Difficulty` metadata used by vocabulary filters. In the vocabulary table, choose **Hard**, **Medium**, or **Easy**; an unset word behaves as Medium. Completing the learning steps schedules the first review after 1, 2, or 3 days, respectively. Later successful reviews apply a `0.7`, `1.0`, or `1.3` multiplier to the existing SM-2-style interval calculation, so harder words return sooner and easier words less often. Failed answers retain the existing short relearning steps. A difficulty change affects intervals calculated by subsequent answers; it does not rewrite an already scheduled due date.

## API contracts

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Model/runtime settings without secrets |
| POST | `/api/agent/stream` | Agent request, SSE response |
| POST | `/api/agent/respond` | Scope response, SSE continuation |
| GET / POST | `/api/words` | Frequency ranking / manual ingestion |
| POST | `/api/words/translate` | Fill missing Chinese meanings with the model |
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

See [the system design](docs/system-design.md) for integrity rules and limitations. SQLite `user_version` records schema version 2; existing version 1 databases add the study-difficulty field without replacing vocabulary or review data. An incompatible older database requires a migration rather than overwriting user data. Keep the server on loopback; public deployment requires authentication. PDF/PPT parsing, vector search, accounts, cloud sync, native apps, generated images, and audio caching remain outside v1.

## Troubleshooting a failed Agent request

The header status line reports whether the model is configured. When it reads "Cannot reach the local server", the page was loaded without a running backend: start `run.ps1`, then reload. The browser keeps a cached copy of the UI, so a stopped server does not blank the page.

Every Agent failure writes its real exception to `logs/agent-errors.log` (rotated at 1 MB, ignored by Git). The browser message stays short by design, so read that file first when a request fails.

| Browser message | Meaning |
| --- | --- |
| `Set DEEPSEEK_API_KEY to enable the Agent.` | No key in the environment or `.env`. |
| `The model call timed out.` | The request reached DeepSeek but exceeded the 90 s budget twice. |
| `The model endpoint could not be reached.` | DNS, TLS or proxy failure before DeepSeek answered. |
| `The model returned an unusable decision.` | Two replies were not valid JSON for the decision schema. |
| `Agent request failed. Check model connectivity...` | An unclassified exception; the log has the traceback. |

Retry with the same `source_id` after fixing the cause: unchanged input keeps one source fingerprint, so a successful retry updates counts instead of duplicating rows.

A `NO_PROXY` entry containing a bracketed IPv6 address such as `[::1]` makes `httpx` 0.28 abort client creation, which surfaces as a hard failure on any new HTTP client. The adapter strips those entries at startup and logs one `Removed N unsupported bracketed entry` line in `logs/agent-errors.log`.

To start the server detached from a shell instead of in the foreground:

```powershell
.venv\Scripts\python.exe -m scripts.start_server
```

## Historical materials

| Version | Files | Contents |
| --- | --- | --- |
| v0.1 | `version control/v0.1/` | Six-word Excel prototype and design |
| v0.2 | `version control/v0.2/` | 18 words, seven fields, improved filtering/layout |
| v0.3 | `version control/v0.3/` | 30 words, eight fields, usage notes |

Earlier screenshots are in `pictures/`. Source code, examples, and documentation are in English. User-provided vocabulary content may contain other languages.
