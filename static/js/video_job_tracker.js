/* static/js/video_job_tracker.js  -  add to GAME pages / any other page:
   <script src="{{ url_for('static', filename='js/video_job_tracker.js') }}"></script> */
(function () {
  "use strict";
  if (window.__eduJobTracker) return;
  window.__eduJobTracker = true;
  if (location.pathname.indexOf("generate_video") > -1) return;     /* the Study Studio page has its own progress bar */

  var K = "eduvision_video_job", D = "eduvision_video_done", box = null, timer = null;
  function g(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function s(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function r(k) { try { localStorage.removeItem(k); } catch (e) {} }
  function el(tag, txt) { var n = document.createElement(tag); if (txt != null) n.textContent = txt; return n; }

  function mk() {
    if (box) return box;
    var st = document.createElement("style");
    st.textContent = "#edj{position:fixed;right:14px;bottom:14px;z-index:99999;width:min(320px,calc(100vw - 28px));background:#fff;border-radius:16px;box-shadow:0 12px 34px #1820334d;padding:14px 16px;font-family:'Segoe UI',Arial,sans-serif;color:#182033;border-left:6px solid #5546e8}#edj.ok{border-left-color:#22c3a6}#edj.bad{border-left-color:#c0262d}#edj b{display:block;font-size:14px;margin-bottom:6px}#edj p{font-size:13px;color:#667089;margin:6px 0 0;word-break:break-word}#edj .bar{height:10px;background:#e8ebf6;border-radius:99px;overflow:hidden}#edj .bar i{display:block;height:100%;background:linear-gradient(90deg,#5546e8,#22c3a6);transition:width .4s}#edj a,#edj button{display:inline-block;margin:10px 8px 0 0;padding:9px 14px;border:0;border-radius:10px;font:700 13px 'Segoe UI',Arial,sans-serif;cursor:pointer;text-decoration:none;background:#5546e8;color:#fff}#edj button{background:#e9e7ff;color:#3b2fc0}";
    document.head.appendChild(st);
    box = document.createElement("div"); box.id = "edj"; document.body.appendChild(box);
    return box;
  }
  function gone() { if (box) { box.remove(); box = null; } }

  function card(cls, title, text, url, linkText) {
    var b = mk(); b.className = cls; b.textContent = "";
    b.appendChild(el("b", title));
    if (text) b.appendChild(el("p", text));
    if (url) { var a = el("a", linkText); a.href = url; b.appendChild(a); }
    var x = el("button", "Close"); x.type = "button";
    x.onclick = function () { r(D); gone(); };
    b.appendChild(x);
  }
  function progress(pc, msg) {
    var b = mk(); b.className = ""; b.textContent = "";
    b.appendChild(el("b", "Your video is being made"));
    var bar = el("div"); bar.className = "bar";
    var i = el("i"); i.style.width = Math.max(1, pc) + "%"; bar.appendChild(i); b.appendChild(bar);
    b.appendChild(el("p", (msg || "Working") + " (" + pc + "%). You can keep playing, it will not stop."));
  }
  function stop() { clearInterval(timer); timer = null; r(K); }

  async function poll() {
    var id = g(K);
    if (!id) { stop(); return; }
    try {
      var res = await fetch("/generate_video/status/" + encodeURIComponent(id), { credentials: "same-origin" });
      if (res.status === 404) { stop(); gone(); return; }
      var d = await res.json();
      if (!d.ok) { stop(); gone(); return; }
      if (d.status === "failed") {
        stop();
        return card("bad", "Video could not be made", d.error || "Something went wrong.", "/generate_video", "Try again");
      }
      if (d.status === "done") {
        stop();
        var rs = d.result || {}; var title = (rs.info && rs.info.title) || rs.title || "Your video";
        s(D, JSON.stringify({ t: title }));
        return card("ok", "Your video is ready!", title, "/dashboard#my-videos", "Open my videos");
      }
      progress(d.percent || 1, d.message);
    } catch (x) { /* network hiccup: try again on the next tick */ }
  }

  async function init() {
    var done = g(D);
    if (done && !g(K)) {
      try { card("ok", "Your video is ready!", JSON.parse(done).t, "/dashboard#my-videos", "Open my videos"); } catch (x) { r(D); }
    }
    if (!g(K)) {                         /* a job started in another tab, or before this script existed */
      try {
        var a = await (await fetch("/generate_video/active", { credentials: "same-origin" })).json();
        if (a.ok && a.job_id) { s(K, a.job_id); r(D); }
      } catch (x) {}
    }
    if (g(K)) { timer = setInterval(poll, 3000); poll(); }
  }
  window.addEventListener("storage", function (ev) {                /* another tab started a video */
    if (ev.key === K && ev.newValue && !timer) { r(D); gone(); timer = setInterval(poll, 3000); poll(); }
  });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();

