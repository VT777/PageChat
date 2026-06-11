# Next Phase Roadmap

Date: 2026-06-10

## Roadmap Authority

This roadmap supersedes the "Recommended Next Phases" section in `docs/superpowers/2026-06-10-phase-1-improvement-report.md`.

The Phase 1 report recommended model configuration as the next candidate phase. After reviewing the 2026-06-10 source plans, the execution order was changed to protect the product's core value first: reliable document-grounded answers with stable evidence anchors, quality signals, and scoped retrieval behavior.

## Current Baseline

Phase 7 is the current implementation baseline. Phase 4 remains the retrieval-scope foundation baseline that later frontend and adapter phases must preserve.

Verified baseline from the Phase 4 report:

- Phase 4 focused backend suite: `45 passed`
- Full backend suite: `342 passed, 8 skipped`
- Folder-aware chat scope fields are available: `folder_id`, `include_subfolders`, `document_ids`, and `strict_scope`.
- Folder-scoped search filters documents by folder, descendants, selected documents, and allowed document boundaries.
- Agent tools can list folder trees and folder contents.
- `find_related_documents` can honor explicit document and folder scope and returns scope trace metadata.
- Compact tree output is available for Agent-facing structure inspection.
- A lightweight retrieval planner chooses deterministic first-step retrieval routes before the Agent fallback loop.
- Pushed commit: `f219756 feat: add folder-aware agent retrieval`

Phase 4 changed the backend assumption from "selected documents are the main chat scope" to "chat scope is an explicit retrieval boundary." Later phases should treat Phase 4 scope semantics and trace metadata as the current contract.

Verified baseline from the Phase 3 report:

- Phase 3 focused backend suite: `19 passed`
- Full backend suite: `308 passed, 8 skipped`
- Tree quality reports are persisted as additive PDF index metadata.
- Document responses can expose optional `quality_report` metadata.
- Retrieval regression fixtures cover index quality and source anchors.
- The agent prompt has an explicit tree-first retrieval policy with visible fallback expectations.
- Pushed commit: `e8ce754 feat: add phase 2 and 3 retrieval foundations`

Verified baseline from the Phase 2 report:

- Phase 2 focused backend suite: `37 passed`
- Full backend suite: `293 passed, 8 skipped`
- Frontend compatibility build: passed from `frontend/` with `npm.cmd run build`

Phase 1 established these safety contracts:

- Tool, search, cache, and document access paths require user scope.
- `allowed_doc_ids` narrows access but does not grant cross-user access.
- Retrieval results expose additive trace fields.
- Upload filenames are normalized and stored with generated safe names.
- Folder and document deletion clear files, indexes, document caches, and agent state.
- JWT signing secret is stable and environment-backed.
- Lightweight migrations and core indexes exist.

Phase 2 established these evidence contracts:

- Current non-PDF adapters emit explicit `source_anchor.unit_type`.
- Search and tool outputs preserve `source_anchor`, `display_label`, `retrieval_source`, `confidence`, and `why_selected`.
- Preview blocks may carry additive `source_anchor` metadata.
- A canonical adapter data model exists under `backend/app/services/format_adapters/`.
- Source anchors can be resolved to bounded source content for TXT, Markdown, CSV/TSV, XLSX, DOCX, and PPTX through the current resolver.
- PDF page anchors remain handled by the existing page-content path.

## Strategic Direction

The next work should protect the product's core value: reliable document-grounded answers.

Do not start with a model settings UI or a production frontend redesign. Those are valuable, but they depend on stable retrieval evidence, source anchors, quality signals, and tool behavior.

Recommended order:

1. Phase 2: Source Anchor And Multi-Format Foundation
2. Phase 3: Tree Retrieval Quality Gates
3. Phase 4: Folder-Aware Agent Retrieval
4. Phase 5: User-Configurable Model Foundation
5. Phase 6: Frontend Evidence And Settings Integration
6. Phase 7: Multi-Format Adapter Migration
7. Phase 8: Document Management Production Redesign

## Phase Documents

- `docs/superpowers/plans/2026-06-10-phase-2-source-anchor-multiformat-foundation.md`
- `docs/superpowers/plans/2026-06-10-phase-3-tree-retrieval-quality-gates.md`
- `docs/superpowers/plans/2026-06-10-phase-4-folder-aware-agent-retrieval.md`
- `docs/superpowers/plans/2026-06-10-phase-5-user-configurable-model-foundation.md`
- `docs/superpowers/plans/2026-06-10-phase-6-frontend-evidence-settings-integration.md`
- `docs/superpowers/plans/2026-06-10-phase-7-multiformat-adapter-migration.md`
- `docs/superpowers/plans/2026-06-10-phase-8-document-management-production-redesign.md`

## Source Plan Mapping

The 2026-06-10 source plans under the user-provided copied source-plan directory were consolidated into the phase documents above.

Use `<source-plan-copy>` below to mean that copied source-plan root.

| Source plan | Current phase coverage |
| --- | --- |
| `2026-06-10-core-tree-retrieval-quality-plan.md` | Phase 2 source anchors, Phase 3 quality gates, Phase 6 evidence display |
| `2026-06-10-multi-format-document-support-plan.md` | Phase 2 anchor foundation, Phase 7 full adapter migration |
| `2026-06-10-agent-retrieval-improvement-plan.md` | Phase 4 folder-aware agent retrieval |
| `2026-06-10-user-configurable-models.md` | Phase 5 backend model foundation, Phase 6 settings UI |
| `2026-06-10-frontend-design-plan.md` | Phase 6 evidence/settings integration, Phase 8 document management redesign |

When source plans and phase plans disagree, use the current phase plan as the implementation contract. Use source plans only for background rationale and gap checks.

## Dependency Map

```text
Phase 1 safety baseline
  -> Phase 2 source anchors and multi-format parsing
    -> Phase 3 tree retrieval quality gates
      -> Phase 4 folder-aware agent retrieval
        -> Phase 6 evidence-aware frontend
      -> Phase 7 full multi-format adapter migration
        -> Phase 8 document management production redesign
  -> Phase 5 model settings foundation
    -> Phase 6 settings frontend
```

Phase 5 can begin after Phase 2 if team capacity allows, but it should not modify retrieval cache semantics without preserving the user/scope/model-route cache contracts.

## Post-Phase-5 Baseline

Phase 5 is now implemented as the backend model-settings foundation.

Current Phase 5 evidence:

- Phase 5 focused backend suite: `39 passed`
- Full backend suite: `369 passed, 8 skipped`
- Completion gate result: conditional pass with no P0/P1 gaps
- Accepted P2 follow-up: deep PageIndex indexing calls needed user-aware route integration before the frontend could treat indexing model controls as production-ready.

Phase 5.1 has closed that P2 follow-up:

- `docs/superpowers/plans/2026-06-11-phase-5-1-indexing-route-closure.md`
- `docs/superpowers/2026-06-11-phase-5-and-5-1-execution-report.md`

Current Phase 5.1 evidence:

- Phase 5.1 focused backend suite: `25 passed`
- Indexing regression suite: `34 passed, 4 skipped`
- Full backend suite after Phase 5.1: `379 passed, 8 skipped`
- Final commit: `f3fb13d feat: add user-configurable model routing foundation`

Use the Phase 5.1 report and verification output as the backend baseline for indexing model controls.

## Post-Phase-6 Baseline

Phase 6 is now implemented as the frontend evidence and settings integration layer.

Current Phase 6 evidence:

- Frontend evidence and retrieval-scope utility tests: `9 passed`
- Model settings API focused backend suite: `9 passed`
- Frontend production build: passed
- Full backend suite after Phase 6: `383 passed, 8 skipped`
- Completion gate result: pass, with no P0/P1 gaps
- Browser smoke verification covered login/register, chat scope controls and evidence preview shell, document empty-state rendering, provider key replacement, and route mapping save.

Use the Phase 6 implementation report as the current frontend contract for:

- Anchor-aware evidence labels in chat and source preview.
- Retrieval fallback disclosure.
- Retrieval scope controls and trace display.
- Optional document `quality_report` display.
- Write-only model provider credentials and route mapping fallback behavior.

Phase 7 must preserve these Phase 6 UI contracts while migrating non-PDF parsing internals. New adapter output should remain additive and compatible with the Phase 6 frontend evidence, preview, quality, and scope displays.

## Post-Phase-7 Baseline

Phase 7 is now implemented as the main multi-format adapter migration.

Current Phase 7 evidence:

- Phase 7 focused backend suite: `42 passed`
- Retrieval and citation contract suite: `14 passed`
- Full backend suite after Phase 7: `412 passed, 8 skipped`
- Frontend production build: passed
- Completion gate result: pass, with no P0/P1 gaps
- Accepted P2 follow-up: legacy `.doc`, `.xls`, and `.ppt` conversion remains deferred as Phase 7b.

Use the Phase 7 implementation report as the current backend parsing contract for:

- Canonical TXT, Markdown, CSV/TSV, XLSX, DOCX, and PPTX adapters.
- `multi_format_adapter.py` as the compatibility facade for non-PDF index generation.
- Canonical preview extraction for supported non-PDF formats where available.
- Table aggregation citations with canonical `source_anchor` and `display_label`.
- Parser-backed source-anchor resolution for line, row, paragraph, and slide anchors.
- Legacy Office rejection unless conversion support is explicitly implemented and tested.

Phase 8 must preserve the Phase 6 frontend evidence contract and the Phase 7 canonical preview/source-anchor behavior while redesigning document management UI.

## Immediate Recommendation

Proceed to Phase 8: Document Management Production Redesign.

Why:

- Phase 7 has stabilized non-PDF parsing, preview anchors, table citations, and source-anchor resolution for the current supported formats.
- Phase 6 already surfaces evidence labels, preview anchors, quality status, retrieval scope traces, and model routes in the frontend.
- Phase 8 can now redesign document management on top of stable evidence, preview, and quality contracts.
- Legacy Office conversion remains valuable, but it should only interrupt Phase 8 if the product explicitly prioritizes `.doc`, `.xls`, and `.ppt` upload compatibility.

Recommended immediate execution order:

1. Confirm Phase 7 worktree changes are committed or explicitly accepted as the current baseline before starting Phase 8 implementation.
2. Run a Phase 8 entry audit of the current document API/store fields and record graceful placeholders for unavailable detail-panel fields.
3. Implement the production three-column document workbench layout.
4. Implement the dense document list, stable batch mode, and compact detail panel.
5. Refine the preview modal without regressing Phase 6 evidence labels or Phase 7 canonical source anchors.
6. Run frontend build, responsive/manual QA, and the Phase 8 completion gate.

Phase 7b branch candidate:

- Add detector and converter modules for legacy Office formats.
- Detect LibreOffice availability without failing startup.
- Keep `.doc`, `.xls`, and `.ppt` rejected when conversion is unavailable.
- Store converted artifacts under a controlled directory and clean them up with document/folder deletion.
- Add conversion, rejection, and cleanup tests before adding legacy extensions to `ALLOWED_EXTENSIONS`.

## Cross-Phase Rules

- Keep Phase 1 safety contracts intact.
- Preserve existing response fields when adding new metadata.
- Treat new backend response fields as additive unless a phase explicitly approves a breaking API change.
- Keep frontend types and API clients synchronized whenever backend response shapes are extended.
- Write failing tests before implementation.
- Run focused tests after each task.
- Run the completion gate before claiming a phase complete:
  `docs/superpowers/completion-gate-gap-audit.md`
- Do not add legacy `.doc`, `.xls`, or `.ppt` upload support until conversion support exists and is tested.
- Do not expose user API keys back to the frontend after saving model settings.
- Do not treat Phase 2 as the full multi-format implementation. Phase 2 only stabilizes anchors and current paths; Phase 7 migrates current whitelisted formats to canonical adapters, and Phase 7b handles legacy Office conversion if prioritized.
- Treat Phase 2 as complete for roadmap sequencing. Do not reopen Phase 2 scope unless the Phase 2 report or completion gate records a regression.
- Do not claim tree retrieval quality is complete until tree-first policy, fallback thresholds, and compact tree output are covered in Phases 3 and 4.
- Keep legacy `NULL user_id` records quarantined from new retrieval, tool, and settings behavior unless a phase explicitly defines a migration or ownership policy.
- Add bounded retrieval and parsing limits when new flows can expand work: candidate document count, fetched source range, row chunk size, and agent/tool loop count should be explicit in the relevant phase.

## Completion Gate Inputs

Every phase should run the completion gate with these inputs:

- `docs/superpowers/completion-gate-gap-audit.md`
- This roadmap.
- The current phase plan under `docs/superpowers/plans/`.
- `docs/superpowers/2026-06-10-phase-1-improvement-report.md`
- `docs/superpowers/2026-06-10-phase-2-improvement-report.md`
- `docs/superpowers/2026-06-10-phase-3-improvement-report.md`
- `docs/superpowers/2026-06-11-phase-4-improvement-report.md`
- `docs/superpowers/plans/2026-06-11-phase-4-gap-closure.md`
- `docs/superpowers/2026-06-11-phase-5-improvement-report.md`
- `docs/superpowers/2026-06-11-phase-5-and-5-1-execution-report.md`
- `docs/superpowers/plans/2026-06-11-phase-5-1-indexing-route-closure.md`
- `docs/superpowers/2026-06-11-phase-6-implementation-report.md`
- `docs/superpowers/2026-06-11-phase-7-implementation-report.md`
- Any source plan listed in the mapping above that corresponds to the phase.
- Current git status and test output from the phase verification commands.

## Verification At The End Of Every Phase

Backend-focused phases should run:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest -q
```

Frontend-touching phases should also run:

```powershell
cd frontend
npm.cmd run build
```

Before final completion claims, run the completion gate audit and record any gaps as a phase-specific gap-closure plan.
