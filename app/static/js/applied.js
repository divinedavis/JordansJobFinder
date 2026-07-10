// "Tailored Resume" generates a per-job PDF on demand (a ~20s Claude call), so
// a plain download link just sits there with no feedback. This fetches the PDF
// via JS: the button shows "Generating…" until the file is ready, then the
// download starts and the green "Applied" badge appears. Same-origin fetch is
// allowed by the CSP (connect-src 'self'); on any failure we fall back to the
// link's normal behavior so the download still works.
(function () {
  "use strict";

  function showAppliedForJob(jobId) {
    if (!jobId) return;
    var badges = document.querySelectorAll(
      '.applied-badge[data-job-id="' + jobId + '"]'
    );
    for (var i = 0; i < badges.length; i++) {
      badges[i].style.display = "inline-flex";
    }
  }

  function filenameFrom(disposition, fallback) {
    var m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition || "");
    return (m && decodeURIComponent(m[1])) || fallback;
  }

  document.addEventListener("click", function (event) {
    var btn = event.target.closest && event.target.closest(".tailored-btn");
    if (!btn || !window.fetch) return;
    event.preventDefault();
    if (btn.getAttribute("data-loading") === "1") return;

    var href = btn.getAttribute("href");
    var original = btn.textContent;
    var jobId = btn.getAttribute("data-job-id");
    btn.setAttribute("data-loading", "1");
    btn.setAttribute("aria-busy", "true");
    btn.style.opacity = "0.7";
    btn.textContent = "Generating…";

    fetch(href, { credentials: "same-origin" })
      .then(function (resp) {
        var ct = resp.headers.get("Content-Type") || "";
        if (!resp.ok || ct.indexOf("pdf") === -1) {
          // Out of quota / error: the server redirected (e.g. to billing).
          // Go there so the user sees the flash / upgrade prompt.
          window.location = resp.url || href;
          return null;
        }
        var name = filenameFrom(resp.headers.get("Content-Disposition"), "tailored-resume.pdf");
        return resp.blob().then(function (blob) {
          var url = URL.createObjectURL(blob);
          var a = document.createElement("a");
          a.href = url;
          a.download = name;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
          showAppliedForJob(jobId);
        });
      })
      .catch(function () {
        // Anything unexpected: fall back to a normal navigation/download.
        window.location = href;
      })
      .finally(function () {
        btn.removeAttribute("data-loading");
        btn.removeAttribute("aria-busy");
        btn.style.opacity = "";
        btn.textContent = original;
      });
  });
})();
