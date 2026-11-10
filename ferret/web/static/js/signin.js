document.addEventListener("submit", (event) => {
  const form = event.target.closest("form[data-sending]");
  if (!form) return;
  const card = form.closest(".signin-card");
  const button = event.submitter || form.querySelector("button[type=submit]");
  button.querySelector(".btn-label").hidden = true;
  button.querySelector(".btn-sending").hidden = false;
  // Disabling buttons here does not cancel the submission; the buttons carry no form data.
  card.querySelectorAll("button").forEach((b) => {
    b.disabled = true;
  });
  card.querySelectorAll("a.btn").forEach((a) => {
    a.setAttribute("aria-disabled", "true");
  });
});

window.addEventListener("pageshow", (event) => {
  if (event.persisted) window.location.reload();
});
