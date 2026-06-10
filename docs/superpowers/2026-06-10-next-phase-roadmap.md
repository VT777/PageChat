# Next Phase Roadmap

Date: 2026-06-10

## Roadmap Authority

This roadmap supersedes the "Recommended Next Phases" section in `docs/superpowers/2026-06-10-phase-1-improvement-report.md`.

The Phase 1 report recommended model configuration as the next candidate phase. After reviewing the 2026-06-10 source plans, the execution order was changed to protect the product's core value first: reliable document-grounded answers with stable evidence anchors, quality signals, and scoped retrieval behavior.

## Current Baseline

Phase 3 is the current foundation baseline.

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

## Immediate Recommendation

Start with Phase 4.

Why:

- Phase 3 has already made tree retrieval quality measurable through quality reports, regression fixtures, fallback thresholds, and tree-first policy tests.
- The next unlock is making retrieval scope explicit across folders, selected document sets, and current-user library search.
- Phase 4 should use Phase 3 quality signals when deciding whether to trust document structure or disclose fallback evidence.
- Phase 6 evidence UI can start with Phase 2/3 fields, but chat scope UI should wait for Phase 4 backend behavior.
- Phase 5 can proceed in parallel only after the model-settings ownership and secret-storage decisions are recorded.

Recommended immediate execution order:

1. Phase 4 Task 1: folder-aware search filtering.
2. Phase 4 Task 2: folder navigation tools.
3. Phase 4 Task 3: scope-aware `find_related_documents`.
4. Phase 4 Task 4: compact tree structure output.
5. Phase 4 Task 5: lightweight retrieval planner.

Parallel candidate:

- Phase 5 may begin only after its security gate decisions are resolved. It should not change retrieval cache semantics unless user, scope, and model-route cache contracts stay explicit.

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
- Do not treat Phase 2 as the full multi-format implementation. Phase 2 only stabilizes anchors and current paths; Phase 7 migrates each format to canonical adapters and handles legacy conversion.
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
