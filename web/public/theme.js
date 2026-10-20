// Applied before the app renders, so the page never flashes the wrong theme.
(function () {
  var t = localStorage.getItem("harbor.theme") || "dark";
  if (t === "system") t = matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  document.documentElement.classList.toggle("dark", t === "dark");
})();
