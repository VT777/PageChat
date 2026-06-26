# PageChat LLM Planner Agent Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This repository session must not dispatch subagents.

**Goal:** Replace the deterministic `PolicyGuidedPlanner` product path with a model-driven structured planner while keeping PageChat's explicit runtime event protocol, tool guardrails, and evidence controls.

**Architecture:** `AgentLoopRuntime` remains the loop coordinator. A new `StructuredLLMPlanner` asks the configured QA model for one short visible thought and one structured action at a time. A new `AgentPolicy` validates actions, injects safe scope defaults, blocks invalid/repeated/unauthorized actions, and asks the planner to retry through guardrail observations instead of hardcoding a route.

**Tech Stack:** Python 3.11, pytest, PageChat backend services, existing OpenAI-compatible `chat_by_scenario`, Vue timeline already compatible with `progress(kind=plan|observation|guardrail)` and tool rows.

---

## File Structure

- Create `backend/app/agent/planner.py`
  - Owns planner protocols, `StructuredLLMPlanner`, JSON parsing, retry prompt construction, and a small deterministic fallback planner used only by tests or explicit fallback.
- Create `backend/app/agent/policy.py`
  - Owns action validation, safe argument patching, web search gating, evidence checks, and repeated tool signature checks.
- Modify `backend/app/agent/loop_runtime.py`
  - Keep `PlannerAction`, `ObservationBuilder`, and runtime stream shape.
  - Move deterministic planner out of the product path.
  - Add policy validation before executing actions or final answers.
  - Emit guardrail progress events and retry planner decisions.
- Modify `backend/app/services/agent_service.py`
  - Build `StructuredLLMPlanner` with request tool catalog, user id, route settings, and policy constraints.
  - Continue simple chat bypass for non-retrieval conversation.
- Modify `backend/app/prompts/__init__.py`
  - Add planner prompt builder or constants if not colocated in `planner.py`.
- Modify tests:
  - `backend/tests/test_agent_loop_runtime.py`
  - `backend/tests/test_agent_service_loop_runtime.py`
  - Add `backend/tests/test_agent_structured_llm_planner.py`
  - Add `backend/tests/test_agent_policy.py`

## Task 1: Add Planner Contract and Parsing Tests

**Files:**
- Create: `backend/app/agent/planner.py`
- Test: `backend/tests/test_agent_structured_llm_planner.py`

- [ ] **Step 1: Write failing tests**

Cover:

```python
def test_structured_planner_parses_call_tool_action():
    planner = StructuredLLMPlanner(completion_fn=fake_completion_json(...), tools=[...])
    action = await planner.next_action(state)
    assert action.thought == "我先查看资料库目录。"
    assert action.action_type == "call_tool"
    assert action.tool_name == "view_folder_structure"
```

Also cover:

```python
def test_structured_planner_retries_invalid_json_once():
    # first response: non-json, second response: valid JSON
```

```python
def test_structured_planner_does_not_use_template_thought():
    # fake model returns a unique thought; planner must pass it through exactly
```

- [ ] **Step 2: Verify red**

Run:

```powershell
D:/projects/page_chat/backend/venv/Scripts/python.exe -m pytest backend/tests/test_agent_structured_llm_planner.py -q
```

Expected: fails because `app.agent.planner` does not exist.

- [ ] **Step 3: Implement minimal planner**

Implement:

```python
class PlannerAdapter(Protocol):
    async def next_action(self, state: AgentRunState) -> PlannerAction: ...

class StructuredLLMPlanner:
    def __init__(self, *, completion_fn, tools, user_id=None, max_retries=1): ...
    async def next_action(self, state): ...
```

Rules:

- call `completion_fn` with `scenario="qa"`, `stream=False`, `temperature=0`;
- return JSON only prompt;
- accept OpenAI-compatible message response shapes;
- strip fenced code blocks before JSON parse;
- normalize action schema into `PlannerAction`.

- [ ] **Step 4: Verify green**

Run the same pytest command. Expected: all tests in the new file pass.

## Task 2: Add Policy Guardrails With Tests

**Files:**
- Create: `backend/app/agent/policy.py`
- Test: `backend/tests/test_agent_policy.py`

- [ ] **Step 1: Write failing tests**

Cover:

```python
def test_policy_rejects_unknown_tool():
    result = policy.validate(PlannerAction.call_tool("delete_everything", {}), state)
    assert not result.allowed
    assert result.observation["kind"] == "guardrail"
```

```python
def test_policy_injects_single_selected_doc_id():
    state.scope["document_ids"] = ["doc-alpha"]
    action = PlannerAction.call_tool("get_document_structure", {})
    assert result.action.arguments["doc_id"] == "doc-alpha"
```

```python
def test_policy_blocks_web_search_when_disabled():
```

```python
def test_policy_blocks_repeated_same_tool_signature():
```

```python
def test_policy_blocks_document_answer_without_evidence():
```

- [ ] **Step 2: Verify red**

Run:

```powershell
D:/projects/page_chat/backend/venv/Scripts/python.exe -m pytest backend/tests/test_agent_policy.py -q
```

Expected: fails because `app.agent.policy` does not exist.

- [ ] **Step 3: Implement minimal policy**

Implement:

```python
@dataclass(frozen=True)
class PolicyValidation:
    allowed: bool
    action: PlannerAction | None = None
    observation: dict[str, Any] | None = None

class AgentPolicy:
    def validate(self, action: PlannerAction, state: AgentRunState) -> PolicyValidation: ...
    def mark_tool_executed(self, action: PlannerAction) -> None: ...
```

Policy responsibilities:

- allowed tools from runtime catalog;
- patch doc id for single selected document scope;
- patch folder id and recursive flag for strict selected folder scope where safe;
- reject `web_search` unless both requested and enabled;
- reject repeated same normalized tool signature;
- reject document answer if no observation/evidence has `evidence_sufficient=True`, unless the question is clearly conversational or planner is asking clarification/failing.

- [ ] **Step 4: Verify green**

Run the same pytest command. Expected: all policy tests pass.

## Task 3: Wire Policy Into AgentLoopRuntime

**Files:**
- Modify: `backend/app/agent/loop_runtime.py`
- Test: `backend/tests/test_agent_loop_runtime.py`

- [ ] **Step 1: Add failing runtime tests**

Add tests that prove:

- invalid planner action emits `progress(kind="guardrail")` and planner is called again;
- model-generated `thought` appears in `progress(kind="plan")`;
- rejected final answer without evidence does not stream answer immediately;
- runtime stops with a useful error after max guardrail retries.

- [ ] **Step 2: Verify red**

Run:

```powershell
D:/projects/page_chat/backend/venv/Scripts/python.exe -m pytest backend/tests/test_agent_loop_runtime.py -q
```

Expected: new guardrail tests fail.

- [ ] **Step 3: Implement runtime policy loop**

Add optional `policy` parameter to `AgentLoopRuntime`.

Loop:

```text
planner.next_action
emit plan thought
policy.validate
if rejected: append guardrail observation, emit guardrail progress, continue
if call_tool: execute, mark executed, observe, continue
if answer: stream answer
```

Do not generate template thought in runtime.

- [ ] **Step 4: Verify green**

Run the same pytest command. Expected: all runtime tests pass.

## Task 4: Replace Product Planner in AgentService

**Files:**
- Modify: `backend/app/services/agent_service.py`
- Test: `backend/tests/test_agent_service_loop_runtime.py`

- [ ] **Step 1: Write failing service tests**

Cover:

```python
def test_agent_service_builds_structured_llm_planner_not_policy_guided():
    runtime = service.build_agent_loop_runtime(...)
    assert type(runtime.planner).__name__ == "StructuredLLMPlanner"
```

```python
def test_agent_service_passes_request_tool_catalog_to_planner_and_policy():
```

- [ ] **Step 2: Verify red**

Run:

```powershell
D:/projects/page_chat/backend/venv/Scripts/python.exe -m pytest backend/tests/test_agent_service_loop_runtime.py -q
```

Expected: fails because service still builds `PolicyGuidedPlanner`.

- [ ] **Step 3: Implement product wiring**

In `build_agent_loop_runtime()`:

- create `StructuredLLMPlanner(completion_fn=chat_by_scenario, tools=self._tools_for_request(...), user_id=...)`;
- create `AgentPolicy(tools=runtime_tools)`;
- pass both into `AgentLoopRuntime`;
- keep deterministic fallback import available only for tests.

In `run_agent_stream()`:

- pass `runtime_tools`, `user_id`, and web search active state into runtime builder.

- [ ] **Step 4: Verify green**

Run service runtime tests. Expected: pass.

## Task 5: Integration Event Contract and Regression Tests

**Files:**
- Modify existing backend tests as needed:
  - `backend/tests/test_agent_run_event_protocol.py`
  - `backend/tests/test_agent_retrieval_planner_integration.py`
  - `backend/tests/test_agent_service_sanitize.py`

- [ ] **Step 1: Run focused integration tests**

Run:

```powershell
D:/projects/page_chat/backend/venv/Scripts/python.exe -m pytest backend/tests/test_agent_run_event_protocol.py backend/tests/test_agent_retrieval_planner_integration.py backend/tests/test_agent_service_sanitize.py -q
```

- [ ] **Step 2: Fix real regressions**

Expected fixes may include monkeypatching planner responses in tests that used to assume deterministic first steps.

- [ ] **Step 3: Re-run focused tests**

Expected: all focused tests pass.

## Task 6: Full Verification and Service Restart

**Files:**
- No production edits unless verification finds bugs.

- [ ] **Step 1: Run full backend tests**

Run:

```powershell
D:/projects/page_chat/backend/venv/Scripts/python.exe -m pytest backend/tests -q
```

Expected: pass.

- [ ] **Step 2: Run full frontend tests**

Run:

```powershell
npm.cmd test
```

Expected: pass.

- [ ] **Step 3: Restart backend and frontend**

Stop stale local processes on ports `8000` and `5173`, then start from:

```text
C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration
```

Expected:

- Backend health `http://127.0.0.1:8000/health` returns `{"status":"ok"}`.
- Frontend loads `http://127.0.0.1:5173/`.

## Acceptance Checklist

- [ ] `AgentService` product path uses `StructuredLLMPlanner`.
- [ ] Planner thought/action comes from model response, not backend templates.
- [ ] Runtime still emits PageChat events only.
- [ ] Guardrails reject bad actions without turning into a deterministic route planner.
- [ ] Web search is only callable when requested and enabled.
- [ ] Document answers require evidence or clarification.
- [ ] Tests prove the old hardcoded planner is not the default product path.
