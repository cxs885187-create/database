# Personal Vocabulary Management System Implementation Plan

**Goal:** Build a runnable local vocabulary management system whose Agent uses the DeepSeek cloud API through an OpenAI-compatible adapter with `temperature=0.3`.

**Architecture:** A FastAPI application owns deterministic analysis, SQLite persistence, Wiki CRUD/search, and SM-2+ learning endpoints. Two independent stdio MCP processes expose read-only and transactional write operations to the LangChain Agent; the Agent calls DeepSeek only for intent decisions and human-readable summaries, while all counts, filters, IDs, and writes remain code-controlled.

**Tech Stack:** Python 3.13, FastAPI, Uvicorn, SQLite FTS5, LangChain, langchain-openai, langchain-mcp-adapters, MCP SDK, spaCy with en_core_web_sm, Pydantic, httpx, pytest, vanilla HTML/CSS/JavaScript.

---

### Task 1: Application foundation and configuration

**Files:**
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `run.ps1`

- [x] Define environment-backed settings for `DEEPSEEK_API_KEY`, `DEEPSEEK_API_BASE`, `DEEPSEEK_MODEL_ALIAS`, `DEEPSEEK_TEMPERATURE`, `DATABASE_PATH`, and `DICTIONARY_ENABLED`.
- [x] Resolve `deepseekapiv41flash` to the canonical `deepseek-flash` ID without hard-coding the API key.
- [x] Add a one-command Windows startup script and dependency list.

### Task 2: SQLite repository and schema

**Files:**
- Create: `app/db.py`
- Create: `app/repository.py`

- [x] Create the `words`, `occurrences`, `words_fts`, `word_notes`, `note_links`, `learning_states`, `review_events`, `logs`, and `agent_traces` tables with indexes.
- [x] Implement transactional vocabulary UPSERTs, occurrence logging, FTS synchronization, lookup/top/log reads, and note/link persistence.
- [x] Implement learning-state reads and writes without allowing terminal audit data to drive business logic.

### Task 3: Deterministic analysis and tool boundary

**Files:**
- Create: `app/analysis.py`
- Create: `app/tools.py`

- [x] Implement spaCy tokenization, lemma normalization, POS tagging, frequency counts, existing-word lookup, and deterministic filter application.
- [x] Expose JSON-shaped read/write contracts through separate stdio MCP processes using LangChain MCP Adapter, with no LLM-dependent calculations.
- [x] Preserve source/context IDs and return exact new/updated/failed counts from repository operations.

### Task 4: DeepSeek Agent and SSE contracts

**Files:**
- Create: `app/deepseek.py`
- Create: `app/agent.py`
- Create: `app/schemas.py`

- [x] Implement an async LangChain ChatOpenAI DeepSeek client using the resolved model and temperature 0.3.
- [x] Implement scope policy, session-held analysis pools, max-two scope rounds, deterministic writes, and summary generation with code-injected stats.
- [x] Emit `step`, `token`, `scope_confirm`, `clarify`, `final`, and `error` SSE events.

### Task 5: FastAPI endpoints and static client

**Files:**
- Create: `app/main.py`
- Create: `app/static/index.html`
- Create: `app/static/app.js`
- Create: `app/static/styles.css`

- [x] Add Agent stream/respond endpoints, Wiki search/note endpoints, word detail, learning today/next/answer/master endpoints, and health endpoint.
- [x] Serve a minimal static page that can submit an article, display SSE events, search the Wiki, and answer a review question.
- [x] Keep the frontend as a contract verifier rather than a separate framework or visual redesign.

### Task 6: Tests and documentation

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_analysis.py`
- Create: `tests/test_repository.py`
- Create: `tests/test_api.py`
- Modify: `README.md`

- [x] Test alias resolution, deterministic counts/filters, idempotent writes, FTS search, note backlinks, and learning transitions.
- [x] Mock DeepSeek in API tests and verify SSE event shapes and scope confirmation behavior.
- [x] Document setup, environment variables, startup, endpoint examples, and the model mapping.

### Task 7: Verification and delivery

- [x] Run the full pytest suite and import/compile checks.
- [x] Start Uvicorn, call `/api/health`, and exercise an Agent request with a mocked or configured DeepSeek path.
- [x] Review Git diff, preserve unrelated user changes, commit the implementation, and push to `origin/master`.

## Execution notes

The user requested installation of the specified dependencies rather than simplified replacements. LangChain, MCP Adapter, MCP SDK 1.x, spaCy, and the English model were installed in .venv and are used in the implementation. Twenty-five local tests and a real synthetic DeepSeek-to-MCP ingestion check passed. Browser verification identified a ranking limit mismatch, which now has a regression test. The original local v0.2 workbook modification remains outside the implementation commit.
