---
id: S05
name: Settings
purpose: Control Gmail, saved statement passwords, chatbot access and the account
size: 1280x800
---

## Content and actions
- Gmail: status chip, connected address, what Ferret reads, "Disconnect Gmail" (confirm: already saved transactions
  stay). When disconnected: "Connect Gmail".
- AI chatbots (MCP): what a chatbot can do (read transactions and totals, change nothing), server address with
  "Copy", access token row (created, last used) with "New token" and "Revoke". A new token is shown once in a dialog
  with "Copy" and "I've saved it".
- Statement passwords: one row per card: Saved / Not saved, last used, "Replace" (opens S04 in replace mode, without
  needing a statement) and "Remove" (confirm). Passwords are never displayed.
- Delete account: what will be deleted, "Delete account…" opens the confirm dialog.

## States
- Main (`screen.html`): Gmail connected, token exists, two saved passwords, one card without.
- Delete account (`states/delete-account.html`): alert dialog listing exact counts to be deleted, type DELETE to
  enable "Delete everything". After deletion: signed out to S01 with a notice "Your account and all its data were
  deleted."
- No token yet: the token row shows "Create token".
- No cards yet: "Passwords appear here after your first locked statement."

## Notes and open questions
- Removing a password means the next locked statement for that card asks again (S04).

## Change log
- First version.
