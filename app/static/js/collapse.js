/* Remember which city sections the user collapsed, across sessions.
 *
 * The collapsing itself is native <details>/<summary> — this file only
 * persists the state. localStorage rather than the server because it's a
 * per-device display preference, and because a failed write must never break
 * the board (Safari private browsing throws on setItem).
 *
 * State is keyed by board tab as well as city: the PM and HR boards can both
 * show "Philadelphia, PA" and collapsing it on one shouldn't collapse it on
 * the other.
 */
(function () {
  "use strict";

  var STORAGE_KEY = "jjf.collapsedCities";

  function read() {
    try {
      var raw = window.localStorage.getItem(STORAGE_KEY);
      var parsed = raw ? JSON.parse(raw) : {};
      // Guard against a hand-edited or half-written value.
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    } catch (err) {
      return {};
    }
  }

  function write(state) {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (err) {
      /* Quota or private browsing — the section still collapses, it just
         won't be remembered. Not worth surfacing to the user. */
    }
  }

  function apply() {
    var board = document.querySelector("[data-board-tab]");
    var sections = document.querySelectorAll("[data-city-section]");
    if (!board || !sections.length) return;

    var tab = board.getAttribute("data-board-tab") || "pm";
    var state = read();
    var collapsed = state[tab] || [];

    Array.prototype.forEach.call(sections, function (section) {
      var city = section.getAttribute("data-city-section");
      if (collapsed.indexOf(city) !== -1) {
        section.open = false;
      }

      section.addEventListener("toggle", function () {
        var current = read();
        var list = (current[tab] || []).filter(function (name) {
          return name !== city;
        });
        if (!section.open) list.push(city);
        if (list.length) {
          current[tab] = list;
        } else {
          delete current[tab];
        }
        write(current);
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", apply);
  } else {
    apply();
  }
})();
