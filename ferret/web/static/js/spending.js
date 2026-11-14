// Filters apply on change; the Show button is the no-JS fallback.
for (const form of document.querySelectorAll("form[data-autosubmit]")) {
  form.querySelector("button[type=submit]").hidden = true;
  form.addEventListener("change", () => form.requestSubmit());
}
