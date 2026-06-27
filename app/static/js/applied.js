// Per-job "Applied" memory for the dashboard.
//
// Each match card carries a clickable ".applied-toggle" button. Clicking it
// POSTs to /jobs/<id>/applied, which stamps (or clears) applied_at server-side
// so the green check persists across reloads — the point being that the user
// can remember which roles they've already applied to and not apply twice.
//
// Downloading a "Tailored Resume" also counts as applying (the server stamps it
// on that same GET), so we optimistically flip the toggle for that job too.
(function () {
  "use strict";

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
  }

  function togglesForJob(jobId) {
    return document.querySelectorAll(
      '.applied-toggle[data-job-id="' + jobId + '"]'
    );
  }

  function paint(btn, applied) {
    if (applied) {
      btn.classList.add("is-applied");
      btn.setAttribute("aria-pressed", "true");
    } else {
      btn.classList.remove("is-applied");
      btn.setAttribute("aria-pressed", "false");
    }
    var label = btn.querySelector(".applied-label");
    if (label) label.textContent = applied ? "Applied" : "Mark applied";
  }

  // A job can appear under more than one city section — keep every copy in sync.
  function setApplied(jobId, applied) {
    var btns = togglesForJob(jobId);
    for (var i = 0; i < btns.length; i++) paint(btns[i], applied);
  }

  function postApplied(jobId, wasApplied) {
    setApplied(jobId, !wasApplied); // optimistic
    fetch("/jobs/" + encodeURIComponent(jobId) + "/applied", {
      method: "POST",
      headers: { "X-CSRFToken": csrfToken() },
      credentials: "same-origin",
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error("request failed");
        return resp.json();
      })
      .then(function (data) {
        setApplied(jobId, !!data.applied);
      })
      .catch(function () {
        setApplied(jobId, wasApplied); // revert on failure
      });
  }

  document.addEventListener("click", function (event) {
    if (!event.target.closest) return;

    var toggle = event.target.closest(".applied-toggle");
    if (toggle) {
      event.preventDefault();
      postApplied(
        toggle.getAttribute("data-job-id"),
        toggle.classList.contains("is-applied")
      );
      return;
    }

    var tailored = event.target.closest(".tailored-btn");
    if (tailored) {
      // Don't block the download — just reflect the server-side stamp.
      setApplied(tailored.getAttribute("data-job-id"), true);
    }
  });
})();
