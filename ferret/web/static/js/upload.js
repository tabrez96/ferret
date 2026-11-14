const TITLE = "Drop a statement PDF here";
let uploading = false;

function showFailure() {
  document.getElementById("upload-notices").innerHTML =
    '<div class="notice notice-danger upload-notice" role="alert"><p><strong>' +
    "That upload didn't go through. Try again." +
    '</strong></p><button type="button" class="btn btn-text" data-dismiss-notice>Dismiss</button></div>';
}

async function upload(files) {
  if (files.length === 0 || uploading) return;
  uploading = true;
  const zone = document.querySelector("[data-dropzone]");
  const title = zone.querySelector(".dropzone-title");
  const input = zone.querySelector("input[type=file]");
  const form = new FormData();
  for (const f of files) form.append("file", f);
  zone.setAttribute("aria-busy", "true");
  title.textContent = "Uploading…";
  try {
    const res = await fetch(zone.dataset.uploadUrl, {
      method: "POST",
      body: form,
      headers: { "x-csrf-token": zone.dataset.csrf },
      credentials: "same-origin",
    });
    if (res.redirected || res.status === 303 || res.status === 403) {
      location.reload();
      return;
    }
    const doc = new DOMParser().parseFromString(await res.text(), "text/html");
    const notices = doc.getElementById("upload-notices");
    const history = doc.getElementById("history-root");
    if (!notices || !history) throw new Error("unexpected response");
    document.getElementById("upload-notices").replaceWith(notices);
    document.getElementById("history-root").replaceWith(history);
  } catch {
    showFailure();
  } finally {
    uploading = false;
    zone.removeAttribute("aria-busy");
    title.textContent = TITLE;
    input.value = "";
  }
}

document.addEventListener("change", (event) => {
  if (event.target.matches("#statement-file")) upload(event.target.files);
});

for (const name of ["dragover", "dragenter"]) {
  document.addEventListener(name, (event) => {
    const zone = event.target.closest && event.target.closest("[data-dropzone]");
    if (!zone) return;
    event.preventDefault();
    zone.classList.add("is-dragover");
  });
}

document.addEventListener("dragleave", (event) => {
  const zone = event.target.closest && event.target.closest("[data-dropzone]");
  if (zone && !zone.contains(event.relatedTarget)) zone.classList.remove("is-dragover");
});

document.addEventListener("drop", (event) => {
  const zone = event.target.closest && event.target.closest("[data-dropzone]");
  if (!zone) return;
  event.preventDefault();
  zone.classList.remove("is-dragover");
  upload(event.dataTransfer.files);
});

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-dismiss-notice]");
  if (button) button.closest(".upload-notice").remove();
});
