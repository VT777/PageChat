# Evaluation Fixtures

These fixtures provide small, deterministic checks for index and retrieval quality.

Rules:

- Keep files tiny enough for the normal backend suite.
- Do not require network access or live model calls.
- Prefer synthetic content with obvious expected headings and anchors.
- Add expected query metadata to `queries.json` whenever a fixture is used by retrieval regression tests.

The goal is not to benchmark model quality. The goal is to catch accidental loss of nodes, anchors, retrieval trace fields, or fallback visibility.
