# Ferret
Credit card spending visibility without manual entry.

## Problem
Credit card holders have no clear view of what they spend. Entering transactions by hand is a chore, so it never gets done. The owner has this problem and so do their friends. Statements already contain every transaction, but they arrive as password-protected PDFs or as emails, and nothing turns them into usable data.

Evidence: first-hand need from the owner and friends. No market numbers have been gathered, and none are claimed here.

## Users & buyer
- Users: the owner and friends first, then anyone with credit cards from supported banks in India or the UAE, through a hosted multi-user service.
- Buyer: nobody. The product is free and open source.

## Competition
- India: LabhPay, StatementGPT, StmtSnap, FinAnalyser, Parsify, plus open-source parsers for HDFC, ICICI and SBI.
- UAE: Emirates NBD statement converters (the password format is known).
- Global: Parsio, Skwad, Sortlumo and Prism mostly rely on bank-linking (Plaid) or email parsing.
- Gap: none found combines PDF upload and Gmail ingestion, password-protected PDFs, per-user encryption, immediate statement deletion and an MCP server. This comes from a search, not an exhaustive survey.

## MVP scope
- Login, with a separate database per user.
- Two sources: PDF statement upload and Gmail ingestion.
- Password-protected PDFs: the password is asked for once per card or bank and then stored, so later uploads and Gmail statements are opened automatically. It is stored encrypted with the user's own key, kept apart from the database. A wrong password shows a clear error and lets the user enter a new one. Users can view that a password is saved, replace it or remove it at any time.
- First parser: Emirates NBD. Other banks are added one at a time: HDFC, ICICI, SBI, IndusInd, AU Bank.
- Reconciliation check on every statement: opening balance plus transactions must equal the closing balance and the statement totals. A statement that doesn't reconcile is flagged and its numbers are not saved.
- Parsed transactions (dates, merchants, amounts) are kept. The statement file is deleted immediately after parsing, whether parsing succeeds or fails.
- Per-user encryption at rest, with the key kept apart from the database.
- Account deletion wipes that user's data, stored passwords and any leftover files.
- No passwords or raw statement text in logs.
- Read-only MCP server so AI chatbots can query transactions and totals.
- Testing: real statements stay on the owner's machine, git-ignored and never in the repo. Tests use synthetic statements that copy each bank's layout with invented names, merchants and amounts, one set per bank before its parser counts as done.

## Out of scope
- Manual transaction entry.
- Chat inside the product (chatbots connect through MCP).
- MCP write actions (categorize, flag, export).
- Bank-linking (Plaid and similar).
- Payments and pricing.
- Banks beyond the list above.
- Keeping statement files for re-parsing.

## Pricing hypothesis
Free and open source. There is no revenue, so the cost of hosting the service is a risk (see below).

## Success metrics
- Parse accuracy: 100% of saved statements reconcile. Anything that doesn't reconcile is flagged and never saved with wrong numbers.
- Emirates NBD: every line of the owner's real statements matches the parsed output.
- Each new bank ships only after its synthetic statement set passes.
- Gmail statements are parsed with no password prompt after the first one.
- Adoption targets (users, statements per month) at 30/90/180 days are not set yet and are listed as an open point.

## Risks
- Parser drift: banks change layouts, so each parser needs ongoing maintenance. With files deleted immediately, a fixed parser cannot re-run old statements; users must re-upload or Gmail must be re-fetched.
- Stored passwords: the service must be able to decrypt them to open statements, so a server compromise exposes them. Per-user keys kept apart from the database limit but do not remove this. Statement passwords are typically derived from personal details, so leaking them is sensitive.
- Gmail API verification and quotas: reading mail needs a sensitive-scope review by Google, which can delay or limit the Gmail source.
- Trust: users must trust a hosted service with financial data, and any breach would be serious.
- Hosting cost: a free hosted service has no revenue to cover infrastructure.
- "No errors" is strict: reconciliation catches totals that don't add up, but not every misread merchant name or date.
- Legal and regulatory: handling financial data in India and the UAE may carry obligations that haven't been reviewed.
- Name overlap: "Ferret" is a common word and is likely used by other software projects (for example, I recall a database called FerretDB). This could affect search visibility and package names. Not checked.

## Open points
- Success metrics for adoption at 30/90/180 days.
- Login method (email and password, magic link, SSO).
- Hosting plan and who covers the cost.
- Availability of the repo, domain and package names for "Ferret" hasn't been checked.

## Runner-up ideas
- None. This is the owner's own idea and no alternatives were explored.
