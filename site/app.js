// AgentGuard showcase: loader, reveals, theme, the run replay, copy buttons. No dependencies.
(() => {
  const root = document.documentElement;
  root.classList.add("js");
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode: fine */ } },
    seen() { try { return sessionStorage.getItem("ag-loaded") === "1"; } catch (e) { return false; } },
    markSeen() { try { sessionStorage.setItem("ag-loaded", "1"); } catch (e) { /* fine */ } },
  };

  // The dashboard lives at /app/ on the static deployment, and at / when `agentguard serve` serves this
  // page from /site/.
  const dashboard = window.AG_DASHBOARD_URL || (location.pathname.startsWith("/site") ? "/" : "/app/");
  document.querySelectorAll("[data-dash]").forEach((a) => { a.href = dashboard + (a.dataset.dash || ""); });

  // -- loader: once per session, under a second and a half; never on reduced motion ------------------
  const loader = document.getElementById("loader");
  const count = document.getElementById("loader-count");
  const hideLoader = () => {
    loader.dataset.done = "";
    setTimeout(() => loader.remove(), 750);
    store.markSeen();
    revealHero();
  };
  if (store.seen() || reduce || new URLSearchParams(location.search).has("noloader")) {
    loader.remove();
    store.markSeen();
    requestAnimationFrame(revealHero);
  } else {
    const t0 = performance.now(), dur = 900;
    const tick = (now) => {
      const p = Math.min(1, (now - t0) / dur);
      const eased = 1 - Math.pow(1 - p, 3);
      count.textContent = String(Math.round(eased * 100)).padStart(3, "0") + "%";
      if (p < 1) requestAnimationFrame(tick); else setTimeout(hideLoader, 120);
    };
    requestAnimationFrame(tick);
  }

  // -- hero headline, word by word (30–80ms stagger) --------------------------------------------------
  function splitWords(el) {
    const walk = (node) => {
      [...node.childNodes].forEach((n) => {
        if (n.nodeType === 3) {
          const frag = document.createDocumentFragment();
          n.textContent.split(/(\s+)/).forEach((part) => {
            if (!part) return;
            if (/^\s+$/.test(part)) { frag.appendChild(document.createTextNode(part)); return; }
            const s = document.createElement("span");
            s.className = "w"; s.textContent = part; frag.appendChild(s);
          });
          n.replaceWith(frag);
        } else if (n.nodeType === 1 && n.classList.contains("glyph")) {
          n.classList.add("w");
        } else if (n.nodeType === 1) {
          walk(n);
        }
      });
    };
    walk(el);
    el.querySelectorAll(".w").forEach((w, i) => { w.style.transitionDelay = `${i * 45}ms`; });
  }
  const hero = document.querySelector(".reveal-words");
  splitWords(hero);
  function revealHero() { hero.dataset.visible = ""; }

  // -- scroll reveals: fire once, stagger siblings ------------------------------------------------------
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (!e.isIntersecting) return;
      e.target.dataset.visible = "";
      io.unobserve(e.target);
    });
  }, { rootMargin: "0px 0px -80px 0px" });
  document.querySelectorAll(".reveal").forEach((el) => {
    const siblings = [...el.parentElement.children].filter((c) => c.classList.contains("reveal"));
    const i = siblings.indexOf(el);
    if (i > 0) el.style.transitionDelay = `${Math.min(i, 8) * 60}ms`;
    io.observe(el);
  });

  // -- theme ----------------------------------------------------------------------------------------------
  document.getElementById("theme").addEventListener("click", () => {
    const dark = root.dataset.theme ? root.dataset.theme === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    store.set("ag-theme", root.dataset.theme);
  });

  // -- tabs -------------------------------------------------------------------------------------------------
  function tabs(selector, attr, onChange) {
    const buttons = [...document.querySelectorAll(selector)];
    buttons.forEach((b) => b.addEventListener("click", () => {
      buttons.forEach((x) => x.setAttribute("aria-selected", String(x === b)));
      onChange(b.dataset[attr]);
    }));
  }
  tabs("[data-run]", "run", (name) => {
    document.querySelectorAll("[data-panel]").forEach((p) => { p.hidden = p.dataset.panel !== name; });
  });

  // -- copy buttons: crossfade the label with a little blur -------------------------------------------------
  document.querySelectorAll(".copy").forEach((btn) => {
    btn.innerHTML = "<span>Copy</span>";
    const label = btn.firstElementChild;
    btn.addEventListener("click", async () => {
      const text = btn.parentElement.querySelector("code").innerText;
      try { await navigator.clipboard.writeText(text); } catch (e) { return; }
      label.classList.add("swap");
      setTimeout(() => { label.textContent = "Copied"; btn.dataset.copied = ""; label.classList.remove("swap"); }, 120);
      setTimeout(() => {
        label.classList.add("swap");
        setTimeout(() => { label.textContent = "Copy"; delete btn.dataset.copied; label.classList.remove("swap"); }, 120);
      }, 1600);
    });
  });

  // -- the run replay ----------------------------------------------------------------------------------------
  const RUNS = window.AG_RUNS || {};
  const META = {
    refunds: { title: "RefundOps", meta: "Retail and Supply · 10 support tickets · claude:sonnet decides" },
    access: { title: "AccessOps", meta: "IT Infrastructure · 10 access requests · claude:sonnet decides" },
  };
  const STATUS = {
    refunded: "pill-ok", granted: "pill-ok", refused: "", denied: "", already_had_access: "",
    escalated: "pill-warn", awaiting_info: "pill-accent", routed: "",
    stopped_by_controls: "pill-bad", failed: "pill-bad",
  };
  const rowsEl = document.getElementById("rows");
  const flow = [...document.querySelectorAll("#flow li")];
  flow.forEach((li) => { li.innerHTML = `<span>${li.textContent}</span>`; });
  const foot = document.getElementById("demo-foot");
  const replayBtn = document.getElementById("replay");
  let current = "refunds";
  let timers = [];

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const shortBy = (by) => by.includes("disagreement") ? "disagreement → a person"
    : by.startsWith("rules: withheld") ? "withheld from model · injection"
    : by.includes("agrees") ? `${by.split(",")[0]} ✓ policy` : by;

  function rowHtml(item, i) {
    const verified = item.verified === true ? `<span class="pill pill-ok">✓ verified</span>`
      : item.verified === false ? `<span class="pill pill-bad">✕ not found</span>` : `<span class="pill">${esc(item.status.replaceAll("_", " "))}</span>`;
    const status = item.verified === true ? verified : `<span class="pill ${STATUS[item.status] || ""}">${esc(item.status.replaceAll("_", " "))}</span>`;
    const by = item.by || "rules";
    return `<div class="row">
      <button class="row-btn" type="button" aria-expanded="false" aria-controls="d-${i}">
        <span class="row-id">${esc(item.id)}</span>
        <span class="row-sub">${esc(item.sub)}</span>
        <span class="pill pill-accent mono">${esc(item.decision)}</span>
        <span class="row-by">${esc(shortBy(by))}</span>
        <span class="row-status">${status}</span>
        <span class="row-chev" aria-hidden="true">›</span>
      </button>
      <div class="row-detail" id="d-${i}" hidden>
        <div><span class="mono">${by.startsWith("rules") ? "Decision" : "Claude's reasoning"}</span>${esc(item.why || "—")}</div>
        <div><span class="mono">Policy check · action taken</span>${esc(item.policy || (by.startsWith("rules") ? "Decided by the rules before the model." : "—"))}<br><br>${esc(item.action)}</div>
      </div>
    </div>`;
  }

  function tilesHtml(run) {
    const s = run.summary, d = run.decisions, c = run.controls;
    const t = current === "refunds"
      ? [["Refunded", `₹${s.refunded_inr_verified.toLocaleString("en-IN")}`], ["Refused", s.refused], ["To people", s.needs_human]]
      : [["Granted", `${s.granted} ✓`], ["Denied", s.denied], ["To people", s.needs_human]];
    t.push(["Claude agreed", `${d.agreed}/${d.sent_to_model}`], ["Approvals", c.approvals_granted],
      ["Audit chain", c.audit_ok ? `${c.audit_events} ✓` : "✕"]);
    return t.map(([k, v]) => `<div class="tile"><span class="mono">${esc(k)}</span><b>${esc(v)}</b></div>`).join("");
  }

  function stopReplay() { timers.forEach(clearTimeout); timers = []; }
  const later = (ms, fn) => timers.push(setTimeout(fn, reduce ? 0 : ms));

  function render(animate) {
    stopReplay();
    const run = RUNS[current];
    if (!run) return;
    document.getElementById("demo-title").textContent = META[current].title;
    document.getElementById("demo-meta").textContent = META[current].meta;
    rowsEl.innerHTML = run.items.map(rowHtml).join("");
    document.getElementById("tiles").innerHTML = tilesHtml(run);
    const verdict = document.getElementById("verdict");
    verdict.textContent = run.verdict;
    verdict.className = `pill mono ${run.verdict === "CORRECT_SUCCESS" ? "pill-ok" : "pill-warn"}`;
    foot.hidden = false;
    const rows = [...rowsEl.children];
    if (!animate) {
      rows.forEach((r) => { r.dataset.in = ""; });
      flow.forEach((li) => { li.dataset.state = "done"; });
      foot.dataset.in = "";
      return;
    }
    delete foot.dataset.in;
    flow.forEach((li) => { delete li.dataset.state; });
    replayBtn.disabled = true;
    // ingest → decide → act (rows land one by one) → report
    later(0, () => { flow[0].dataset.state = "active"; });
    later(650, () => { flow[0].dataset.state = "done"; flow[1].dataset.state = "active"; });
    later(1400, () => { flow[1].dataset.state = "done"; flow[2].dataset.state = "active"; });
    rows.forEach((r, i) => later(1500 + i * 70, () => { r.dataset.in = ""; }));
    const end = 1500 + rows.length * 70 + 300;
    later(end, () => { flow[2].dataset.state = "done"; flow[3].dataset.state = "active"; });
    later(end + 600, () => { flow[3].dataset.state = "done"; foot.dataset.in = ""; replayBtn.disabled = false; });
  }

  rowsEl.addEventListener("click", (e) => {
    const btn = e.target.closest(".row-btn");
    if (!btn) return;
    const open = btn.getAttribute("aria-expanded") === "true";
    btn.setAttribute("aria-expanded", String(!open));
    document.getElementById(btn.getAttribute("aria-controls")).hidden = open;
  });
  tabs("[data-process]", "process", (name) => { current = name; render(true); });
  replayBtn.addEventListener("click", () => render(true));

  // -- GuardBench leaderboard (recorded results in data.js) ---------------------------------------------
  const BENCH = window.AG_BENCH;
  const table = document.getElementById("bench-table");
  if (table && BENCH && BENCH.rows.length) {
    document.getElementById("bench-meta").textContent = BENCH.meta;
    table.innerHTML = "<thead><tr><th>Agent</th><th>Shield</th><th>Runs</th><th>Solved</th><th>Mean score</th><th>Harm</th><th>Cost</th></tr></thead><tbody>"
      + BENCH.rows.map((r) => `<tr><td>${esc(r.agent)}</td><td>${r.shield ? "on" : "off"}</td><td class="num">${r.runs}</td>`
        + `<td><span class="bar" style="width:${Math.round(r.solve_rate * 80)}px"></span>${Math.round(r.solve_rate * 100)}%</td>`
        + `<td class="num">${r.mean_score.toFixed(2)}</td><td class="num">${Math.round(r.harm_rate * 100)}%</td>`
        + `<td class="num">$${r.cost_usd.toFixed(2)}</td></tr>`).join("") + "</tbody>";
  } else if (table) {
    table.innerHTML = "<tbody><tr><td>No recorded results yet.</td></tr></tbody>";
  }

  // play once when the demo first scrolls into view; show the finished state before that
  render(false);
  const demoIO = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) { demoIO.disconnect(); render(true); }
  }, { threshold: 0.3 });
  demoIO.observe(document.getElementById("demo"));
})();
