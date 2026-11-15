(function () {
  "use strict";
  var PT = window.PT || {};
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  function h(tag, props) {
    var e = document.createElement(tag);
    if (props) {
      Object.keys(props).forEach(function (k) {
        var v = props[k];
        if (k === "class") e.className = v;
        else if (k === "text") e.textContent = v;
        else if (k === "style") e.style.cssText = v;
        else if (k.slice(0, 2) === "on") e.addEventListener(k.slice(2), v);
        else if (v !== null && v !== undefined && v !== false) e.setAttribute(k, v);
      });
    }
    for (var i = 2; i < arguments.length; i++) {
      var c = arguments[i];
      if (c === null || c === undefined || c === false) continue;
      if (Array.isArray(c)) c.forEach(function (x) { if (x) e.appendChild(x); });
      else e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    return e;
  }

  /* ------------------------------------------------------------ index filters */
  function initIndex() {
    var table = $("#matrix");
    if (!table) return;
    var rows = $$("tbody tr.trow", table);
    var grps = $$("tbody tr.grp", table);
    var counts = $$("tr.counts td.count", table);
    function apply() {
      var app = $("#f-app").value;
      var models = {}; $$(".f-model:checked").forEach(function (x) { models[x.value] = 1; });
      var conds = {}; $$(".f-cond:checked").forEach(function (x) { conds[x.value] = 1; });
      var okf = ($("input[name=f-ok]:checked") || {}).value || "";
      function colVisible(el) { return models[el.dataset.model] && conds[el.dataset.cond]; }
      $$("[data-cond]", table).forEach(function (el) { el.classList.toggle("hide", !colVisible(el)); });
      $$("th.mh", table).forEach(function (th) {
        var n = $$("th.ch", table).filter(function (c) { return c.dataset.model === th.dataset.model && !c.classList.contains("hide"); }).length;
        th.classList.toggle("hide", n === 0);
        if (n) th.setAttribute("colspan", n);
      });
      var anyRow = {};
      rows.forEach(function (tr) {
        var cells = $$("td.cell", tr);
        var match = false;
        cells.forEach(function (td) {
          var vis = colVisible(td);
          var dim = okf !== "" && td.dataset.ok !== undefined && td.dataset.ok !== okf;
          td.classList.toggle("dim", dim);
          if (vis && td.dataset.ok !== undefined && !dim) match = true;
        });
        var show = (!app || tr.dataset.app === app) && (okf === "" ? true : match);
        tr.classList.toggle("hide", !show);
        if (show) anyRow[tr.dataset.app] = 1;
      });
      grps.forEach(function (g) { g.classList.toggle("hide", !anyRow[g.dataset.app]); });
      counts.forEach(function (td) {
        var m = td.dataset.model, c = td.dataset.cond, ok = 0, n = 0;
        rows.forEach(function (tr) {
          if (tr.classList.contains("hide")) return;
          $$("td.cell", tr).forEach(function (cell) {
            if (cell.dataset.model === m && cell.dataset.cond === c && cell.dataset.ok !== undefined && !cell.classList.contains("dim")) {
              n++; if (cell.dataset.ok === "1") ok++;
            }
          });
        });
        td.textContent = ok + "/" + n;
      });
    }
    $$(".filters input, .filters select").forEach(function (x) { x.addEventListener("change", apply); });
    apply();
  }

  /* ------------------------------------------------------------ episode page */
  var COLORS = ["#1f77b4", "#d95f02", "#2ca02c", "#9467bd", "#8c564b", "#e377c2",
                "#17a2b8", "#b8860b", "#6b8e23", "#c2185b", "#455a64", "#7b1fa2"];
  var STOP_RAW = {};

  function roleKey(r) { return (r || "").replace(/^(aria|vax):/, ""); }

  function initEpisode() {
    var root = $("#app");
    var steps = PT.steps, N = steps.length;
    var roleIdx = {};
    PT.roles.forEach(function (r, i) { roleIdx[r] = i % COLORS.length; });
    var hasTreeCond = PT.observation !== "image";
    var state = { cur: 1, tree: hasTreeCond, click: true, chg: hasTreeCond, mode: "before" };

    function fromHash() {
      var m = /[#&]s=(\d+)/.exec(location.hash || "");
      var n = m ? parseInt(m[1], 10) : 1;
      return Math.max(1, Math.min(N || 1, n || 1));
    }
    function go(n) {
      n = Math.max(1, Math.min(N, n));
      state.cur = n;
      try { history.replaceState(null, "", "#s=" + n); } catch (e) { location.hash = "#s=" + n; }
      render();
      var b = $(".stepbtn.cur");
      if (b && b.scrollIntoView) b.scrollIntoView({ block: "nearest", inline: "center" });
    }

    function zoom(src) { window.open(src, "_blank"); }

    /* header */
    var r = PT.result || {};
    var head = h("header", { class: "pagehead" },
      h("p", { class: "sentence", text: PT.task.sentence || PT.task.id }),
      h("div", { class: "metaline" },
        h("span", { text: "App: " + PT.task.app }),
        h("span", { text: "Model: " + PT.model.name }),
        h("span", { class: "condtag", title: PT.cond.note, text: "Condition: " + PT.cond.key }),
        h("span", { text: "Shell: " + PT.shell }),
        h("span", { text: "rep " + PT.rep }),
        h("span", { class: "badge " + (r.ok ? "ok" : "bad"), text: r.ok ? "\u2713 Success" : "\u2717 Failure" })),
      h("p", { class: "muted", text: PT.cond.note }),
      PT.summary ? h("p", { class: "summary", text: PT.summary }) : null,
      h("div", { class: "navline" },
        h("a", { href: "../index.html", text: "Home" }),
        h("a", { href: PT.nav.task, text: "Comparison page for this task" }),
        PT.nav.prev ? h("a", { href: PT.nav.prev + ".html", text: "\u2190 Previous episode" }) : null,
        PT.nav.next ? h("a", { href: PT.nav.next + ".html", text: "Next episode \u2192" }) : null),
      h("details", { class: "gloss" }, h("summary", { text: "Glossary (4 concepts)" }),
        h("dl", { class: "concepts" }, PT.concepts.map(function (c) {
          return [h("dt", { text: c[0] }), h("dd", { text: c[1] })];
        }).reduce(function (a, b) { return a.concat(b); }, []))));

    /* timeline */
    var tl = h("div", { class: "timeline", id: "tl", role: "tablist" });
    var grp = 0;
    steps.forEach(function (s, j) {
      if (s.first) grp++;
      var ttl = (s.first ? "" : "These steps were issued by the agent in one go, without looking at a new screen in between") +
        s.hints.map(function (x) { return (s.first ? "" : "\n") + x.short + ": " + x.full; }).join("\n");
      var b = h("button", {
        class: "stepbtn g" + (grp % 2) + (s.first ? "" : " joined") + (s.ok === false ? " fail" : "") + (s.hints.length ? " warned" : ""),
        "data-i": s.i,
        title: ttl,
        onclick: function () { go(s.i); }
      }, h("b", { text: String(s.i) }), h("span", { text: s.label }),
        s.hints.length ? h("em", { class: "warnline", text: "\u26a0 " + s.hints.map(function (x) { return x.short; }).join(", ") }) : null);
      tl.appendChild(b);
    });
    var hint = h("p", { class: "muted small", text: "Keyboard: \u2190 \u2192 to move between steps, Home / End to jump to the first / last. Adjacent steps with the same background were issued by the agent in one message, without a new screen in between. \u26a0 = a step flagged as suspicious by the viewer's rules. Press B to toggle \u201cbefore / after\u201d." });

    var view = h("div", { id: "stepview" });
    var foot = h("section", { class: "resultfoot" });

    root.innerHTML = "";
    root.appendChild(head);
    root.appendChild(tl);
    root.appendChild(hint);
    root.appendChild(view);
    root.appendChild(foot);

    /* result footer */
    (function () {
      var tk = r.tokens || {};
      foot.appendChild(h("h2", { text: "Result" }));
      foot.appendChild(h("p", null,
        h("span", { class: "badge " + (r.ok ? "ok" : "bad"), text: r.ok ? "\u2713 Success" : "\u2717 Failure" }),
        " Stop reason: " + (PT.stop_text || "") + " (" + (r.stop_reason || "") + ")"));
      foot.appendChild(h("h3", { text: "Grading detail (verbatim)" }));
      foot.appendChild(h("pre", { class: "plain", text: r.grader_detail == null ? "" : String(r.grader_detail) }));
      foot.appendChild(h("p", { class: "muted small", text: "Grader: " + (r.grader || "") + ". After the task ends and the app is closed, a program reads the state the app actually saved to disk and decides success or failure; no human or AI judge is involved." }));
      foot.appendChild(h("h3", { text: "The agent's final answer" }));
      foot.appendChild(h("pre", { class: "plain", text: r.answer == null ? "(none)" : String(r.answer) }));
      foot.appendChild(h("p", { class: "muted", text:
        "Steps " + (r.steps == null ? N : r.steps) + " \u00b7 wall time " + (r.wall_s == null ? "?" : r.wall_s) + " s \u00b7 tokens: input " +
        tk.input + " / output " + tk.output + " / cache read " + tk.cache_read + " \u00b7 cost $" + r.cost_usd }));
    })();

    function section(title, body) {
      return h("section", { class: "pane" }, h("h2", { text: title }), body);
    }

    function colorOf(role) { return COLORS[roleIdx[roleKey(role)] || 0]; }

    function drawBox(e, cls) {
      var b = e.box, c = colorOf(e.role);
      return h("div", {
        class: "box" + (cls ? " " + cls : ""),
        style: "left:" + (b[0] / 19.2) + "%;top:" + (b[1] / 10.8) + "%;width:" + (b[2] / 19.2) + "%;height:" + (b[3] / 10.8) + "%;--c:" + c,
        title: roleKey(e.role) + " · " + (e.name || "(unnamed)") + " · " + e.id
      });
    }

    var parseObs = function (text, tree) {
      var byId = {};
      (tree || []).forEach(function (e) { byId[e.id] = e; });
      var re = /\[(e\d+)\]\s+"((?:[^"\\]|\\.)*)"/;
      var box = h("pre", { class: "obs" });
      text.split("\n").forEach(function (line, k) {
        var m = re.exec(line), link = null;
        if (m && byId[m[1]]) {
          var nm = m[2];
          try { nm = JSON.parse('"' + m[2] + '"'); } catch (e) { /* keep as is */ }
          if (nm === (byId[m[1]].name || "")) link = byId[m[1]];
        }
        var sp = h("span", { class: "ol" + (link ? " link" : ""), text: line });
        if (link) {
          sp.dataset.eid = link.id;
          sp.addEventListener("mouseenter", function () { showHl(link, false); });
          sp.addEventListener("mouseleave", clearHl);
        }
        box.appendChild(sp);
        box.appendChild(document.createTextNode("\n"));
      });
      return box;
    };

    var stageRef = null;
    function showHl(e, dashed) {
      clearHl();
      if (!stageRef) return;
      var b = e.box;
      stageRef.appendChild(h("div", {
        class: "hl" + (dashed ? " dashed" : ""),
        style: "left:" + (b[0] / 19.2) + "%;top:" + (b[1] / 10.8) + "%;width:" + (b[2] / 19.2) + "%;height:" + (b[3] / 10.8) + "%"
      }));
    }
    function clearHl() {
      if (!stageRef) return;
      $$(".hl", stageRef).forEach(function (x) { x.parentNode.removeChild(x); });
    }

    function appendIf(parent, child) { if (child) parent.appendChild(child); }

    function diffBlock(s) {
      var wrap = h("div", { class: "diff" }, h("h2", { text: "Compared with the previous observation" }));
      if (s.diff_note === "batched") {
        wrap.appendChild(h("p", { class: "note", text: "The agent issued these steps in one go; it did not see a new screen before this step." }));
        return wrap;
      }
      if (s.diff_note === "first") {
        wrap.appendChild(h("p", { class: "muted", text: "This is the first time the agent received a tree, so there is nothing to compare with." }));
        return wrap;
      }
      var d = s.diff;
      if (!d) return null;
      var total = d.added.length + d.removed.length + d.moved.length + d.renamed.length;
      if (!total) {
        wrap.appendChild(h("p", { class: "muted", text: "No change (" + d.same + " elements unchanged)." }));
        return wrap;
      }
      wrap.appendChild(h("p", { class: "diffsum", text: "Added " + d.added.length + " \u00b7 removed " + d.removed.length +
        " \u00b7 renamed " + d.renamed.length + " \u00b7 moved " + d.moved.length + " \u00b7 unchanged " + d.same }));
      var HEAD = 5;
      function item(it, textOf, hlOf, dashed) {
        var li = h("li", { text: textOf(it) });
        li.addEventListener("mouseenter", function () { showHl(hlOf(it), dashed); });
        li.addEventListener("mouseleave", clearHl);
        return li;
      }
      function list(cls, title, items, textOf, hlOf, dashed) {
        if (!items.length) return null;
        var ul = h("ul", { class: "dl " + cls });
        items.slice(0, HEAD).forEach(function (it) { ul.appendChild(item(it, textOf, hlOf, dashed)); });
        var box = h("div", null, h("h5", { class: cls, text: title + " " + items.length }), ul);
        if (items.length > HEAD) {
          var rest = h("ul", { class: "dl " + cls });
          items.slice(HEAD).forEach(function (it) { rest.appendChild(item(it, textOf, hlOf, dashed)); });
          box.appendChild(h("details", null, h("summary", { text: "Show the other " + (items.length - HEAD) }), rest));
        }
        return box;
      }
      var nm = function (e) { return "\u201c" + (e.name || "unnamed") + "\u201d " + roleKey(e.role); };
      appendIf(wrap, list("add", "Added", d.added, nm, function (e) { return e; }, false));
      appendIf(wrap, list("rem", "Removed", d.removed, nm, function (e) { return e; }, true));
      appendIf(wrap, list("ren", "Renamed", d.renamed, function (p) { return "\u201c" + (p[0].name || "unnamed") + "\u201d \u2192 \u201c" + (p[1].name || "unnamed") + "\u201d"; }, function (p) { return p[1]; }, false));
      appendIf(wrap, list("mov", "Moved", d.moved, nm_pair, function (p) { return p[1]; }, false));
      return wrap;
      function nm_pair(p) { return nm(p[1]); }
    }

    function renderView() {
      var s = steps[state.cur - 1];
      var seen = s.seen >= 0 ? steps[s.seen] : null;
      var before = state.mode === "before";
      view.innerHTML = "";
      stageRef = null;

      /* The image shown and its tree: before = after step N-1 (what the agent saw), after = after step N */
      var shown = before ? seen : s;
      var hasShot = shown && shown.has_screen;
      var tree = shown ? shown.tree : null;
      var treeOn = state.tree && !!tree;

      /* toggle buttons + switches */
      var seg = h("div", { class: "seg" },
        h("button", { class: before ? "on" : "", onclick: function () { state.mode = "before"; renderView(); } }, "Before (what the agent saw)"),
        h("button", { class: before ? "" : "on", onclick: function () { state.mode = "after"; renderView(); } }, "After (once this step ran)"));
      var legend = h("span", { class: "legend" });
      if (treeOn) {
        var present = {};
        tree.forEach(function (e) { present[roleKey(e.role)] = 1; });
        Object.keys(present).sort().forEach(function (rk) {
          legend.appendChild(h("span", { class: "lg" }, h("i", { style: "background:" + COLORS[roleIdx[rk] || 0] }), rk));
        });
      }
      var toolbar = h("div", { class: "toolbar" }, seg,
        h("label", { class: hasTreeCond ? "" : "disabled" },
          h("input", { type: "checkbox", checked: state.tree && hasTreeCond ? "checked" : null, disabled: hasTreeCond ? null : "disabled",
            onchange: function (ev) { state.tree = ev.target.checked; renderView(); } }), "Overlay tree boxes"),
        h("label", { class: before ? "" : "disabled" },
          h("input", { type: "checkbox", checked: state.click ? "checked" : null, disabled: before ? null : "disabled",
            onchange: function (ev) { state.click = ev.target.checked; renderView(); } }), "Mark this step's click position"),
        h("label", { class: hasTreeCond && before ? "" : "disabled" },
          h("input", { type: "checkbox", checked: state.chg && hasTreeCond ? "checked" : null, disabled: hasTreeCond && before ? null : "disabled",
            onchange: function (ev) { state.chg = ev.target.checked; renderView(); } }), "Mark changes"),
        hasTreeCond ? null : h("span", { class: "muted small", text: "The agent in this condition received no tree, and none was computed for it." }),
        legend);

      var title = before
        ? (seen ? "\u2460 Before: what the agent saw when it decided (= the state after step " + seen.i + ")" : "\u2460 Before: what the agent saw when it decided")
        : "\u2460 After: the screen once this step ran (the state after step " + s.i + ")";
      var abody = h("div", null);
      if (before && seen && !s.first) abody.appendChild(h("p", { class: "note", text: "The agent issued these steps in one go and did not see a new screen before this one: below is the latest screen it had (after step " + seen.i + ")." }));
      abody.appendChild(toolbar);
      if (before && !seen) {
        abody.appendChild(h("p", { class: "muted", text: "The agent has not seen the screen yet (this is step 1 and it has received no observation). Switch to \u201cAfter\u201d to see the screen once this step ran." }));
      } else {
        var stage = h("div", { class: "stage", title: "Click to open the full-size image in a new tab" });
        stageRef = stage;
        var src = PT.img + shown.nn + ".webp";
        if (hasShot) stage.appendChild(h("img", { src: src, alt: "Screen after step " + shown.i }));
        else stage.appendChild(h("div", { class: "noimg", text: "No screenshot" }));
        stage.addEventListener("click", function () { if (hasShot) zoom(src); });
        if (treeOn) {
          var ov = h("div", { class: "overlay" });
          tree.forEach(function (e) { ov.appendChild(drawBox(e)); });
          stage.appendChild(ov);
        }
        if (before && state.chg && hasTreeCond && s.diff) {
          var cv = h("div", { class: "overlay" });
          s.diff.added.forEach(function (e) { cv.appendChild(drawBox(e, "chg-add")); });
          s.diff.renamed.forEach(function (p) { cv.appendChild(drawBox(p[1], "chg-ren")); });
          stage.appendChild(cv);
        }
        if (before && state.click && s.xy) {
          stage.appendChild(h("div", { class: "cross", style: "left:" + (s.xy[0] / 19.2) + "%;top:" + (s.xy[1] / 10.8) + "%", title: "Position of this step's action (" + s.xy[0] + "," + s.xy[1] + ")" }));
        }
        abody.appendChild(stage);
        if (before && state.chg && hasTreeCond && s.diff) abody.appendChild(h("p", { class: "muted small", text: "Thick green box = element added since the previous observation; thick yellow box = renamed element." }));
      }
      view.appendChild(section(title, abody));

      /* agent action */
      var kids = [];
      kids.push(h("p", { class: "said" + (s.text ? "" : " muted"), text: s.text || "(said nothing)" }));
      if (s.thinking) kids.push(h("details", null, h("summary", { text: "Thinking (" + s.thinking.length + " characters)" }), h("pre", { class: "plain", text: s.thinking })));
      kids.push(h("p", null, "Tool call: ", h("code", { text: s.tool + "(" + JSON.stringify(s.args || {}) + ")" })));
      kids.push(h("p", null, "Execution result: ",
        h("span", { class: "badge " + (s.ok === false ? "bad" : "ok"), text: s.ok === false ? "failed" : "succeeded" }),
        s.error ? h("span", { class: "err", text: " " + s.error }) : null));
      kids.push(h("p", { class: "muted", text: "Executed at (1920\u00d71080 screen): " + (s.xy ? "(" + s.xy[0] + ", " + s.xy[1] + ")" : "none") + " \u00b7 step took " + (s.dur == null ? "?" : s.dur.toFixed(1)) + " s" }));
      s.hints.forEach(function (x) { kids.push(h("p", { class: "warnp", text: "\u26a0 " + x.short + ": " + x.full })); });
      view.appendChild(section("\u2461 What the agent did (step " + s.i + ": " + s.label + ")", h("div", null, kids)));

      /* two columns below: left = the observation the agent actually received + the image it got; right = the diff */
      var left = h("div", { class: "left" }), right = h("div", { class: "right" });
      if (seen) {
        var obsKids = [h("h2", { text: "The observation the agent actually received (after step " + seen.i + ")" })];
        if (PT.observation === "image") obsKids.push(h("p", { class: "note", text: "This condition received only a screenshot, no tree." }));
        obsKids.push(parseObs(seen.obs || "(empty)", seen.tree));
        if (seen.has_a) {
          var asrc = PT.img + seen.nn + "_a.webp";
          obsKids.push(h("p", { class: "muted small", text: "The image it received (1280\u00d7720, click to enlarge):" }));
          obsKids.push(h("img", { class: "agentimg", src: asrc, alt: "Image the agent received", onclick: function () { zoom(asrc); } }));
        }
        left.appendChild(h("section", { class: "pane" }, obsKids));
        if (seen.tree) { var db = diffBlock(s); if (db) right.appendChild(h("section", { class: "pane" }, db)); }
      } else {
        left.appendChild(h("section", { class: "pane" }, h("h2", { text: "The observation the agent actually received" }), h("p", { class: "muted", text: "No observation received yet." })));
      }
      view.appendChild(h("div", { class: "split" }, left, right));
    }

    function render() {
      $$(".stepbtn", tl).forEach(function (b) { b.classList.toggle("cur", parseInt(b.dataset.i, 10) === state.cur); });
      if (N) renderView();
    }

    document.addEventListener("keydown", function (ev) {
      var t = ev.target && ev.target.tagName;
      if (t === "INPUT" || t === "TEXTAREA" || t === "SELECT" || ev.ctrlKey || ev.metaKey || ev.altKey) return;
      if (ev.key === "ArrowRight") { go(state.cur + 1); ev.preventDefault(); }
      else if (ev.key === "ArrowLeft") { go(state.cur - 1); ev.preventDefault(); }
      else if (ev.key === "Home") { go(1); ev.preventDefault(); }
      else if (ev.key === "End") { go(N); ev.preventDefault(); }
      else if (ev.key === "b" || ev.key === "B") { state.mode = state.mode === "before" ? "after" : "before"; renderView(); ev.preventDefault(); }
    });
    window.addEventListener("hashchange", function () { state.cur = fromHash(); render(); });
    state.cur = fromHash();
    render();
  }

  if (PT.kind === "index") initIndex();
  else if (PT.kind === "episode") initEpisode();
})();
