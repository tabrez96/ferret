<!-- about -->
# Ferret

**Credit card spending visibility from your statements, with no manual entry**

## What it does

Ferret shows you what you spend on your credit cards without you typing anything in. Upload a statement PDF or connect Gmail, and Ferret opens the statement (it asks for the statement password once per card and remembers it), reads every transaction, and checks that the numbers add up to the bank's own totals before saving anything. The statement file is deleted as soon as it has been read. You get this month's total, spending per card, top merchants and every transaction, and you can connect an AI chatbot to ask questions about your spending without letting it change anything. Ferret is free and open source, starts with Emirates NBD cards and adds Indian banks one at a time.

## Screens

### S01 · Sign in

Sign in or create an account without a Ferret password

![S01 Sign in](design/screens/S01-sign-in/screen.png)

### S02 · Spending

See what you spent this month, per card, at which merchants, and every transaction

![S02 Spending](design/screens/S02-spending/screen.png)

### S03 · Statements

Bring statements in (Gmail or PDF) and see whether each one added up

![S03 Statements](design/screens/S03-statements/screen.png)

### S04 · Statement password

Enter a statement PDF's password once so this card's statements open by themselves from then on

![S04 Statement password](design/screens/S04-statement-password/screen.png)

### S05 · Settings

Control Gmail, saved statement passwords, chatbot access and the account

![S05 Settings](design/screens/S05-settings/screen.png)

## Built with

| Layer | Choice | Reason |
|---|---|---|
| Language | Python 3.15 | Chosen for the product. Best PDF tooling, and existing open-source parsers for Indian banks are Python. |
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

Python 3.15 is new. If any dependency has no 3.15 wheel yet, the Docker image builds it from source (build tools in a builder stage); the project does not pin an older Python.
<!-- /about -->

## Development

Requires [uv](https://docs.astral.sh/uv/); it installs Python 3.14 itself (see `.python-version`).

```
uv sync                                        # install dependencies (dev included)
uv run uvicorn ferret.web.app:app --reload     # run locally; health check at http://127.0.0.1:8000/healthz
uv run pytest                                  # tests
uv run pytest --cov=ferret                     # tests with coverage
uv run ruff check . && uv run ruff format --check .   # lint and format check
uv run ruff format .                           # fix formatting
docker compose build                           # build the container image
docker compose up                              # run it on port 8000
```

### Master key

Ferret will not start without a master key. It wraps every user's data key, so keep it outside
`data/` and back it up separately: losing it makes every user database unreadable.

```
mkdir -p secrets && openssl rand -hex 32 > secrets/ferret_master_key && chmod 600 secrets/ferret_master_key
export FERRET_MASTER_KEY_FILE=$PWD/secrets/ferret_master_key   # must be outside FERRET_DATA_DIR (default ./data)
```

The container runs as uid 1000, so the key file must be readable by uid 1000. `FERRET_DATA_DIR`
defaults to `./data`. User databases use SQLCipher through the `sqlcipher3-wheels` package, which
bundles the library (no system package needed).

### Sign-in email

Users sign in with a link emailed to them. It works once and expires after 15 minutes. Ferret sends it
over SMTP; any provider's free tier works.

| Variable | Default | Meaning |
|---|---|---|
| `FERRET_BASE_URL` | `http://127.0.0.1:8000` | Public address of the site. Sign-in links are built from it. |
| `FERRET_SMTP_HOST` | (unset) | SMTP server. Without it, sending the link fails with an inline error. |
| `FERRET_SMTP_PORT` | `587` | SMTP port. |
| `FERRET_SMTP_USERNAME` | (unset) | Login for the SMTP server, if it needs one. |
| `FERRET_SMTP_PASSWORD` | (unset) | Password for that login. |
| `FERRET_SMTP_FROM` | `Ferret <no-reply@localhost>` | Sender of the email. |
| `FERRET_SMTP_SECURITY` | `starttls` | `starttls`, `ssl` or `none`. |

For local testing without SMTP, `FERRET_DEV_PRINT_LINKS=1` prints sign-in links to the terminal. Never set it
in production.

### Google sign-in

"Continue with Google" needs an OAuth client. In Google Cloud Console, create an OAuth client of type
"Web application" and add `<FERRET_BASE_URL>/signin/google/callback` as an authorized redirect URI.
Ferret asks Google only for `openid email`; Gmail access is requested separately, later.

| Variable | Default | Meaning |
|---|---|---|
| `FERRET_GOOGLE_CLIENT_ID` | (unset) | Client ID of the OAuth client, like `1234-example.apps.googleusercontent.com`. |
| `FERRET_GOOGLE_CLIENT_SECRET` | (unset) | Client secret of the OAuth client. |

Without both, the button shows "Google sign-in isn't set up here." and the email link still works.

Sign-in and session cookies are `Secure`. Browsers accept them on `http://127.0.0.1` and `localhost`;
any other address needs HTTPS (Caddy provides it in production).

`private/` and `data/` are git-ignored; real statements go in `private/statements/` only.

---

<sub>Created with ❤️ by Dunder Mifflin agents</sub>
