# Ferret — System design

## Overview
Ferret shows you what you spend on your credit cards without you typing anything in. Upload a statement PDF or connect Gmail, and Ferret opens the statement (it asks for the statement password once per card and remembers it), reads every transaction, and checks that the numbers add up to the bank's own totals before saving anything. The statement file is deleted as soon as it has been read. You get this month's total, spending per card, top merchants and every transaction, and you can connect an AI chatbot to ask questions about your spending without letting it change anything. Ferret is free and open source, starts with Emirates NBD cards and adds Indian banks one at a time.

## Stack
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

## Components
- **web** (`ferret/web/`): FastAPI app. Routes for S01–S05, session middleware, CSRF protection on forms, upload endpoint, OAuth callbacks, `/mcp`. Renders Jinja templates; HTMX swaps the S03 history table, processing card and S04 dialog.
- **auth** (`ferret/auth/`): emailed sign-in links (random 32-byte token, only its SHA-256 stored, single use, 15-minute expiry) and Google OIDC sign-in. Creates the account on first sign-in. Sessions are server-side rows in `control.db` with an HttpOnly, Secure, SameSite=Lax cookie.
- **keys** (`ferret/keys.py`): the master key (KEK) is read from a file mounted outside the data volume (`FERRET_MASTER_KEY_FILE`). Each user gets a random 256-bit data key (DEK) at sign-up, stored only wrapped (AES-GCM under the KEK) in `control.db`. The DEK opens the user's SQLCipher file and encrypts secret fields inside it. The KEK never touches the data volume or the database.
- **userdb** (`ferret/userdb/`): opens `data/users/<user_id>.db` with the unwrapped DEK, runs schema migrations, and provides query functions (spending totals, per-card totals, top merchants, transaction search, statement history).
- **pipeline** (`ferret/pipeline/`): one statement run, always in this order: unlock → detect bank → parse → reconcile → save or flag → delete file. The file deletion sits in a `finally` block, so it happens whether parsing succeeds, fails or raises. The only early exit that keeps the file is "locked, no working password", which leaves it in `pending/`. Emits progress events for the S03 processing card.
- **parsers** (`ferret/parsers/`): one module per bank behind a small interface: `detect(first_page_text) -> bool`, `parse(pdf) -> ParsedStatement` (card last 4, period, currency, opening and closing balance, printed total debits and credits, transactions), plus the Gmail search query for that bank. Emirates NBD first. A registry lists supported banks for S02/S03 copy.
- **reconcile** (`ferret/reconcile.py`): pure function. A statement passes only if `opening + debits − credits == closing` and the summed debits and credits equal the printed totals, exactly to the minor unit. Returns expected, parsed and difference for the S03 "Didn't add up" panel.
- **pending files** (`data/pending/<user_id>/`): a locked statement with no working password waits here, encrypted with the user's DEK, for at most 7 days from `received_at`. It leaves when the password is entered (parsing continues), when the user picks "Skip this statement" on S04, or when the `sweep_pending` job (hourly) finds it past the deadline. The last two delete the file and set the row to `skipped`. S03 shows "Waiting until <date>" (`received_at` + 7 days) under the Needs password chip.
- **gmail** (`ferret/gmail/`): connect/disconnect, refresh token stored encrypted in the user DB, a search query per supported bank (from the parser module), a seen-message list so nothing is fetched twice. Polled every 6 hours per connected user and on "Check now". Token revocation by Google sets the S03 "Gmail stopped connecting" state.
- **worker** (`ferret/worker.py`): claims jobs from `control.db` (`parse_statement`, `gmail_poll`, `sweep_pending`, `delete_account`) one at a time per user. Runs as its own container from the same image.
- **mcp** (`ferret/mcp/`): read-only tools over the user DB: `list_cards`, `list_statements`, `spending_summary(month, card?)`, `top_merchants(month, card?, limit)`, `search_transactions(query?, from?, to?, card?, limit)`. Bearer token auth; the token's SHA-256 maps to one user. No write tools exist.
- **logging** (`ferret/logging.py`): stdlib logging with a redaction filter; log records carry IDs and counts only. Passwords, PDF bytes and statement text are never passed to a logger. A test enforces this.
- **problem reports**: "Report problem" stores bank, statement month, and the expected/parsed totals in `control.db`; a CLI command (`ferret reports`) lists them for maintainers. Never the file or transaction text.

## Data model
**control.db** (plain SQLite, nothing financial)
- `users(id, email UNIQUE, google_sub NULL, wrapped_dek, created_at)`
- `sessions(id_hash, user_id, created_at, expires_at)`
- `login_links(token_hash, email, expires_at, used_at)`
- `mcp_tokens(id, user_id, token_hash, created_at, last_used_at, revoked_at)`
- `jobs(id, user_id, kind, payload_json, status, attempts, run_after, created_at)` — payloads hold IDs only, never passwords or file contents.
- `problem_reports(id, bank, statement_month, opening, closing, expected, parsed, created_at)` — no user ID.

**data/users/<user_id>.db** (SQLCipher, keyed by the user's DEK)
- `cards(id, bank, last4, currency, nickname NULL)` — unique (bank, last4).
- `statement_passwords(card_id NULL, bank, ciphertext, nonce, created_at, last_used_at)` — AES-GCM under the DEK on top of SQLCipher; keyed per card, falling back to per bank before the card is known.
- `statements(id, card_id NULL, bank, period_start, period_end, source 'upload'|'gmail', source_ref, received_at, status 'reading'|'needs_password'|'reconciled'|'didnt_add_up'|'unsupported'|'not_a_statement'|'skipped', opening, closing, total_debits, total_credits, parsed_debits, parsed_credits, fingerprint UNIQUE NULL)` — the pending deadline is derived as `received_at + 7 days`, not stored.
- `transactions(id, statement_id, card_id, posted_on, merchant, amount_minor, currency, is_credit)` — only written for reconciled statements, in the same SQL transaction that marks the statement reconciled.
- `gmail_account(email, refresh_token_ciphertext, nonce, connected_at, last_checked_at, status)`
- `gmail_seen(message_id PRIMARY KEY, seen_at)`

Fingerprint = hash of bank, card last 4, period end and closing balance; a second upload with the same fingerprint gives the "You already have this statement" toast. Amounts are integer minor units plus a currency code; totals are never summed across currencies.

## Key flows
**1. Upload a statement (S03, S04)**
1. User drops one or more PDFs (≤10 MB each, `.pdf`, checked by magic bytes). Each file is written encrypted to `pending/`, a `statements` row is created as `reading`, and a `parse_statement` job is queued.
2. Worker unlocks the PDF: no password needed → continue; otherwise try the saved password for the detected bank/card.
3. No saved password, or it fails → row becomes `needs_password` with "Waiting until <date>"; S03 shows "Enter password", which opens S04.
4. S04 "Open and save": the password is tried in memory. Wrong → S04 wrong-password state, file stays pending. Right → password saved (replacing any old one) and the job resumes. "Skip this statement" → file deleted, row `skipped`. Esc → dialog closes, focus returns to the row's button, nothing changes (row stays `needs_password`, file stays pending).
5. Parser runs, then reconciliation. Pass → transactions saved, row `reconciled`, S02 updates. Fail → row `didnt_add_up` with totals and difference, nothing saved. Unknown bank → `unsupported`; unreadable → `not_a_statement`.
6. The file is deleted in every outcome except "waiting for a password", and that wait ends after 7 days at most (`sweep_pending` deletes the file, row `skipped`). S03 polls the processing card via HTMX (`aria-live="polite"`).

**2. Monthly Gmail statement (no prompts)**
1. `gmail_poll` searches each supported bank's query since the last check and skips message IDs in `gmail_seen`.
2. Each PDF attachment is downloaded straight into `pending/` and handed to the same pipeline as an upload, with `source = gmail`.
3. The saved password opens it; it parses, reconciles, saves, and the file is deleted. The user just sees the new month on S02.
4. If the saved password fails (bank changed it), the row becomes `needs_password` (same 7-day limit) and S02 shows the warn chip linking to S03.

**3. Delete account (S05)**
1. User types DELETE and confirms. The session is ended immediately and a `delete_account` job runs.
2. The job revokes the Gmail token with Google, deletes `users/<id>.db`, the user's `pending/` folder, MCP tokens, sessions, jobs and finally the `users` row with the wrapped DEK.
3. The browser lands on S01 with "Your account and all its data were deleted."

## Testing approach
- `uv run pytest` runs everything; `uv run pytest --cov=ferret` reports coverage (target about 90% on pure code); `uv run ruff check . && uv run ruff format --check .` for lint. GitHub Actions runs the same commands on every pull request.
- **Synthetic statements:** `tests/fixtures/make_statements.py` draws Emirates NBD-layout PDFs with reportlab using invented names, merchants and amounts, including password-protected copies (pikepdf), a statement that doesn't add up, a non-statement PDF and an unsupported-bank PDF. Generated at test time into a temp dir; no generated PDFs committed.
- **Parser done rule:** a bank's parser is done when its full synthetic set passes, each test asserting every transaction line and every total.
- **Real statements:** kept in `private/statements/` (git-ignored). `uv run python -m ferret.tools.check_real private/statements` prints per-statement reconcile results and line counts locally; it never writes to the repo or logs.
- **Security tests:** files are gone after every pipeline outcome (including exceptions); a pending file older than 7 days is deleted by the sweeper (clock injected); Esc on S04 leaves the file and row untouched; passwords and statement text never appear in captured logs; one user's session or MCP token can't read another user's data; the user DB file can't be opened without the DEK; account deletion leaves no files or rows.
- **Web tests:** FastAPI `TestClient` per screen state (status codes, key copy, chips with words, `aria-*` attributes). Google and SMTP are faked in tests.
- **Manual QA:** `docker compose up` and walk the flows in light and dark (system setting) against the screenshots in `design/screens/`.

## Open questions
- **Hosting and budget:** designed for one ~$5–10/month VPS with Docker Compose; also self-hostable as is.
- **Sign-in:** Google sign-in plus emailed link (per S01). Needs an SMTP sender; any free tier works.
- **Gmail access:** the read-only Gmail scope is restricted by Google. The design assumes the Google project stays in testing mode (up to 100 added users); public launch needs Google's security assessment.
