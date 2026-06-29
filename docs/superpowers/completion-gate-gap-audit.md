# Completion Gate Gap Audit

## Purpose

This document defines the required audit gate before any implementation work may be described as complete.

The gate is not limited to pull requests. It applies whenever an implementation task, phase, fix, or feature appears finished and the agent is about to make a completion claim.

The goal is to compare the implementation against the user's request, the design documents, the implementation plan, and the actual project state, then identify any remaining gaps before saying the work is done.

## Trigger

Run this audit when the user asks for completion verification or provides this file path after implementation.

The user will provide:

- Path to this audit process document.
- Path to the relevant design document or source requirement document.
- Path to the relevant implementation plan document.
- Optional paths to extra source plans, review notes, or prior gap-closure documents.

Example request:

```text
After implementation, run the audit defined in:
D:\projects\page_chat\docs\superpowers\completion-gate-gap-audit.md
Design document: ...
Implementation document: ...
```

## Completion Rule

Do not say "complete", "done", "finished", or equivalent unless this audit has been run and the result allows completion.

If gaps are found, say:

```text
The main implementation is done, but the completion gate found gaps, so completion cannot be claimed yet.
```

Then list the gaps and recommend either immediate fixes or a gap-closure plan.

## Inputs

The audit should use these inputs, in this order:

1. The latest user request.
2. The design or source requirement document.
3. The implementation plan document.
4. Any related source plans referenced by the design or plan.
5. Current git status and recent commits.
6. Current codebase state.
7. Current focused and regression test results.

If an expected input is missing, continue with available context and record the missing input as an audit limitation.

## Audit Workflow

### 1. Read The Contract

Read the design and implementation documents.

Extract:

- Goal.
- Scope.
- Out-of-scope items.
- Done criteria.
- Task list.
- Required files.
- Required tests.
- Required verification commands.
- Any explicit safety or migration requirements.

Produce a short checklist from the documents before inspecting code.

### 2. Inspect Git State

Run:

```powershell
git status --short
git log --oneline -10
```

Check:

- Which files changed.
- Whether expected files changed.
- Whether unexpected files changed.
- Whether generated files or temporary artifacts are present.
- Whether work is committed, staged, or untracked.

Do not revert unrelated changes. If unrelated changes exist, record them separately.

### 3. Compare Plan To Code

For every task and done criterion, inspect the relevant implementation.

Classify each item:

- `Complete`: implemented and covered by tests or verification.
- `Partial`: implemented but missing coverage, edge cases, or contract details.
- `Missing`: required by plan but not implemented.
- `Diverged`: implemented differently from the plan in a way that may change behavior.
- `Out of scope`: intentionally excluded by the plan.

Use exact file references when reporting findings.

### 4. Scan Risk Boundaries

Use `rg` to scan for stale call paths, old signatures, or bypasses.

Choose scan patterns based on the task. For this project, common boundary scans include:

```powershell
rg -n "ToolExecutor\(|search_service\.search\(|get_indexed_documents\(|get_document\(" backend/app backend/tests
rg -n "cache_service\.|clear_conversation_cache|_CONVERSATION_" backend/app backend/tests
rg -n "retrieval_source|source_anchor|confidence|why_selected|display_label" backend/app backend/tests
rg -n "JWT_SECRET|SECRET_KEY|secrets\.token_hex" backend/app backend/tests
rg -n "delete_folder|delete_document|cleanup_document_artifacts" backend/app backend/tests
```

Adapt the scan to the current work. For frontend work, scan routes, components, state stores, API clients, build config, and tests instead.

### 5. Check Test Coverage

For every requirement, identify the test that proves it.

Record:

- Existing tests that directly cover the requirement.
- Tests that only cover the happy path.
- Requirements with no test.
- Tests that exist but do not assert the critical behavior.

If a requirement is safety-sensitive, missing tests are at least a P1 gap.

### 6. Run Verification

Run the focused verification from the implementation plan.

If the work affects shared backend behavior, also run the relevant regression tests or the full backend suite.

If the work affects frontend behavior, run the frontend build and any relevant frontend tests.

For this project, common commands are:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest <focused-tests> -q
C:\Users\TT_WT\.local\bin\uv.exe run pytest -q
npm.cmd run build
```

If a command cannot be run, record:

- Command.
- Reason it could not be run.
- Risk created by missing verification.

### 7. Produce Gap Report

Report findings before summaries.

Use this severity model:

- `P0`: Security issue, data leakage, destructive data loss, auth bypass, migration breakage, or broad test failure. Must fix before completion.
- `P1`: Explicit plan requirement missing, core behavior wrong, critical test missing, or done criterion not satisfied. Must fix before completion unless the user explicitly accepts a gap-closure plan.
- `P2`: Non-blocking quality issue, explainability gap, minor missing coverage, documentation mismatch, or cleanup item. Can be deferred only if documented.

Each finding must include:

- Severity.
- Short title.
- File and line reference when possible.
- Why it matters.
- Suggested fix or next action.

### 8. Decide Completion Status

Use this decision table:

| Audit result | Completion claim allowed? | Required response |
| --- | --- | --- |
| No P0/P1 gaps, tests pass | Yes | State completion and summarize verification. |
| P2 gaps only | Conditional | State completion with documented follow-up items. |
| Any P0 gap | No | Do not claim completion. Fix immediately or ask for direction if blocked. |
| Any P1 gap | No by default | Fix immediately or generate a gap-closure plan if user wants deferral. |
| Required verification not run | No by default | State what was not verified and why. |

## Output Format

Use this report shape:

```markdown
**Completion Gate Result:** Pass | Conditional Pass | Fail

**Findings**
- P1: Title
  File: path:line
  Why it matters:
  Fix:

**Plan Alignment**
- Complete:
- Partial:
- Missing:
- Out of scope:

**Verification**
- Passed:
- Failed:
- Not run:

**Decision**
Can/cannot declare implementation complete because ...

**Next Step**
Fix now / create Phase X.Y gap-closure plan / ask user for scope decision.
```

Keep the report concise, but include enough detail for implementation to continue without rediscovery.

## Gap-Closure Plan Rule

If completion fails because of P0 or P1 gaps and the user chooses not to fix immediately, create a gap-closure plan.

Name it according to the current phase:

```text
docs/superpowers/<YYYY-MM-DD>-phase-<N>.<M>-gap-closure.md
```

The plan must include:

- Why it exists.
- Current verification baseline.
- Files and responsibilities.
- Bite-sized tasks.
- Failing tests first.
- Exact verification commands.
- Done criteria.
- Out-of-scope items.

## Agent Behavior Requirements

The agent running this gate must:

- Treat the audit as a separate task from implementation.
- Avoid changing files during the audit unless the user explicitly asks to fix gaps.
- Prefer `rg` for code scanning.
- Run verification commands when feasible.
- Report command failures accurately.
- Avoid declaring completion when verification was skipped.
- Work with existing uncommitted user changes instead of reverting them.

## Notes For Future Automation

This document is intentionally process-first. A later automation can collect raw evidence automatically:

- Git status.
- Recent commits.
- Changed files.
- Plan headings and checkbox status.
- Test command output.
- `rg` scan results.

The semantic comparison between plan, code, tests, and user intent should remain an explicit review step until the project has enough repeated audit examples to script safely.
