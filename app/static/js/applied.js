// Clicking "Tailored Resume" downloads the PDF (handled by the link's href) and
// also marks the match as applied server-side. This gives the user instant
// visual feedback by revealing the green "Applied" badge for that job; the
// server-side stamp (set on the same GET) makes it persist across reloads.
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

  document.addEventListener("click", function (event) {
    var btn = event.target.closest && event.target.closest(".tailored-btn");
    if (!btn) return;
    // Don't block the download — just reveal the badge optimistically.
    showAppliedForJob(btn.getAttribute("data-job-id"));
  });
})();
