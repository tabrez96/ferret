---
id: S02
name: Spending
purpose: See what you spent this month, per card, at which merchants, and every transaction
size: 1280x800
---

## Content and actions
- Header: title, source line ("From 2 Emirates NBD cards · statements up to 30 Oct 2026"), month picker and card
  filter (All cards or one card). Both filters apply to every panel.
- Total card: amount spent in the month, comparison with the previous month, transaction count. Status chips: how many
  of the month's statements reconciled (ok) and, if any, "1 new card needs a password" (warn, links to S03).
- By card: total per card for the month.
- Last 6 months: bar chart, current month highlighted in amber; text equivalent in `aria-label`.
- Top merchants: top 5 by amount with bars and numbers (an ordered list, readable without the bars).
- Transactions: date, merchant, card, amount, newest first; search by merchant or amount. Refunds and credits show a
  "Refund" chip, a leading minus and ok colour, and are subtracted from the total. 50 rows per page, then "Show more".
- Only reconciled statements feed this screen. Flagged statements never appear here.

## States
- Main (`screen.html`): October with data.
- First run (`states/empty.html`): "Let's find your spending" with Connect Gmail (recommended) and Choose a PDF;
  supported banks listed.
- Month with no statement yet: panels replaced by "No statement for November yet. It usually arrives in the first
  week of the next month." with a link to S03.
- Loading: grey skeleton blocks in each card, no spinners.
- Search with no results: "No transactions match "xyz" in October."
- Mixed currencies (later, when Indian banks land): one total per currency, never added together.
- Dark theme: `states/dark.html` shows the main state with the dark tokens. The app follows the system setting; every state above has a dark version through the same tokens.

## Notes and open questions
- No categories in the MVP; merchants only.
- Month is the calendar month of the transaction date, not the statement period.

## Change log
- First version.
- Added the dark theme (follows the system setting) and moved all colours to theme tokens; replaced the older ferret drawing in the page with the approved mark. Asked for in design review.
