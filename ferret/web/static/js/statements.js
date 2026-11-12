document.addEventListener("click", (event) => {
  const zone = event.target.closest("[data-dropzone]");
  if (zone && !event.target.closest("input")) zone.querySelector("input[type=file]").click();
});
