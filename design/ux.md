# Ferret: UX spec

Ferret turns credit card statements (uploaded PDFs or statements arriving in Gmail) into a clear view of what you
spent, with no manual entry. Every statement is checked so the numbers add up before anything is saved, and the
statement file is deleted as soon as it has been read.

## Users and primary jobs

Users: credit card holders with cards from supported banks (Emirates NBD first; HDFC, ICICI, SBI, IndusInd and AU
Bank later). They are comfortable with web apps but do not want to do bookkeeping.

Primary jobs:
1. **See what I spent**: this month's total, per card, top merchants, and every transaction.
2. **Get statements in with no effort**: connect Gmail once, or drop a PDF; enter a statement password only once.
3. **Trust it**: know each statement reconciled, that files are gone, and control saved passwords and data.

A secondary job, done once: connect an AI chatbot to Ferret (read-only MCP) to ask questions about spending.

## Information architecture

Web app, desktop first (1280 wide), single column layout below 768px. Left sidebar with three items:
Spending, Statements, Settings. The account email and the Ferret logo sit in the sidebar.

| ID  | Screen             | Reached from |
|-----|--------------------|--------------|
| S01 | Sign in            | Logged-out visit, sign out |
| S02 | Spending           | Default after sign in; sidebar "Spending" |
| S03 | Statements         | Sidebar "Statements"; first-run actions on S02 |
| S04 | Statement password | Dialog over S03 when a statement is locked and no password is saved, or the saved one fails |
| S05 | Settings           | Sidebar "Settings" (Gmail, saved passwords, AI chatbots, account) |

## Key flows

**First run**
1. S01: sign in with Google or with an email link.
2. S02 (states/empty.html): "Let's find your spending" with two actions: Connect Gmail, Upload a statement.
3. Connect Gmail: Google consent (read-only mail scope), then back to S03 with Gmail shown as connected and the
   first search running.
4. Upload: S03 drop zone. Ferret detects the bank. A locked PDF with no saved password opens S04.
5. S04: the user enters the password once. It is saved for that card. Parsing continues (S03 states/processing.html).
6. Statement reconciles: row shows "Reconciled", S02 fills in.

**Monthly, hands-off (Gmail)**
1. A new statement email arrives. Ferret opens it with the saved password, parses, checks, deletes the file.
2. The user opens S02 and sees the new month. No prompts.

**Statement does not reconcile**
1. S03 row shows "Didn't add up" (danger chip). Nothing from it appears on S02.
2. Row expands: the expected and parsed totals and the difference, "No numbers from this statement were saved.
   The file has been deleted." Action: "Upload again" (after a parser fix) and "Report problem" (sends the bank
   name, statement month and totals only, never the file or transactions).

**Wrong or changed password**
1. A saved password fails (bank changed it) or a typed one is wrong: S04 states/wrong-password.html.
2. The user types a new one; it replaces the saved one on success.

**Manage passwords and data**: S05. Replace or remove a saved password per card, disconnect Gmail, create or revoke the
chatbot token, delete the account (S05 states/delete-account.html, type DELETE to confirm).

## Design system

### Themes: light and dark
Ferret has a light and a dark theme and follows the system setting (`prefers-color-scheme`). There is no in-app
switch: whatever the operating system or browser is set to, Ferret matches it, and it changes live if the system
changes. Set `color-scheme: light dark` on `:root` so native controls (selects, scrollbars, date pickers) match.

All colours are CSS custom properties defined once on `:root`, with the dark values in a
`@media (prefers-color-scheme: dark)` block. Components only use tokens, never raw hex. Every mockup carries the
same token block; each screen has `states/dark.html` showing it in the dark theme.

Dark theme is warm charcoal, not pure black, so the amber brand still feels friendly. In dark, accents get lighter
(not more saturated) and tints become deep, low-contrast washes.

### Colours
| Token | Light | Dark | Use |
|-------|-------|------|-----|
| ink | `#1C2430` | `#ECE6DC` | Primary text |
| ink-muted | `#5B6472` | `#A9B0BB` | Secondary text (7.0:1 on paper light, 7.1:1 on surface dark) |
| paper | `#FAF7F2` | `#14181F` | App background |
| surface | `#FFFFFF` | `#1E242D` | Sidebar, cards, tables, dialogs, inputs |
| line | `#E6E0D6` | `#343B46` | Borders, dividers |
| line-soft | `#F0EBE3` | `#2A3039` | Row dividers inside tables and cards |
| field-line | `#CFC6B8` | `#4A525E` | Input borders |
| btn-line | `#D6CEC1` | `#4A525E` | Secondary button border |
| amber | `#C9772F` | `#D98A45` | Brand colour: charts, current-month bar, decorative only (not for text) |
| amber-strong | `#9A4F14` | `#F0A866` | Links, text buttons, icons, focus ring (6.0:1 on white; 7.8:1 on dark surface) |
| accent-fill / on-accent | `#9A4F14` / `#FFFFFF` | `#E39A5B` / `#14181F` | Primary button fill and its text (7.6:1 in dark) |
| amber-tint / amber-ink | `#FBEBD9` / `#7A3D0E` | `#3A2A1C` / `#F6C08E` | Selected nav item background / text |
| amber-track / amber-past / amber-edge | `#F3E6D6` / `#EAD9C4` / `#E8C9A6` | `#2E2A26` / `#4A3D30` / `#6A4A2C` | Bar tracks, past-month bars, drop-zone edge |
| ok / ok-tint | `#1F7A5A` / `#E3F2EB` | `#5CC79C` / `#173328` | Reconciled, connected, refunds |
| warn / warn-tint | `#8A5A00` / `#FFF3D6` | `#E8B44C` / `#3A2E12` | Needs password, waiting |
| danger / danger-tint | `#B42318` / `#FDE8E6` | `#F38A80` / `#3D1C1A` | Didn't add up, errors (text and chips) |
| danger-fill | `#B42318` | `#E0655A` | Danger button fill (text is on-accent) |
| danger-wash / danger-edge | `#FFF8F7` / `#F4C2BD` | `#2A1B1A` / `#6B2C27` | Error panels and their border |
| neutral-tint | `#EFEBE4` | `#2C333D` | Neutral chips (Reading…, Bank not supported yet) |
| backdrop / shadow | `rgba(28,36,48,.45)` / `rgba(28,36,48,.25)` | `rgba(0,0,0,.6)` / `rgba(0,0,0,.5)` | Dialog backdrop and shadow |

Third-party marks (the Google "G") keep their own colours in both themes.

### Type
System stack: `Inter, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`. Amounts use `font-variant-numeric:
tabular-nums` and are right-aligned.
Scale: 32/40 bold (headline totals), 24/32 semibold (page title), 18/26 semibold (section), 15/22 regular (body),
13/18 (labels, table meta).

### Spacing and shape
4px base; common steps 8, 12, 16, 24, 32. Cards: 12px radius, 1px `line` border, no heavy shadows. Buttons: 40px
tall, 8px radius. Dialogs: 16px radius, 480px wide, `backdrop` token behind them.

### Components
- **Sidebar**: 232px, logo at top, nav items with icon + label, account email and "Sign out" at the bottom.
- **Buttons**: primary (accent-fill, on-accent text), secondary (surface, ink text, btn-line border), danger
  (danger-fill, on-accent text), text button (amber-strong text).
- **Status chips**: dot + word, never colour alone: Reconciled (ok), Needs password (warn), Reading… (neutral),
  Didn't add up (danger), Bank not supported yet (neutral).
- **Amount**: currency code before the number (`AED 1,284.50`). Refunds and credits show a leading minus and ok colour
  with the word "Refund" in the row.
- **Trust line**: one plain sentence under uploads: "Ferret reads the file, checks the totals, then deletes it."

### Tone of voice
Plain, calm, a little warm. Say what happened and what to do next. No blame ("That password didn't open the file",
not "Invalid password"). No finance jargon beyond what is printed on a statement.

### Logo
The mark is a ferret peeking over the top of a statement, paws on the page, its bandit mask in ink: Ferret goes
through your statements and ferrets out what you spent. Only the head and the page are drawn, so it stays readable
at 16px (orange head, dark mask, white page). The head is long and tapers to a pointed snout, with small low ears and
a pale muzzle, so it reads as a ferret and not a raccoon or a bear; keep those features if the mark is redrawn. The white page with an ink outline keeps it visible on light and dark
backgrounds.
- `brand/mark.svg`: app icon, favicon, sidebar on narrow screens. Minimum 16px.
- `brand/logo.svg`: mark plus the lowercase wordmark "ferret" in ink. On dark backgrounds the wordmark switches
  to `paper` (`#FAF7F2`); the mark stays as is. In the app the wordmark is HTML text in the `ink` token, so it
  follows the theme on its own. The mark is the same in both themes: its white page with the ink outline is what
  keeps it readable on the dark sidebar.
- Clear space around the logo: at least half the mark's height. Don't recolour the ferret or put it on amber.

## Accessibility
- WCAG 2.2 AA contrast in both themes. Amber is never used for text or as the only signal.
- Focus ring, chips and error text are checked in both themes; status chips keep their dot and word in dark.
- Every status uses a word as well as a colour.
- Full keyboard use: skip link to main content; visible 3px amber-strong focus ring; dialogs trap focus, close on Esc,
  return focus to the control that opened them.
- The upload drop zone is also a real button that opens the file picker.
- Password fields have a show/hide toggle with an accessible label; errors are tied to fields with
  `aria-describedby` and announced with `role="alert"`.
- Charts have a text equivalent (the top-merchant list is a list with numbers, not just bars).
- Processing progress uses `aria-live="polite"`.

## Open questions
- Sign-in method: designed as "Continue with Google" plus an emailed sign-in link (no Ferret password to store or
  leak). Google sign-in is separate from connecting Gmail; using the same account is convenient but not required.
- Merchant categories are not in the MVP; S02 groups by merchant only.
- Multiple currencies (AED and INR cards in one account): S02 shows a total per currency and never adds them together.
  To confirm when the first Indian bank parser lands.
