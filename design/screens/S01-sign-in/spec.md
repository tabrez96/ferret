---
id: S01
name: Sign in
purpose: Sign in or create an account without a Ferret password
size: 1280x800
---

## Content and actions
- Left: logo, headline "See what you spend on your cards. Type nothing.", one-line explanation, four trust points
  (totals checked, files deleted, own encryption key, free and open source).
- Right card: "Continue with Google" (secondary button), then an email field and "Email me a sign-in link" (primary).
- The same steps create an account for a new email. New users land on S02 (states/empty.html); returning users on S02.

## States
- Main (`screen.html`): sign-in form.
- Link sent (`states/link-sent.html`): "Check your inbox" with the address, expiry note, "Send another link" and
  "Use a different email".
- Link expired or already used (`states/link-expired.html`): danger notice above the form, email pre-filled.
- Loading: the pressed button shows a spinner and "Sending…"; both buttons are disabled.
- Error sending: inline `role="alert"` under the email field: "We couldn't send the link. Try again in a minute."
- Dark theme: `states/dark.html` shows the main state with the dark tokens. The app follows the system setting; every state above has a dark version through the same tokens.

## Notes and open questions
- Sign-in method is still an open product point. Designed as Google + emailed link because neither needs Ferret to
  store a login password. Signing in with Google does not connect Gmail; that is a separate, explicit step (S03/S05).
- Links work once and expire in 15 minutes.

## Change log
- First version.
- Added the dark theme (follows the system setting) and moved all colours to theme tokens; replaced the older ferret drawing in the page with the approved mark. Asked for in design review.
- Sidebar and header mark replaced with the redrawn logo (ferret leaping as a check mark), after the original logo was sent back for something stronger.
- Logo redrawn as a flat ferret silhouette without face details, for a more modern look; sidebar and header mark updated in every state (requested in design review).
