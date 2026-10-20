// Harbor landing page: scroll reveals, the architecture walkthrough, the typing terminal, copy buttons.
(function () {
  var reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Reveal sections as they scroll into view.
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
    });
  }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
  document.querySelectorAll(".reveal").forEach(function (el) { io.observe(el); });

  // Copy buttons.
  document.querySelectorAll("[data-copy]").forEach(function (b) {
    b.addEventListener("click", function () {
      navigator.clipboard.writeText(b.getAttribute("data-copy")).then(function () {
        b.textContent = "copied"; setTimeout(function () { b.textContent = "copy"; }, 1400);
      });
    });
  });

  // Feature cards: a soft light that follows the pointer.
  document.querySelectorAll(".feat").forEach(function (c) {
    c.addEventListener("pointermove", function (e) {
      var r = c.getBoundingClientRect();
      c.style.setProperty("--mx", (e.clientX - r.left) + "px");
      c.style.setProperty("--my", (e.clientY - r.top) + "px");
    });
  });

  // Architecture: hovering a box or a step lights up both; otherwise the steps play in turn.
  var arch = document.querySelector(".arch");
  var steps = Array.prototype.slice.call(document.querySelectorAll(".steps li"));
  var nodes = Array.prototype.slice.call(document.querySelectorAll(".arch .node"));
  var current = 0, hovering = false;
  function show(step) {
    arch.classList.toggle("focus", step !== null);
    steps.forEach(function (li) { li.classList.toggle("on", String(step) === li.dataset.step); });
    nodes.forEach(function (n) { n.classList.toggle("on", String(step) === n.dataset.step); });
  }
  function bind(el) {
    el.addEventListener("mouseenter", function () { hovering = true; show(el.dataset.step); });
    el.addEventListener("mouseleave", function () { hovering = false; });
  }
  steps.forEach(bind); nodes.forEach(bind);
  if (!reduced) {
    setInterval(function () {
      if (hovering || !arch.classList.contains("in")) return;
      show(current); current = (current + 1) % steps.length;
    }, 2400);
  }
  show(0);

  // Terminal: types a short session, then starts over.
  var pre = document.getElementById("typer");
  var script = [
    ["cmd", "harbor ls"],
    ["out", '<span class="dim">  PORT    PID  WHAT            PROJECT          UP  HTTP</span>'],
    ["out", '  <span class="b">5173</span>   6072  Docs site       @acme/docs       1d  <span class="g">200</span>'],
    ["out", '  <span class="b">5174</span>  55958  Shop web        shop            58m  <span class="g">200</span>'],
    ["out", '  <span class="b">8787</span>  55937  Shop API        shop            58m  <span class="g">200</span>'],
    ["out", '  <span class="b">3000</span>  41207  old-prototype   proto            2d  <span class="g">200</span> <span class="y">⚠</span>'],
    ["pause", 900],
    ["cmd", "harbor who 5174"],
    ["out", '<span class="b">5174</span>  Shop web  <span class="dim">(dev, Vite)</span>'],
    ["out", "  folder   ~/shop/frontend"],
    ["out", "  app      pid 55935: make dev (7 processes)"],
    ["out", '  http     <span class="g">200</span> Shop web (7 ms)'],
    ["pause", 900],
    ["cmd", "harbor kill 3000 --app -y"],
    ["out", '<span class="g">Stopped</span> 3 process(es).'],
    ["pause", 700],
    ["cmd", "harbor free 5173 -n 3"],
    ["out", "5175 5176 5177"],
    ["pause", 2600],
  ];
  if (!pre) return;
  if (reduced) {
    pre.innerHTML = script.filter(function (s) { return s[0] !== "pause"; })
      .map(function (s) { return s[0] === "cmd" ? '<span class="p">❯</span> ' + s[1] : s[1]; }).join("\n");
    return;
  }
  var started = false;
  new IntersectionObserver(function (e, obs) {
    if (e[0].isIntersecting && !started) { started = true; obs.disconnect(); run(); }
  }, { threshold: 0.3 }).observe(pre);

  function run() {
    var html = "", i = 0;
    function render(extra) { pre.innerHTML = html + (extra || "") + '<span class="caret"></span>'; }
    function next() {
      if (i >= script.length) { setTimeout(function () { html = ""; i = 0; next(); }, 400); return; }
      var s = script[i++];
      if (s[0] === "pause") return setTimeout(next, s[1]);
      if (s[0] === "out") { html += s[1] + "\n"; render(); return setTimeout(next, 90); }
      var k = 0, prefix = '<span class="p">❯</span> ';
      (function type() {
        if (k <= s[1].length) { render(prefix + s[1].slice(0, k++)); return setTimeout(type, 38 + Math.random() * 40); }
        html += prefix + s[1] + "\n"; setTimeout(next, 260);
      })();
    }
    next();
  }
})();
