document.addEventListener("click", (event) => {
  const zone = event.target.closest("[data-dropzone]");
  if (zone && !event.target.closest("input")) zone.querySelector("input[type=file]").click();
});

let opener = null;
const FOCUSABLE = "a[href], button:not(:disabled), input:not(:disabled):not([type=hidden])";

function passwordDialog() {
  return document.querySelector("dialog.password-dialog");
}

function openDialog() {
  const dialog = passwordDialog();
  if (!dialog) return;
  // A server-rendered [open] dialog is not modal yet: reopen it as a modal.
  if (dialog.open && !dialog.matches(":modal")) dialog.removeAttribute("open");
  if (!dialog.open) dialog.showModal();
  dialog.querySelector("input[name=password]").focus();
}

document.addEventListener("htmx:after:settle", openDialog);
document.addEventListener("DOMContentLoaded", openDialog);

document.addEventListener("htmx:before:request", (event) => {
  const source = event.detail.ctx.sourceElement;
  if (source.matches("[data-password-opener]")) opener = source;
});

// "close" doesn't bubble, so listen while it travels down. Esc is the native cancel then close:
// nothing is sent to the server.
document.addEventListener(
  "close",
  (event) => {
    const dialog = event.target;
    if (!dialog.matches || !dialog.matches("dialog.password-dialog")) return;
    const id = dialog.dataset.statementId;
    dialog.remove();
    const target = opener || document.querySelector(`[data-password-opener="${id}"]`);
    if (target) target.focus();
    opener = null;
  },
  true,
);

document.addEventListener("keydown", (event) => {
  if (event.key !== "Tab") return;
  const dialog = document.querySelector("dialog.password-dialog[open]");
  if (!dialog) return;
  const items = [...dialog.querySelectorAll(FOCUSABLE)];
  const first = items[0];
  const last = items[items.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    last.focus();
    event.preventDefault();
  } else if (!event.shiftKey && document.activeElement === last) {
    first.focus();
    event.preventDefault();
  }
});

document.addEventListener("click", (event) => {
  const toggle = event.target.closest("[data-toggle-password]");
  if (!toggle) return;
  const input = toggle.closest(".password-field").querySelector("input");
  const show = input.type === "password";
  input.type = show ? "text" : "password";
  toggle.textContent = show ? "Hide" : "Show";
  toggle.setAttribute("aria-pressed", String(show));
});
