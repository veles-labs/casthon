# Repository guidance

Casthon's code and tests are the source of truth. Keep the detailed Markdown
references and the approachable website guides aligned when behavior, commands,
or examples change.

| Topic | Detailed reference | Website guide |
| --- | --- | --- |
| Setup, CLI, build, deployment | README.md, docs/casthon.md | website/index.html |
| Contract classes, state, ABI, events | docs/python-api.md | website/python-api.html |
| Native, Wasm, and live testing | docs/testing.md | website/testing.html |
| CEP-18 and CEP-78 examples | docs/cep18.md, docs/cep78.md, contracts/, templates/flipper/ | website/examples.html |

When editing a row's code or reference, review both documentation columns in
the same change. Keep commands runnable from the directory named beside each
block. Match snippets to current contract source. Label output excerpts as
examples when paths, versions, test counts, gas, hashes, or block heights vary.
Verify CLI output wording against the implementation or a local run.
Keep the install hint in cli/doctor.rs aligned with the deployment guide and
website tutorial.

The website is a static GitHub Pages project site under /casthon/. Keep
internal links and assets relative. website/llms.txt is its agent-readable
map; update it when guides or detailed reference paths change. The pages link
back to the full Markdown references for details they intentionally summarize.

For website edits, run python3 scripts/check_website_links.py, check JavaScript
syntax with node --check website/main.js, serve website/ locally, and inspect
the affected pages at desktop and mobile widths. Keep the Flipper examples in
the tutorial and guides consistent with
templates/flipper/contracts/flipper.py and its tests.
