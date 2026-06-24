# PageChat AnySearch API Web Search Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build PageChat's first production Web Search loop by integrating AnySearch through its REST API only, wiring it from Settings and Chat composer into a gated agent tool.

**Architecture:** Add per-user Web Search settings, a compact AnySearch REST client, and a `web_search` agent tool that is available only when the user's QA setting and current chat request permit it. The frontend stops appending Web Search hints into the prompt and instead sends structured request fields; tool traces expose concise search metadata and never persist full page content.

**Tech Stack:** FastAPI, aiosqlite migrations, `requests` via `asyncio.to_thread`, Pydantic, existing PageChat agent tool executor, Vue 3, Pinia, Axios/fetch, pytest, Vitest.

---

## Context

Official AnySearch API reference, checked on 2026-06-25 at `https://www.anysearch.com/docs`:

- REST endpoint: `POST https://api.anysearch.com/v1/search`
- API key is optional. Anonymous requests are per-IP quota limited.
- Auth header, when configured: `Authorization: Bearer YOUR_ANYSEARCH_API_KEY`
- If an invalid/disabled/expired key is sent, AnySearch returns `401` or `403`; it does not silently fall back to anonymous mode.
- Request fields: `query`, `max_results`, `domain`, `tag`, `content_types`, `zone`, `language`, `params`
- `max_results` defaults to `10`; allowed range is `1-100`.
- `zone` is `cn` or `intl`.
- Successful response has `results[]` and `metadata`, with result fields such as `title`, `url`, `snippet`, `content`, and metadata such as `total_results`, `search_time_ms`, `request_id`.
- Error responses include `request_id`; `429` also includes `Retry-After` and `X-RateLimit-*` headers.

Product decision for this plan:

- Do not implement MCP now.
- Do not add AnySearch extract/batch/advanced verticals now.
- Do not store or stream full AnySearch `content`; expose a bounded `content_preview`.
- Do not make Web Search a hidden backend augmentation. The model receives a visible `web_search` tool and the user-visible trace shows that web search ran.

## File Structure

Create:

- `backend/app/services/web_search_settings_service.py`
  - Per-user Web Search settings persistence and secret masking.
- `backend/app/services/anysearch_client.py`
  - AnySearch REST API wrapper with request validation, timeout, error normalization, and preview truncation.
- `backend/app/services/web_search_tool.py`
  - Tool definition plus executor wrapper for `web_search`.
- `backend/tests/test_web_search_settings_service.py`
  - Service-level settings persistence and user isolation tests.
- `backend/tests/test_web_search_settings_api.py`
  - FastAPI settings endpoints and masking tests.
- `backend/tests/test_anysearch_client.py`
  - REST request/response/error/truncation tests with mocked `requests.post`.
- `backend/tests/test_agent_web_search_tool.py`
  - Tool availability, gating, execution, and compact payload tests.
- `frontend/src/types/webSearchSettings.ts`
  - Shared frontend types for settings and request payloads.

Modify:

- `backend/app/models/migrations.py`
  - Add a `web_search_settings` table migration.
- `backend/app/api/settings.py`
  - Add Web Search settings endpoints and test endpoint.
- `backend/app/models/schemas.py`
  - Add the structured chat field `web_search`; screenshot/image attachment request design stays out of this plan.
- `backend/app/api/chat.py`
  - Pass Web Search request fields into `ChatService.stream_chat`.
- `backend/app/services/chat_service.py`
  - Thread Web Search request state into `AgentService.run_agent_stream`.
- `backend/app/services/agent_service.py`
  - Build the runtime tool list with `web_search` only when permitted; sanitize tool results.
- `backend/app/prompts/__init__.py`
  - Add concise Web Search usage/citation guidance.
- `frontend/src/api/index.ts`
  - Add Web Search settings API calls and send structured `web_search` in chat stream requests.
- `frontend/src/components/settings/SettingsModal.vue`
  - Persist QA Web Search mode/provider fields instead of local-only state.
- `frontend/src/components/chat/ChatComposer.vue`
  - Keep existing UI, but submit structured Web Search state.
- `frontend/src/views/ChatView.vue`
  - Remove prompt suffix `[Context: Web Search enabled]`; forward structured payload.
- `frontend/src/stores/chat.ts`
  - Include Web Search fields in chat stream request type and persistence-safe session data.
- `frontend/src/ui/pagechatContracts.ts`
  - Add `web_search` tool trace summary and settings contract constants if needed.
- `frontend/src/ui/pagechatContracts.test.ts`
  - Lock down Web Search setting labels and tool summary behavior.
- `frontend/src/stores/chat.test.ts`
  - Verify chat payload sends Web Search as structured data.

## Task 0: Branch And Baseline Safety

**Files:**
- Inspect only: repository state

- [ ] **Step 1: Confirm the worktree is on the product closure branch**

Run:

```powershell
git -C C:\Users\TT_WT\.codex\worktrees\pagechat-integration branch --show-current
```

Expected: `codex/pagechat-product-behavior-closure`

- [ ] **Step 2: Confirm no unrelated work is present**

Run:

```powershell
git -C C:\Users\TT_WT\.codex\worktrees\pagechat-integration status --short
```

Expected: only this plan file before implementation starts.

- [ ] **Step 3: Run focused baseline tests**

Run:

```powershell
cd C:\Users\TT_WT\.codex\worktrees\pagechat-integration
py -m pytest backend/tests/test_agent_navigation_tools_contract.py backend/tests/test_agent_service_sanitize.py backend/tests/test_model_settings_api.py backend/tests/test_runtime_settings_service.py
```

Expected: all selected tests pass.

- [ ] **Step 4: Run frontend baseline contract tests**

Run:

```powershell
cd C:\Users\TT_WT\.codex\worktrees\pagechat-integration\frontend
npm.cmd test -- pagechatContracts chat
```

Expected: selected Vitest suites pass.

## Task 1: Web Search Settings Persistence

**Files:**
- Modify: `backend/app/models/migrations.py`
- Create: `backend/app/services/web_search_settings_service.py`
- Test: `backend/tests/test_web_search_settings_service.py`

- [ ] **Step 1: Write failing migration/service tests**

Add tests covering:

```python
async def test_defaults_without_saved_settings():
    settings = await service.get_settings("user-a")
    assert settings["provider"] == "anysearch"
    assert settings["mode"] == "on-demand"
    assert settings["zone"] == "cn"
    assert settings["language"] == "zh-CN"
    assert settings["max_results"] == 5
    assert settings["content_types"] == ["web", "news"]
    assert "api_key" not in settings

async def test_save_masks_optional_api_key():
    saved = await service.save_settings(
        user_id="user-a",
        mode="auto",
        provider="anysearch",
        api_key="as-secret-123456",
        zone="intl",
        language="en",
        max_results=8,
        content_types=["web"],
    )
    assert saved["api_key_mask"] == "as-...3456"
    assert "as-secret-123456" not in str(saved)

async def test_users_are_isolated():
    await service.save_settings("user-a", api_key="as-secret-123456")
    assert (await service.get_secret("user-b")) is None
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
py -m pytest backend/tests/test_web_search_settings_service.py -v
```

Expected: FAIL because the migration/service does not exist.

- [ ] **Step 3: Add the migration**

Add a migration like:

```python
async def _add_web_search_settings_table(db: aiosqlite.Connection) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS web_search_settings (
            user_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL DEFAULT 'anysearch',
            mode TEXT NOT NULL DEFAULT 'on-demand',
            api_key_ciphertext TEXT,
            api_key_mask TEXT,
            zone TEXT NOT NULL DEFAULT 'cn',
            language TEXT NOT NULL DEFAULT 'zh-CN',
            max_results INTEGER NOT NULL DEFAULT 5,
            content_types_json TEXT NOT NULL DEFAULT '["web","news"]',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
```

Append it to `MIGRATIONS` with an ID after `20260615_004_add_ocr_settings_tables`.

- [ ] **Step 4: Implement `WebSearchSettingsService`**

Use existing key protection helpers from `backend/app/services/model_settings_service.py` for consistency:

```python
VALID_WEB_SEARCH_MODES = {"on-demand", "auto"}
VALID_ZONES = {"cn", "intl"}
VALID_CONTENT_TYPES = {"web", "news"}

DEFAULT_WEB_SEARCH_SETTINGS = {
    "provider": "anysearch",
    "mode": "on-demand",
    "zone": "cn",
    "language": "zh-CN",
    "max_results": 5,
    "content_types": ["web", "news"],
    "api_key_mask": "",
}
```

Required methods:

- `get_settings(user_id: str) -> dict`
- `save_settings(...) -> dict`
- `get_secret(user_id: str) -> str | None`
- `resolve_for_request(user_id: str, requested: bool) -> dict`

Validation rules:

- `mode`: only `on-demand` or `auto`
- `provider`: only `anysearch` for this plan
- `zone`: only `cn` or `intl`
- `max_results`: clamp or reject outside `1-10` for PageChat's agent tool, even though AnySearch allows `1-100`
- `content_types`: non-empty subset of `web/news`
- empty API key means anonymous mode; do not store a blank ciphertext

- [ ] **Step 5: Run service tests**

Run:

```powershell
py -m pytest backend/tests/test_web_search_settings_service.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/models/migrations.py backend/app/services/web_search_settings_service.py backend/tests/test_web_search_settings_service.py
git commit -m "feat(settings): persist web search settings"
```

## Task 2: Web Search Settings API

**Files:**
- Modify: `backend/app/api/settings.py`
- Test: `backend/tests/test_web_search_settings_api.py`

- [ ] **Step 1: Write failing API tests**

Mirror the existing style in `backend/tests/test_model_settings_api.py`:

```python
def test_get_web_search_settings_defaults(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/api/settings/web-search")
    assert response.status_code == 200
    assert response.json()["mode"] == "on-demand"

def test_save_web_search_settings_masks_key(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.put("/api/settings/web-search", json={
        "provider": "anysearch",
        "mode": "auto",
        "api_key": "as-secret-123456",
        "zone": "intl",
        "language": "en",
        "max_results": 5,
        "content_types": ["web"],
    })
    assert response.status_code == 200
    assert response.json()["api_key_mask"] == "as-...3456"
    assert "as-secret-123456" not in response.text
```

Also test invalid mode/zone/content type and user isolation.

- [ ] **Step 2: Run tests and verify they fail**

```powershell
py -m pytest backend/tests/test_web_search_settings_api.py -v
```

Expected: FAIL with missing route/service errors.

- [ ] **Step 3: Add request models and endpoints**

Add Pydantic models in `backend/app/api/settings.py`:

```python
class WebSearchSettingsUpdate(BaseModel):
    provider: str = "anysearch"
    mode: str = "on-demand"
    api_key: str | None = None
    zone: str = "cn"
    language: str = "zh-CN"
    max_results: int = 5
    content_types: list[str] = ["web", "news"]
```

Add endpoints:

- `GET /api/settings/web-search`
- `PUT /api/settings/web-search`

Do not return raw API keys.

- [ ] **Step 4: Run API tests**

```powershell
py -m pytest backend/tests/test_web_search_settings_api.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/api/settings.py backend/tests/test_web_search_settings_api.py
git commit -m "feat(api): expose web search settings"
```

## Task 3: AnySearch REST Client

**Files:**
- Create: `backend/app/services/anysearch_client.py`
- Test: `backend/tests/test_anysearch_client.py`

- [ ] **Step 1: Write failing client tests**

Test request shape, optional auth, preview truncation, and normalized errors:

```python
def test_search_posts_compact_anysearch_payload(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(200, {
            "results": [{
                "title": "Result",
                "url": "https://example.test",
                "snippet": "Short",
                "content": "A" * 2000,
            }],
            "metadata": {"request_id": "req-1", "search_time_ms": 123},
        })

    monkeypatch.setattr("requests.post", fake_post)
    result = asyncio.run(client.search(query="PageChat", api_key="as-key"))
    assert calls[0][0] == "https://api.anysearch.com/v1/search"
    assert calls[0][1]["headers"]["Authorization"] == "Bearer as-key"
    assert len(result["results"][0]["content_preview"]) <= 700
    assert "content" not in result["results"][0]
```

Add tests for:

- anonymous request has no `Authorization`
- `max_results` sent as configured
- `400/401/402/403/429/500` become `success: false` with safe fields
- `429` preserves `retry_after`
- timeout returns `error_code: "timeout"`

- [ ] **Step 2: Run tests and verify they fail**

```powershell
py -m pytest backend/tests/test_anysearch_client.py -v
```

Expected: FAIL because the client does not exist.

- [ ] **Step 3: Implement `AnySearchClient`**

Use existing `requests` dependency from `backend/requirements.txt`; keep async callers non-blocking:

```python
response = await asyncio.to_thread(
    requests.post,
    ANYSEARCH_SEARCH_URL,
    json=payload,
    headers=headers,
    timeout=timeout_seconds,
)
```

Return compact shape:

```python
{
    "success": True,
    "query": query,
    "results": [
        {
            "title": title,
            "url": url,
            "snippet": snippet,
            "content_preview": truncated_content,
            "source": "anysearch",
        }
    ],
    "metadata": {
        "request_id": request_id,
        "search_time_ms": search_time_ms,
        "total_results": total_results,
    },
}
```

Do not include raw `content`.

- [ ] **Step 4: Run client tests**

```powershell
py -m pytest backend/tests/test_anysearch_client.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/anysearch_client.py backend/tests/test_anysearch_client.py
git commit -m "feat(search): add AnySearch REST client"
```

## Task 4: Agent `web_search` Tool

**Files:**
- Create: `backend/app/services/web_search_tool.py`
- Modify: `backend/app/services/tool_executor.py`
- Modify: `backend/app/services/agent_service.py`
- Modify: `backend/app/prompts/__init__.py`
- Modify: `frontend/src/ui/pagechatContracts.ts`
- Test: `backend/tests/test_agent_web_search_tool.py`
- Test: `backend/tests/test_tools_prompt_catalog.py`
- Test: `frontend/src/ui/pagechatContracts.test.ts`

- [ ] **Step 1: Write failing backend tool tests**

Expected behavior:

```python
def test_web_search_tool_is_not_in_base_document_navigation_tools():
    names = {tool["function"]["name"] for tool in AGENT_TOOLS}
    assert "web_search" not in names

def test_runtime_tools_include_web_search_when_enabled():
    tools = AgentService._tools_for_request(web_search_enabled=True)
    assert "web_search" in {tool["function"]["name"] for tool in tools}

def test_runtime_tools_omit_web_search_when_disabled():
    tools = AgentService._tools_for_request(web_search_enabled=False)
    assert "web_search" not in {tool["function"]["name"] for tool in tools}
```

Execution test:

```python
async def test_web_search_execution_returns_compact_results(monkeypatch):
    fake_service = FakeWebSearchService(result={"success": True, "results": [{"title": "A"}]})
    result = await execute_web_search_tool(fake_service, user_id="user-a", arguments={"query": "latest PageChat"})
    assert result["success"] is True
    assert result["results"][0]["title"] == "A"
```

- [ ] **Step 2: Run tests and verify they fail**

```powershell
py -m pytest backend/tests/test_agent_web_search_tool.py backend/tests/test_tools_prompt_catalog.py -v
```

Expected: FAIL because no runtime `web_search` tool exists.

- [ ] **Step 3: Define `WEB_SEARCH_TOOL`**

Tool schema:

```python
WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web through AnySearch when the user requested web search or QA settings allow automatic web search. Returns compact external source previews only.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "1-10, defaults to user setting"},
                "language": {"type": "string", "description": "Preferred language, e.g. zh-CN or en"},
                "zone": {"type": "string", "enum": ["cn", "intl"]},
                "content_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["web", "news"]},
                },
            },
            "required": ["query"],
        },
    },
}
```

- [ ] **Step 4: Add runtime tool composition to `AgentService`**

Do not mutate global `AGENT_TOOLS`.

Implement helper:

```python
@staticmethod
def _tools_for_request(web_search_enabled: bool) -> list[dict]:
    tools = list(AGENT_TOOLS)
    if web_search_enabled:
        tools.append(WEB_SEARCH_TOOL)
    return tools
```

Use this list for:

- system prompt tool catalog
- model `tools=...`
- deterministic "现在有哪些工具" response

- [ ] **Step 5: Execute `web_search` outside document `ToolExecutor` or as a narrow extension**

Preferred split:

- Keep document-navigation tools in `ToolExecutor`.
- Route `web_search` in `AgentService` to `execute_web_search_tool(...)`.

This prevents a web provider dependency from leaking into the document tool executor.

- [ ] **Step 6: Update prompt policy**

Add rules:

- In `on-demand` mode, use `web_search` only when the user selected Web Search or explicitly asks to search the web.
- In `auto` mode, use `web_search` only for questions needing current/external information unavailable in the selected documents.
- Do not answer from `web_search` result titles only; use snippet/content_preview as external evidence.
- Cite web sources inline with markdown links, while document facts still use `[[document p.x]]`.
- Never collect all references at the end.

- [ ] **Step 7: Update frontend tool trace summary**

In `summarizeToolStep`, add:

```ts
case 'web_search':
  return {
    action: step.status === 'calling' ? 'Searching the web' : 'Searched the web',
    detail: pluralize(resultCount(step, ['results']), 'result'),
    icon: 'Globe',
    tone,
  }
```

- [ ] **Step 8: Run backend and frontend contract tests**

```powershell
py -m pytest backend/tests/test_agent_web_search_tool.py backend/tests/test_tools_prompt_catalog.py -v
cd frontend
npm.cmd test -- pagechatContracts
```

Expected: PASS.

- [ ] **Step 9: Commit**

```powershell
git add backend/app/services/web_search_tool.py backend/app/services/tool_executor.py backend/app/services/agent_service.py backend/app/prompts/__init__.py backend/tests/test_agent_web_search_tool.py backend/tests/test_tools_prompt_catalog.py frontend/src/ui/pagechatContracts.ts frontend/src/ui/pagechatContracts.test.ts
git commit -m "feat(agent): add gated web search tool"
```

## Task 5: Chat Request Gating

**Files:**
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/api/chat.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/app/services/agent_service.py`
- Test: `backend/tests/test_chat_scope_contract.py`
- Test: `backend/tests/test_agent_web_search_tool.py`

- [ ] **Step 1: Write failing chat contract tests**

Add tests for:

```python
def test_chat_request_accepts_structured_web_search_flag():
    payload = ChatRequest(question="查一下最新政策", web_search=True)
    assert payload.web_search is True

async def test_web_search_flag_is_passed_to_agent_service():
    # FakeAgentService captures kwargs from run_agent_stream
    assert captured["web_search_requested"] is True
```

Also test:

- default is `False`
- selected document/folder scope still works with `web_search=True`
- `strict_scope=True` limits document tools but does not block web search when user explicitly requests it

- [ ] **Step 2: Run tests and verify they fail**

```powershell
py -m pytest backend/tests/test_chat_scope_contract.py backend/tests/test_agent_web_search_tool.py -v
```

Expected: FAIL because request plumbing is missing.

- [ ] **Step 3: Extend `ChatRequest`**

Add:

```python
class ChatRequest(BaseModel):
    question: str
    document_ids: Optional[List[str]] = None
    folder_id: Optional[str] = None
    include_subfolders: bool = False
    strict_scope: Optional[bool] = None
    conversation_id: Optional[str] = None
    web_search: bool = False
```

Do not add arbitrary provider fields to chat requests yet. Provider config comes from saved settings.

- [ ] **Step 4: Thread `web_search` through the backend**

Pass `web_search_requested=request.web_search` from:

- `backend/app/api/chat.py`
- `backend/app/services/chat_service.py`
- `backend/app/services/agent_service.py`

In `AgentService`, resolve settings:

```python
settings = await WebSearchSettingsService(self.db).resolve_for_request(
    user_id=user_id,
    requested=web_search_requested,
)
web_search_enabled = settings["mode"] == "auto" or web_search_requested
```

If `mode == "on-demand"` and request flag is false, omit the tool.

- [ ] **Step 5: Run tests**

```powershell
py -m pytest backend/tests/test_chat_scope_contract.py backend/tests/test_agent_web_search_tool.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/models/schemas.py backend/app/api/chat.py backend/app/services/chat_service.py backend/app/services/agent_service.py backend/tests/test_chat_scope_contract.py backend/tests/test_agent_web_search_tool.py
git commit -m "feat(chat): pass structured web search requests"
```

## Task 6: Frontend Chat Composer Wiring

**Files:**
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/views/ChatView.vue`
- Modify: `frontend/src/stores/chat.ts`
- Modify: `frontend/src/components/chat/ChatComposer.vue`
- Test: `frontend/src/stores/chat.test.ts`

- [ ] **Step 1: Write failing frontend store test**

Add or update a mocked `chatApi.stream` expectation:

```ts
expect(chatApi.stream).toHaveBeenCalledWith(expect.objectContaining({
  question: '查一下最新资料',
  web_search: true,
}))
```

Verify the sent `question` does not contain `[Context: Web Search enabled]`.

- [ ] **Step 2: Run test and verify it fails**

```powershell
cd C:\Users\TT_WT\.codex\worktrees\pagechat-integration\frontend
npm.cmd test -- chat
```

Expected: FAIL because the payload is still prompt-suffixed.

- [ ] **Step 3: Update frontend API types**

In `chatApi.stream`, include:

```ts
web_search?: boolean
```

- [ ] **Step 4: Update `ChatView.handleSubmit`**

Replace prompt suffix construction with structured payload:

```ts
await chatStore.sendMessage(payload.text, {
  ...buildScope(payload),
  web_search: payload.webSearch,
})
```

If `ChatScopeRequest` is too narrow, create a `ChatSendOptions` type in `frontend/src/stores/chat.ts` instead of overloading retrieval types.

- [ ] **Step 5: Preserve composer UX**

Keep:

- plus menu
- Web Search chip
- document chips
- folder chips
- image UI

But only send `images` after the later screenshot upload plan. For this plan, do not pretend image files reach the backend.

- [ ] **Step 6: Run frontend tests**

```powershell
npm.cmd test -- chat
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add frontend/src/api/index.ts frontend/src/views/ChatView.vue frontend/src/stores/chat.ts frontend/src/components/chat/ChatComposer.vue frontend/src/stores/chat.test.ts
git commit -m "feat(frontend): send web search as structured chat state"
```

## Task 7: Settings Modal Web Search Persistence

**Files:**
- Create: `frontend/src/types/webSearchSettings.ts`
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/components/settings/SettingsModal.vue`
- Modify: `frontend/src/ui/pagechatContracts.ts`
- Test: `frontend/src/ui/pagechatContracts.test.ts`

- [ ] **Step 1: Write failing contract tests**

Lock the approved labels:

```ts
expect(WEB_SEARCH_MODE_OPTIONS.map((item) => item.label)).toEqual([
  '用户要求使用',
  '自动调用',
])
```

Add a type-level or simple API payload test if existing test style allows it:

```ts
expect(defaultWebSearchSettings()).toMatchObject({
  provider: 'anysearch',
  mode: 'on-demand',
  zone: 'cn',
})
```

- [ ] **Step 2: Run tests and verify they fail where new helpers are missing**

```powershell
npm.cmd test -- pagechatContracts
```

- [ ] **Step 3: Add API calls**

In `settingsApi`:

```ts
getWebSearchSettings: () => api.get('/settings/web-search'),
updateWebSearchSettings: (payload: WebSearchSettingsUpdate) =>
  api.put('/settings/web-search', payload),
```

- [ ] **Step 4: Wire `SettingsModal.vue` QA section**

Load Web Search settings on modal mount along with providers:

```ts
const [providerResponse, webSearchResponse] = await Promise.all([
  settingsApi.listModelProviders(),
  settingsApi.getWebSearchSettings(),
])
```

Replace local-only `qaSettings.webSearchMode` with saved state.

QA section fields for this plan:

- QA model select remains visually present; if model route persistence is incomplete, show it but do not claim it is saved by this task.
- Web Search mode: `用户要求使用` / `自动调用`
- Provider: `AnySearch`
- API Key: optional, empty means anonymous quota
- Zone: `cn` / `intl`
- Language: `zh-CN` / `en`
- Max results: 1-10
- Content types: Web, News
- Save button with success/error state

- [ ] **Step 5: Run frontend tests**

```powershell
npm.cmd test -- pagechatContracts
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/types/webSearchSettings.ts frontend/src/api/index.ts frontend/src/components/settings/SettingsModal.vue frontend/src/ui/pagechatContracts.ts frontend/src/ui/pagechatContracts.test.ts
git commit -m "feat(settings): wire AnySearch web search settings"
```

## Task 8: End-To-End Behavior Tests

**Files:**
- Modify: `backend/tests/test_agent_web_search_tool.py`
- Modify: `backend/tests/test_agent_service_sanitize.py`
- Modify: `frontend/src/ui/pagechatContracts.test.ts`

- [ ] **Step 1: Add regression tests for large payload safety**

Backend:

```python
def test_web_search_result_does_not_persist_raw_content():
    raw = {"results": [{"content": "A" * 5000, "content_preview": "A" * 700}]}
    cleaned = AgentService._sanitize_tool_result_for_history(raw)
    assert "content" not in str(cleaned)
```

If the sanitizer should not know raw `content`, enforce this in `AnySearchClient` instead and test there.

- [ ] **Step 2: Add trace summary tests**

Frontend:

```ts
const summary = summarizeToolStep({
  toolName: 'web_search',
  arguments: { query: 'PageChat' },
  result: { results: [{ title: 'A' }, { title: 'B' }] },
  status: 'done',
})
expect(summary.action).toBe('Searched the web')
expect(summary.detail).toBe('2 results')
```

- [ ] **Step 3: Run focused tests**

```powershell
py -m pytest backend/tests/test_anysearch_client.py backend/tests/test_agent_web_search_tool.py backend/tests/test_agent_service_sanitize.py -v
cd frontend
npm.cmd test -- pagechatContracts chat
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add backend/tests/test_anysearch_client.py backend/tests/test_agent_web_search_tool.py backend/tests/test_agent_service_sanitize.py frontend/src/ui/pagechatContracts.test.ts
git commit -m "test(search): cover web search payload safety"
```

## Task 9: Full Verification And Browser Smoke

**Files:**
- No intended source changes unless smoke finds a bug.

- [ ] **Step 1: Run backend tests**

```powershell
cd C:\Users\TT_WT\.codex\worktrees\pagechat-integration
py -m pytest backend/tests
```

Expected: all backend tests pass.

- [ ] **Step 2: Run frontend tests**

```powershell
cd C:\Users\TT_WT\.codex\worktrees\pagechat-integration\frontend
npm.cmd test
```

Expected: all frontend tests pass.

- [ ] **Step 3: Run frontend build**

```powershell
npm.cmd run build
```

Expected: build succeeds.

- [ ] **Step 4: Start local preview only if browser verification is needed**

```powershell
npm.cmd run dev -- --host 127.0.0.1
```

Expected: Vite provides a local URL.

- [ ] **Step 5: Browser smoke**

Verify:

- Settings opens as a modal.
- QA settings loads Web Search fields.
- Saving Web Search settings shows success and masks API key.
- Chat composer Web Search chip can be enabled and disabled.
- Submitting with Web Search sends `web_search: true` in the request payload.
- Agent trace shows one inline `Searched the web` row when the mocked or real backend calls the tool.
- No bottom reference pile is introduced; web links stay inline in the answer.

- [ ] **Step 6: Commit any smoke fixes**

```powershell
git add <changed-files>
git commit -m "fix(search): polish web search integration smoke issues"
```

Only commit if smoke revealed and fixed issues.

## Task 10: Integration Handoff

**Files:**
- Modify: `docs/pagechat_integration_development_guide.md` only if needed
- Modify: this plan file only if execution revealed a changed decision

- [ ] **Step 1: Record what is complete**

Update the integration guide or this plan's completion notes with:

- AnySearch API-only integration status
- Settings endpoints added
- Agent tool gating behavior
- Test commands run
- Known limitations

- [ ] **Step 2: Push branch**

```powershell
git push -u origin codex/pagechat-product-behavior-closure
```

Expected: branch exists on remote.

- [ ] **Step 3: Decide next plan**

Do not merge to main yet. After this plan passes, create the next focused plan for one of:

1. Chat screenshot upload backend and multimodal request persistence policy.
2. OCR/Parsing/QA settings full persistence beyond Web Search.
3. Document folder-level backend actions: recursive download, reparse, move, delete.
4. Production empty-state cleanup to remove demo fallbacks from real user flows.

Recommended next item: screenshot upload, because the UI already exposes it and the backend request shape must be designed carefully to avoid base64 persistence.

## Acceptance Criteria

- `GET/PUT /api/settings/web-search` work per user and never return raw API keys.
- Chat requests include `web_search: true` when the user selects Web Search.
- In `on-demand` mode, `web_search` tool is available only when requested.
- In `auto` mode, `web_search` tool is available without requiring the composer chip.
- `web_search` calls AnySearch `POST /v1/search` through REST API only.
- Tool results are compact: no raw AnySearch `content`, no unbounded payloads, no hidden context mutation.
- Tool trace is inline and consistent with the redesigned PageChat chat UI.
- Backend focused tests pass.
- Frontend focused tests pass.
- Full backend tests, frontend tests, and frontend build pass before claiming implementation complete.

## Open Risks

- Anonymous AnySearch quota can fail with `402 daily_free_quota_exhausted`; UI and agent should surface a concise configuration hint.
- AnySearch official docs are dynamic; if response shape differs in practice, normalize defensively and keep tests based on our PageChat contract.
- QA model route persistence is adjacent but not solved by this plan except where already supported by `model_route_mappings`.
- Screenshot upload is still UI-only after this plan; do not describe it as backend-enabled.
- Real web results can be noisy; prompts must require inline links and distinguish web evidence from document evidence.

## Self-Review

Review criteria from `plan-document-reviewer-prompt.md`:

- Completeness: Approved. The plan includes files, tests, implementation steps, verification, and handoff.
- Spec alignment: Approved. It implements API-only AnySearch integration and explicitly excludes MCP for now.
- Task decomposition: Approved. Tasks are split by persistence, API, REST client, agent tool, chat plumbing, frontend wiring, and verification.
- Buildability: Approved with one caution. The plan intentionally uses existing `requests` instead of adding `httpx`; implementers must keep calls off the event loop with `asyncio.to_thread`.

## Execution Notes

Completed on branch `codex/pagechat-product-behavior-closure`.

Implemented:

- Per-user Web Search settings persistence and API endpoints.
- AnySearch REST client with compact result payloads and normalized errors.
- Runtime-gated `web_search` agent tool and prompt/catalog wiring.
- Structured chat request field `web_search`.
- Frontend composer payload wiring and settings modal persistence.
- Payload safety regression for AnySearch raw `content`.

Verification run:

```powershell
py -m pytest backend/tests
cd frontend
npm.cmd test
npm.cmd run build
```

Known limitations:

- MCP integration is intentionally out of scope.
- Screenshot upload remains UI-only until a dedicated multimodal upload/persistence plan.
- Full OCR/Parsing/QA model route persistence remains a later settings milestone.
