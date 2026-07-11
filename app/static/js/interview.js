// Interview-plan generation is a ~20-30s synchronous AI call. Without feedback
// the page looks frozen, so on submit we disable the button and show a clear
// "generating…" note. Self-hosted because the CSP only allows script-src 'self'.
(function () {
  var form = document.querySelector("[data-interview-form]");
  if (!form) return;
  form.addEventListener("submit", function () {
    var btn = form.querySelector('button[type="submit"]');
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Building your prep…";
    }
    var note = document.createElement("p");
    note.className = "muted";
    note.style.marginTop = "12px";
    note.textContent =
      "Hang tight — your interview prep is generating. This can take up to a minute. Please don't refresh or leave the page.";
    form.appendChild(note);
  });
})();
