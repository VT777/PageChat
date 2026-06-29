# PageChat Screenshot Upload and Multimodal Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing chat composer image UI into a real screenshot/image upload path that lets PageChat answer with model vision while keeping binary/base64 payloads out of persisted chat state.

**Architecture:** Treat screenshots as chat-scoped attachments, not as documents. The frontend uploads images before streaming a message, then sends only `attachment_ids`; the backend validates ownership, stores image files on disk plus compact metadata in SQLite, binds attachments to the user message, and injects temporary `image_url` data URLs only into the live model request. Persisted DB rows, SSE events, frontend localStorage, and reusable agent history must contain metadata only, never raw base64.

**Tech Stack:** FastAPI `UploadFile`, aiosqlite migrations, aiofiles, Pillow image validation, existing `ChatService`/`AgentService`, Vue 3, Pinia, Axios/fetch, pytest, Vitest.

---

## Context

Current state on `codex/pagechat-product-behavior-closure`:

- `frontend/src/components/chat/ChatComposer.vue` already supports selecting/pasting image files and shows local object URL previews.
- `frontend/src/views/ChatView.vue` receives `payload.images`, but intentionally does not forward them to the backend yet.
- `backend/app/models/schemas.py::ChatRequest` has `question`, document/folder scope, `conversation_id`, and `web_search`, but no attachment field.
- `backend/app/services/agent_service.py` already knows how to pass tool-produced document images to the model through OpenAI-style `image_url` multimodal messages.
- `AgentService._sanitize_messages_for_conversation_history` already removes `data:image/...` payloads from reusable in-memory history.

Product decisions for this plan:

- Only support image attachments for chat now: PNG, JPEG, WebP.
- Do not add PDF/document upload through this path.
- Do not OCR screenshots automatically in this plan.
- Do not persist base64 in SQLite, SSE events, Pinia localStorage, or conversation history.
- Do not send image bytes inside `/api/chat/stream`; chat stream receives only attachment IDs.
- Limit one chat request to at most 6 image attachments.
- Default max size is 10 MB per image; keep this as a backend constant that can become config later.

## File Structure

Create:

- `backend/app/services/chat_attachment_service.py`
  - Owns upload validation, file storage, metadata persistence, ownership checks, message binding, and model payload preparation.
- `backend/tests/test_chat_attachment_service.py`
  - Service tests for validation, persistence, ownership, binding, and no-base64 metadata.
- `backend/tests/test_chat_attachments_api.py`
  - FastAPI upload/content/delete endpoint tests.
- `frontend/src/types/chatAttachments.ts`
  - Shared frontend attachment status and metadata types.

Modify:

- `backend/app/core/config.py`
  - Add `CHAT_ATTACHMENTS_DIR`, `CHAT_ATTACHMENT_MAX_BYTES`, `CHAT_ATTACHMENT_MAX_PER_MESSAGE`, and allowed MIME constants.
- `backend/app/models/migrations.py`
  - Add `chat_attachments` table and `messages.attachments_json`.
- `backend/app/models/database.py`
  - Ensure fresh DB bootstrap creates `messages.attachments_json` if needed through migrations.
- `backend/app/models/schemas.py`
  - Add `attachment_ids: Optional[List[str]] = None` to `ChatRequest`.
- `backend/app/api/chat.py`
  - Add attachment upload/content/delete endpoints and pass `attachment_ids` into `ChatService.stream_chat`.
- `backend/app/services/chat_service.py`
  - Validate/bind attachments, save user message metadata, include attachments in message retrieval, and pass model-ready attachments into `AgentService`.
- `backend/app/services/agent_service.py`
  - Add request attachment multimodal message injection and extend tests around sanitizer/history.
- `frontend/src/api/index.ts`
  - Add `chatApi.uploadAttachment`, `chatApi.deleteAttachment`, `chatApi.fetchAttachmentBlob`, and `attachment_ids` in stream payload type.
- `frontend/src/components/chat/ChatComposer.vue`
  - Track upload status, call upload API before submit or expose files to parent for upload depending on chosen frontend boundary.
- `frontend/src/views/ChatView.vue`
  - Forward uploaded `attachment_ids` and display sent message image chips through authenticated blob previews.
- `frontend/src/stores/chat.ts`
  - Store attachment metadata with user messages and persist only metadata/content URLs, not `File` or object URL state.
- `frontend/src/stores/chat.test.ts`
  - Lock down `attachment_ids` payload and localStorage no-base64 behavior.
- `frontend/src/ui/pagechatContracts.test.ts`
  - Add UI contract tests for image attachment display/status labels if helper constants are added.

## Task 0: Branch And Baseline Safety

**Files:**
- Inspect only

- [ ] **Step 1: Confirm branch**

Run:

```powershell
git -C C:\Users\TT_WT\.codex\worktrees\pagechat-integration branch --show-current
```

Expected: `codex/pagechat-product-behavior-closure` or a new branch created from it.

- [ ] **Step 2: Confirm clean worktree**

Run:

```powershell
git -C C:\Users\TT_WT\.codex\worktrees\pagechat-integration status --short
```

Expected: empty, or only this plan file before implementation starts.

- [ ] **Step 3: Run focused baseline tests**

Run:

```powershell
cd C:\Users\TT_WT\.codex\worktrees\pagechat-integration
py -m pytest backend/tests/test_agent_service_sanitize.py backend/tests/test_chat_scope_contract.py backend/tests/test_database_migrations.py
cd frontend
npm.cmd test -- chat pagechatContracts
```

Expected: all selected tests pass.

## Task 1: Attachment Storage Schema And Service

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/models/migrations.py`
- Create: `backend/app/services/chat_attachment_service.py`
- Test: `backend/tests/test_chat_attachment_service.py`
- Test: `backend/tests/test_database_migrations.py`

- [ ] **Step 1: Write failing migration/service tests**

Add tests covering:

```python
async def test_upload_image_persists_metadata_without_base64(tmp_path: Path):
    service = ChatAttachmentService(db, storage_dir=tmp_path)
    saved = await service.save_upload(
        user_id="user-a",
        filename="screen.png",
        content_type="image/png",
        data=_tiny_png_bytes(),
    )
    assert saved["attachment_id"]
    assert saved["mime_type"] == "image/png"
    assert saved["size_bytes"] == len(_tiny_png_bytes())
    assert "base64" not in str(saved).lower()
    assert "data:image" not in str(saved).lower()

async def test_rejects_non_image_or_oversized_upload(tmp_path: Path):
    with pytest.raises(ValueError):
        await service.save_upload("user-a", "notes.txt", "text/plain", b"hello")
    with pytest.raises(ValueError):
        await service.save_upload("user-a", "huge.png", "image/png", b"x" * (CHAT_ATTACHMENT_MAX_BYTES + 1))

async def test_user_cannot_resolve_another_users_attachment(tmp_path: Path):
    saved = await service.save_upload("user-a", "screen.png", "image/png", _tiny_png_bytes())
    with pytest.raises(ValueError):
        await service.attachments_for_model("user-b", [saved["attachment_id"]])
```

Also update `backend/tests/test_database_migrations.py` to assert:

```python
assert {
    "attachment_id",
    "user_id",
    "conversation_id",
    "message_id",
    "original_name",
    "stored_path",
    "mime_type",
    "size_bytes",
    "width",
    "height",
    "status",
}.issubset(await _column_names(db, "chat_attachments"))
assert "attachments_json" in await _column_names(db, "messages")
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
py -m pytest backend/tests/test_chat_attachment_service.py backend/tests/test_database_migrations.py -v
```

Expected: FAIL because service/table/column do not exist.

- [ ] **Step 3: Add config constants**

In `backend/app/core/config.py` add:

```python
CHAT_ATTACHMENTS_DIR = DATA_DIR / "chat_attachments"
CHAT_ATTACHMENT_MAX_BYTES = int(os.getenv("CHAT_ATTACHMENT_MAX_BYTES", str(10 * 1024 * 1024)))
CHAT_ATTACHMENT_MAX_PER_MESSAGE = int(os.getenv("CHAT_ATTACHMENT_MAX_PER_MESSAGE", "6"))
CHAT_ATTACHMENT_ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
```

- [ ] **Step 4: Add migration**

In `backend/app/models/migrations.py` add a migration after the Web Search settings migration:

```python
async def _add_chat_attachments(db: aiosqlite.Connection) -> None:
    if not await _column_exists(db, "messages", "attachments_json"):
        await db.execute("ALTER TABLE messages ADD COLUMN attachments_json TEXT")
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_attachments (
            attachment_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            conversation_id TEXT,
            message_id TEXT,
            original_name TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            width INTEGER,
            height INTEGER,
            status TEXT NOT NULL DEFAULT 'uploaded',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_attachments_user_created
        ON chat_attachments(user_id, created_at)
        """
    )
```

Append `("20260625_006_add_chat_attachments", _add_chat_attachments)` to `MIGRATIONS`.

- [ ] **Step 5: Implement `ChatAttachmentService`**

Responsibilities:

- `save_upload(user_id, filename, content_type, data) -> dict`
- `get_attachment(user_id, attachment_id) -> dict`
- `content_path_for_user(user_id, attachment_id) -> Path`
- `delete_unbound_attachment(user_id, attachment_id) -> bool`
- `bind_to_message(user_id, attachment_ids, conversation_id, message_id) -> list[dict]`
- `attachments_for_model(user_id, attachment_ids) -> list[dict]`

Validation:

- user_id required.
- `content_type` must be in `CHAT_ATTACHMENT_ALLOWED_MIME_TYPES`.
- byte length must be `1..CHAT_ATTACHMENT_MAX_BYTES`.
- Pillow must successfully open and verify image bytes.
- Store under `CHAT_ATTACHMENTS_DIR / user_id / attachment_id.ext`.
- Never return bytes/base64 from metadata methods.

- [ ] **Step 6: Run service and migration tests**

Run:

```powershell
py -m pytest backend/tests/test_chat_attachment_service.py backend/tests/test_database_migrations.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/core/config.py backend/app/models/migrations.py backend/app/services/chat_attachment_service.py backend/tests/test_chat_attachment_service.py backend/tests/test_database_migrations.py
git commit -m "feat(chat): persist image attachments"
```

## Task 2: Attachment API Endpoints

**Files:**
- Modify: `backend/app/api/chat.py`
- Test: `backend/tests/test_chat_attachments_api.py`

- [ ] **Step 1: Write failing API tests**

Mirror existing authenticated test client style from settings/chat tests:

```python
def test_upload_chat_attachment_returns_metadata(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post(
        "/api/chat/attachments",
        files={"file": ("screen.png", _tiny_png_bytes(), "image/png")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["attachment_id"]
    assert payload["mime_type"] == "image/png"
    assert "data:image" not in response.text

def test_fetch_attachment_content_requires_owner(tmp_path: Path) -> None:
    # user A upload succeeds; user B GET returns 404 or 403
```

Also test invalid MIME and oversize response codes.

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
py -m pytest backend/tests/test_chat_attachments_api.py -v
```

Expected: FAIL because endpoints do not exist.

- [ ] **Step 3: Add endpoints**

In `backend/app/api/chat.py`:

- `POST /api/chat/attachments`
  - accepts `UploadFile = File(...)`
  - reads bytes once
  - calls `ChatAttachmentService.save_upload`
  - returns metadata only
- `GET /api/chat/attachments/{attachment_id}/content`
  - validates ownership
  - returns `FileResponse` with stored MIME type
- `DELETE /api/chat/attachments/{attachment_id}`
  - only deletes unbound `status='uploaded'` attachments
  - returns `{ "success": true }`

Important:

- The content endpoint must not be used by the model; it is only for UI previews after reload.
- Because auth is sent through the `Authorization` header, the frontend must not render this URL directly in a plain `<img src>`. It must fetch the blob through `chatApi.fetchAttachmentBlob(...)`, then create a temporary object URL for display.
- Do not return file system paths to the frontend.

- [ ] **Step 4: Run API tests**

Run:

```powershell
py -m pytest backend/tests/test_chat_attachments_api.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/api/chat.py backend/tests/test_chat_attachments_api.py
git commit -m "feat(api): expose chat image attachments"
```

## Task 3: Chat Request Plumbing And Message Persistence

**Files:**
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/api/chat.py`
- Modify: `backend/app/services/chat_service.py`
- Test: `backend/tests/test_chat_scope_contract.py`
- Test: `backend/tests/test_chat_attachment_service.py`

- [ ] **Step 1: Write failing chat contract tests**

Add tests:

```python
def test_chat_request_accepts_attachment_ids() -> None:
    request = ChatRequest(question="看这张截图", attachment_ids=["att-a"])
    assert request.attachment_ids == ["att-a"]

async def test_chat_service_binds_attachments_to_user_message():
    # Fake attachment service captures bind_to_message call.
    assert captured["conversation_id"]
    assert captured["message_id"]
```

Also test:

- more than `CHAT_ATTACHMENT_MAX_PER_MESSAGE` IDs fails validation or service rejects.
- invalid/foreign attachment ID prevents the chat stream from starting normal answer generation.
- `GET /api/chat/conversations/{id}/messages` returns attachment metadata with the user message.

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
py -m pytest backend/tests/test_chat_scope_contract.py backend/tests/test_chat_attachment_service.py -v
```

Expected: FAIL because `attachment_ids` and binding are missing.

- [ ] **Step 3: Extend `ChatRequest`**

In `backend/app/models/schemas.py`:

```python
class ChatRequest(BaseModel):
    question: str
    ...
    attachment_ids: Optional[List[str]] = None
```

Validation:

- Normalize `None` to empty list in service layer.
- Reject more than `CHAT_ATTACHMENT_MAX_PER_MESSAGE`.
- Keep `question` required for this plan; do not add image-only prompts yet unless product explicitly asks later.

- [ ] **Step 4: Update `ChatService.save_message`**

Add optional `attachments: list[dict] | None = None`.

Persist only compact metadata:

```python
attachments_json=json.dumps([
    {
        "attachment_id": item["attachment_id"],
        "original_name": item["original_name"],
        "mime_type": item["mime_type"],
        "size_bytes": item["size_bytes"],
        "width": item.get("width"),
        "height": item.get("height"),
        "content_url": f"/api/chat/attachments/{item['attachment_id']}/content",
    }
], ensure_ascii=False)
```

- [ ] **Step 5: Update `ChatService.stream_chat`**

Flow:

1. Ensure conversation.
2. Validate attachment IDs and fetch model attachment descriptors.
3. Save user message with attachment metadata.
4. Bind attachment rows to `conversation_id` and user `message_id`.
5. Pass `attachments_for_model` into `AgentService.run_agent_stream`.

If attachment validation fails:

- yield a concise `event: content` error message,
- yield `event: done`,
- save assistant error state if a conversation was created.

- [ ] **Step 6: Update conversation message retrieval**

In `backend/app/api/chat.py`, include `attachments` from `messages.attachments_json`:

```python
"attachments": json.loads(row["attachments_json"]) if row["attachments_json"] else []
```

- [ ] **Step 7: Run tests**

Run:

```powershell
py -m pytest backend/tests/test_chat_scope_contract.py backend/tests/test_chat_attachments_api.py backend/tests/test_chat_attachment_service.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add backend/app/models/schemas.py backend/app/api/chat.py backend/app/services/chat_service.py backend/tests/test_chat_scope_contract.py backend/tests/test_chat_attachments_api.py backend/tests/test_chat_attachment_service.py
git commit -m "feat(chat): bind image attachments to messages"
```

## Task 4: Agent Multimodal Attachment Injection

**Files:**
- Modify: `backend/app/services/agent_service.py`
- Test: `backend/tests/test_agent_service_sanitize.py`
- Test: `backend/tests/test_chat_scope_contract.py`

- [ ] **Step 1: Write failing agent tests**

Add tests:

```python
def test_request_attachments_are_injected_as_multimodal_user_message(monkeypatch):
    attachments = [{
        "attachment_id": "att-a",
        "mime_type": "image/png",
        "data": _tiny_png_base64(),
        "original_name": "screen.png",
    }]
    # fake chat_by_scenario captures messages
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"][0] == {"type": "text", "text": "这张图里有什么？"}
    assert messages[-1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")

def test_conversation_history_cache_omits_request_attachment_base64(monkeypatch):
    # after run, _CONVERSATION_MESSAGES must not contain data:image or raw base64
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
py -m pytest backend/tests/test_agent_service_sanitize.py backend/tests/test_chat_scope_contract.py -v
```

Expected: FAIL because request attachments are not accepted/injected.

- [ ] **Step 3: Extend `AgentService.run_agent_stream` signature**

Add:

```python
request_attachments: Optional[List[Dict[str, Any]]] = None
```

Expected model descriptor shape from `ChatAttachmentService.attachments_for_model`:

```python
{
    "attachment_id": "att-a",
    "original_name": "screen.png",
    "mime_type": "image/png",
    "data_base64": "...",
    "width": 800,
    "height": 600,
}
```

- [ ] **Step 4: Add helper to build multimodal user message**

In `AgentService`:

```python
@staticmethod
def _user_message_with_attachments(question: str, attachments: list[dict] | None) -> dict:
    if not attachments:
        return {"role": "user", "content": question}
    content = [{"type": "text", "text": question}]
    for item in attachments[:CHAT_ATTACHMENT_MAX_PER_MESSAGE]:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{item['mime_type']};base64,{item['data_base64']}"
            },
        })
    return {"role": "user", "content": content}
```

Use this helper anywhere the current question is appended to model messages.

- [ ] **Step 5: Add prompt guidance**

In `backend/app/prompts/__init__.py`, add a short QA rule:

- If the current user message includes image attachments, inspect the images directly with vision.
- Do not claim an image contains text/objects that are not visible.
- If document scope and screenshots are both present, answer using both and distinguish screenshot evidence from document evidence.

- [ ] **Step 6: Ensure sanitizers cover request images**

`_sanitize_messages_for_conversation_history` already replaces `image_url` payloads, but tests must cover request attachments specifically.

Do not include request image data in:

- tool result SSE,
- `done.tool_results`,
- `_CONVERSATION_MESSAGES`,
- DB message `content`,
- DB `attachments_json`.

- [ ] **Step 7: Run tests**

Run:

```powershell
py -m pytest backend/tests/test_agent_service_sanitize.py backend/tests/test_chat_scope_contract.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add backend/app/services/agent_service.py backend/app/prompts/__init__.py backend/tests/test_agent_service_sanitize.py backend/tests/test_chat_scope_contract.py
git commit -m "feat(agent): inject chat image attachments"
```

## Task 5: Frontend Upload And Chat Payload Wiring

**Files:**
- Create: `frontend/src/types/chatAttachments.ts`
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/components/chat/ChatComposer.vue`
- Modify: `frontend/src/views/ChatView.vue`
- Modify: `frontend/src/stores/chat.ts`
- Test: `frontend/src/stores/chat.test.ts`

- [ ] **Step 1: Write failing frontend tests**

Add tests:

```ts
it('sends attachment ids instead of image payloads', async () => {
  await store.sendMessage('看截图', {
    attachment_ids: ['att-a'],
  })
  expect(chatApi.stream).toHaveBeenCalledWith(expect.objectContaining({
    question: '看截图',
    attachment_ids: ['att-a'],
  }))
  expect(JSON.stringify(localStorage)).not.toContain('data:image')
})

it('persists sent image metadata with the active chat session', () => {
  store.addUserMessage('看截图', [{ attachment_id: 'att-a', original_name: 'screen.png' }])
  store.saveCurrentSession()
  // restore and assert metadata, not File/object URL
})
```

If `addUserMessage` remains private, test via `sendMessage` with mocked stream and attachment metadata.

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
cd C:\Users\TT_WT\.codex\worktrees\pagechat-integration\frontend
npm.cmd test -- chat
```

Expected: FAIL because the store/API do not support `attachment_ids` or message attachments.

- [ ] **Step 3: Add frontend attachment types**

Create `frontend/src/types/chatAttachments.ts`:

```ts
export interface ChatAttachmentMetadata {
  attachment_id: string
  original_name: string
  mime_type: string
  size_bytes: number
  width?: number | null
  height?: number | null
  content_url?: string
}

export interface ComposerImageAttachment {
  localId: string
  name: string
  file: File
  previewUrl: string
  status: 'local' | 'uploading' | 'uploaded' | 'failed'
  error?: string
  remote?: ChatAttachmentMetadata
}

export interface ChatAttachmentPreview extends ChatAttachmentMetadata {
  preview_url?: string
  preview_status?: 'idle' | 'loading' | 'ready' | 'failed'
}
```

- [ ] **Step 4: Add API methods**

In `frontend/src/api/index.ts`:

```ts
uploadAttachment: (file: File) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/chat/attachments', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
},
deleteAttachment: (attachmentId: string) =>
  api.delete(`/chat/attachments/${attachmentId}`),
fetchAttachmentBlob: (attachmentId: string) =>
  api.get(`/chat/attachments/${attachmentId}/content`, {
    responseType: 'blob',
  }),
```

Add `attachment_ids?: string[]` to stream payload type.

- [ ] **Step 5: Decide upload boundary in component**

Use this boundary:

- `ChatComposer.vue` owns local file selection, preview, and upload status.
- `ChatComposer.vue` calls `chatApi.uploadAttachment(file)` during submit before emitting.
- It emits only uploaded metadata:

```ts
interface ComposerSubmitPayload {
  text: string
  webSearch: boolean
  documentIds: string[]
  folderIds: string[]
  attachments: ChatAttachmentMetadata[]
}
```

If any upload fails:

- keep the composer text and images,
- mark failed image,
- do not emit submit.

- [ ] **Step 6: Update `ChatView.handleSubmit`**

Forward:

```ts
await chatStore.sendMessage(payload.text, {
  ...buildScope(payload),
  web_search: payload.webSearch,
  attachment_ids: payload.attachments.map((item) => item.attachment_id),
  attachments: payload.attachments,
})
```

Do not pass `File`, object URLs, or base64 into the store.

- [ ] **Step 7: Update `chat.ts` store**

Add:

```ts
export interface Message {
  ...
  attachments?: ChatAttachmentMetadata[]
}

interface ChatSendOptions extends ChatScopeRequest {
  attachment_ids?: string[]
  attachments?: ChatAttachmentMetadata[]
}
```

`sendMessage(question, options)` should:

- add user message with `attachments: options.attachments || []`,
- call `chatApi.stream` with `attachment_ids` but not `attachments`,
- persist only metadata.

- [ ] **Step 8: Render sent image chips**

In `ChatView.vue`, under user bubble, render attachment thumbnails:

- if `content_url` exists, call `chatApi.fetchAttachmentBlob(attachment_id)` after the message appears or after a conversation reload;
- convert the returned blob to `URL.createObjectURL(blob)` for `<img :src="preview_url">`;
- revoke object URLs when previews are replaced or the component unmounts;
- do not persist `preview_url` because it is local `blob:` state;
- display file name and dimensions if available;
- no download control in this plan.

Keep layout compact and consistent with existing chat bubbles.

- [ ] **Step 9: Run frontend tests**

Run:

```powershell
npm.cmd test -- chat pagechatContracts
npm.cmd run build
```

Expected: PASS.

- [ ] **Step 10: Commit**

```powershell
git add frontend/src/types/chatAttachments.ts frontend/src/api/index.ts frontend/src/components/chat/ChatComposer.vue frontend/src/views/ChatView.vue frontend/src/stores/chat.ts frontend/src/stores/chat.test.ts frontend/src/ui/pagechatContracts.test.ts
git commit -m "feat(frontend): upload chat image attachments"
```

## Task 6: End-To-End Safety And Error Behavior

**Files:**
- Modify: `backend/tests/test_chat_attachments_api.py`
- Modify: `backend/tests/test_agent_service_sanitize.py`
- Modify: `frontend/src/stores/chat.test.ts`

- [ ] **Step 1: Add regression tests**

Backend:

```python
def test_chat_stream_never_emits_base64_attachment_payload(...):
    # upload image, stream chat with attachment_ids
    # fake model adapter if needed
    assert "data:image" not in "".join(events)
    assert raw_base64 not in "".join(events)
```

Frontend:

```ts
expect(JSON.stringify(localStorage)).not.toContain('data:image')
expect(JSON.stringify(localStorage)).not.toContain('blob:')
```

- [ ] **Step 2: Add orphan cleanup behavior tests**

For this plan, minimal cleanup is:

- frontend calls `DELETE /api/chat/attachments/{id}` if an uploaded image chip is removed before submit;
- backend refuses to delete an attachment once bound to a message.

Add API tests for both cases.

- [ ] **Step 3: Run focused safety tests**

Run:

```powershell
py -m pytest backend/tests/test_chat_attachments_api.py backend/tests/test_agent_service_sanitize.py backend/tests/test_chat_scope_contract.py -v
cd frontend
npm.cmd test -- chat
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add backend/tests/test_chat_attachments_api.py backend/tests/test_agent_service_sanitize.py backend/tests/test_chat_scope_contract.py frontend/src/stores/chat.test.ts
git commit -m "test(chat): cover image attachment payload safety"
```

## Task 7: Full Verification And Browser Smoke

**Files:**
- No intended source changes unless smoke finds a bug.

- [ ] **Step 1: Run backend full tests**

Run:

```powershell
cd C:\Users\TT_WT\.codex\worktrees\pagechat-integration
py -m pytest backend/tests
```

Expected: all backend tests pass.

- [ ] **Step 2: Run frontend tests**

Run:

```powershell
cd C:\Users\TT_WT\.codex\worktrees\pagechat-integration\frontend
npm.cmd test
```

Expected: all frontend tests pass.

- [ ] **Step 3: Run frontend build**

Run:

```powershell
npm.cmd run build
```

Expected: build succeeds.

- [ ] **Step 4: Browser smoke**

Start the app as needed and verify:

- selecting an image opens the file picker and shows a local preview;
- pasting a screenshot shows a local preview;
- submit uploads the image first;
- failed upload keeps the prompt and image visible with an error state;
- successful send creates a user message with image thumbnail metadata;
- network request to `/api/chat/stream` contains `attachment_ids`, not image bytes;
- assistant can answer based on the screenshot when the configured model supports vision;
- reloading the conversation shows sent image metadata and authenticated blob thumbnail previews through the content endpoint;
- localStorage contains no `File`, `blob:`, `data:image`, or base64 image payload.

- [ ] **Step 5: Commit smoke fixes if needed**

Only if smoke reveals issues, first inspect the exact files changed:

```powershell
git status --short
```

Then stage only the files that were changed to fix the smoke issue. Do not stage unrelated user changes. Example if the fix only touched chat attachment preview code:

```powershell
git add frontend/src/views/ChatView.vue frontend/src/components/chat/ChatComposer.vue
git commit -m "fix(chat): polish image attachment smoke issues"
```

## Task 8: Documentation And Handoff

**Files:**
- Modify: `docs/pagechat_integration_development_guide.md`
- Modify: this plan file

- [ ] **Step 1: Record completion notes**

Document:

- attachment upload API endpoints;
- DB/storage model;
- no-base64 persistence guarantee;
- model vision injection path;
- verification commands run;
- known limitations.

- [ ] **Step 2: Push branch**

Run:

```powershell
git push -u origin codex/pagechat-product-behavior-closure
```

or push a dedicated branch if created for this plan.

- [ ] **Step 3: Recommended next plan**

After screenshots are real, the next best plan is:

1. OCR/Parsing/QA settings full persistence beyond Web Search.
2. Document/folder backend actions: recursive download, reparse, move, delete.
3. Production cleanup: remove demo fallback from real user flows.

## Acceptance Criteria

- Users can add or paste PNG/JPEG/WebP images in the chat composer.
- Frontend uploads images through `POST /api/chat/attachments` before streaming chat.
- `/api/chat/stream` receives only `attachment_ids`, never image bytes/base64.
- Backend validates image type, size, ownership, and max count.
- Backend persists metadata and disk file, not base64.
- User messages persist compact attachment metadata and reload correctly.
- Sent attachment thumbnails are loaded through authenticated blob fetches, not direct unauthenticated image URLs.
- Agent model request includes current-turn images as temporary multimodal `image_url` content.
- Reusable conversation history, SSE, DB messages, and frontend localStorage never contain `data:image` or raw base64.
- Removing an uploaded-but-unsent image deletes the unbound attachment.
- Bound message attachments cannot be deleted through the draft cleanup endpoint.
- Full backend tests, frontend tests, and frontend build pass.

## Open Risks

- If the selected QA model/provider does not support vision, the backend should return a clear configuration hint rather than silently ignoring images. This may require a small model capability check in the QA settings follow-up.
- Very large screenshots can slow model calls even if upload size is valid. This plan validates size but does not yet resize/compress server-side.
- Orphan cleanup for abandoned browser sessions is minimal in this plan. A scheduled cleanup for old unbound attachments can be added later.
- Image-only messages are intentionally out of scope; this plan keeps `question` required.
- Mobile layout polish is out of scope unless smoke reveals a blocking overlap.

## Self-Review

- Completeness: Covers backend storage, API, chat plumbing, agent multimodal injection, frontend upload UX, safety tests, and full verification.
- Scope control: Keeps screenshots as chat attachments, not documents; excludes OCR, document parsing, MCP, and image-only messages.
- Testability: Each task starts with failing tests and has focused verification commands.
- Safety: The no-base64 rule is enforced across backend service, SSE, agent history, DB messages, and frontend localStorage.

## Completion Notes（2026-06-25）

Implemented on branch `codex/pagechat-product-behavior-closure`.

Key commits:

- `8f43386 feat(chat): persist image attachments`
- `41ef892 feat(api): expose chat image attachments`
- `c20d469 feat(chat): bind image attachments to messages`
- `c9c55f8 feat(agent): inject chat image attachments`
- `8ae3559 feat(frontend): upload chat image attachments`
- `739fda2 test(chat): cover image attachment payload safety`

Implemented behavior:

- `POST /api/chat/attachments` validates and stores PNG/JPEG/WebP chat images as metadata plus disk files.
- `GET /api/chat/attachments/{attachment_id}/content` serves authenticated UI previews.
- `DELETE /api/chat/attachments/{attachment_id}` deletes only unbound draft attachments and returns conflict for bound message attachments.
- `/api/chat/stream` accepts `attachment_ids` and never receives or emits image bytes/base64.
- `ChatService` binds attachments to the user message and persists only compact `attachments_json`.
- `AgentService` injects current-turn image attachments into the live model call as temporary multimodal `image_url` parts.
- Frontend uploads images before send, stores only metadata in Pinia/localStorage, and reloads previews through authenticated blob fetches.

Verification run:

```powershell
py -m pytest backend/tests/test_chat_attachments_api.py backend/tests/test_agent_service_sanitize.py backend/tests/test_chat_scope_contract.py -v
cd frontend
npm.cmd test -- chat
cd ..
py -m pytest backend/tests
cd frontend
npm.cmd test
npm.cmd run build
```

Verification results:

- Backend focused safety: `27 passed`
- Frontend focused chat/contracts: `42 passed`
- Backend full suite: `660 passed, 19 skipped`
- Frontend full suite: `75 passed`
- Frontend production build: passed

Known follow-ups:

- Add model capability checks or clear configuration hints when the selected QA model does not support vision.
- Add scheduled cleanup for abandoned unbound attachments.
- Consider server-side image compression/resizing for very large screenshots.
- Keep image-only messages out of scope until product explicitly wants them.
