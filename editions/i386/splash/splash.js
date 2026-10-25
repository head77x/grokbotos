// Show the Grok Bot face; go offline-sad when there is no network.
(function () {
  const m = GBMascot.create(navigator.onLine ? "idle" : "sad", "", { hero: true });
  document.getElementById("face").append(m);
  const upd = () => m.setMood(navigator.onLine ? "idle" : "sad");
  addEventListener("online", upd); addEventListener("offline", upd);
})();
