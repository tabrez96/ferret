---
id: S04
name: Statement password
purpose: Enter a statement PDF's password once so this card's statements open by themselves from then on
size: 1280x800
---

## Content and actions
- Modal dialog over S03. Lock icon, title "This statement is locked", which statement it is (bank, card, month,
  source), explanation that the password is saved encrypted with the user's own key.
- Password field with Show/Hide toggle; hint "the password your bank set for statement PDFs, not your online banking
  password".
- "Open and save" (primary): tries the password. Success saves it for this card, closes the dialog and shows the
  processing card on S03. "Not now" (secondary) closes the dialog; the statement file is deleted and the row shows
  "Skipped".
- Footer: "You can replace or remove saved passwords any time in Settings." (link to S05).
- Focus starts in the password field; Enter submits; Esc equals "Not now"; focus returns to the row's button.

## States
- Main (`screen.html`): first password for a new card.
- Wrong password (`states/wrong-password.html`): title "That password didn't work", field outlined in danger,
  `role="alert"` message. Also used when a saved password stops working (bank changed it); a correct new password
  replaces the saved one.
- Checking: primary button shows a spinner and "Opening…", field disabled.
- Dark theme: `states/dark.html` shows the main state with the dark tokens. The app follows the system setting; every state above has a dark version through the same tokens.

## Notes and open questions
- No bank-specific password format hints in the MVP; formats change and hints could leak personal-detail patterns.

## Change log
- First version.
- Added the dark theme (follows the system setting) and moved all colours to theme tokens; replaced the older ferret drawing in the page with the approved mark. Asked for in design review.
- Sidebar and header mark replaced with the redrawn logo (ferret leaping as a check mark), after the original logo was sent back for something stronger.
- Logo redrawn as a flat ferret silhouette without face details, for a more modern look; sidebar and header mark updated in every state (requested in design review).
