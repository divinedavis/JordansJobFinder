// State-first city picker: choosing a state narrows its paired city select
// to just that state's cities (already ordered by population, descending).
// The city select ships with every state as an optgroup so it also works with
// no JS (progressive enhancement). Self-hosted because the CSP only allows
// script-src 'self'.
//
// NOTE: we physically detach/re-attach optgroups instead of toggling
// hidden/disabled — Safari still renders disabled or hidden optgroups (and
// their options) in the native dropdown, which showed every state's cities at
// once. Removing them from the DOM is the only cross-browser way to hide them.
(function () {
  document.querySelectorAll("[data-city-pair]").forEach(function (pair) {
    var state = pair.querySelector('select[data-role="state"]');
    var city = pair.querySelector('select[data-role="city"]');
    if (!state || !city) return;

    // Snapshot every optgroup once, in document order, then detach them all.
    var groups = Array.prototype.slice.call(city.querySelectorAll("optgroup"));
    groups.forEach(function (g) { g.parentNode.removeChild(g); });

    function render(resetSelection) {
      var chosen = state.value;
      var keep = resetSelection ? "" : city.value;
      // Clear any attached optgroups (the placeholder option stays — it lives
      // outside every optgroup).
      Array.prototype.slice
        .call(city.querySelectorAll("optgroup"))
        .forEach(function (g) { g.parentNode.removeChild(g); });
      // Re-attach only the matching state (or all when "All states").
      groups.forEach(function (g) {
        if (!chosen || g.getAttribute("data-state") === chosen) {
          city.appendChild(g);
        }
      });
      // Restore the prior selection when it's still available; otherwise the
      // assignment falls back to the empty placeholder option.
      city.value = keep;
    }

    state.addEventListener("change", function () { render(true); });
    render(false);
  });
})();
