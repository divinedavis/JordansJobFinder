// State-first city picker: choosing a state narrows its paired city select
// to that state's optgroup. Works without JS too (the city select carries
// every state as an optgroup), so this is pure progressive enhancement.
// Self-hosted because the CSP only allows script-src 'self'.
(function () {
  document.querySelectorAll("[data-city-pair]").forEach(function (pair) {
    var state = pair.querySelector('select[data-role="state"]');
    var city = pair.querySelector('select[data-role="city"]');
    if (!state || !city) return;

    function filter(resetSelection) {
      var chosen = state.value;
      city.querySelectorAll("optgroup").forEach(function (group) {
        var show = !chosen || group.getAttribute("data-state") === chosen;
        group.hidden = !show;
        group.disabled = !show;
      });
      var current = city.selectedOptions[0];
      if (
        resetSelection &&
        current &&
        current.parentElement.tagName === "OPTGROUP" &&
        current.parentElement.disabled
      ) {
        city.value = "";
      }
    }

    state.addEventListener("change", function () { filter(true); });
    filter(false);
  });
})();
