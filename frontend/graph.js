/* Howdy day-graph renderer — dependency-free SVG, an animated "ocean of nodes".
 *
 * renderDayGraph(svg, data) draws the day's recorded graph and keeps it alive.
 * Every frame a lightweight force simulation runs: node repulsion, edge springs
 * (relations) and a left-weighted gravity keep the structure intact, while a
 * travelling sine wave gently pushes every node — so the whole graph undulates
 * like the surface of the ocean without losing its relationships.
 *
 * Positions are cached by node id so the graph stays stable as new entries
 * arrive; new nodes are seeded near the centre and settle in smoothly. The
 * layout is responsive (tracks the svg's own size) and theme-aware.
 */
(function () {
  "use strict";

  const SVGNS = "http://www.w3.org/2000/svg";

  const RADIUS = { day: 30, entry: 18, entity: 14, todo: 16 };

  const LABEL_COLORS = {
    Person: "#f472b6", Place: "#60a5fa", Food: "#fbbf24", Meal: "#fbbf24",
    Event: "#a78bfa", Organization: "#34d399", Thing: "#94a3b8",
    Activity: "#2dd4bf", Mood: "#fb7185", Health: "#4ade80", Work: "#facc15",
    Finance: "#fb923c", Clothing: "#c084fc", Shelter: "#38bdf8",
    Transport: "#818cf8",
  };
  const COLOR_DAY = "#22d3ee";
  const COLOR_ENTRY = "#64748b";
  const COLOR_TODO = "#f87171";
  const COLOR_TODO_FUTURE = "#fbbf24";

  // id -> {x, y} (persists across re-renders so nodes don't jump)
  const POS = {};

  // Theme-aware SVG colours (SVG presentation attributes can't read CSS vars).
  const isDark = () => window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  const theme = () => ({
    nodeStroke: isDark() ? "rgba(255,255,255,0.25)" : "rgba(15,23,42,0.22)",
    labelFill: isDark() ? "#cbd5e1" : "#475569",
    thumbRing: isDark() ? "#0b1020" : "#f8fafc",
  });

  let animId = null;
  let sim = null;

  function todayISO() {
    const d = new Date();
    return d.getFullYear() + "-" +
      String(d.getMonth() + 1).padStart(2, "0") + "-" +
      String(d.getDate()).padStart(2, "0");
  }

  function el(name, attrs) {
    const e = document.createElementNS(SVGNS, name);
    if (attrs) for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  function truncate(s, n) {
    s = (s || "").toString();
    return s.length > n ? s.slice(0, n - 1) + "…" : s;
  }

  function colorFor(node) {
    if (node.type === "day") return COLOR_DAY;
    if (node.type === "entry") return COLOR_ENTRY;
    if (node.type === "todo") {
      const fut = node.for_date && node.for_date > todayISO();
      return fut ? COLOR_TODO_FUTURE : COLOR_TODO;
    }
    return LABEL_COLORS[node.label] || "#94a3b8";
  }

  // ── force simulation (real pixel space) ─────────────────────────
  // Tuned for a calm, slow "ocean" drift: the wave is clearly alive but gentle
  // enough that nodes stay clickable (small per-frame step, heavy damping).
  const REP = 26000;     // node–node repulsion coefficient
  const SPRING = 0.045;  // edge spring constant
  const GRAV = 0.014;    // pull toward the left-weighted centre
  const WAVE = 0.35;     // ocean-wave driving force (subtle)
  const DAMP = 0.92;     // velocity damping per frame
  const MAXSTEP = 2.2;   // max per-frame displacement (px)

  function step(sim) {
    const nodes = sim.nodes;
    const n = nodes.length;
    const fx = new Float64Array(n);
    const fy = new Float64Array(n);

    // Repulsion
    for (let i = 0; i < n; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < n; j++) {
        const b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        const d2 = dx * dx + dy * dy + 1;
        const f = REP / d2;
        const d = Math.sqrt(d2);
        const ux = dx / d, uy = dy / d;
        fx[i] += ux * f; fy[i] += uy * f;
        fx[j] -= ux * f; fy[j] -= uy * f;
      }
    }

    // Springs — the edges (relations) constrain the wave.
    for (const e of sim.edges) {
      const a = e.a, b = e.b;
      let dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.sqrt(dx * dx + dy * dy) + 0.01;
      const rest = e.type === "has_entry" ? 150 : 105;
      const f = (d - rest) * SPRING;
      const ux = dx / d, uy = dy / d;
      fx[e.ai] += ux * f; fy[e.ai] += uy * f;
      fx[e.bi] -= ux * f; fy[e.bi] -= uy * f;
    }

    // Gravity toward the left-weighted centre (keeps the right side sparse).
    for (let i = 0; i < n; i++) {
      fx[i] += (sim.cx - nodes[i].x) * GRAV;
      fy[i] += (sim.cy - nodes[i].y) * GRAV;
    }

    // Ocean wave — a slow travelling field that gently undulates the graph.
    sim.t += 0.016;
    const t = sim.t;
    for (let i = 0; i < n; i++) {
      const a = nodes[i];
      fx[i] += Math.sin(a.y * 0.022 + t * 0.9) * WAVE;
      fy[i] += Math.cos(a.x * 0.022 + t * 0.7) * WAVE;
    }

    // Integrate
    for (let i = 0; i < n; i++) {
      const a = nodes[i];
      let vx = (a.vx + fx[i]) * DAMP;
      let vy = (a.vy + fy[i]) * DAMP;
      vx = Math.max(-MAXSTEP, Math.min(MAXSTEP, vx));
      vy = Math.max(-MAXSTEP, Math.min(MAXSTEP, vy));
      a.vx = vx; a.vy = vy;
      if (a.n.type === "day") {
        // The Day node is the anchor — keep it pinned at the centre.
        a.x += (sim.cx - a.x) * 0.4;
        a.y += (sim.cy - a.y) * 0.4;
      } else {
        a.x += vx; a.y += vy;
        a.x = Math.max(50, Math.min(sim.W - 50, a.x));
        a.y = Math.max(50, Math.min(sim.H - 50, a.y));
      }
    }
  }

  function draw(sim) {
    const t = theme();
    for (const e of sim.edges) {
      e.line.setAttribute("x1", e.a.x);
      e.line.setAttribute("y1", e.a.y);
      e.line.setAttribute("x2", e.b.x);
      e.line.setAttribute("y2", e.b.y);
    }
    for (const node of sim.nodes) {
      node.g.setAttribute("transform", `translate(${node.x},${node.y})`);
      if (node.circle) node.circle.style.stroke = t.nodeStroke;
      if (node.ring) node.ring.style.fill = t.thumbRing;
      if (node.label) node.label.style.fill = t.labelFill;
    }
  }

  function loop() {
    if (!sim) return;
    step(sim);
    draw(sim);
    animId = requestAnimationFrame(loop);
  }

  function stopLoop() {
    if (animId) { cancelAnimationFrame(animId); animId = null; }
  }

  function buildSim(svg, data) {
    const nodes = (data && data.nodes) || [];
    const edges = (data && data.edges) || [];
    while (svg.firstChild) svg.removeChild(svg.firstChild);

    const W = Math.max(320, svg.clientWidth || 900);
    const H = Math.max(280, svg.clientHeight || 640);
    const cx = W * 0.38, cy = H * 0.5;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);

    if (!nodes.length) return null;

    // Seed positions: keep cached, scatter new nodes near the centre.
    nodes.forEach((nd, i) => {
      const k = String(nd.id);
      if (!POS[k]) {
        const a = (i / Math.max(1, nodes.length)) * Math.PI * 2;
        POS[k] = {
          x: cx + Math.cos(a) * 170 + (Math.random() - 0.5) * 30,
          y: cy + Math.sin(a) * 170 + (Math.random() - 0.5) * 30,
        };
      }
    });
    const present = new Set(nodes.map(nd => String(nd.id)));
    for (const k in POS) if (!present.has(k)) delete POS[k];

    const byId = {};
    nodes.forEach(nd => { byId[String(nd.id)] = nd; });

    // Thumbnail clip paths
    let clipN = 0;
    for (const nd of nodes) {
      if (nd.type === "entity" && nd.has_thumb && nd.thumb_url) {
        const id = "clip" + (clipN++);
        const c = el("clipPath", { id });
        const rad = RADIUS.entity + 4;
        c.appendChild(el("circle", { cx: 0, cy: 0, r: rad }));
        svg.appendChild(c);
        nd._clip = id;
      }
    }

    const S = theme();
    const simNodes = nodes.map(nd => {
      const p = POS[String(nd.id)];
      const rad = RADIUS[nd.type] || 14;
      const g = el("g", { transform: `translate(${p.x},${p.y})` });

      const title = el("title");
      title.textContent = nd.text || nd.key || nd.label;
      g.appendChild(title);

      let circle = null, ring = null;
      if (nd.type === "entity" && nd._clip) {
        ring = el("circle", { r: rad + 4, fill: S.thumbRing, stroke: colorFor(nd), "stroke-width": 2 });
        g.appendChild(ring);
        const img = el("image", {
          href: nd.thumb_url, x: -(rad + 4), y: -(rad + 4),
          width: (rad + 4) * 2, height: (rad + 4) * 2,
          "clip-path": `url(#${nd._clip})`, preserveAspectRatio: "xMidYMid slice",
        });
        // If the thumbnail fails to load, drop the image so the tinted ring
        // underneath shows as a clean fallback instead of a broken frame.
        img.addEventListener("error", () => img.remove());
        g.appendChild(img);
      } else {
        circle = el("circle", {
          r: rad, fill: colorFor(nd), "fill-opacity": nd.type === "entry" ? 0.85 : 1,
          stroke: S.nodeStroke, "stroke-width": 1.5,
        });
        g.appendChild(circle);
      }

      let label = null;
      let labelText = "";
      if (nd.type === "day") labelText = nd.text || "Day";
      else if (nd.type === "todo") labelText = nd.for_date ? `${truncate(nd.text, 12)} →${nd.for_date.slice(5)}` : truncate(nd.text, 16);
      else if (nd.type === "entity") labelText = truncate(nd.key, 10);
      else if (nd.type === "entry") labelText = truncate(nd.text, 12) || "Entry";
      if (labelText) {
        label = el("text", {
          x: 0, y: rad + 14, "text-anchor": "middle",
          fill: S.labelFill, "font-size": nd.type === "day" ? 18 : nd.type === "entry" ? 11 : 12.5,
          "font-weight": nd.type === "day" ? 600 : 500,
          "font-family": "system-ui, sans-serif",
        });
        // Halo behind the text so labels stay readable over edges/dots.
        label.style.paintOrder = "stroke";
        label.style.stroke = "var(--bg)";
        label.style.strokeWidth = "3px";
        label.style.strokeLinejoin = "round";
        label.textContent = labelText;
        g.appendChild(label);
      }

      if (nd.type === "entry" && typeof window.__openDiaryFromNode === "function") {
        g.style.cursor = "pointer";
        g.addEventListener("click", () => window.__openDiaryFromNode(nd.id));
      }
      svg.appendChild(g);

      return { n: nd, x: p.x, y: p.y, vx: 0, vy: 0, g, circle, ring, label };
    });

    const simEdges = edges.map(e => {
      const a = byId[String(e.from)], b = byId[String(e.to)];
      if (!a || !b) return null;
      const da = simNodes.find(sn => sn.n === a);
      const db = simNodes.find(sn => sn.n === b);
      if (!da || !db) return null;
      const dash = e.type === "has_todo" && b.for_date && b.for_date > todayISO() ? "6 5" : null;
      const line = el("line", {
        x1: da.x, y1: da.y, x2: db.x, y2: db.y,
        stroke: e.type === "mentions" ? "rgba(148,163,184,0.5)"
              : e.type === "has_todo" ? "rgba(248,113,113,0.6)"
              : "rgba(100,116,139,0.45)",
        "stroke-width": e.type === "mentions" ? 1.2 : 2,
        "stroke-dasharray": dash || "none",
      });
      svg.insertBefore(line, svg.firstChild);  // edges under nodes
      return { a: da, b: db, ai: simNodes.indexOf(da), bi: simNodes.indexOf(db), type: e.type, line };
    }).filter(Boolean);

    // Track size changes and keep the centre left-weighted.
    if (!svg._ro && typeof ResizeObserver !== "undefined") {
      svg._ro = new ResizeObserver(() => {
        if (!sim || sim.svg !== svg) return;
        sim.W = Math.max(320, svg.clientWidth || sim.W);
        sim.H = Math.max(280, svg.clientHeight || sim.H);
        sim.cx = sim.W * 0.38; sim.cy = sim.H * 0.5;
        svg.setAttribute("viewBox", `0 0 ${sim.W} ${sim.H}`);
      });
      svg._ro.observe(svg);
    }

    return { svg, W, H, cx, cy, t: 0, nodes: simNodes, edges: simEdges };
  }

  // Re-colour on dark/light switch without rebuilding the graph.
  if (typeof window.matchMedia === "function") {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => { if (sim) draw(sim); };
    if (mq.addEventListener) mq.addEventListener("change", onChange);
    else if (mq.addListener) mq.addListener(onChange);
  }

  function renderDayGraph(svg, data) {
    stopLoop();
    sim = buildSim(svg, data);
    if (!sim) return;
    // Settle quickly from the seeded positions so the graph doesn't "pop".
    for (let i = 0; i < 140; i++) step(sim);
    draw(sim);
    animId = requestAnimationFrame(loop);
  }

  window.renderDayGraph = renderDayGraph;
})();
