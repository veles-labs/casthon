# Casthon website

Static, buildless tutorial site published at
<https://veles-labs.github.io/casthon/>. Preview it from the repository root with:

```sh
python3 -m http.server 8000 --directory website
```

Then visit `http://localhost:8000/`. All internal links and asset paths are
relative so the site also works under the project's `/casthon/` Pages path.
Run `python3 scripts/check_website_links.py` from the repository root before
each push. It checks shipped paths, anchors, and repository source links; the
Pages workflow runs the same check before upload. External sites need a separate
network check.

| Website page | Detailed source |
| --- | --- |
| `index.html` (getting started) | `README.md`, `docs/casthon.md`, `templates/flipper/` |
| `python-api.html` | `docs/python-api.md` |
| `testing.html` | `docs/testing.md` |
| `examples.html` | `docs/cep18.md`, `docs/cep78.md`, `contracts/` |

`llms.txt` is the Pages site's agent-readable guide map. It links to
these pages and the detailed Markdown references in the repository. Update it
when page or reference paths change. `AGENTS.md` has the corresponding
documentation-maintenance instructions.

The GitHub Actions workflow in `.github/workflows/pages.yml` uploads `website/`
and deploys when website files or its link checker change on `main`, or on
manual runs. The repository's Pages source is **GitHub Actions**. The site
links to source and documentation in the same public repository.

The setup tutorial installs `casthon` from crates.io. The deployment tutorial
installs `casper-cli` from crates.io. Run `casthon doctor` after installation;
it probes the CLI features needed for speculative execution, RPC-backed
simulation, and stored calls.

The guides reflect the developer-preview workflow described in the Markdown
references and the maintained Flipper scaffold in `templates/flipper/`. Update
both the relevant Markdown reference and website page when commands or contract
APIs change.

Code blocks use a local copy of Prism 1.30.0 (MIT license in
`assets/prism/LICENSE`), so highlighting works in an offline preview. The output
cards are representative excerpts; machine versions, test counts, gas, paths,
transaction hashes, and block heights vary.
