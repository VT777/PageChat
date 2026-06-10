# Phase 1 Safety, Scope, And Retrieval Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the shared safety, database migration, user-scope, cache-isolation, and retrieval-metadata foundation required before multi-format expansion, frontend production redesign, or user-configurable model settings.

**Architecture:** Keep the current FastAPI/PageIndex workflow intact while hardening its shared boundaries. Add a lightweight migration runner, make user scope explicit in service and tool calls, fail closed when scope is missing, normalize retrieval metadata and source anchors without removing existing response fields, and add tests that prevent cross-user leakage and cache contamination.

**Tech Stack:** FastAPI backend, aiosqlite/SQLite, existing `DocumentService`, `ToolExecutor`, `AgentService`, `ChatService`, `DocumentSearchService`, `CacheService`, pytest, current frontend only for compatibility checks.

---

## Why This Plan Exists

The 2026-06-10 plans overlap in four critical areas:

- User and document authorization.
- Search and retrieval scope.
- Source anchor and retrieval trace metadata.
- Database schema evolution.

Those boundaries must be stabilized first. This plan deliberately does not implement the full multi-format adapter rewrite, model provider settings, frontend redesign, legacy Office conversion, or a new retrieval planner. It creates the contracts those later plans can safely build on.

## Source Plans Consolidated

This plan consolidates the first-phase requirements from:

- `<source-plan-copy>\docs\superpowers\plans\2026-06-10-user-configurable-models.md`
- `<source-plan-copy>\docs\superpowers\plans\2026-06-10-core-tree-retrieval-quality-plan.md`
- `<source-plan-copy>\docs\superpowers\plans\2026-06-10-agent-retrieval-improvement-plan.md`
- `<source-plan-copy>\docs\superpowers\plans\2026-06-10-multi-format-document-support-plan.md`
- `<source-plan-copy>\docs\superpowers\plans\2026-06-10-frontend-design-plan.md`

## Current Code Facts

Current implementation details verified in this workspace:

- `backend/app/services/tool_executor.py`
  - `ToolExecutor.allowed_doc_ids` defaults to `None`.
  - `_is_doc_allowed()` currently returns `True` when `allowed_doc_ids is None`.
  - Tool methods call `DocumentService.get_document(doc_id)` without `user_id`.
  - `_list_documents()` and `_aggregate_tables()` call `get_indexed_documents()` without mandatory user scope.

- `backend/app/services/document_service.py`
  - `get_document(doc_id, user_id=None)` supports user filtering but does not require it.
  - `get_indexed_documents(user_id=None)` supports user filtering but does not require it.
  - `save_document()` writes uploaded files as `DOCUMENTS_DIR / f"{doc_id}_{filename}"`.
  - `validate_file()` checks extension and file size but does not reject path separators or unsafe names.

- `backend/app/services/search_service.py`
  - `DocumentSearchService` has a global corpus.
  - `search(..., allowed_doc_ids=None)` exists, but user scope is not mandatory.
  - query expansion cache is keyed by query text only.

- `backend/app/services/agent_service.py`
  - The per-conversation cache is keyed by `conversation_id` and tool arguments, not user/scope.
  - `AgentService.__init__()` creates `ToolExecutor(...)` without a user id.

- `backend/app/models/database.py`
  - `init_db()` uses `CREATE TABLE IF NOT EXISTS`.
  - There is no migration history table.
  - SQLite foreign keys are not explicitly enabled in the visible initialization path.

- `backend/app/services/cache_service.py`
  - document structure cache is keyed by `doc_id`.
  - page content cache is keyed by `doc_id`, page number, and image flag.
  - search cache is keyed by query and doc ids.

## Design Decisions For Phase 1

1. User scope is mandatory at API-facing service boundaries.
2. `allowed_doc_ids` is a narrower document subset, not the primary authorization mechanism.
3. Missing user scope fails closed in `ToolExecutor` and search entry points.
4. Existing response fields such as `start_index`, `end_index`, `relevance`, and page-based citation fields remain for compatibility.
5. New retrieval metadata is additive: `retrieval_source`, `confidence`, `why_selected`, `source_anchor`, and `display_label`.
6. `needs_review` is not introduced as a top-level document status in this phase. Later quality work may store it in `quality_report.status`.
7. Database migrations are lightweight and local. Do not introduce Alembic in this phase.
8. Uploaded file storage names use `{doc_id}{extension}`. Original filenames remain metadata only.

## Target Contracts

### Retrieval Scope

Create a simple backend model or dataclass:

```python
@dataclass(frozen=True)
class RetrievalScope:
    user_id: str
    allowed_doc_ids: Optional[tuple[str, ...]] = None

    def __post_init__(self):
        if not self.user_id:
            raise ValueError("user_id is required")

    @property
    def cache_key(self) -> str:
        ids = sorted(self.allowed_doc_ids or ())
        return json.dumps({"user_id": self.user_id, "allowed_doc_ids": ids}, sort_keys=True)
```

Rules:

- `user_id` is required.
- `allowed_doc_ids=None` means all documents owned by this user, not all documents globally.
- `allowed_doc_ids=[]` means no documents are allowed.

### Source Anchor

Normalize toward this additive shape:

```json
{
  "format": "pdf",
  "unit_type": "page",
  "start_page": 12,
  "end_page": 15
}
```

Supported first-phase anchor types:

- PDF: `{"format": "pdf", "unit_type": "page", "start_page": 1, "end_page": 1}`
- Markdown/TXT: `{"format": "markdown", "unit_type": "line", "start_line": 20, "end_line": 42}`
- DOCX: `{"format": "docx", "unit_type": "paragraph", "start_paragraph": 10, "end_paragraph": 18}`
- CSV/TSV/XLSX: `{"format": "xlsx", "unit_type": "row_range", "sheet": "Sheet1", "start_row": 2, "end_row": 80}`
- PPTX: `{"format": "pptx", "unit_type": "slide", "start_slide": 7, "end_slide": 7}`

### Retrieval Result Metadata

Every retrieval result should add:

```json
{
  "retrieval_source": "document_search",
  "confidence": 0.82,
  "why_selected": "Matched node title and summary.",
  "source_anchor": {},
  "display_label": "report.pdf p.12-15"
}
```

Allowed `retrieval_source` values in phase 1:

- `tree_reasoning`
- `document_search`
- `visual_summary`
- `table_schema`
- `keyword_fallback`
- `manual_scope`

## Proposed File Structure

Create:

- `backend/app/models/retrieval.py`
  - `RetrievalScope`
  - `SourceAnchor`
  - `RetrievalTrace`
  - display label helpers

- `backend/app/models/migrations.py`
  - migration registry
  - `run_migrations(db)`
  - idempotent migration helpers

- `backend/tests/test_database_migrations.py`
  - migration table creation
  - idempotency
  - `documents.last_reindex_at`
  - core indexes

- `backend/tests/test_safe_upload_filenames.py`
  - filename validation and storage-name behavior

- `backend/tests/test_tool_executor_scope.py`
  - fail-closed tool authorization
  - cross-user access rejection

- `backend/tests/test_search_scope.py`
  - mandatory user scope
  - allowed subset behavior
  - query cache isolation

- `backend/tests/test_cache_scope_keys.py`
  - user-aware cache keys
  - document-derived cache invalidation shape

- `backend/tests/test_retrieval_trace_contract.py`
  - additive metadata on search and fallback results

Modify:

- `backend/app/models/database.py`
  - enable foreign keys per connection
  - call migration runner

- `backend/app/services/document_service.py`
  - safe upload filename handling
  - helper methods that require `user_id` for API-facing reads

- `backend/app/services/tool_executor.py`
  - require `user_id`
  - pass `user_id` into document service calls
  - fail closed if constructed without scope
  - add retrieval/source metadata where results are produced

- `backend/app/services/chat_service.py`
  - pass `user_id` into `AgentService`/tool execution flow

- `backend/app/services/agent_service.py`
  - construct scoped `ToolExecutor`
  - include user/scope in conversation cache keys

- `backend/app/services/search_service.py`
  - require `user_id` in search calls
  - filter corpus by user before scoring
  - include user/scope in query expansion cache key

- `backend/app/services/cache_service.py`
  - include `user_id` in structure/page/search cache keys
  - preserve compatibility wrappers only if all call sites are updated in this phase

- `backend/app/services/folder_service.py`
  - collect document records before recursive folder deletion
  - use document cleanup helper or equivalent file/index cleanup

## Task 1: Add Lightweight Database Migrations

**Files:**

- Create: `backend/app/models/migrations.py`
- Modify: `backend/app/models/database.py`
- Test: `backend/tests/test_database_migrations.py`

- [ ] **Step 1: Write failing migration tests**

Create tests that initialize a temporary SQLite database and assert:

- `schema_migrations` table is created.
- migrations are recorded exactly once.
- `documents.last_reindex_at` exists after migration.
- running migrations twice is safe.
- common indexes exist.

Example test shape:

```python
async def test_migrations_are_idempotent(tmp_path):
    db_path = tmp_path / "app.db"
    async with aiosqlite.connect(db_path) as db:
        await bootstrap_schema(db)
        await run_migrations(db)
        await run_migrations(db)

        cursor = await db.execute("SELECT id FROM schema_migrations")
        rows = await cursor.fetchall()
        assert len(rows) == len({row[0] for row in rows})
```

Run:

```powershell
cd backend
pytest tests/test_database_migrations.py -v
```

Expected before implementation: FAIL because `migrations.py` does not exist.

- [ ] **Step 2: Implement migration registry**

Create migrations for:

- `20260610_001_add_documents_last_reindex_at`
- `20260610_002_add_core_indexes`

Core indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_documents_user_status_updated
ON documents(user_id, status, updated_at);

CREATE INDEX IF NOT EXISTS idx_documents_user_folder_updated
ON documents(user_id, folder_id, updated_at);

CREATE INDEX IF NOT EXISTS idx_folders_user_parent
ON folders(user_id, parent_id);

CREATE INDEX IF NOT EXISTS idx_folders_user_path
ON folders(user_id, path);

CREATE INDEX IF NOT EXISTS idx_conversations_user_created
ON conversations(user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
ON messages(conversation_id, created_at);
```

- [ ] **Step 3: Enable SQLite foreign keys**

In database connection setup, execute:

```python
await db.execute("PRAGMA foreign_keys=ON")
```

Do this in `init_db()` and `get_db()` so every app connection enforces foreign keys.

- [ ] **Step 4: Call migrations after bootstrap tables**

Keep `CREATE TABLE IF NOT EXISTS` as bootstrap. After bootstrap table creation, call:

```python
from app.models.migrations import run_migrations
await run_migrations(db)
```

- [ ] **Step 5: Run migration tests**

```powershell
cd backend
pytest tests/test_database_migrations.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/models/database.py backend/app/models/migrations.py backend/tests/test_database_migrations.py
git commit -m "feat: add lightweight database migrations"
```

## Task 2: Normalize Uploaded Filenames And Storage Paths

**Files:**

- Modify: `backend/app/services/document_service.py`
- Test: `backend/tests/test_safe_upload_filenames.py`

- [ ] **Step 1: Write failing filename safety tests**

Cover:

- `../secret.pdf` is rejected.
- `folder\secret.pdf` is rejected.
- `folder/secret.pdf` is rejected.
- filenames containing null bytes or control characters are rejected.
- Windows reserved names such as `CON.pdf` and `NUL.txt` are rejected.
- normal Unicode display names are accepted.
- storage path is `{doc_id}{extension}`, not `{doc_id}_{filename}`.

Run:

```powershell
cd backend
pytest tests/test_safe_upload_filenames.py -v
```

Expected before implementation: FAIL.

- [ ] **Step 2: Add filename normalization helper**

Add private helpers to `DocumentService`:

```python
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

def _normalize_upload_display_name(filename: str) -> str:
    if not filename:
        raise ValueError("文件名不能为空")
    if "\x00" in filename or any(ord(ch) < 32 for ch in filename):
        raise ValueError("文件名包含非法控制字符")
    if "/" in filename or "\\" in filename:
        raise ValueError("文件名不能包含路径分隔符")
    name = Path(filename).name.strip()
    if not name or name in {".", ".."}:
        raise ValueError("文件名无效")
    stem = Path(name).stem.upper()
    if stem in WINDOWS_RESERVED_NAMES:
        raise ValueError("文件名为系统保留名称")
    return name
```

- [ ] **Step 3: Update `validate_file()`**

Call the helper before checking extension and size.

- [ ] **Step 4: Update `save_document()` storage path**

Use:

```python
display_name = self._normalize_upload_display_name(filename)
ext = Path(display_name).suffix.lower()
file_path = DOCUMENTS_DIR / f"{doc_id}{ext}"
```

Store `display_name` in `name` and `original_name`.

- [ ] **Step 5: Run tests**

```powershell
cd backend
pytest tests/test_safe_upload_filenames.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/document_service.py backend/tests/test_safe_upload_filenames.py
git commit -m "fix: normalize uploaded file storage names"
```

## Task 3: Add Retrieval Scope Models And Display Label Helpers

**Files:**

- Create: `backend/app/models/retrieval.py`
- Test: `backend/tests/test_retrieval_models.py`

- [ ] **Step 1: Write failing model tests**

Cover:

- `RetrievalScope(user_id="")` raises.
- `allowed_doc_ids=None` means user-wide scope.
- `allowed_doc_ids=[]` means empty explicit subset.
- cache key differs by user.
- cache key differs by allowed doc set.
- PDF label is `report.pdf p.12-15`.
- Markdown label is `notes.md lines 20-42`.
- DOCX label is `contract.docx paragraphs 10-18`.
- XLSX label is `sales.xlsx Sheet1 rows 2-80`.
- PPTX label is `deck.pptx slide 7`.

Run:

```powershell
cd backend
pytest tests/test_retrieval_models.py -v
```

Expected before implementation: FAIL.

- [ ] **Step 2: Implement dataclasses**

Add:

- `RetrievalScope`
- `SourceAnchor`
- `RetrievalTrace`

Keep these dependency-light. Do not import service modules here.

- [ ] **Step 3: Implement display labels**

Add:

```python
def build_source_display_label(document_name: str, anchor: Mapping[str, Any]) -> str:
    ...
```

Return stable fallback text if an anchor is incomplete:

```text
report.pdf source unavailable
```

- [ ] **Step 4: Run tests**

```powershell
cd backend
pytest tests/test_retrieval_models.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/models/retrieval.py backend/tests/test_retrieval_models.py
git commit -m "feat: add retrieval scope and source anchor models"
```

## Task 4: Make ToolExecutor Fail Closed With Mandatory User Scope

**Files:**

- Modify: `backend/app/services/tool_executor.py`
- Modify: `backend/app/services/agent_service.py`
- Modify: `backend/app/services/chat_service.py`
- Test: `backend/tests/test_tool_executor_scope.py`

- [ ] **Step 1: Write failing authorization tests**

Cover:

- constructing `ToolExecutor` without `user_id` raises `ValueError`.
- user A cannot call `get_document_structure` for user B's document.
- user A cannot call `get_page_content` for user B's document.
- `list_documents` returns only user A's documents.
- `aggregate_tables` silently ignores or rejects out-of-scope documents and reports the rejected ids.
- `allowed_doc_ids=[]` allows no documents.
- `allowed_doc_ids=None` allows all indexed documents for that user only.

Run:

```powershell
cd backend
pytest tests/test_tool_executor_scope.py -v
```

Expected before implementation: FAIL.

- [ ] **Step 2: Update ToolExecutor constructor**

Change constructor shape to:

```python
def __init__(
    self,
    pageindex_service: PageIndexService,
    document_service: DocumentService,
    user_id: str,
    allowed_doc_ids: Optional[List[str]] = None,
):
    if not user_id:
        raise ValueError("ToolExecutor requires user_id")
    self.user_id = user_id
    self.allowed_doc_ids = set(allowed_doc_ids) if allowed_doc_ids is not None else None
```

Keep `set_allowed_doc_ids()` only if existing call sites still need it, but it must not remove user scope.

- [ ] **Step 3: Change `_is_doc_allowed()` semantics**

Use:

```python
def _is_doc_allowed(self, doc_id: str) -> bool:
    if self.allowed_doc_ids is None:
        return True
    return doc_id in self.allowed_doc_ids
```

This method only checks subset scope. Ownership must be enforced by `DocumentService.get_document(doc_id, user_id=self.user_id)`.

- [ ] **Step 4: Pass `user_id` into all document reads**

Update:

- `_get_document_structure()`
- `_get_page_content()`
- `_get_document_image()`
- `_list_documents()`
- `_aggregate_tables()`
- `_find_related_documents()`

Use:

```python
doc = await self.document_service.get_document(doc_id, user_id=self.user_id)
docs = await self.document_service.get_indexed_documents(user_id=self.user_id)
```

- [ ] **Step 5: Update AgentService construction**

Do not keep a permanently scoped `ToolExecutor` on `self` if one `AgentService` instance can serve different users.

Preferred:

```python
tool_executor = ToolExecutor(
    self.pageindex_service,
    self.document_service,
    user_id=user_id,
    allowed_doc_ids=document_ids,
)
```

inside `run_agent_stream()`.

Add `user_id` to `AgentService.run_agent_stream(...)` and pass it from `ChatService.stream_chat(...)`.

- [ ] **Step 6: Run tests**

```powershell
cd backend
pytest tests/test_tool_executor_scope.py tests/test_find_related_documents_modes.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/services/tool_executor.py backend/app/services/agent_service.py backend/app/services/chat_service.py backend/tests/test_tool_executor_scope.py
git commit -m "fix: require user scope for agent tools"
```

## Task 5: Make Search Scope Mandatory And User-Aware

**Files:**

- Modify: `backend/app/services/search_service.py`
- Modify: `backend/app/services/tool_executor.py`
- Test: `backend/tests/test_search_scope.py`

- [ ] **Step 1: Write failing search scope tests**

Cover:

- `search(query="x", user_id=None)` raises `ValueError`.
- user A search does not return user B documents.
- `allowed_doc_ids` narrows results inside user A's documents.
- query expansion cache differs between users.
- index snapshot can report user-scoped counts.

Run:

```powershell
cd backend
pytest tests/test_search_scope.py -v
```

Expected before implementation: FAIL.

- [ ] **Step 2: Add `user_id` parameter to search API**

Change:

```python
async def search(..., user_id: str, allowed_doc_ids: Optional[List[str]] = None, ...)
```

Validate:

```python
if not user_id:
    raise ValueError("user_id is required for document search")
```

- [ ] **Step 3: Include user metadata in corpus records**

During `rebuild_index()`, store `user_id`, `folder_id`, and `folder_path` in document/segment metadata.

- [ ] **Step 4: Filter by user before scoring**

Build candidate segment indexes from records where:

```python
segment["user_id"] == user_id
```

Then apply `allowed_doc_ids` if provided.

- [ ] **Step 5: Scope query expansion cache**

Change query cache key from query text only to:

```python
cache_key = (user_id, query)
```

If model settings later become per-user, extend this to include model route/settings version.

- [ ] **Step 6: Update ToolExecutor call sites**

Update `_find_related_documents()` to call:

```python
response = await search_service.search(
    query=query,
    user_id=self.user_id,
    allowed_doc_ids=list(self.allowed_doc_ids) if self.allowed_doc_ids is not None else None,
    ...
)
```

- [ ] **Step 7: Run tests**

```powershell
cd backend
pytest tests/test_search_scope.py tests/test_find_related_documents_modes.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add backend/app/services/search_service.py backend/app/services/tool_executor.py backend/tests/test_search_scope.py
git commit -m "fix: require user scope for document search"
```

## Task 6: Add User-Aware Cache Keys

**Files:**

- Modify: `backend/app/services/cache_service.py`
- Modify: `backend/app/services/tool_executor.py`
- Modify: `backend/app/services/agent_service.py`
- Test: `backend/tests/test_cache_scope_keys.py`

- [ ] **Step 1: Write failing cache tests**

Cover:

- structure cache entries for same `doc_id` and different users do not collide.
- page content cache entries for same `doc_id` and different users do not collide.
- search result cache entries differ by user.
- per-conversation agent cache differs when scope changes.

Run:

```powershell
cd backend
pytest tests/test_cache_scope_keys.py -v
```

Expected before implementation: FAIL.

- [ ] **Step 2: Update CacheService methods**

Change method signatures:

```python
def get_structure(self, user_id: str, doc_id: str) -> Optional[Dict]:
def set_structure(self, user_id: str, doc_id: str, structure: Dict):
def get_page_content(self, user_id: str, doc_id: str, page_num: int, include_image: bool) -> Optional[Dict[str, Any]]:
def set_page_content(self, user_id: str, doc_id: str, page_num: int, include_image: bool, result: Dict[str, Any]):
def get_search_result(self, user_id: str, query: str, doc_ids: List[str]) -> Optional[List[Dict]]:
def set_search_result(self, user_id: str, query: str, doc_ids: List[str], results: List[Dict]):
```

- [ ] **Step 3: Update call sites**

Update `ToolExecutor` and any other callers to pass `self.user_id`.

- [ ] **Step 4: Update AgentService per-conversation cache**

Include user and scope in cache keys:

```python
scope_key = RetrievalScope(user_id=user_id, allowed_doc_ids=tuple(document_ids or ())).cache_key
cache_key = f"{scope_key}:{tool_name}:{json.dumps(norm_args, sort_keys=True)}"
```

Also include scope in `_CONVERSATION_MESSAGES` key or explicitly reset messages when the same conversation is used with a different scope.

- [ ] **Step 5: Run tests**

```powershell
cd backend
pytest tests/test_cache_scope_keys.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/cache_service.py backend/app/services/tool_executor.py backend/app/services/agent_service.py backend/tests/test_cache_scope_keys.py
git commit -m "fix: scope document caches by user"
```

## Task 7: Add Retrieval Trace Metadata To Existing Results

**Files:**

- Modify: `backend/app/services/pageindex_service.py`
- Modify: `backend/app/services/search_service.py`
- Modify: `backend/app/services/tool_executor.py`
- Test: `backend/tests/test_retrieval_trace_contract.py`

- [ ] **Step 1: Write failing retrieval trace tests**

Assert that results from existing search/tool paths include:

- `retrieval_source`
- `confidence`
- `why_selected` or equivalent reasoning text
- `source_anchor` when page/range data exists
- `display_label` when document name and anchor exist

Run:

```powershell
cd backend
pytest tests/test_retrieval_trace_contract.py -v
```

Expected before implementation: FAIL.

- [ ] **Step 2: Normalize document search results**

In `DocumentSearchService.search()`, add metadata for node/segment results:

```python
"retrieval_source": "document_search",
"confidence": normalized_score,
"why_selected": "Matched document search index.",
```

Keep existing fields such as `score`, `relevance`, `start_index`, and `end_index`.

- [ ] **Step 3: Normalize tool output**

In `_find_related_documents()`, propagate metadata into:

- `related_documents`
- `matched_segments`
- `metadata`

- [ ] **Step 4: Add anchor helper for existing page ranges**

When a result has PDF-like `start_index` / `end_index`, add:

```python
source_anchor = {
    "format": doc.file_type.lstrip(".") or "pdf",
    "unit_type": "page",
    "start_page": start_index,
    "end_page": end_index,
}
```

For non-PDF adapter results that already include `source_anchor`, preserve it.

- [ ] **Step 5: Normalize fallback paths**

For simple or keyword fallback results in `PageIndexService`, add:

```python
"retrieval_source": "keyword_fallback",
"confidence": relevance,
"why_selected": "Matched fallback keyword search.",
```

For visual summary results, use:

```python
"retrieval_source": "visual_summary"
```

- [ ] **Step 6: Run tests**

```powershell
cd backend
pytest tests/test_retrieval_trace_contract.py tests/test_find_related_documents_modes.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/services/pageindex_service.py backend/app/services/search_service.py backend/app/services/tool_executor.py backend/tests/test_retrieval_trace_contract.py
git commit -m "feat: add retrieval trace metadata"
```

## Task 8: Fix Folder Deletion Cleanup Boundary

**Files:**

- Modify: `backend/app/services/document_service.py`
- Modify: `backend/app/services/folder_service.py`
- Modify: `backend/app/services/cache_service.py`
- Test: `backend/tests/test_folder_delete_cleanup.py`

- [ ] **Step 1: Write failing folder cleanup tests**

Cover:

- deleting a folder removes child document DB rows.
- deleting a folder removes source files.
- deleting a folder removes index files.
- deleting user A's folder does not remove user B's files with similar folder names.
- relevant document caches are invalidated.

Run:

```powershell
cd backend
pytest tests/test_folder_delete_cleanup.py -v
```

Expected before implementation: FAIL because folder deletion currently deletes DB rows directly.

- [ ] **Step 2: Add document cleanup helper**

In `DocumentService`, add a helper such as:

```python
async def cleanup_document_artifacts(self, doc: DocumentResponse) -> None:
    ...
```

It should remove:

- `doc.file_path`
- `doc.index_path` when present
- default index path under `backend/data/indexes/{doc.id}.json` if used by existing code

It must not delete paths outside configured data directories.

- [ ] **Step 3: Update folder deletion**

Before deleting DB rows, query the target documents for `user_id` and collect file/index paths. Then call cleanup helper for each document.

- [ ] **Step 4: Invalidate caches**

Add a targeted cache invalidation helper:

```python
def clear_document(self, user_id: str, doc_id: str) -> None:
    ...
```

Call it for each deleted document.

- [ ] **Step 5: Run tests**

```powershell
cd backend
pytest tests/test_folder_delete_cleanup.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/document_service.py backend/app/services/folder_service.py backend/app/services/cache_service.py backend/tests/test_folder_delete_cleanup.py
git commit -m "fix: clean document artifacts on folder delete"
```

## Task 9: Verification Sweep

**Files:**

- No planned source edits unless tests reveal an issue.

- [ ] **Step 1: Run focused backend regression suite**

```powershell
cd backend
pytest tests/test_database_migrations.py tests/test_safe_upload_filenames.py tests/test_retrieval_models.py tests/test_tool_executor_scope.py tests/test_search_scope.py tests/test_cache_scope_keys.py tests/test_retrieval_trace_contract.py tests/test_folder_delete_cleanup.py tests/test_find_related_documents_modes.py tests/test_multi_format_adapter.py tests/test_table_analysis_service.py -v
```

Expected: PASS.

- [ ] **Step 2: Run broader backend tests if time allows**

```powershell
cd backend
pytest -q
```

Expected: PASS or documented unrelated failures.

- [ ] **Step 3: Run frontend build for compatibility**

```powershell
cd frontend
npm run build
```

Expected: PASS. Phase 1 should not require frontend code changes.

- [ ] **Step 4: Record manual verification notes**

Create or update a short note in the implementation PR/commit summary:

- upload normal file
- reject unsafe filename
- chat with user A's document
- verify user A cannot access user B document by direct tool path
- delete folder and confirm files/indexes are removed

- [ ] **Step 5: Final commit if verification required fixes**

```powershell
git add <fixed-files>
git commit -m "test: verify phase 1 safety foundation"
```

## Acceptance Criteria

Phase 1 is complete when:

- `init_db()` creates bootstrap tables and then runs idempotent migrations.
- `schema_migrations` records applied migrations.
- `documents.last_reindex_at` is present on fresh and migrated databases.
- core SQLite indexes exist.
- uploaded filenames cannot escape `DOCUMENTS_DIR`.
- source files are stored with safe generated names.
- `ToolExecutor` cannot be constructed without `user_id`.
- tool access is fail-closed for cross-user documents.
- search requires `user_id`.
- search results are filtered by user before scoring.
- `allowed_doc_ids` narrows user scope but never grants cross-user access.
- structure, page, search, and agent conversation caches include user/scope.
- retrieval/search/fallback results include additive trace metadata.
- folder deletion removes DB rows, source files, index files, and relevant caches.
- existing tests for `find_related_documents`, multi-format adapter basics, and table aggregation still pass.

## Explicit Non-Goals

Do not implement these in Phase 1:

- LiteLLM/user-configurable model settings.
- model provider UI.
- API key encryption schema.
- full canonical multi-format adapter package.
- DOCX/XLSX/PPTX parser migration.
- legacy `.doc`, `.xls`, `.ppt` conversion.
- frontend document-management redesign.
- new retrieval planner.
- PDF quality scoring thresholds or `needs_review` status.
- replacing `find_related_documents` with `search_documents`.

## Recommended Execution Order

1. Task 1: database migrations.
2. Task 2: safe upload filenames.
3. Task 3: retrieval scope/source anchor models.
4. Task 4: mandatory user scope in `ToolExecutor`.
5. Task 5: user-scoped search.
6. Task 6: user-aware cache keys.
7. Task 7: retrieval trace metadata.
8. Task 8: folder deletion cleanup.
9. Task 9: verification sweep.

This order intentionally puts schema and security before retrieval metadata. It also leaves feature-expansion plans blocked until the shared boundaries are stable.

## Open Questions To Resolve Before Execution

- Should legacy `NULL user_id` documents remain visible to any authenticated user, be hidden, or be migrated to an owner?
- Should `allowed_doc_ids=[]` make chat fall back to simple chat, or return a scoped "no documents available" response?
- Should folder deletion cleanup run inside the same DB transaction, or should artifact deletion happen after DB commit with a retryable cleanup queue later?
- Should cache invalidation use targeted key removal now, or is clearing whole cache acceptable for the first implementation?
- Should migration tests use a copied bootstrap schema helper, or should `init_db()` accept an override database path for cleaner tests?

Default recommendations:

- Treat `NULL user_id` records as legacy and hidden from authenticated user tools until an explicit migration decision is made.
- Make `allowed_doc_ids=[]` return "no scoped documents available" rather than global search.
- Delete artifacts after collecting rows but before DB row deletion; if filesystem deletion fails, abort folder deletion.
- Use targeted cache invalidation where practical, but clearing all document-derived caches is acceptable as a temporary safe fallback.
- Prefer a small test-only helper for temporary DB setup instead of changing app runtime configuration broadly.
