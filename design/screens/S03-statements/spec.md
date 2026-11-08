---
id: S03
name: Statements
purpose: Bring statements in (Gmail or PDF) and see whether each one added up
size: 1280x800
---

## Content and actions
- Gmail strip: connection status, account, last checked, "Check now". When not connected: "Connect Gmail" (Google
  consent, read-only), returning here.
- Upload drop zone: drag a PDF or "Choose PDF" (a real button opening the file picker; accepts .pdf, max 10 MB,
  several files at once). Trust line: "Ferret reads the file, checks the totals, then deletes it."
- History table, newest first: statement month, card, source and date, status chip, amount spent, action.
  - Reconciled (ok): numbers saved and shown on S02.
  - Needs password (warn): "Enter password" opens S04. Happens for a new card or when a saved password stops working.
    The file is kept only until the password is entered or the user picks "Not now"; in that case it is deleted and
    the row says "Skipped: upload or re-fetch from Gmail to try again".
  - Didn't add up (danger): row expands to show opening balance, transactions read, closing balance and the
    difference, the message that nothing was saved and the file is deleted, "Upload again" and "Report problem"
    (sends bank, month and totals only).
  - Bank not supported yet (neutral).
- Duplicate upload of an already reconciled statement: info toast "You already have this statement. Nothing changed."

## States
- Main (`screen.html`): Gmail connected, one statement needing a password, one that didn't add up (expanded).
- Processing (`states/processing.html`): progress card replacing the drop zone: Opened, Read N transactions,
  Checking the totals add up, Deleting the file. `aria-live="polite"`.
- Empty (`states/empty.html`): Gmail not connected, drop zone, "No statements yet".
- Unsupported bank (`states/unsupported-bank.html`): danger notice naming the detected bank and the supported list;
  file deleted, nothing saved.
- Not a statement / unreadable PDF: same notice pattern: "This doesn't look like a credit card statement."
- Gmail disconnected by Google (token expired): warn strip "Gmail stopped connecting. Reconnect to keep statements
  coming in." with "Reconnect".

## Notes and open questions
- "Didn't add up" is the plain-language name for a failed reconciliation check, used everywhere.
- Report problem never sends the file or any transaction text.

## Change log
- First version.
