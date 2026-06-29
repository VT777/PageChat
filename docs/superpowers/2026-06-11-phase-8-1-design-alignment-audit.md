# Phase 8.1 Design Alignment Audit

Date: 2026-06-11

## Baseline

The visual baseline demo has been restored from:

```text
D:\projects\page_chat - 副本\frontend\src\views\DesignDemoView.vue
```

It is available in the current app as:

```text
/design-demo
```

This route is a QA reference only. Production screens should borrow layout rhythm, density, spacing, and control styling from the demo without turning the demo component itself into production code.

## Files Compared

- `frontend/src/views/DesignDemoView.vue`
- `frontend/src/views/DocumentView.vue`
- `frontend/src/views/SettingsView.vue`
- `frontend/src/views/ChatView.vue`
- `frontend/src/components/preview/*`
- `frontend/src/components/document/TocTree.vue`

## Document Management Alignment

Current drift:

- The production document workbench is denser and more operational than the demo, but some Phase 8 additions read as extra chrome instead of integrated controls.
- Preview copy and several preview subviews had corrupted text or assumptions that only PDF worked reliably.
- Non-PDF preview routing was inconsistent with backend canonical content for TXT, Markdown, table, DOCX, and PPTX.

Keep:

- Batch operations, folder scope, processing status, parse mode, evidence-oriented metadata, and dense list controls. These are later-phase product requirements.
- The document detail/preview split as the production information architecture.

Fix direction:

- Keep controls visually quiet and aligned with the demo's restrained toolbar/card rhythm.
- Avoid adding explanatory panels that are not needed for repeated document-management workflows.
- Treat the restored demo as the visual comparator before adding new workbench surface area.

## Settings Alignment

Current drift:

- Settings includes later model/provider controls that were not part of the original demo.
- The settings page should preserve the demo's compact form rhythm and section hierarchy, not become a broad dashboard.

Keep:

- Model/provider settings, because later phases intentionally added configurable model behavior.

Fix direction:

- Keep settings sections narrow, form-first, and predictable.
- Avoid marketing-style cards or oversized explanatory blocks.
- Group advanced model controls behind compact sections if the page grows.

## Main Chat Alignment

Current drift:

- The chat screen has added scope selection, evidence labels, rollback controls, and source preview affordances beyond the original demo.
- Some of these controls can visually compete with the conversation if they are always expanded.

Keep:

- Evidence labels, scoped retrieval controls, rollback state, and right-side source preview. They are core to the later retrieval and audit workflow.

Fix direction:

- Keep default chat composition close to the demo: conversation first, controls secondary.
- Collapse or visually quiet advanced controls unless actively needed.
- Do not fall back to fake PDF preview for unsupported file types; show an honest unsupported state.

## Preview Alignment

Implemented in this slice:

- Restored the `/design-demo` route.
- Centralized preview support mapping for TXT, Markdown, CSV, TSV, XLSX, DOCX, and PPTX.
- Kept legacy `.doc`, `.xls`, and `.ppt` outside frontend preview support, matching the backend boundary.
- Repaired canonical non-PDF preview rendering for text, markdown, table, and presentation blocks.
- Replaced corrupted visible copy in touched preview and TOC paths.

Remaining visual QA:

- Compare `DocumentView`, `SettingsView`, and `ChatView` side by side with `/design-demo`.
- Remove or restyle any production-only blocks that do not support repeated workflows.
- Run browser screenshots for `/design-demo`, `/documents`, `/settings`, and `/chat` after the final UI pass.
