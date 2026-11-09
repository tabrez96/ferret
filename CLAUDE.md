# Ferret

Credit card spending visibility from your statements, with no manual entry

Credit card holders have no clear view of what they spend. Entering transactions by hand is a chore, so it never gets done. The owner has this problem and so do their friends. Statements already contain every transaction, but they arrive as password-protected PDFs or as emails, and nothing turns them into usable data. Evidence: first-hand need from the owner and friends. No market numbers have been gathered, and none are claimed here.

## Where things are
- `design/` is the design library: `brief.md`, `ux.md`, and `screens/S01-name/` (`screen.png` + `spec.md`, plus
  `states/*.png` for empty, error and other states). Screens have permanent IDs (S01, S02, ...). Tickets name the
  screens they build by ID. **Read the spec and look at the screenshot of every screen you build**; `ux.md` has the
  colors, type and spacing. Don't edit `design/`; the designer owns it.
- Design canvas (private and behind a login, so you can't open it; it's where the design gets reviewed): <!-- canvas -->not published yet<!-- /canvas -->
- Source code lives outside `design/`. Put it where the stack below says.

## Stack
<!-- stack -->
| Layer | Choice | Reason |
|---|---|---|
| Language | Python 3.14 | Chosen for the product. Best PDF tooling, and existing open-source parsers for Indian banks are Python. |
| Packaging | uv, `pyproject.toml`, lockfile committed | Fast, reproducible installs; one command for dev and CI. |
| Web framework | FastAPI + Uvicorn | Mature, typed, async; also hosts the MCP endpoint in the same process. |
| Pages | Server-rendered Jinja2 templates + HTMX (vendored, no CDN) | The screens are tables, forms and one dialog; no SPA build chain needed. |
| Styling | One hand-written CSS file with the `ux.md` tokens on `:root` and a `prefers-color-scheme: dark` block | Matches the design system exactly; no CSS framework to fight. |
| Charts | Inline SVG rendered server-side | Two small bar charts don't justify a JS chart library; works in both themes through tokens. |
| PDF unlock | pikepdf (qpdf) | Opens AES/RC4 password-protected PDFs and reports wrong passwords reliably. |
| PDF text/tables | pdfplumber | Gives words with coordinates, which statement layouts need. |
| Money | `decimal.Decimal`, stored as integer minor units | No floating-point error in reconciliation. |
| Per-user storage | One SQLCipher database file per user (`sqlcipher3` binding) | Literal "separate database per user", encrypted at rest; deleting an account deletes one file. |
| Shared storage | One plain SQLite file `control.db` (accounts, sessions, jobs, wrapped keys, token hashes) | Holds nothing financial; no extra database server. |
| Crypto | `cryptography` (AES-256-GCM, HKDF) | Standard, audited primitives for key wrapping and secret fields. |
| Background work | A worker process polling a `jobs` table in `control.db` | No Redis/Celery for a small user count; jobs survive restarts. |
| Google sign-in and Gmail | Authlib (OAuth 2.0 / OIDC) + `google-api-python-client` | Proven libraries; Gmail uses the `gmail.readonly` scope. |
| Email sign-in links | SMTP via stdlib `smtplib`, any provider's free tier | No vendor SDK; provider is configuration. |
| MCP | Official `mcp` Python SDK, Streamable HTTP transport, mounted at `/mcp` | Standard transport that chatbots support; same process and auth model. |
| Hosting | One small VPS, Docker Compose: `web`, `worker`, `caddy` (automatic HTTPS) | Cheap for a free product and easy for anyone to self-host. |
| CI | GitHub Actions: lint and tests on every pull request | The code lives on GitHub; no extra service. |
| Tests and lint | pytest, pytest-cov, ruff, reportlab (fixture generation only) | Boring defaults; reportlab draws the synthetic statements. |

Python 3.14 is used until `sqlcipher3-wheels` publishes 3.15 wheels; then the project moves to 3.15.
<!-- /stack -->

## How we work here
- Two long-lived branches: `develop` is where the work lands (every ticket's PR goes there); `master` is the
  release branch and only moves when the maintainer launches a release. Never commit to `master`.
- One ticket at a time, on its own branch (`dmi/t-<n>`), cut from `develop`. Small, focused changes.
- Each ticket becomes a pull request into `develop` that the maintainer reviews. Keep the diff small enough to read in one sitting.
- Prefer boring, proven tools. Don't add a dependency unless the ticket needs it.
- Keep platform-specific code thin and put logic in pure code with unit tests (aim for about 90% coverage). Code
  that can't run in the sandbox is verified by review plus those tests, and then by hand by the maintainer.
- Write tests for what you build, and run them before you say you're done. Document the build and test commands in the README under "Development".
- Never commit secrets, tokens or personal data. Don't put real credentials in examples.
- If the ticket is unclear or the design is missing something, ask the architect or designer instead of guessing.
