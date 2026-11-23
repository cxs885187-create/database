# Personal Vocabulary Management System v1.0

The finalized supplied design is implemented as a FastAPI backend with a lightweight local contract-verification client. Historical Excel releases are retained. SQLite is the local source of truth. Wiki and learning do not call an LLM.

## Architecture

The Agent uses spaCy pre-analysis, a DeepSeek intent/filter decision, and bounded LangChain tool calling. The model connects through `langchain-openai`; `deepseekapiv41flash` is an alias for `deepseek-flash`, with temperature `0.3`. The alias does not claim a pinned provider revision. This cloud model dependency replaces the proposal's claim of an entirely offline application.

`langchain-mcp-adapters` connects to two persistent local stdio processes. Read MCP exposes only `read_vocabulary`, opens the SQLite file using `mode=ro`, and sets `query_only`. Write MCP exposes only `write_vocabulary`, uses transactions, and optionally enriches new records through Free Dictionary API.

## Storage and integrity

- Unique lowercase words have occurrence history and a learning state.
- A unique `(word_id, source_id)` key prevents retry double-counting. A batch fingerprint rejects reuse of the same source ID for changed counts or entries. Different IDs represent new encounters.
- Ingestion fills missing metadata without overwriting curated fields. Explicit metadata changes use PATCH.
- Timestamps use one UTC ISO format, including ranking windows and learning comparisons.
- A stored-text FTS5 index uses word IDs as rowids. Application transactions synchronize words, grammatical labels, definitions, examples, contexts, tags, difficulty, and note text.
- `[[word]]` links resolve on note save and when a formerly absent target is inserted. Foreign keys handle deletions.
- IDs are UUID-based. Tool traces and action summaries are archived locally; secrets and model reasoning chains are not logged.

The schema is version 1 and is created by `app/db.py`. Future releases must add an explicit migration before changing a populated schema. This release never rewrites historical Excel workbooks.

## Agent and scope

The application calculates lemmas, frequencies, POS distribution, known-word overlap, filter output, counts, and ordering. The model selects an intent/filter and calls a tool. Executable tool arguments come from the validated code-selected batch, replacing model-suggested entries and counts. A maximum of eight tool-call attempts bounds the loop.

Explicit filters execute directly. Larger ambiguous pools ask for scope; very small inputs execute directly. Scope pools are bound to the originating chat, expire after the configured TTL, and support at most two clarification rounds. After two ambiguous replies, the default is top 30 including existing words; the final payload reports the applied filter. Difficulty labels are verified metadata, never guessed by the LLM. If labels are absent, a specific validation response requests a different filter.

The original request contract remains supported. Optional `text` separates the article from its instruction, and optional `source_id` enables safe retries. The client reuses the source ID while its input is unchanged.

Six SSE event kinds are supported: `step`, `token`, `scope_confirm`, `clarify`, `final`, and `error`. Scope confirmation uses the specified `{type, data}` envelope. Final structured statistics and highlights come from tool results. Model prose is kept separate from numeric fields; authoritative counts are appended by code. Missing credentials fail before writes. A failed summary after a successful write returns a deterministic final with a warning.

## Wiki

Markdown notes support CRUD, safe rendering, resolved internal links, and backlinks. Raw HTML is disabled and code spans are not converted to links. Search supports FTS token/prefix matching, relevance ranking, and literal word-substring fallback. It is lexical search, not vector semantics or edit-distance typo correction.

## Learning

The scheduler implements `new`, `learning`, `review`, `relearning`, and `mastered`. Minute-based steps precede day-based review. Ease has a lower bound; rating zero resets a review item into relearning. Mastered words become due after 90 days.

All six question types are present: `en_to_zh`, `zh_to_en`, `audio_to_zh`, `cloze_context`, `spelling`, and `definition_match`. Choice questions require three distinct same-POS distractors. Word choices additionally require edit distance greater than two. Cloze uses a whole-word example match and enough remaining context. Missing data removes unavailable question types; no valid scheduled type produces a first-contact card without advancing state.

Questions have private stored answers, opaque IDs, expiry, and persisted results. The answer endpoint accepts the question ID and actual answer and grades correctness on the server. This strengthens the original client-provided `is_correct` contract. Retries return the prior result without a second schedule update. Daily new-word introductions respect the quota; daily statistics currently use UTC day boundaries.

Free Dictionary API provides English definitions, IPA and optional audio. Translation-dependent questions require user-supplied Chinese meanings, and exam filters require verified difficulty labels. The system never fabricates missing metadata or silently treats a missing question as completed.

## Operating boundary

The plain browser page verifies the API contracts without a frontend framework, CDN, or build step. The startup script binds loopback. The API validates local Host headers and rejects cross-origin writes. Model calls use the cloud; SQLite, notes, traces, and review history are local. There is no multi-user authentication or cloud synchronization.

PDF/PPT parsing, embeddings, native apps, picture questions, public deployment, and audio caching remain outside v1. These exclusions follow the supplied scope rather than adding a separate system.
