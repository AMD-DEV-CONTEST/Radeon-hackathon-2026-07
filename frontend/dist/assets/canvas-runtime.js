/**
 * NodeFlow AI Canvas Runtime v2
 * Features: DotField, ContextMenu, NodeSystem, Connections, Pan/Zoom,
 *           Slider, StylePicker, GenerationSettings, ButtonFeedback,
 *           AgentPanel, QuickProToggle, LanguageToggle, CanvasImport
 */
(function () {
  'use strict';

  /* ════════ State ════════ */
  var state = {
    nodes: [],
    connections: [],
    selectedNodes: [],
    connectMode: false,
    connectSource: null,
    importMode: false,
    importTarget: null,
    quickConnectMode: false,
    quickConnectSource: null,
    batchGenBtn: null,
    language: 'zh',
    genSettings: { ratio: '16:9', quality: '高清 2K', quantity: 1 },
    zoom: 1, panX: 0, panY: 0
  };

  /* ── Helpers ── */
  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }
  function clamp(v, min, max) { return Math.min(Math.max(v, min), max); }
  function uid() { return 'nf-' + Math.random().toString(36).slice(2, 9); }

  /* ════════════════════════════════════════
   * 0. Toast + Init indicator
   * ════════════════════════════════════════ */
  var toastEl = null;
  function showToast(msg, duration) {
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.style.cssText = 'position:fixed;bottom:100px;left:50%;transform:translateX(-50%) translateY(20px);background:var(--nf-glass);backdrop-filter:blur(20px);border:1px solid var(--nf-glass-border-hi);border-radius:var(--nf-radius-medium);padding:10px 20px;font-size:13px;color:var(--nf-text-1);z-index:99999;opacity:0;transition:opacity .25s,transform .25s;pointer-events:none;white-space:nowrap;';
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = msg;
    toastEl.style.opacity = '1';
    toastEl.style.transform = 'translateX(-50%) translateY(0)';
    clearTimeout(toastEl._timer);
    toastEl._timer = setTimeout(function () {
      toastEl.style.opacity = '0';
      toastEl.style.transform = 'translateX(-50%) translateY(20px)';
    }, duration || 2000);
  }
  window.showToast = showToast;

  /* ════════════════════════════════════════
   * 1. DotField — interactive dot grid background (fixed visibility)
   * ════════════════════════════════════════ */
  function initDotField() {
    var region = document.getElementById('excalidraw-canvas-region');
    if (!region || region.querySelector('.nf-dotfield')) return;

    /* Enhance background — visible mesh gradient + dot grid (inline = highest priority) */
    region.style.backgroundColor = 'var(--nf-ink-0)';
    region.style.backgroundImage =
      'radial-gradient(ellipse 70% 50% at 20% 20%, rgba(255,255,255,.03), transparent 60%),' +
      'radial-gradient(ellipse 60% 45% at 80% 80%, rgba(255,255,255,.04), transparent 60%),' +
      'radial-gradient(ellipse 50% 40% at 85% 15%, rgba(255,255,255,.02), transparent 60%),' +
      'radial-gradient(circle, rgba(255,255,255,.11) 1px, transparent 1.5px)';
    region.style.backgroundSize = '100% 100%, 100% 100%, 100% 100%, 22px 22px';
    region.style.backgroundPosition = 'center, center, center, 0 0';
    region.style.backgroundRepeat = 'no-repeat, no-repeat, no-repeat, repeat';

    var canvas = document.createElement('canvas');
    canvas.className = 'nf-dotfield';
    canvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:1;';
    region.insertBefore(canvas, region.firstChild);

    var svgNS = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(svgNS, 'svg');
    svg.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:1;';
    var defs = document.createElementNS(svgNS, 'defs');
    var grad = document.createElementNS(svgNS, 'radialGradient');
    grad.setAttribute('id', 'nf-dot-glow');
    var s1 = document.createElementNS(svgNS, 'stop');
    s1.setAttribute('offset', '0%');
    s1.setAttribute('stop-color', cssVar('--nf-mesh-1') || '#ffffff');
    var s2 = document.createElementNS(svgNS, 'stop');
    s2.setAttribute('offset', '100%');
    s2.setAttribute('stop-color', 'transparent');
    grad.appendChild(s1); grad.appendChild(s2); defs.appendChild(grad);
    var circle = document.createElementNS(svgNS, 'circle');
    circle.setAttribute('cx', '-9999');
    circle.setAttribute('cy', '-9999');
    circle.setAttribute('r', '160');
    circle.setAttribute('fill', 'url(#nf-dot-glow)');
    circle.style.cssText = 'opacity:0;will-change:opacity;transition:opacity .3s;';
    svg.appendChild(defs); svg.appendChild(circle);
    region.insertBefore(svg, canvas.nextSibling);

    var ctx = canvas.getContext('2d');
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var dots = [], mouse = { x: -9999, y: -9999, speed: 0, prevX: -9999, prevY: -9999 };
    var glowOpacity = 0, engagement = 0;
    var size = { w: 0, h: 0 };
    var rafId = null, frameCount = 0;
    var DOT_R = 1.5, DOT_SPACING = 18, CURSOR_R = 300, BULGE = 55;
    var visible = true;

    function resize() {
      var r = region.getBoundingClientRect();
      size.w = r.width; size.h = r.height;
      if (size.w < 1 || size.h < 1) { setTimeout(resize, 200); return; }
      canvas.width = r.width * dpr; canvas.height = r.height * dpr;
      canvas.style.width = r.width + 'px'; canvas.style.height = r.height + 'px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      buildDots();
    }
    function buildDots() {
      var step = DOT_R + DOT_SPACING;
      var cols = Math.floor(size.w / step), rows = Math.floor(size.h / step);
      var padX = (size.w % step) / 2, padY = (size.h % step) / 2;
      dots = [];
      for (var row = 0; row < rows; row++) {
        for (var col = 0; col < cols; col++) {
          var ax = padX + col * step + step / 2;
          var ay = padY + row * step + step / 2;
          dots.push({ ax: ax, ay: ay, sx: ax, sy: ay });
        }
      }
    }
    function onMouseMove(e) {
      var r = region.getBoundingClientRect();
      mouse.x = e.clientX - r.left;
      mouse.y = e.clientY - r.top;
    }

    document.addEventListener('visibilitychange', function () {
      visible = !document.hidden;
      if (visible && !rafId) rafId = requestAnimationFrame(tick);
      else if (!visible && rafId) { cancelAnimationFrame(rafId); rafId = null; }
    });

    function tick() {
      if (!visible) { rafId = null; return; }
      frameCount++;
      var dx = mouse.prevX - mouse.x, dy = mouse.prevY - mouse.y;
      mouse.speed += (Math.sqrt(dx * dx + dy * dy) - mouse.speed) * 0.5;
      if (mouse.speed < 0.001) mouse.speed = 0;
      mouse.prevX = mouse.x; mouse.prevY = mouse.y;

      var target = Math.min(mouse.speed / 5, 1);
      engagement += (target - engagement) * 0.06;
      if (engagement < 0.001) engagement = 0;
      glowOpacity += (engagement - glowOpacity) * 0.08;

      circle.setAttribute('cx', mouse.x);
      circle.setAttribute('cy', mouse.y);
      circle.style.opacity = glowOpacity * 0.7;

      ctx.clearRect(0, 0, size.w, size.h);
      if (engagement < 0.01) { rafId = requestAnimationFrame(tick); return; }
      var g = ctx.createLinearGradient(0, 0, size.w, size.h);
      var m1 = cssVar('--nf-mesh-1') || '#ffffff';
      var m3 = cssVar('--nf-mesh-3') || '#ffffff';
      g.addColorStop(0, m1 + '99');
      g.addColorStop(1, m3 + '80');
      ctx.fillStyle = g;

      var crSq = CURSOR_R * CURSOR_R, rad = DOT_R / 2;
      ctx.beginPath();
      for (var i = 0; i < dots.length; i++) {
        var d = dots[i];
        var ddx = mouse.x - d.ax, ddy = mouse.y - d.ay;
        var distSq = ddx * ddx + ddy * ddy;
        if (distSq < crSq && engagement > 0.01) {
          var dist = Math.sqrt(distSq);
          var t = 1 - dist / CURSOR_R;
          var push = t * t * BULGE * engagement;
          var angle = Math.atan2(ddy, ddx);
          d.sx += (d.ax - Math.cos(angle) * push - d.sx) * 0.15;
          d.sy += (d.ay - Math.sin(angle) * push - d.sy) * 0.15;
        } else {
          d.sx += (d.ax - d.sx) * 0.1;
          d.sy += (d.ay - d.sy) * 0.1;
        }
        ctx.moveTo(d.sx + rad, d.sy);
        ctx.arc(d.sx, d.sy, rad, 0, Math.PI * 2);
      }
      ctx.fill();
      rafId = requestAnimationFrame(tick);
    }

    resize();
    window.addEventListener('resize', resize);
    region.addEventListener('mousemove', onMouseMove, { passive: true });
    rafId = requestAnimationFrame(tick);
  }

  /* ════════════════════════════════════════
   * 2. ContextMenu — right-click / double-click (updated structure)
   * ════════════════════════════════════════ */
  /* ════════════════════════════════════════
   * 2. ContextMenu — DISABLED (menus owned by nodeflow-app.js)
   * ════════════════════════════════════════
   * nodeflow-app.js's setupContextMenu owns ALL add-node menu entry points:
   *   - right-click on empty canvas
   *   - double-click on empty canvas
   *   - dragging out of a connection port (connection-point quick menu)
   * All of them open ONE unified menu (showAddNodeMenu). This legacy menu is
   * intentionally a no-op so no duplicate "unknown" menu DOM ever appears. */
  function initContextMenu() {
    /* no-op — nodeflow-app.js owns context & dbl-click menus. */
  }

  /* ════════════════════════════════════════
   * 3. NodeSystem — nodes with ports, selection, drag, connections
   * ════════════════════════════════════════ */
  function createNode(type, name, icon, x, y) {
    var content = document.querySelector('.canvas-content-layer');
    if (!content) return null;

    var node = document.createElement('div');
    node.className = 'nf-canvas-node nf-node-' + type;
    node.setAttribute('data-node-id', uid());
    node.setAttribute('data-node-type', type);
    node.style.cssText =
      'position:absolute;left:' + x + 'px;top:' + y + 'px;' +
      'min-width:180px;max-width:300px;padding:0;' +
      'background:var(--nf-glass);backdrop-filter:blur(20px) saturate(140%);' +
      'border:1px solid var(--nf-glass-border-hi);border-radius:var(--nf-radius-large);' +
      'box-shadow:0 8px 32px rgba(0,0,0,.35);z-index:10;' +
      'animation:nf-node-in .25s cubic-bezier(.22,1,.36,1);user-select:none;';

    var iconColors = {
      text: 'var(--nf-text-2)', sketch: 'var(--nf-text-1)', image: 'var(--nf-mesh-2)',
      note: '#999999', mindmap: '#cccccc', flow: '#666666'
    };
    var iconColor = iconColors[type] || 'var(--nf-text-2)';

    /* Ports — input (left) and output (right) */
    var portIn = '<div class="nf-node-port nf-port-in" data-port="in" style="position:absolute;left:-7px;top:50%;transform:translateY(-50%);width:14px;height:14px;border-radius:50%;background:var(--nf-ink-3);border:2px solid var(--nf-glass-border-hi);cursor:crosshair;z-index:12;transition:transform 150ms,background-color 150ms;"></div>';
    var portOut = '<div class="nf-node-port nf-port-out" data-port="out" style="position:absolute;right:-7px;top:50%;transform:translateY(-50%);width:14px;height:14px;border-radius:50%;background:var(--nf-ink-3);border:2px solid var(--nf-text-1);cursor:crosshair;z-index:12;transition:transform 150ms,background-color 150ms;"></div>';

    node.innerHTML =
      portIn + portOut +
      '<div class="nf-node-header" style="display:flex;align-items:center;gap:8px;padding:10px 14px;border-bottom:1px solid var(--nf-glass-border);cursor:grab;">' +
        '<i data-lucide="' + icon + '" width="15" height="15" style="color:' + iconColor + ';flex-shrink:0;"></i>' +
        '<span class="nf-node-title" style="font-size:12.5px;font-weight:600;color:var(--nf-text-1);flex:1;">' + name + '</span>' +
        '<button class="nf-node-close" style="width:20px;height:20px;border:none;background:transparent;color:var(--nf-text-3);cursor:pointer;border-radius:4px;display:flex;align-items:center;justify-content:center;">' +
          '<i data-lucide="x" width="13" height="13"></i></button>' +
      '</div>' +
      '<div class="nf-node-body" style="font-size:12px;color:var(--nf-text-2);line-height:1.5;min-height:36px;padding:10px 14px;" contenteditable="true">' + getPlaceholder(type) + '</div>';

    content.appendChild(node);
    if (typeof lucide !== 'undefined') lucide.createIcons();

    state.nodes.push(node);
    makeNodeDraggable(node);
    makeNodeSelectable(node);
    initPortInteraction(node);

    /* Close button */
    var closeBtn = node.querySelector('.nf-node-close');
    closeBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      removeNode(node);
    });

    node.addEventListener('click', function (e) { e.stopPropagation(); });
    node.addEventListener('contextmenu', function (e) { e.stopPropagation(); });

    /* Editable body */
    var body = node.querySelector('.nf-node-body');
    body.addEventListener('focus', function () {
      if (body.textContent === getPlaceholder(type)) body.textContent = '';
    });
    body.addEventListener('blur', function () {
      if (body.textContent.trim() === '') body.textContent = getPlaceholder(type);
    });

    return node;
  }

  function getPlaceholder(type) {
    var map = {
      text: '输入文本...', sketch: '双击在此区域画草图',
      image: '点击右侧端口导入图片', note: '写点什么...',
      mindmap: '中心主题', flow: '流程步骤'
    };
    return map[type] || '编辑内容...';
  }

  function removeNode(node) {
    var nodeId = node.getAttribute('data-node-id');
    /* Remove connections involving this node */
    state.connections = state.connections.filter(function (conn) {
      if (conn.from === nodeId || conn.to === nodeId) {
        if (conn.pathEl) conn.pathEl.remove();
        if (conn.handleEl) conn.handleEl.remove();
        return false;
      }
      return true;
    });
    /* Remove from selection */
    state.selectedNodes = state.selectedNodes.filter(function (n) { return n !== node; });
    state.nodes = state.nodes.filter(function (n) { return n !== node; });
    node.style.animation = 'nf-node-out .2s ease-in forwards';
    setTimeout(function () { node.remove(); updateGenerateBtn(); }, 200);
  }

  /* ── Node Dragging ── */
  function makeNodeDraggable(node) {
    var isDragging = false, startX = 0, startY = 0, nodeX = 0, nodeY = 0;
    var header = node.querySelector('.nf-node-header');

    function onMouseDown(e) {
      if (e.target.closest('.nf-node-close') || e.target.closest('.nf-node-body') || e.target.closest('.nf-node-port')) return;
      isDragging = true;
      startX = e.clientX; startY = e.clientY;
      nodeX = parseFloat(node.style.left); nodeY = parseFloat(node.style.top);
      node.style.cursor = 'grabbing';
      node.style.zIndex = '20';
      e.preventDefault();
    }
    function onMouseMove(e) {
      if (!isDragging) return;
      /* Account for zoom scale */
      var scale = state.zoom || 1;
      node.style.left = (nodeX + (e.clientX - startX) / scale) + 'px';
      node.style.top = (nodeY + (e.clientY - startY) / scale) + 'px';
      redrawConnections();
    }
    function onMouseUp() {
      if (isDragging) { isDragging = false; node.style.cursor = ''; node.style.zIndex = '10'; }
    }
    if (header) header.addEventListener('mousedown', onMouseDown);
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  }

  /* ── Node Selection ── */
  function makeNodeSelectable(node) {
    node.addEventListener('mousedown', function (e) {
      if (e.target.closest('.nf-node-port') || e.target.closest('.nf-node-body') || e.target.closest('.nf-node-close')) return;
      var additive = e.shiftKey || e.ctrlKey || e.metaKey;
      if (!additive && !state.selectedNodes.includes(node)) {
        deselectAllNodes();
      }
      selectNode(node, true);
    });
  }

  function selectNode(node, additive) {
    if (!additive) deselectAllNodes();
    if (!state.selectedNodes.includes(node)) {
      state.selectedNodes.push(node);
    }
    node.classList.add('nf-selected');
    node.style.borderColor = 'var(--nf-text-1)';
    node.style.boxShadow = '0 0 0 1px var(--nf-text-1), 0 8px 32px rgba(0,0,0,.35), 0 0 24px rgba(255,255,255,.12)';
    updateGenerateBtn();
  }

  function deselectAllNodes() {
    state.selectedNodes.forEach(function (n) {
      n.classList.remove('nf-selected');
      n.style.borderColor = '';
      n.style.boxShadow = '0 8px 32px rgba(0,0,0,.35)';
    });
    state.selectedNodes = [];
    updateGenerateBtn();
  }

  function updateGenerateBtn() {
    var genBtns = document.querySelectorAll('.generate-btn');
    var count = state.selectedNodes.length;
    genBtns.forEach(function (btn) {
      var span = btn.querySelector('span');
      if (!span) return;
      if (count > 0) {
        span.textContent = 'Generate (' + count + ')';
        btn.classList.add('nf-batch-active');
      } else {
        span.textContent = 'Generate';
        btn.classList.remove('nf-batch-active');
      }
    });
    updateBatchGenerateBtn();
  }

  /* ════════════════════════════════════════
   * 3b. fixStaticConnectors — reposition static SVG connector-layer
   *     inside canvas-content-layer, recalculate path coordinates from
   *     actual node positions, and render double-bezier (parallel pair)
   * ════════════════════════════════════════ */
  function fixStaticConnectors() {
    var region = document.getElementById('excalidraw-canvas-region');
    if (!region) return;

    var content = region.querySelector('.canvas-content-layer');
    if (!content) return;

    /* Move missing elements into content layer so coordinates are unified */
    var missingSelectors = '.prompt-node, .result-nodes-layer, .result-layer, .connector-layer';
    region.querySelectorAll(missingSelectors).forEach(function (el) {
      if (el.parentElement !== content) content.appendChild(el);
    });

    var svg = content.querySelector('.connector-layer');
    if (!svg) return;
    svg.style.overflow = 'visible';

    /* Find source node (sketch-node or prompt-node) */
    var sourceNode = content.querySelector('.sketch-node, .prompt-node');
    if (!sourceNode) return;

    /* Find result nodes */
    var resultNodes = content.querySelectorAll('.result-node');
    if (resultNodes.length === 0) return;

    /* Get source port position (right edge, vertical center) using computed style */
    var sCs = getComputedStyle(sourceNode);
    var sx = parseFloat(sCs.left) + sourceNode.offsetWidth;
    var sy = parseFloat(sCs.top) + sourceNode.offsetHeight / 2;

    /* Preserve defs, clear old paths */
    var defs = svg.querySelector('defs');
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    if (defs) svg.appendChild(defs);

    var svgNS = 'http://www.w3.org/2000/svg';

    /* For each result node, create double-bezier (two parallel cubic curves) */
    resultNodes.forEach(function (node, idx) {
      if (!node.dataset.nfConnId) node.dataset.nfConnId = String(idx);
      if (node.dataset.disconnected) return; /* skip cut connections */
      var nCs = getComputedStyle(node);
      var tx = parseFloat(nCs.left);
      var ty = parseFloat(nCs.top) + node.offsetHeight / 2;

      /* Single smooth cubic-bezier S-curve — matches reference design.
         Horizontal control points produce a clean horizontal-flow curve. */
      var dx = Math.max(48, Math.abs(tx - sx) * 0.5);
      var d = 'M ' + sx + ' ' + sy +
              ' C ' + (sx + dx) + ' ' + sy +
              ' ' + (tx - dx) + ' ' + ty +
              ' ' + tx + ' ' + ty;

      var path = document.createElementNS(svgNS, 'path');
      path.setAttribute('d', d);
      path.setAttribute('fill', 'none');
      path.setAttribute('stroke', 'rgba(255,255,255,0.4)');
      path.setAttribute('stroke-width', '1.5');
      path.setAttribute('stroke-linecap', 'round');
      path.setAttribute('stroke-dasharray', '4 6');
      path.setAttribute('vector-effect', 'non-scaling-stroke');
      path.setAttribute('data-target-idx', node.dataset.nfConnId);
      path.style.animation = 'nf-flow 1.2s linear infinite';
      svg.appendChild(path);

      /* Port dots at both ends for a finished, clearly-anchored look */
      var dotA = document.createElementNS(svgNS, 'circle');
      dotA.setAttribute('cx', sx); dotA.setAttribute('cy', sy);
      dotA.setAttribute('r', '2.5'); dotA.setAttribute('fill', 'rgba(255,255,255,0.65)');
      svg.appendChild(dotA);

      var dotB = document.createElementNS(svgNS, 'circle');
      dotB.setAttribute('cx', tx); dotB.setAttribute('cy', ty);
      dotB.setAttribute('r', '2.5'); dotB.setAttribute('fill', 'rgba(255,255,255,0.65)');
      svg.appendChild(dotB);
    });
  }

  /* ════════════════════════════════════════
   * 3c. Cut Mode — scissors tool to sever connections
   * ════════════════════════════════════════ */
  function toggleCutMode(btn) {
    state.cutMode = !state.cutMode;
    var region = document.getElementById('excalidraw-canvas-region');
    if (region) region.classList.toggle('nf-cut-cursor', state.cutMode);
    /* Toggle cuttable class on static + dynamic connector paths */
    document.querySelectorAll('.connector-layer path, .nf-connections-svg path').forEach(function (p) {
      if (state.cutMode) p.classList.add('nf-cuttable');
      else p.classList.remove('nf-cuttable');
    });
    if (btn) btn.classList.toggle('is-active', state.cutMode);
    /* Bind deletion handler once */
    if (!window.__nfCutBound) {
      window.__nfCutBound = true;
      document.addEventListener('click', function (e) {
        if (!state.cutMode) return;
        var path = e.target.closest('.connector-layer path[data-target-idx], .nf-connections-svg path');
        if (!path) return;
        e.stopPropagation(); e.preventDefault();
        var idx = path.getAttribute('data-target-idx');
        if (idx != null) {
          /* Static connector — mark target node disconnected, rebuild */
          var content = region ? region.querySelector('.canvas-content-layer') : null;
          var nodes = content ? content.querySelectorAll('.result-node') : [];
          nodes.forEach(function (n) {
            if (n.dataset.nfConnId === idx) n.dataset.disconnected = '1';
          });
          fixStaticConnectors();
          document.querySelectorAll('.connector-layer path').forEach(function (p) { p.classList.add('nf-cuttable'); });
        } else {
          /* Dynamic connection — remove directly */
          path.remove();
        }
        showToast('已切断连接');
      }, true);
    }
    showToast(state.cutMode ? '切断模式:点击连线即可切断 (ESC 退出)' : '已退出切断模式');
  }

  /* Bind scissors tool — dedicated handler to avoid double-toggle */
  function initCutTool() {
    document.querySelectorAll('.tool-btn[aria-label="Cut"]').forEach(function (btn) {
      if (btn.dataset.nfCutBound) return;
      btn.dataset.nfCutBound = '1';
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        toggleCutMode(btn);
      });
    });
  }

  /* ════════════════════════════════════════
   * 4. Connections — curved bezier paths between nodes
   * ════════════════════════════════════════ */
  function initConnections() {
    var region = document.getElementById('excalidraw-canvas-region');
    if (!region) return;

    /* NOTE: connection rendering & drag-to-connect are owned entirely by
       nodeflow-app.js (nf-connections-svg + startConnectionDrag). This legacy
       layer no longer creates a duplicate SVG, so there is exactly ONE
       connection model and ONE rendered layer. connectMode stays false and
       the legacy temp path is removed. */

    /* Click empty canvas to deselect */
    region.addEventListener('click', function (e) {
      if (e.target.closest('.nf-canvas-node') || e.target.closest('button') || e.target.closest('input') || e.target.closest('[contenteditable]')) return;
      if (state.importMode) exitCanvasImportMode();
      else if (state.quickConnectMode) toggleQuickConnect();
      else deselectAllNodes();
    });
  }

  function getPortPos(node, portType) {
    /* Nodes use style.left/top in content-layer coordinates — read directly */
    var nx = parseFloat(node.style.left) || 0;
    var ny = parseFloat(node.style.top) || 0;
    var nw = node.offsetWidth;
    var nh = node.offsetHeight;
    if (portType === 'out') {
      return { x: nx + nw, y: ny + nh / 2 };
    } else {
      return { x: nx, y: ny + nh / 2 };
    }
  }

  function getBezierPath(x1, y1, x2, y2) {
    /* Standard cubic bezier — horizontal control points for smooth flow */
    var dx = Math.max(50, Math.abs(x2 - x1) * 0.4);
    return 'M' + x1 + ',' + y1 +
      ' C' + (x1 + dx) + ',' + y1 +
      ' ' + (x2 - dx) + ',' + y2 +
      ' ' + x2 + ',' + y2;
  }

  function createConnection(fromNode, toNode) {
    var fromId = fromNode.getAttribute('data-node-id');
    var toId = toNode.getAttribute('data-node-id');
    if (!fromId || !toId || fromId === toId) return;
    /* Delegate to nodeflow-app's single connection system so there is only one
       connection model and one rendered layer (no duplicate lines). */
    if (window.NF && NF.app && typeof NF.app.addConnection === 'function') {
      NF.app.addConnection(fromId, toId);
    }
  }

  function removeConnection(conn) {
    if (conn.pathEl) conn.pathEl.remove();
    if (conn.handleEl) conn.handleEl.remove();
    state.connections = state.connections.filter(function (c) { return c !== conn; });
  }

  function redrawConnections() {
    state.connections.forEach(function (conn) {
      var from = getPortPos(conn.fromNode, 'out');
      var to = getPortPos(conn.toNode, 'in');
      var d = getBezierPath(from.x, from.y, to.x, to.y);
      conn.pathEl.setAttribute('d', d);
      /* Position handle at midpoint */
      var midX = (from.x + to.x) / 2;
      var midY = (from.y + to.y) / 2;
      conn.handleEl.setAttribute('cx', midX);
      conn.handleEl.setAttribute('cy', midY);
    });
  }

  /* ════════════════════════════════════════
   * 5. CanvasController — smooth pan / zoom
   * ════════════════════════════════════════ */
  function initCanvasController() {
    var region = document.getElementById('excalidraw-canvas-region');
    if (!region) return;

    /* Force overflow:hidden — overrides overflow-y-auto class for canvas behavior */
    region.style.overflow = 'hidden';

    var content = region.querySelector('.canvas-content-layer');
    if (!content) {
      content = document.createElement('div');
      content.className = 'canvas-content-layer';
      content.style.cssText = 'position:absolute;inset:0;transform-origin:0 0;will-change:transform;z-index:5;';
      var moveSelectors = '.excalidraw-wrapper, .empty-state-hint, .prompt-card, .result-card-glow, .sketch-node, .gen-rings, .gen-status';
      region.querySelectorAll(moveSelectors).forEach(function (el) { content.appendChild(el); });
      region.appendChild(content);
    }

    function apply(animate) {
      content.style.transition = animate ? 'transform 0.15s ease-out' : '';
      content.style.transform = 'translate3d(' + state.panX + 'px,' + state.panY + 'px,0) scale(' + state.zoom + ')';
      var label = document.querySelector('.zoom-label');
      if (label) label.textContent = Math.round(state.zoom * 100) + '%';
      /* Move background dots with pan/zoom — creates infinite canvas feel */
      var dotSize = 22 * state.zoom;
      var bgX = ((state.panX % dotSize) + dotSize) % dotSize;
      var bgY = ((state.panY % dotSize) + dotSize) % dotSize;
      region.style.backgroundPosition =
        'center, center, center, ' + bgX + 'px ' + bgY + 'px';
      region.style.backgroundSize = '100% 100%, 100% 100%, 100% 100%, ' + dotSize + 'px ' + dotSize + 'px';
      redrawConnections();
      /* Redraw minimap immediately on every pan/zoom instead of a polling loop */
      if (window.__nfMinimapRefresh) window.__nfMinimapRefresh();
    }

    region.addEventListener('wheel', function (e) {
      e.preventDefault();
      var delta = e.deltaY > 0 ? 0.92 : 1.08;
      var newZoom = clamp(state.zoom * delta, 0.25, 4);
      var r = region.getBoundingClientRect();
      var cx = e.clientX - r.left, cy = e.clientY - r.top;
      var scaleRatio = newZoom / state.zoom;
      state.panX = cx - (cx - state.panX) * scaleRatio;
      state.panY = cy - (cy - state.panY) * scaleRatio;
      state.zoom = newZoom;
      apply(false);
    }, { passive: false });

    var handBtn = region.querySelector('.tool-btn[title="Pan"], .tool-btn[aria-label="Hand"]');
    if (handBtn) {
      handBtn.addEventListener('click', function () {
        handBtn.classList.toggle('is-active');
        region.style.cursor = handBtn.classList.contains('is-active') ? 'grab' : '';
      });
    }

    var spaceDown = false;
    document.addEventListener('keydown', function (e) {
      if (e.code === 'Space' && !e.target.matches('input, textarea, [contenteditable]')) {
        spaceDown = true; region.style.cursor = 'grab'; e.preventDefault();
      }
      if (e.code === 'Escape') {
        deselectAllNodes();
        if (state.connectMode) {
          state.connectMode = false; state.connectSource = null;
          if (state.tempPath) state.tempPath.style.display = 'none';
        }
        if (state.importMode) exitCanvasImportMode();
        if (state.quickConnectMode) toggleQuickConnect();
        if (state.cutMode) {
          var cutBtn = document.querySelector('.tool-btn[aria-label="Cut"]');
          toggleCutMode(cutBtn);
        }
      }
      if ((e.key === 'Delete' || e.key === 'Backspace') && !e.target.matches('input, textarea, [contenteditable]')) {
        if (state.selectedNodes.length > 0) {
          e.preventDefault();
          state.selectedNodes.slice().forEach(function (n) { removeNode(n); });
          showToast('已删除 ' + state.selectedNodes.length + ' 个节点');
        }
      }
    });
    document.addEventListener('keyup', function (e) {
      if (e.code === 'Space') { spaceDown = false; region.style.cursor = handBtn && handBtn.classList.contains('is-active') ? 'grab' : ''; }
    });

    region.addEventListener('mousedown', function (e) {
      if (e.button === 1 || (handBtn && handBtn.classList.contains('is-active')) || spaceDown) {
        state.isPanning = true;
        state._panStartX = e.clientX - state.panX;
        state._panStartY = e.clientY - state.panY;
        region.style.cursor = 'grabbing';
        e.preventDefault();
      }
    });
    document.addEventListener('mousemove', function (e) {
      if (!state.isPanning) return;
      state.panX = e.clientX - state._panStartX;
      state.panY = e.clientY - state._panStartY;
      apply(false);
    });
    document.addEventListener('mouseup', function () {
      if (state.isPanning) { state.isPanning = false; region.style.cursor = (handBtn && handBtn.classList.contains('is-active')) || spaceDown ? 'grab' : ''; }
    });

    var zoomIn = document.querySelector('.zoom-btn[aria-label="Zoom in"]');
    var zoomOut = document.querySelector('.zoom-btn[aria-label="Zoom out"]');
    var zoomFit = document.querySelector('.zoom-btn[aria-label="Fit to screen"]');
    if (zoomIn) zoomIn.addEventListener('click', function () { state.zoom = clamp(state.zoom * 1.2, 0.25, 4); apply(true); });
    if (zoomOut) zoomOut.addEventListener('click', function () { state.zoom = clamp(state.zoom * 0.8, 0.25, 4); apply(true); });
    if (zoomFit) zoomFit.addEventListener('click', function () { state.zoom = 1; state.panX = 0; state.panY = 0; apply(true); });

    /* Set initial background to match pan/zoom state */
    apply(false);
  }

  /* ════════════════════════════════════════
   * 6. SliderController
   * ════════════════════════════════════════ */
  function initSliders() {
    document.querySelectorAll('.strength-slider input[type="range"]').forEach(function (slider) {
      if (slider.dataset.nfBound) return;
      slider.dataset.nfBound = '1';
      function update() {
        var pct = ((slider.value - slider.min) / (slider.max - slider.min)) * 100;
        slider.style.background = 'linear-gradient(to right, var(--nf-text-1) ' + pct + '%, rgba(255,255,255,.08) ' + pct + '%)';
        var valDisplay = slider.parentElement.querySelector('.strength-value');
        if (valDisplay) valDisplay.textContent = parseFloat(slider.value).toFixed(1);
      }
      slider.addEventListener('input', update);
      update();
    });
  }

  /* ════════════════════════════════════════
   * 7. StylePicker — in-page overlay (fixes jump bug)
   * ════════════════════════════════════════ */
  function initStylePicker() {
    var styleBtns = document.querySelectorAll('[data-dom-id^="btn-style-picker"], #btn-style-picker, #btn-style-picker-text');
    if (!styleBtns.length) return;

    var panel = document.querySelector('.style-panel, .style-popover-panel');
    var backdrop = document.querySelector('.style-picker-backdrop, .style-popover-backdrop');
    var closeBtn = document.querySelector('.style-panel-close, .style-popover-close, [data-dom-id="style-picker-close"], [data-dom-id="style-popover-close"]');

    if (!panel) {
      panel = document.createElement('div');
      panel.className = 'style-panel nf-style-overlay';
      panel.style.cssText = 'display:none;position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:680px;max-width:92vw;max-height:80vh;overflow-y:auto;z-index:50;background:var(--nf-glass);backdrop-filter:blur(24px) saturate(140%);border:1px solid var(--nf-glass-border-hi);border-radius:var(--nf-radius-large);box-shadow:0 16px 48px rgba(0,0,0,.45);padding:24px;';
      var styles = [
        { name: 'Cyberpunk', img: '../assets/style-cyberpunk.jpg', desc: '霓虹未来都市' },
        { name: 'Anime', img: '../assets/style-anime.jpg', desc: '日系动漫风格' },
        { name: 'Watercolor', img: '../assets/style-watercolor.jpg', desc: '水彩晕染质感' },
        { name: 'Oil Painting', img: '../assets/style-oil.jpg', desc: '古典油画笔触' },
        { name: '3D Render', img: '../assets/style-3d.jpg', desc: '3D渲染真实感' },
        { name: 'Pixel Art', img: '../assets/style-pixel.jpg', desc: '像素复古风格' },
        { name: 'Concept Art', img: '../assets/style-concept.jpg', desc: '概念艺术设计' },
        { name: 'Minimalist', img: '../assets/style-minimalist.jpg', desc: '极简留白美学' }
      ];
      panel.innerHTML =
        '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:18px;">' +
        '<span style="font-size:16px;font-weight:600;color:var(--nf-text-1);">选择风格</span>' +
        '<button class="nf-style-close" style="width:32px;height:32px;border:none;background:transparent;color:var(--nf-text-2);border-radius:var(--nf-radius-medium);cursor:pointer;display:inline-flex;align-items:center;justify-content:center;"><i data-lucide="x" width="18" height="18"></i></button></div>' +
        '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;">' +
        styles.map(function (s, i) {
          return '<button class="nf-style-card' + (i === 0 ? ' nf-selected' : '') + '" data-style="' + s.name + '" style="background:var(--nf-ink-2);border:1px solid var(--nf-glass-border);border-radius:12px;padding:0;cursor:pointer;text-align:left;font-family:inherit;overflow:hidden;transition:transform 150ms,border-color 150ms;">' +
            '<div style="height:80px;position:relative;overflow:hidden;background:linear-gradient(135deg,#1a1a1a,#242424);">' +
              '<img src="' + s.img + '" style="width:100%;height:100%;object-fit:cover;display:block;" alt="' + s.name + '" onerror="this.style.display=\'none\'" />' +
            '</div>' +
            '<div style="padding:8px 10px;">' +
              '<span style="font-size:13px;font-weight:500;color:var(--nf-text-1);display:block;">' + s.name + '</span>' +
              '<span style="font-size:11px;color:var(--nf-text-3);">' + s.desc + '</span>' +
            '</div></button>';
        }).join('') +
        '</div>' +
        '<div style="margin-top:14px;font-size:11px;color:var(--nf-text-3);text-align:center;">点击选择风格</div>';
      var appShell = document.getElementById('app-shell') || document.body;
      appShell.appendChild(panel);

      backdrop = document.createElement('div');
      backdrop.className = 'style-picker-backdrop nf-backdrop-overlay';
      backdrop.style.cssText = 'display:none;position:absolute;inset:0;background:rgba(0,0,0,.55);backdrop-filter:blur(3px);z-index:40;';
      appShell.insertBefore(backdrop, panel);

      closeBtn = panel.querySelector('.nf-style-close');
    }

    function showPanel() { if (backdrop) backdrop.style.display = 'block'; panel.style.display = 'block'; if (typeof lucide !== 'undefined') lucide.createIcons(); }
    function hidePanel() { if (backdrop) backdrop.style.display = 'none'; panel.style.display = 'none'; }

    styleBtns.forEach(function (btn) {
      if (btn.dataset.nfBound) return;
      btn.dataset.nfBound = '1';
      btn.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); showPanel(); }, true);
    });
    if (closeBtn && !closeBtn.dataset.nfBound) {
      closeBtn.dataset.nfBound = '1';
      closeBtn.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); hidePanel(); }, true);
    }
    if (backdrop && !backdrop.dataset.nfBound) {
      backdrop.dataset.nfBound = '1';
      backdrop.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); hidePanel(); }, true);
    }

    panel.querySelectorAll('.nf-style-card, .style-card, .style-option').forEach(function (card) {
      if (card.dataset.nfBound) return;
      card.dataset.nfBound = '1';
      card.addEventListener('click', function (e) {
        e.preventDefault(); e.stopPropagation();
        panel.querySelectorAll('.nf-style-card, .style-card, .style-option').forEach(function (c) {
          c.classList.remove('nf-selected', 'is-selected');
          c.style.borderColor = ''; c.style.boxShadow = '';
        });
        card.classList.add('nf-selected', 'is-selected');
        card.style.borderColor = cssVar('--nf-mesh-1');
        card.style.boxShadow = '0 0 0 1px var(--nf-text-1), 0 0 24px rgba(255,255,255,.12)';
        var styleName = card.getAttribute('data-style') || '';
        styleBtns.forEach(function (btn) {
          var nameEl = btn.querySelector('.style-name, span:nth-child(2)');
          if (nameEl && styleName) nameEl.textContent = styleName;
        });
        setTimeout(hidePanel, 200);
      });
    });
  }

  /* ════════════════════════════════════════
   * 8. GenerationSettings — popover for ratio/quality/resolution/quantity
   * ════════════════════════════════════════ */
  function initGenerationSettings() {
    if (document.querySelector('.nf-gen-settings')) return;
    var dock = document.getElementById('floating-control-dock');
    if (!dock) return;

    /* Create settings button */
    var btn = document.createElement('button');
    btn.className = 'nf-gen-settings';
    btn.style.cssText = 'display:flex;align-items:center;gap:6px;background:rgba(255,255,255,.03);border:1px solid var(--nf-glass-border);border-radius:var(--nf-radius-medium);padding:8px 12px;cursor:pointer;font-family:inherit;flex-shrink:0;transition:border-color 150ms;';
    btn.innerHTML = '<i data-lucide="sliders-horizontal" width="15" height="15" style="color:var(--nf-text-2);"></i><span class="nf-gen-summary" style="font-size:12px;color:var(--nf-text-2);white-space:nowrap;">16:9 · 高清 2K · 1张</span>';

    /* Insert before generate button */
    var genBtn = dock.querySelector('.generate-btn');
    if (genBtn) dock.insertBefore(btn, genBtn);
    else dock.appendChild(btn);

    /* Create popover */
    var popover = document.createElement('div');
    popover.className = 'nf-gen-popover';
    popover.style.cssText = 'display:none;position:absolute;bottom:100%;left:50%;transform:translateX(-50%);margin-bottom:8px;background:var(--nf-glass);backdrop-filter:blur(24px) saturate(140%);border:1px solid var(--nf-glass-border-hi);border-radius:var(--nf-radius-large);padding:16px;z-index:50;box-shadow:0 12px 40px rgba(0,0,0,.5);width:280px;';
    dock.style.position = dock.style.position || 'relative';
    dock.appendChild(popover);

    var sections = [
      { key: 'ratio', label: '画面比例', options: ['1:1', '16:9', '4:3', '3:4', '9:16'] },
      { key: 'quality', label: '画质', options: ['标准 1K', '高清 2K', '超清 4K'] },
      { key: 'quantity', label: '数量', options: [1, 2, 4] }
    ];

    popover.innerHTML = sections.map(function (sec) {
      return '<div style="margin-bottom:12px;">' +
        '<div style="font-size:11px;font-weight:600;color:var(--nf-text-3);text-transform:uppercase;letter-spacing:.04em;margin-bottom:6px;">' + sec.label + '</div>' +
        '<div style="display:flex;gap:6px;flex-wrap:wrap;">' +
        sec.options.map(function (opt) {
          var val = String(opt);
          var isQty = sec.key === 'quantity';
          var active = isQty ? state.genSettings.quantity === opt : state.genSettings[sec.key] === val;
          return '<button class="nf-gen-opt" data-key="' + sec.key + '" data-val="' + val + '" style="padding:5px 12px;border:1px solid ' + (active ? 'var(--nf-text-1)' : 'var(--nf-glass-border)') + ';border-radius:var(--nf-radius-full);background:' + (active ? 'rgba(255,255,255,.08)' : 'transparent') + ';color:' + (active ? 'var(--nf-text-1)' : 'var(--nf-text-2)') + ';font-size:12px;font-family:inherit;cursor:pointer;transition:all 120ms;">' + val + (isQty ? '张' : '') + '</button>';
        }).join('') +
        '</div></div>';
    }).join('');

    function updateSummary() {
      var s = state.genSettings;
      var summary = s.ratio + ' · ' + s.quality + ' · ' + s.quantity + '张';
      var sumEl = btn.querySelector('.nf-gen-summary');
      if (sumEl) sumEl.textContent = summary;
    }

    btn.addEventListener('click', function (e) {
      e.preventDefault(); e.stopPropagation();
      var isVisible = popover.style.display === 'block';
      popover.style.display = isVisible ? 'none' : 'block';
    });

    popover.addEventListener('click', function (e) {
      var opt = e.target.closest('.nf-gen-opt');
      if (!opt) return;
      var key = opt.getAttribute('data-key');
      var val = opt.getAttribute('data-val');
      if (key === 'quantity') state.genSettings.quantity = parseInt(val);
      else state.genSettings[key] = val;
      /* Update active states */
      popover.querySelectorAll('.nf-gen-opt').forEach(function (o) {
        var k = o.getAttribute('data-key');
        var v = o.getAttribute('data-val');
        var isActive = k === 'quantity' ? state.genSettings.quantity === parseInt(v) : state.genSettings[k] === v;
        o.style.borderColor = isActive ? 'var(--nf-text-1)' : 'var(--nf-glass-border)';
        o.style.background = isActive ? 'rgba(255,255,255,.08)' : 'transparent';
        o.style.color = isActive ? 'var(--nf-text-1)' : 'var(--nf-text-2)';
      });
      updateSummary();
    });

    document.addEventListener('click', function (e) {
      if (!popover.contains(e.target) && e.target !== btn && !btn.contains(e.target)) {
        popover.style.display = 'none';
      }
    });

    if (typeof lucide !== 'undefined') lucide.createIcons();
  }

  /* ════════════════════════════════════════
   * 9. ButtonFeedback
   * ════════════════════════════════════════ */
  function initButtonFeedback() {
    document.querySelectorAll('.icon-btn[aria-label="History"], .tool-btn[aria-label="History"]').forEach(function (btn) {
      if (btn.dataset.nfBound) return; btn.dataset.nfBound = '1';
      btn.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); showToast('历史记录 — 即将上线'); });
    });
    document.querySelectorAll('.icon-btn[aria-label="Settings"], .tool-btn[aria-label="Settings"]').forEach(function (btn) {
      if (btn.dataset.nfBound) return; btn.dataset.nfBound = '1';
      btn.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); showToast('设置 — 即将上线'); });
    });
    document.querySelectorAll('.tool-btn').forEach(function (btn) {
      if (btn.dataset.nfBound) return; btn.dataset.nfBound = '1';
      btn.addEventListener('click', function (e) {
        if (btn.classList.contains('zoom-btn')) return;
        var label = btn.getAttribute('aria-label') || btn.getAttribute('title') || '';
        if (label === 'Hand' || label === 'Pan') return;
        if (label === 'Cut') return; /* handled by initCutTool */
        if (btn.closest('.canvas-toolbar')) {
          btn.parentElement.querySelectorAll('.tool-btn').forEach(function (s) { s.classList.remove('is-active'); });
          btn.classList.add('is-active');
        }
      });
    });

    /* Generate buttons */
    document.querySelectorAll('[data-dom-id^="btn-generate"]').forEach(function (btn) {
      if (btn.dataset.nfBound) return; btn.dataset.nfBound = '1';
      var domId = btn.getAttribute('data-dom-id') || '';
      if (domId.indexOf('text') !== -1) {
        btn.addEventListener('click', function (e) {
          e.preventDefault(); e.stopPropagation();
          var count = state.selectedNodes.length;
          showToast(count > 0 ? '批量生成 ' + count + ' 张...' : '生成中...');
          btn.style.opacity = '0.7'; btn.style.pointerEvents = 'none';
          setTimeout(function () { btn.style.opacity = ''; btn.style.pointerEvents = ''; }, 1500);
        }, true);
      } else {
        btn.addEventListener('click', function () {
          var count = state.selectedNodes.length;
          showToast(count > 0 ? '批量生成 ' + count + ' 张...' : '生成中...');
        });
      }
    });

    document.querySelectorAll('.mode-btn').forEach(function (btn) {
      if (btn.dataset.nfBound) return; btn.dataset.nfBound = '1';
      btn.addEventListener('click', function () {
        document.querySelectorAll('.mode-btn').forEach(function (b) { b.classList.remove('is-active'); b.setAttribute('aria-selected', 'false'); });
        btn.classList.add('is-active'); btn.setAttribute('aria-selected', 'true');
      });
    });
  }

  /* ════════════════════════════════════════
   * 10. AgentPanel
   * ════════════════════════════════════════ */
  function initAgentPanel() {
    if (document.querySelector('.nf-agent-panel')) return;
    var shell = document.getElementById('app-shell');
    if (!shell) return;

    var panel = document.createElement('aside');
    panel.className = 'nf-agent-panel';
    panel.innerHTML =
      '<div class="nf-agent-toggle" title="Agent"><i data-lucide="bot" width="18" height="18"></i></div>' +
      '<div class="nf-agent-body">' +
        '<div class="nf-agent-head">' +
          '<div style="display:flex;align-items:center;gap:8px;">' +
            '<i data-lucide="bot" width="18" height="18" style="color:var(--nf-text-1);"></i>' +
            '<span style="font-size:13px;font-weight:600;color:var(--nf-text-1);">Agent</span>' +
            '<span style="font-size:10px;color:var(--state-success);background:rgba(255,255,255,.12);padding:2px 8px;border-radius:var(--nf-radius-full);">就绪</span>' +
          '</div>' +
          '<button class="nf-agent-close"><i data-lucide="chevron-right" width="16" height="16"></i></button>' +
        '</div>' +
        '<div class="nf-agent-thread">' +
          '<div class="nf-agent-msg nf-agent-msg-bot"><div class="nf-msg-bubble">你好，我是 NodeFlow Agent。我可以帮你优化提示词、调整参数、批量生成。试试对我说点什么？</div></div>' +
        '</div>' +
        '<div class="nf-agent-input"><input type="text" placeholder="输入指令..." /><button class="nf-agent-send"><i data-lucide="send" width="16" height="16"></i></button></div>' +
      '</div>';
    shell.appendChild(panel);

    var toggle = panel.querySelector('.nf-agent-toggle');
    var closeBtn = panel.querySelector('.nf-agent-close');
    var sendBtn = panel.querySelector('.nf-agent-send');
    var input = panel.querySelector('input');
    var thread = panel.querySelector('.nf-agent-thread');

    toggle.addEventListener('click', function () {
      panel.classList.toggle('nf-agent-open');
      if (panel.classList.contains('nf-agent-open') && typeof lucide !== 'undefined') lucide.createIcons();
    });
    closeBtn.addEventListener('click', function () { panel.classList.remove('nf-agent-open'); });
    function sendMsg() {
      var text = input.value.trim();
      if (!text) return;
      var msg = document.createElement('div');
      msg.className = 'nf-agent-msg nf-agent-msg-user';
      msg.innerHTML = '<div class="nf-msg-bubble">' + text.replace(/</g, '&lt;') + '</div>';
      thread.appendChild(msg); input.value = ''; thread.scrollTop = thread.scrollHeight;
      setTimeout(function () {
        var reply = document.createElement('div');
        reply.className = 'nf-agent-msg nf-agent-msg-bot';
        reply.innerHTML = '<div class="nf-msg-bubble">已收到指令，正在处理中...</div>';
        thread.appendChild(reply); thread.scrollTop = thread.scrollHeight;
      }, 600);
    }
    sendBtn.addEventListener('click', sendMsg);
    input.addEventListener('keydown', function (e) { if (e.key === 'Enter') sendMsg(); });
  }

  /* ════════════════════════════════════════
   * 11. QuickProToggle
   * ════════════════════════════════════════ */
  function initQuickProToggle() {
    if (document.querySelector('.nf-qp-toggle')) return;
    var topBar = document.getElementById('top-bar');
    if (!topBar) return;
    var actions = topBar.querySelector('.top-actions');
    if (!actions) { var divs = topBar.querySelectorAll(':scope > div'); actions = divs[divs.length - 1]; }
    if (!actions) return;

    var toggle = document.createElement('div');
    toggle.className = 'nf-qp-toggle';
    toggle.innerHTML = '<button class="nf-qp-btn is-active" data-mode="quick">快速</button><button class="nf-qp-btn" data-mode="pro">专业</button>';
    actions.insertBefore(toggle, actions.firstChild);

    toggle.querySelectorAll('.nf-qp-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        toggle.querySelectorAll('.nf-qp-btn').forEach(function (b) { b.classList.remove('is-active'); });
        btn.classList.add('is-active');
        var mode = btn.getAttribute('data-mode');
        document.body.classList.toggle('nf-mode-pro', mode === 'pro');
        document.body.classList.toggle('nf-mode-quick', mode === 'quick');
        showToast(mode === 'pro' ? '专业模式 — 解锁高级参数' : '快速模式');
      });
    });
  }

  /* ════════════════════════════════════════
   * 12. LanguageToggle — EN / 中文
   * ════════════════════════════════════════ */
  var i18nMap = {
    '.empty-title': { zh: '画点什么，开始创作', en: 'Draw something to start' },
    '.empty-sub': { zh: '你的草图会成为生成的种子', en: 'Your sketch becomes the seed' },
    '.brand-tag': { zh: 'AI CANVAS', en: 'AI CANVAS' },
    '.mode-btn[data-dom-id="mode-sketch"]': { zh: 'Sketch', en: 'Sketch' },
    '.mode-btn[data-dom-id="mode-text"]': { zh: 'Text', en: 'Text' },
    '.generate-btn span:last-child': { zh: 'Generate', en: 'Generate' },
    '.nf-agent-thread .nf-msg-bubble:first-child': {
      zh: '你好，我是 NodeFlow Agent。我可以帮你优化提示词、调整参数、批量生成。试试对我说点什么？',
      en: 'Hi, I\'m NodeFlow Agent. I can help optimize prompts, adjust params, batch generate. Try asking me something?'
    },
    '.nf-agent-input input': { zh: '输入指令...', en: 'Enter command...' }
  };

  function initLanguageToggle() {
    if (document.querySelector('.nf-lang-toggle')) return;
    var topBar = document.getElementById('top-bar');
    if (!topBar) return;
    var actions = topBar.querySelector('.top-actions');
    if (!actions) { var divs = topBar.querySelectorAll(':scope > div'); actions = divs[divs.length - 1]; }
    if (!actions) return;

    var btn = document.createElement('button');
    btn.className = 'nf-lang-toggle icon-btn';
    btn.setAttribute('aria-label', 'Language');
    btn.style.cssText = 'font-size:11px;font-weight:600;padding:0 10px;width:auto;min-width:34px;border:1px solid var(--nf-glass-border);';
    btn.innerHTML = '<span class="nf-lang-label">EN</span>';
    actions.insertBefore(btn, actions.firstChild);

    btn.addEventListener('click', function () {
      state.language = state.language === 'zh' ? 'en' : 'zh';
      var label = btn.querySelector('.nf-lang-label');
      label.textContent = state.language === 'zh' ? 'EN' : '中';

      Object.keys(i18nMap).forEach(function (selector) {
        var el = document.querySelector(selector);
        if (el) {
          var text = i18nMap[selector][state.language];
          if (selector.indexOf('input') !== -1) el.setAttribute('placeholder', text);
          else el.textContent = text;
        }
      });
      showToast(state.language === 'zh' ? '已切换为中文' : 'Switched to English');
    });
  }

  /* ════════════════════════════════════════
   * 13. CanvasImport — import assets from canvas
   * ════════════════════════════════════════ */
  function triggerUpload(x, y) {
    var input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.style.display = 'none';
    document.body.appendChild(input);
    input.addEventListener('change', function (e) {
      var file = e.target.files[0];
      if (file) {
        var reader = new FileReader();
        reader.onload = function (ev) {
          var node = createNode('image', '图片节点', 'image', x, y);
          if (node) {
            var body = node.querySelector('.nf-node-body');
            body.innerHTML = '<img src="' + ev.target.result + '" style="width:100%;border-radius:6px;display:block;" />';
            body.setAttribute('contenteditable', 'false');
          }
          showToast('已导入图片');
        };
        reader.readAsDataURL(file);
      }
      input.remove();
    });
    input.click();
  }

  function enterCanvasImportMode() {
    state.importMode = true;
    var region = document.getElementById('excalidraw-canvas-region');
    if (region) {
      region.classList.add('nf-import-mode');
      showToast('点击画布中的图片导入，点击空白处退出');
    }
    /* Create overlay hint */
    var hint = document.createElement('div');
    hint.className = 'nf-import-hint';
    hint.style.cssText = 'position:fixed;top:80px;left:50%;transform:translateX(-50%);background:var(--nf-text-1);color:var(--nf-ink-0);padding:8px 20px;border-radius:var(--nf-radius-full);font-size:13px;font-weight:500;z-index:99998;box-shadow:0 4px 16px rgba(255,255,255,.15);';
    hint.innerHTML = '<i data-lucide="mouse-pointer-click" width="14" height="14" style="display:inline-block;vertical-align:middle;margin-right:6px;"></i>画布导入模式 — 点击图片导入，点击空白退出';
    document.body.appendChild(hint);
    state.importHint = hint;
    if (typeof lucide !== 'undefined') lucide.createIcons();

    /* Listen for clicks on images */
    document.addEventListener('click', importClickHandler, true);
  }

  function importClickHandler(e) {
    if (!state.importMode) return;
    var img = e.target.closest('img');
    if (img) {
      e.preventDefault();
      e.stopPropagation();
      var src = img.src;
      var region = document.getElementById('excalidraw-canvas-region');
      var r = region.getBoundingClientRect();
      var x = (e.clientX - r.left - state.panX) / state.zoom - 90;
      var y = (e.clientY - r.top - state.panY) / state.zoom - 50;
      var node = createNode('image', '图片节点', 'image', x, y);
      if (node) {
        var body = node.querySelector('.nf-node-body');
        body.innerHTML = '<img src="' + src + '" style="width:100%;border-radius:6px;display:block;" />';
        body.setAttribute('contenteditable', 'false');
      }
      showToast('已从画布导入图片');
      exitCanvasImportMode();
    }
  }

  function exitCanvasImportMode() {
    state.importMode = false;
    document.removeEventListener('click', importClickHandler, true);
    var region = document.getElementById('excalidraw-canvas-region');
    if (region) region.classList.remove('nf-import-mode');
    if (state.importHint) { state.importHint.remove(); state.importHint = null; }
  }

  /* Port interaction setup */
  function initPortInteraction(node) {
    var ports = node.querySelectorAll('.nf-node-port');
    ports.forEach(function (port) {
      port.addEventListener('mouseenter', function () {
        port.style.transform = 'translateY(-50%) scale(1.3)';
        port.style.borderColor = 'var(--nf-text-1)';
      });
      port.addEventListener('mouseleave', function () {
        if (!state.connectMode || state.connectSource !== node) {
          port.style.transform = '';
          port.style.borderColor = port.classList.contains('nf-port-out') ? 'var(--nf-text-1)' : 'var(--nf-glass-border-hi)';
        }
      });
    });
  }

  /* ════════════════════════════════════════
   * 18. EnsureZoomToolbar — add zoom controls if missing
   * ════════════════════════════════════════ */
  function ensureZoomToolbar() {
    var region = document.getElementById('excalidraw-canvas-region');
    if (!region) return;
    if (region.querySelector('.zoom-toolbar')) return;

    var tb = document.createElement('div');
    tb.className = 'zoom-toolbar';
    tb.setAttribute('role', 'toolbar');
    tb.setAttribute('aria-label', 'Canvas zoom');
    tb.innerHTML =
      '<button type="button" class="zoom-btn" aria-label="Zoom in" title="Zoom in"><i data-lucide="plus" width="16" height="16"></i></button>' +
      '<span class="zoom-label">100%</span>' +
      '<button type="button" class="zoom-btn" aria-label="Zoom out" title="Zoom out"><i data-lucide="minus" width="16" height="16"></i></button>' +
      '<div class="zoom-sep" aria-hidden="true"></div>' +
      '<button type="button" class="zoom-btn" aria-label="Fit to screen" title="Fit"><i data-lucide="maximize" width="16" height="16"></i></button>';
    region.appendChild(tb);
    if (typeof lucide !== 'undefined') lucide.createIcons();
  }

  /* ════════════════════════════════════════
   * 17. StandardizeDock — rebuild dock HTML identically on every page
   * ════════════════════════════════════════ */
  function standardizeDock() {
    var dock = document.getElementById('floating-control-dock');
    if (!dock) return;

    /* Preserve data-dom-id from existing generate button */
    var oldGen = dock.querySelector('.generate-btn');
    var genDomId = oldGen ? (oldGen.getAttribute('data-dom-id') || 'btn-generate-sketch') : 'btn-generate-sketch';

    /* Preserve style-picker dom-id */
    var oldStyle = dock.querySelector('.style-picker');
    var styleDomId = oldStyle ? (oldStyle.getAttribute('data-dom-id') || 'btn-style-picker') : 'btn-style-picker';

    /* Preserve current style name */
    var oldName = oldStyle ? oldStyle.querySelector('.style-name') : null;
    var styleName = oldName ? oldName.textContent : 'Cyberpunk';

    /* Completely rebuild inner HTML — identical on every page */
    dock.innerHTML =
      '<button type="button" class="style-picker" data-dom-id="' + styleDomId + '" aria-label="Pick style">' +
        '<span class="style-swatch" aria-hidden="true"></span>' +
        '<span class="style-name">' + styleName + '</span>' +
        '<i data-lucide="chevron-down" width="15" height="15" style="color:var(--nf-text-3);"></i>' +
      '</button>' +
      '<div class="dock-sep" aria-hidden="true"></div>' +
      '<div class="strength-slider">' +
        '<div class="strength-labels"><span>保留草图</span><span class="strength-value">0.8</span></div>' +
        '<input type="range" min="0" max="1" step="0.1" value="0.8" aria-label="Style strength" />' +
        '<div class="strength-labels" style="margin-top:4px;margin-bottom:0;"><span></span><span>完全重绘</span></div>' +
      '</div>' +
      '<div class="dock-sep" aria-hidden="true"></div>' +
      '<button type="button" class="generate-btn" data-dom-id="' + genDomId + '">' +
        '<i data-lucide="sparkles" width="16" height="16"></i><span>Generate</span>' +
      '</button>';

    /* Force identical position: bottom center — simple, clean style */
    dock.style.cssText =
      'position:absolute;left:50%;bottom:26px;transform:translateX(-50%);' +
      'z-index:25;display:flex;align-items:center;gap:14px;' +
      'padding:12px 14px;background:var(--nf-ink-2);' +
      'border:1px solid var(--nf-glass-border-hi);' +
      'border-radius:var(--nf-radius-large);' +
      'box-shadow:0 8px 24px rgba(0,0,0,.4);' +
      'animation:nf-dock-center-in .65s cubic-bezier(.22,1,.36,1) .3s both;' +
      'cursor:grab;';

    /* Remove any old mesh elements */
    dock.querySelectorAll('.nf-dock-mesh, .nf-dock-inner').forEach(function (el) { el.remove(); });

    if (typeof lucide !== 'undefined') lucide.createIcons();
    initDockDrag(dock);
  }

  /* ── Dock dragging ── */
  function initDockDrag(dock) {
    if (dock.dataset.nfDragBound) return;
    dock.dataset.nfDragBound = '1';
    var isDragging = false, startX = 0, startY = 0, origLeft = 0, origBottom = 0;

    dock.addEventListener('mousedown', function (e) {
      /* Don't drag when clicking buttons or sliders */
      if (e.target.closest('button') || e.target.closest('input') || e.target.closest('.nf-gen-settings') || e.target.closest('.nf-gen-popover')) return;
      isDragging = true;
      startX = e.clientX; startY = e.clientY;
      var r = dock.getBoundingClientRect();
      var parent = dock.parentElement.getBoundingClientRect();
      /* Switch from left:50% to explicit left for dragging.
         Must clear animation first — its keyframes override inline transform. */
      dock.style.animation = 'none';
      dock.style.left = (r.left - parent.left) + 'px';
      dock.style.bottom = 'auto';
      dock.style.top = (r.top - parent.top) + 'px';
      dock.style.transform = 'none';
      dock.style.cursor = 'grabbing';
      e.preventDefault();
    });
    document.addEventListener('mousemove', function (e) {
      if (!isDragging) return;
      var dx = e.clientX - startX;
      var dy = e.clientY - startY;
      dock.style.left = (parseFloat(dock.style.left) + dx) + 'px';
      dock.style.top = (parseFloat(dock.style.top) + dy) + 'px';
      startX = e.clientX; startY = e.clientY;
    });
    document.addEventListener('mouseup', function () {
      if (isDragging) { isDragging = false; dock.style.cursor = 'grab'; }
    });
  }

  /* ════════════════════════════════════════
   * 15. FloatingBatchGenerate — bottom-center floating button
   * ════════════════════════════════════════ */
  function initFloatingBatchGenerate() {
    if (document.querySelector('.nf-batch-gen')) return;
    var shell = document.getElementById('app-shell') || document.body;

    var btn = document.createElement('button');
    btn.className = 'nf-batch-gen';
    btn.style.cssText = 'display:none;position:absolute;bottom:92px;left:50%;transform:translateX(-50%);z-index:28;align-items:center;gap:10px;border:none;border-radius:var(--nf-radius-large);padding:12px 28px;font-size:14px;font-weight:600;font-family:inherit;cursor:pointer;color:var(--nf-ink-0);background:var(--nf-text-1);box-shadow:0 0 0 1px rgba(255,255,255,.2),0 8px 32px rgba(0,0,0,.4);transition:box-shadow 200ms,transform 150ms;animation:nf-batch-in .3s cubic-bezier(.22,1,.36,1);';
    btn.innerHTML = '<i data-lucide="sparkles" width="18" height="18"></i><span class="nf-batch-label">批量生成</span><span class="nf-batch-count" style="background:rgba(255,255,255,.2);padding:2px 10px;border-radius:var(--nf-radius-full);font-size:12px;">0</span>';
    shell.appendChild(btn);

    btn.addEventListener('click', function (e) {
      e.preventDefault(); e.stopPropagation();
      var count = state.selectedNodes.length;
      if (count === 0) return;
      showToast('正在批量生成 ' + count + ' 张图片...');
      btn.style.opacity = '0.6';
      btn.style.pointerEvents = 'none';
      setTimeout(function () {
        btn.style.opacity = '';
        btn.style.pointerEvents = '';
        showToast('批量生成完成 — ' + count + ' 张图片已就绪');
      }, 2000);
    });

    if (typeof lucide !== 'undefined') lucide.createIcons();
    state.batchGenBtn = btn;
  }

  function updateBatchGenerateBtn() {
    var btn = state.batchGenBtn;
    if (!btn) return;
    var count = state.selectedNodes.length;
    if (count > 0) {
      btn.style.display = 'flex';
      var countEl = btn.querySelector('.nf-batch-count');
      if (countEl) countEl.textContent = count;
      var labelEl = btn.querySelector('.nf-batch-label');
      if (labelEl) labelEl.textContent = state.language === 'zh' ? '批量生成' : 'Batch Generate';
    } else {
      btn.style.display = 'none';
    }
  }

  /* ════════════════════════════════════════
   * 16. QuickConnect — fast node connection mode
   * ════════════════════════════════════════ */
  function initQuickConnect() {
    var toolbar = document.querySelector('.canvas-toolbar');
    if (!toolbar || document.querySelector('.nf-quick-connect-btn')) return;

    var sep = document.createElement('div');
    sep.className = 'tool-sep';
    sep.setAttribute('aria-hidden', 'true');

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'tool-btn nf-quick-connect-btn';
    btn.setAttribute('aria-label', 'Quick Connect');
    btn.setAttribute('title', '快速连线 (C)');
    btn.innerHTML = '<i data-lucide="git-branch" width="17" height="17"></i>';
    toolbar.appendChild(sep);
    toolbar.appendChild(btn);
    if (typeof lucide !== 'undefined') lucide.createIcons();

    btn.addEventListener('click', function (e) {
      e.preventDefault(); e.stopPropagation();
      toggleQuickConnect();
    });

    document.addEventListener('keydown', function (e) {
      if ((e.key === 'c' || e.key === 'C') && !e.target.matches('input, textarea, [contenteditable]')) {
        toggleQuickConnect();
      }
    });

    document.addEventListener('click', function (e) {
      if (!state.quickConnectMode) return;
      var node = e.target.closest('.nf-canvas-node');
      if (!node) return;
      e.preventDefault();
      e.stopPropagation();
      if (!state.quickConnectSource) {
        state.quickConnectSource = node;
        node.style.boxShadow = '0 0 0 2px var(--nf-text-2), 0 8px 32px rgba(255,255,255,.12)';
        showToast('选择目标节点进行连接');
      } else if (state.quickConnectSource !== node) {
        createConnection(state.quickConnectSource, node);
        state.quickConnectSource.style.boxShadow = '';
        state.quickConnectSource = null;
      }
    }, true);
  }

  function toggleQuickConnect() {
    state.quickConnectMode = !state.quickConnectMode;
    var btn = document.querySelector('.nf-quick-connect-btn');
    var region = document.getElementById('excalidraw-canvas-region');
    if (state.quickConnectMode) {
      if (btn) btn.classList.add('is-active');
      if (region) region.style.cursor = 'crosshair';
      showToast('快速连线模式 — 点击两个节点进行连接');
    } else {
      if (btn) btn.classList.remove('is-active');
      if (region) region.style.cursor = '';
      if (state.quickConnectSource) {
        state.quickConnectSource.style.boxShadow = '';
        state.quickConnectSource = null;
      }
    }
  }

  /* ════════════════════════════════════════
   * 14. CSS Injection
   * ════════════════════════════════════════ */
  function injectStyles() {
    var style = document.createElement('style');
    style.textContent = `
/* Context Menu */
.nf-context-menu{position:fixed;display:none;flex-direction:column;min-width:200px;background:var(--nf-ink-2);border:1px solid var(--nf-glass-border-hi);border-radius:var(--nf-radius-medium);padding:6px;z-index:99999;box-shadow:0 8px 24px rgba(0,0,0,.5);max-height:400px;overflow-y:auto;}
.nf-context-menu.nf-ctx-visible{display:flex;animation:nf-ctx-in .15s ease-out;}
@keyframes nf-ctx-in{from{opacity:0;transform:scale(.95)}to{opacity:1;transform:scale(1)}}
/* Dock center-in — keeps translateX(-50%) so the dock stays horizontally centered */
@keyframes nf-dock-center-in{from{opacity:0;transform:translateX(-50%) translateY(10px)}to{opacity:1;transform:translateX(-50%) translateY(0)}}
/* Cut mode — clickable connectors */
.connector-layer path.nf-cuttable{pointer-events:stroke!important;cursor:crosshair!important;stroke-width:3!important;opacity:.8!important;}
.nf-cut-cursor{cursor:crosshair!important;}
.nf-ctx-header{font-size:10px;font-weight:600;color:var(--nf-text-3);text-transform:uppercase;letter-spacing:.06em;padding:8px 10px 4px;}
.nf-ctx-item{display:flex;align-items:center;gap:8px;width:100%;border:none;background:transparent;color:var(--nf-text-2);font-size:13px;font-family:inherit;padding:8px 10px;border-radius:var(--nf-radius-small);cursor:pointer;transition:background-color 120ms,color 120ms;}
.nf-ctx-item:hover{background:rgba(255,255,255,.08);color:var(--nf-text-1);}
.nf-ctx-item [data-lucide]{width:15px;height:15px;flex-shrink:0;}
.nf-ctx-sep{height:1px;background:var(--nf-glass-border);margin:4px 6px;}

/* Canvas Nodes */
@keyframes nf-node-in{from{opacity:0;transform:scale(.92)}to{opacity:1;transform:scale(1)}}
@keyframes nf-node-out{from{opacity:1;transform:scale(1)}to{opacity:0;transform:scale(.92)}}
.nf-canvas-node .nf-node-body:focus{outline:none;box-shadow:inset 0 0 0 2px rgba(255,255,255,.2);border-radius:0 0 var(--nf-radius-large) var(--nf-radius-large);}
.nf-node-close:hover{background:rgba(255,255,255,.08)!important;color:var(--nf-text-1)!important;}
.nf-node-port:hover{transform:translateY(-50%) scale(1.3)!important;}
.nf-canvas-node.nf-selected{border-color:var(--nf-text-1)!important;}

/* Import Mode */
.nf-import-mode{cursor:crosshair!important;}
.nf-import-mode img{cursor:pointer!important;outline:2px dashed rgba(255,255,255,.4);outline-offset:2px;}
.nf-import-mode img:hover{outline-color:var(--nf-text-1);outline-style:solid;}

/* Generate Button Batch */
.generate-btn.nf-batch-active{box-shadow:0 0 0 2px var(--nf-text-1)!important;animation:nf-batch-pulse 2s ease-in-out infinite;}
@keyframes nf-batch-pulse{0%,100%{box-shadow:0 0 0 2px var(--nf-text-1)}50%{box-shadow:0 0 0 2px var(--nf-text-2)}}

/* Agent Panel */
.nf-agent-panel{position:absolute;right:0;top:0;bottom:0;z-index:35;pointer-events:none;}
.nf-agent-toggle{position:absolute;right:16px;top:50%;transform:translateY(-50%);width:40px;height:40px;display:flex;align-items:center;justify-content:center;background:var(--nf-ink-2);border:1px solid var(--nf-glass-border);border-radius:var(--nf-radius-full);cursor:pointer;pointer-events:auto;color:var(--nf-text-2);transition:background-color 150ms,color 150ms;box-shadow:0 4px 12px rgba(0,0,0,.4);}
.nf-agent-toggle:hover{background:var(--nf-ink-3);color:var(--nf-text-1);}
.nf-agent-body{position:absolute;right:0;top:0;bottom:0;width:320px;background:var(--nf-ink-2);border-left:1px solid var(--nf-glass-border);display:flex;flex-direction:column;transform:translateX(100%);transition:transform .3s cubic-bezier(.22,1,.36,1);pointer-events:auto;box-shadow:-8px 0 24px rgba(0,0,0,.4);}
.nf-agent-panel.nf-agent-open .nf-agent-body{transform:translateX(0);}
.nf-agent-panel.nf-agent-open .nf-agent-toggle{opacity:0;pointer-events:none;}
.nf-agent-head{display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--nf-glass-border);}
.nf-agent-close{border:none;background:transparent;color:var(--nf-text-2);cursor:pointer;width:28px;height:28px;border-radius:var(--nf-radius-small);display:flex;align-items:center;justify-content:center;transition:background-color 120ms;}
.nf-agent-close:hover{background:rgba(255,255,255,.06);color:var(--nf-text-1);}
.nf-agent-thread{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px;}
.nf-agent-msg{display:flex;max-width:88%;}
.nf-agent-msg-user{align-self:flex-end;}
.nf-agent-msg-bot{align-self:flex-start;}
.nf-msg-bubble{font-size:13px;line-height:1.5;padding:10px 14px;border-radius:12px;}
.nf-agent-msg-user .nf-msg-bubble{background:var(--nf-text-1);color:var(--nf-ink-0);border-bottom-right-radius:4px;}
.nf-agent-msg-bot .nf-msg-bubble{background:var(--nf-ink-3);color:var(--nf-text-1);border-bottom-left-radius:4px;}
.nf-agent-input{display:flex;align-items:center;gap:8px;padding:12px 16px;border-top:1px solid var(--nf-glass-border);}
.nf-agent-input input{flex:1;background:var(--nf-ink-3);border:1px solid var(--nf-glass-border);border-radius:var(--nf-radius-medium);padding:8px 12px;font-size:13px;color:var(--nf-text-1);font-family:inherit;outline:none;}
.nf-agent-input input:focus{border-color:var(--nf-text-2);}
.nf-agent-input input::placeholder{color:var(--nf-text-3);}
.nf-agent-send{border:none;background:var(--nf-text-1);color:var(--nf-ink-0);border-radius:var(--nf-radius-medium);width:34px;height:34px;display:flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0;}
.nf-agent-send:hover{opacity:.85;}

/* Quick/Pro Toggle */
.nf-qp-toggle{display:inline-flex;align-items:center;gap:2px;background:rgba(255,255,255,.03);border:1px solid var(--nf-glass-border);border-radius:var(--nf-radius-full);padding:3px;margin-right:6px;}
.nf-qp-btn{border:none;cursor:pointer;padding:5px 14px;border-radius:var(--nf-radius-full);font-size:11.5px;font-family:inherit;background:transparent;color:var(--nf-text-2);transition:color 150ms,background-color 150ms;}
.nf-qp-btn.is-active{background:var(--nf-text-1);color:var(--nf-ink-0);font-weight:500;}
.nf-qp-btn:hover:not(.is-active){color:var(--nf-text-1);}

/* Language Toggle */
.nf-lang-toggle{display:inline-flex;align-items:center;justify-content:center;gap:0;}
.nf-lang-label{font-size:11px;}

/* Pro mode shows slider, Quick mode hides it */
body.nf-mode-pro .strength-slider{display:flex!important;}
body.nf-mode-quick .strength-slider{display:none!important;}
body.nf-mode-quick .dock-sep:nth-of-type(1){display:none!important;}

/* Generation Settings */
.nf-gen-settings:hover{border-color:var(--nf-glass-border-hi)!important;}
.nf-gen-popover{animation:nf-pop-in .15s ease-out;}
@keyframes nf-pop-in{from{opacity:0;transform:translateX(-50%) translateY(4px)}to{opacity:1;transform:translateX(-50%) translateY(0)}}
.nf-gen-opt:hover{border-color:var(--nf-text-2)!important;color:var(--nf-text-1)!important;}

/* Floating Batch Generate */
.nf-batch-gen:hover{box-shadow:0 4px 20px rgba(0,0,0,.5)!important;transform:translateX(-50%) translateY(-2px);}
.nf-batch-gen:active{transform:translateX(-50%) translateY(0);}
@keyframes nf-batch-in{from{opacity:0;transform:translateX(-50%) translateY(10px)}to{opacity:1;transform:translateX(-50%) translateY(0)}}

/* Quick Connect */
.nf-quick-connect-btn.is-active{background:var(--nf-text-1)!important;color:var(--nf-ink-0)!important;}

/* Zoom Toolbar */
.zoom-toolbar{position:absolute;right:26px;bottom:26px;z-index:22;display:inline-flex;flex-direction:column;align-items:center;gap:2px;background:var(--nf-ink-2);border:1px solid var(--nf-glass-border);border-radius:var(--nf-radius-full);padding:5px;}
.zoom-btn{width:32px;height:32px;display:inline-flex;align-items:center;justify-content:center;border:none;background:transparent;color:var(--nf-text-2);cursor:pointer;border-radius:var(--nf-radius-full);transition:background-color 150ms,color 150ms;}
.zoom-btn:hover{background:rgba(255,255,255,.06);color:var(--nf-text-1);}
.zoom-sep{width:16px;height:1px;background:var(--nf-glass-border);margin:2px 0;}
.zoom-label{font-size:10px;color:var(--nf-text-3);padding:2px 0;text-align:center;font-variant-numeric:tabular-nums;}

/* Minimap — collapsed trigger + expandable panel (kept clear of toolbar/dock) */
.nf-minimap-wrap{position:absolute;left:20px;bottom:20px;z-index:30;}
.nf-minimap-trigger{width:34px;height:34px;border:none;border-radius:var(--nf-radius-full);background:var(--nf-ink-2);border:1px solid var(--nf-glass-border);color:var(--nf-text-2);display:flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.4);transition:background-color 150ms,color 150ms,transform 120ms;}
.nf-minimap-trigger:hover{background:var(--nf-text-1);color:var(--nf-ink-0);transform:translateY(-1px);}
.nf-minimap-trigger.is-active{background:var(--nf-text-1);color:var(--nf-ink-0);}
.nf-minimap{position:absolute;left:-6px;bottom:44px;width:220px;height:150px;background:var(--nf-ink-2);border:1px solid var(--nf-glass-border-hi);border-radius:var(--nf-radius-medium);overflow:hidden;box-shadow:0 12px 32px rgba(0,0,0,.55);opacity:0;transform:translateY(8px) scale(.96);pointer-events:none;transition:opacity 180ms ease,transform 180ms ease;}
.nf-minimap.is-open{opacity:1;transform:translateY(0) scale(1);pointer-events:auto;}
.nf-minimap canvas{display:block;width:100%;height:100%;cursor:pointer;}
.nf-minimap-label{position:absolute;top:5px;left:9px;font-size:9px;color:var(--nf-text-3);text-transform:uppercase;letter-spacing:.05em;pointer-events:none;z-index:2;}
.nf-minimap-count{position:absolute;top:5px;left:50%;transform:translateX(-50%);font-size:9px;color:var(--nf-text-2);letter-spacing:.03em;pointer-events:none;z-index:2;font-variant-numeric:tabular-nums;background:rgba(255,255,255,.05);padding:1px 7px;border-radius:8px;}
.nf-minimap-viewport{position:absolute;display:none;border:1.5px solid rgba(255,255,255,.9);background:rgba(255,255,255,.14);pointer-events:none;border-radius:2px;z-index:3;box-shadow:0 0 6px rgba(0,0,0,.5),inset 0 0 0 rgba(0,0,0,.2);}
.nf-minimap-fit{position:absolute;right:5px;top:5px;width:22px;height:22px;border:none;border-radius:6px;background:rgba(255,255,255,.06);color:var(--nf-text-2);cursor:pointer;display:flex;align-items:center;justify-content:center;z-index:4;transition:background-color 150ms,color 150ms;}
.nf-minimap-fit:hover{background:var(--nf-text-1);color:var(--nf-ink-0);}
/* Floating "return to content" pill — appears when the user pans away and gets lost */
.nf-return-pill{position:absolute;left:50%;bottom:92px;transform:translateX(-50%) translateY(10px);z-index:29;display:flex;align-items:center;gap:8px;padding:9px 16px;border-radius:var(--nf-radius-full);background:var(--nf-ink-2);border:1px solid var(--nf-glass-border-hi);box-shadow:0 8px 24px rgba(0,0,0,.45);color:var(--nf-text-1);font-size:12.5px;font-weight:500;cursor:pointer;opacity:0;pointer-events:none;transition:opacity 200ms,transform 200ms,background-color 150ms,color 150ms;}
.nf-return-pill.is-visible{opacity:1;transform:translateX(-50%) translateY(0);pointer-events:auto;}
.nf-return-pill:hover{color:var(--nf-ink-0);background:var(--nf-text-1);}

/* Dock sub-elements — forced identical across all pages */
#floating-control-dock{display:flex!important;align-items:center!important;gap:14px!important;padding:12px 14px!important;width:auto!important;max-width:none!important;background:var(--nf-ink-2)!important;border:1px solid var(--nf-glass-border-hi)!important;border-radius:var(--nf-radius-large)!important;box-shadow:0 8px 24px rgba(0,0,0,.5)!important;}
#floating-control-dock .style-picker{display:flex;align-items:center;gap:9px;background:rgba(255,255,255,.03);border:1px solid var(--nf-glass-border);border-radius:var(--nf-radius-medium);padding:8px 13px;cursor:pointer;font-family:inherit;flex-shrink:0;transition:border-color 160ms,background-color 160ms;}
#floating-control-dock .style-picker:hover{border-color:var(--nf-glass-border-hi);background:rgba(255,255,255,.05);}
#floating-control-dock .style-swatch{width:18px;height:18px;border-radius:50%;flex-shrink:0;background:var(--nf-text-2);box-shadow:0 0 0 1px rgba(255,255,255,.1);}
#floating-control-dock .style-name{font-size:13px;font-weight:500;color:var(--nf-text-1);}
#floating-control-dock .dock-sep{width:1px;height:28px;background:var(--nf-glass-border);flex-shrink:0;}
#floating-control-dock .strength-slider{width:168px;flex-shrink:0;}
#floating-control-dock .strength-labels{display:flex;justify-content:space-between;margin-bottom:5px;}
#floating-control-dock .strength-labels span{font-size:10.5px;color:var(--nf-text-3);letter-spacing:.02em;}
#floating-control-dock .strength-value{font-size:10.5px;color:var(--nf-text-2);font-variant-numeric:tabular-nums;}
#floating-control-dock .strength-slider input[type="range"]{-webkit-appearance:none;appearance:none;width:100%;height:3px;border-radius:2px;outline:none;cursor:pointer;margin:0;background:rgba(255,255,255,.1);}
#floating-control-dock .strength-slider input[type="range"]::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;width:14px;height:14px;border-radius:50%;background:var(--nf-text-1);border:2px solid var(--nf-ink-1);cursor:pointer;}
#floating-control-dock .strength-slider input[type="range"]::-moz-range-thumb{width:14px;height:14px;border-radius:50%;background:var(--nf-text-1);border:2px solid var(--nf-ink-1);cursor:pointer;}
#floating-control-dock .generate-btn{display:flex;align-items:center;gap:8px;border:none;border-radius:var(--nf-radius-medium);padding:9px 20px;font-size:13.5px;font-weight:600;font-family:inherit;cursor:pointer;flex-shrink:0;color:var(--nf-ink-0);background:var(--nf-text-1);box-shadow:none;transition:opacity 180ms,transform 120ms;}
#floating-control-dock .generate-btn:hover{opacity:.85;transform:translateY(-1px);}
#floating-control-dock .generate-btn:active{transform:translateY(0);}

/* Override ALL page-level styles — force clean monochrome */
.result-node::before,.result-node::after{display:none!important;background:none!important;content:none!important;}
#floating-control-dock::before,#floating-control-dock::after{display:none!important;background:none!important;content:none!important;}
#top-bar{background:var(--nf-ink-2)!important;background-image:none!important;}
#excalidraw-canvas-region{background-image:radial-gradient(circle,rgba(255,255,255,.04) 1px,transparent 1.5px)!important;background-size:22px 22px!important;background-position:0 0!important;background-repeat:repeat!important;background-color:var(--nf-ink-0)!important;}
.style-swatch{background:var(--nf-text-2)!important;background-image:none!important;}
.generate-btn{background:var(--nf-text-1)!important;background-image:none!important;box-shadow:none!important;color:var(--nf-ink-0)!important;}
.generate-btn:hover{opacity:.85!important;background:var(--nf-text-1)!important;}
.mode-btn.is-active{background:var(--nf-text-1)!important;color:var(--nf-ink-0)!important;}
.tool-btn.is-active{background:var(--nf-text-1)!important;color:var(--nf-ink-0)!important;}
.connector-layer path{stroke:rgba(255,255,255,.25)!important;}
.connector-dot{fill:rgba(255,255,255,.3)!important;}
`;
    document.head.appendChild(style);
  }

  /* ════════════════════════════════════════
   * 15. Minimap — canvas overview with viewport indicator
   * ════════════════════════════════════════ */
  function initMinimap() {
    var region = document.getElementById('excalidraw-canvas-region');
    if (!region) return;
    if (region.querySelector('.nf-minimap-wrap')) return;

    var content = region.querySelector('.canvas-content-layer');

    /* Collapsed trigger + expandable panel */
    var wrap = document.createElement('div');
    wrap.className = 'nf-minimap-wrap';
    wrap.innerHTML =
      '<button type="button" class="nf-minimap-trigger" aria-label="Minimap" title="画布总览">' +
        '<i data-lucide="map" width="16" height="16"></i>' +
      '</button>' +
      '<div class="nf-minimap">' +
        '<span class="nf-minimap-label">Minimap</span>' +
        '<span class="nf-minimap-count">0 节点</span>' +
        '<canvas width="220" height="150"></canvas>' +
        '<div class="nf-minimap-viewport"></div>' +
        '<button type="button" class="nf-minimap-fit" aria-label="Fit to content" title="回到内容">' +
          '<i data-lucide="maximize" width="13" height="13"></i>' +
        '</button>' +
      '</div>';
    region.appendChild(wrap);

    var container = wrap.querySelector('.nf-minimap');
    var trigger = wrap.querySelector('.nf-minimap-trigger');
    var canvas = container.querySelector('canvas');
    var ctx = canvas.getContext('2d');
    var viewport = container.querySelector('.nf-minimap-viewport');
    var fitBtn = container.querySelector('.nf-minimap-fit');

    /* Floating "return to content" pill — appears when the user pans away and gets lost */
    var returnPill = document.createElement('div');
    returnPill.className = 'nf-return-pill';
    returnPill.innerHTML = '<i data-lucide="locate-fixed" width="14" height="14"></i><span>回到内容</span>';
    region.appendChild(returnPill);
    if (typeof lucide !== 'undefined') lucide.createIcons();

    /* Open/collapse on click. IMPORTANT: do NOT bind an auto-open on the trigger's
       mouseenter. That would fire before the click on the same interaction and
       make every click toggle the panel closed right after opening (the classic
       "opens then immediately closes" bug). Stay open by clicking the trigger,
       close by clicking the trigger again or clicking anywhere outside. */
    function open() { container.classList.add('is-open'); trigger.classList.add('is-active'); draw(); }
    function close() { container.classList.remove('is-open'); trigger.classList.remove('is-active'); }
    trigger.addEventListener('click', function (e) { e.stopPropagation(); container.classList.contains('is-open') ? close() : open(); });
    container.addEventListener('mouseenter', open);
    container.addEventListener('mouseleave', function (e) { if (!wrap.contains(e.relatedTarget)) close(); });
    document.addEventListener('mousedown', function (e) { if (!wrap.contains(e.target)) close(); });

    /* Read node geometry directly from content coords (robust regardless of zoom/pan or minimap visibility) */
    function getNodes() {
      return content ? content.querySelectorAll('.nf-canvas-node, .prompt-node, .result-node, .sketch-node') : [];
    }
    function getContentBounds() {
      var nodes = getNodes();
      if (!nodes.length) return { minX: 0, minY: 0, maxX: 800, maxY: 600 };
      var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      nodes.forEach(function (n) {
        var x = parseFloat(n.style.left) || 0;
        var y = parseFloat(n.style.top) || 0;
        var w = n.offsetWidth || 0;
        var h = n.offsetHeight || 0;
        if (x < minX) minX = x;
        if (y < minY) minY = y;
        if (x + w > maxX) maxX = x + w;
        if (y + h > maxY) maxY = y + h;
      });
      var pad = 60;
      return { minX: minX - pad, minY: minY - pad, maxX: maxX + pad, maxY: maxY + pad };
    }

    /* World bounds for the minimap — the shown region scales with the current
       zoom: zoom in → world shrinks → content magnifies; zoom out → world grows
       → content shrinks. The region is always at least ~2.5x the current
       viewport (in world coords), so the viewport rectangle stays a stable
       fraction of the map while node sizes visibly track the zoom level. */
    function getWorldBounds() {
      var b = getContentBounds();
      var r = region.getBoundingClientRect();
      var vw = state.zoom > 0 ? r.width / state.zoom : r.width;
      var vh = state.zoom > 0 ? r.height / state.zoom : r.height;
      var minW = Math.max(vw * 2.5, 300);
      var minH = Math.max(vh * 2.5, 300);
      var cx = (b.minX + b.maxX) / 2, cy = (b.minY + b.maxY) / 2;
      var w = Math.max(b.maxX - b.minX, minW);
      var h = Math.max(b.maxY - b.minY, minH);
      return { minX: cx - w / 2, minY: cy - h / 2, maxX: cx + w / 2, maxY: cy + h / 2 };
    }

    function draw() {
      var w = canvas.width, h = canvas.height;
      ctx.fillStyle = '#0a0a0a';
      ctx.fillRect(0, 0, w, h);

      var nodes = getNodes();
      var countEl = container.querySelector('.nf-minimap-count');
      if (countEl) countEl.textContent = nodes.length + ' 节点';

      /* Fit the whole content into the minimap so node sizes and relative
         positions are always visible, independent of the zoom level.
         The viewport rectangle below then shows where you are. */
      var bounds = getWorldBounds();
      var bw = bounds.maxX - bounds.minX;
      var bh = bounds.maxY - bounds.minY;
      if (bw <= 0 || bh <= 0) return;
      var scale = Math.min(w / bw, h / bh);
      var offX = (w - bw * scale) / 2;
      var offY = (h - bh * scale) / 2;

      /* Nodes */
      nodes.forEach(function (n) {
        var x = parseFloat(n.style.left) || 0;
        var y = parseFloat(n.style.top) || 0;
        var cw = n.offsetWidth || 0;
        var ch = n.offsetHeight || 0;
        var px = offX + (x - bounds.minX) * scale;
        var py = offY + (y - bounds.minY) * scale;
        var rw = Math.max(3, cw * scale);
        var rh = Math.max(3, ch * scale);
        ctx.fillStyle = n.classList.contains('nf-selected') || n.classList.contains('is-selected') ? '#ffffff' : '#8b93a1';
        /* Anchor the node rect at its top-left corner (px,py) — this matches the
           connection endpoints and the viewport rectangle, both of which are
           anchored at their top-left. Previously the rect was centered on the
           node's top-left corner, which shifted every node by half its size and
           broke alignment with the viewport box and connection lines. */
        ctx.fillRect(px, py, rw, rh);
      });

      /* Connections — read from nodeflow-app's single connection model */
      var nfConns = (window.NF && NF.app && NF.app.state && NF.app.state.connections) ? NF.app.state.connections : [];
      if (nfConns.length > 0) {
        ctx.strokeStyle = 'rgba(255,255,255,0.4)';
        ctx.lineWidth = 1;
        nfConns.forEach(function (conn) {
          var fromEl = document.querySelector('[data-node-id="' + conn.from + '"]');
          var toEl = document.querySelector('[data-node-id="' + conn.to + '"]');
          if (!fromEl || !toEl) return;
          var fx = offX + (parseFloat(fromEl.style.left) + fromEl.offsetWidth - bounds.minX) * scale;
          var fy = offY + (parseFloat(fromEl.style.top) + fromEl.offsetHeight / 2 - bounds.minY) * scale;
          var tx = offX + (parseFloat(toEl.style.left) - bounds.minX) * scale;
          var ty = offY + (parseFloat(toEl.style.top) + toEl.offsetHeight / 2 - bounds.minY) * scale;
          ctx.beginPath();
          ctx.moveTo(fx, fy);
          ctx.lineTo(tx, ty);
          ctx.stroke();
        });
      }

      /* Viewport rectangle — shows the current zoom/pan window.
         It shrinks when zoomed in and grows when zoomed out.
         IMPORTANT: we clamp it inside the minimap so it is ALWAYS visible,
         even when the current viewport is larger than the content bounds
         (e.g. few/empty content or heavy zoom-out). Reference: excalidraw. */
      var r = region.getBoundingClientRect();
      var vw = r.width / state.zoom;
      var vh = r.height / state.zoom;
      var vx = -state.panX / state.zoom;
      var vy = -state.panY / state.zoom;
      var rx = offX + (vx - bounds.minX) * scale;
      var ry = offY + (vy - bounds.minY) * scale;
      var rw = vw * scale;
      var rh = vh * scale;

      /* Physical minimap draw area — use the container's real client size
         (viewport rect is absolutely positioned inside the .nf-minimap). */
      var mw = container.clientWidth || canvas.width;
      var mh = container.clientHeight || canvas.height;

      /* Effective viewport size inside minimap — never larger than the map */
      var evw = Math.min(rw, mw);
      var evh = Math.min(rh, mh);

      /* Clamp the top-left corner so the viewport rect stays fully on the map.
         When the viewport is bigger than the map, center it on the content. */
      var minLeft = 0, minTop = 0;
      var maxLeft = mw - evw, maxTop = mh - evh;
      var cl = rx, ct = ry;
      if (evw >= mw) cl = (mw - evw) / 2;      /* viewport covers whole width → center */
      else cl = Math.max(minLeft, Math.min(maxLeft, rx));
      if (evh >= mh) ct = (mh - evh) / 2;      /* viewport covers whole height → center */
      else ct = Math.max(minTop, Math.min(maxTop, ry));

      viewport.style.display = 'block';
      viewport.style.left = cl + 'px';
      viewport.style.top = ct + 'px';
      viewport.style.width = Math.max(4, evw) + 'px';
      viewport.style.height = Math.max(4, evh) + 'px';
    }

    /* Click/drag on minimap to navigate */
    var dragging = false;
    function navigateTo(e) {
      var rect = canvas.getBoundingClientRect();
      var mx = e.clientX - rect.left;
      var my = e.clientY - rect.top;
      var bounds = getWorldBounds();
      var bw = bounds.maxX - bounds.minX;
      var bh = bounds.maxY - bounds.minY;
      var scale = Math.min(canvas.width / bw, canvas.height / bh);
      var offX = (canvas.width - bw * scale) / 2;
      var offY = (canvas.height - bh * scale) / 2;
      var cx = (mx - offX) / scale + bounds.minX;
      var cy = (my - offY) / scale + bounds.minY;
      var r = region.getBoundingClientRect();
      state.panX = r.width / 2 - cx * state.zoom;
      state.panY = r.height / 2 - cy * state.zoom;
      applyCanvas();
      scheduleDraw();
    }
    canvas.addEventListener('mousedown', function (e) { dragging = true; navigateTo(e); e.preventDefault(); });
    document.addEventListener('mousemove', function (e) { if (dragging) navigateTo(e); });
    document.addEventListener('mouseup', function () { dragging = false; });

    /* Apply the transform to the content layer — mirrors the canvas controller's apply() */
    function applyCanvas() {
      var c = region.querySelector('.canvas-content-layer');
      if (!c) return;
      c.style.transition = 'transform 0.15s ease-out';
      c.style.transform = 'translate3d(' + state.panX + 'px,' + state.panY + 'px,0) scale(' + state.zoom + ')';
      var label = document.querySelector('.zoom-label');
      if (label) label.textContent = Math.round(state.zoom * 100) + '%';
      if (typeof redrawConnections === 'function') redrawConnections();
      updateReturnPill();
    }

    /* Recenter + zoom so the whole content fits in view */
    function fitToContent() {
      var bounds = getContentBounds();
      var r = region.getBoundingClientRect();
      var bw = bounds.maxX - bounds.minX;
      var bh = bounds.maxY - bounds.minY;
      if (bw <= 0 || bh <= 0) return;
      var zoom = Math.min(r.width / bw, r.height / bh, 1.5);
      state.zoom = Math.max(0.25, Math.min(2, zoom));
      state.panX = r.width / 2 - ((bounds.minX + bounds.maxX) / 2) * state.zoom;
      state.panY = r.height / 2 - ((bounds.minY + bounds.maxY) / 2) * state.zoom;
      applyCanvas();
      scheduleDraw();
    }
    fitBtn.addEventListener('click', function (e) { e.stopPropagation(); fitToContent(); });
    returnPill.addEventListener('click', function () { fitToContent(); });

    /* Show the return pill whenever content is fully outside the current viewport */
    function updateReturnPill() {
      var bounds = getContentBounds();
      var r = region.getBoundingClientRect();
      var vx = -state.panX / state.zoom;
      var vy = -state.panY / state.zoom;
      var vw = r.width / state.zoom;
      var vh = r.height / state.zoom;
      var overlap = !(bounds.maxX < vx || bounds.minX > vx + vw || bounds.maxY < vy || bounds.minY > vy + vh);
      returnPill.classList.toggle('is-visible', !overlap);
    }

    /* Schedule redraws */
    var redrawTimer = null;
    function scheduleDraw() {
      if (redrawTimer) clearTimeout(redrawTimer);
      redrawTimer = setTimeout(function () {
        draw();
        updateReturnPill();
      }, 50);
    }

    /* Node add/remove/move → redraw */
    region.addEventListener('nf-nodes-changed', scheduleDraw);
    if (content) {
      var observer = new MutationObserver(scheduleDraw);
      observer.observe(content, { childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'class'] });
    }

    /* Pan/zoom changes → redraw. The main canvas apply() now calls this hook
       directly on every frame, so we no longer need a polling loop. This hook
       is also used as a safety net for any state change that bypasses apply(). */
    window.__nfMinimapRefresh = scheduleDraw;

    /* Initial draw + resize (draw immediately so count/content are never stale) */
    draw();
    updateReturnPill();
    window.addEventListener('resize', scheduleDraw);
  }

  /* ════════════════════════════════════════
   * Init
   * ════════════════════════════════════════ */
  function init() {
    injectStyles();
    initDotField();
    initContextMenu();
    initCanvasController();
    initConnections();
    /* Fix static connectors after content layer is ready and nodes moved */
    setTimeout(fixStaticConnectors, 100);
    window.addEventListener('resize', function () {
      clearTimeout(window.__nfConnTimer);
      window.__nfConnTimer = setTimeout(fixStaticConnectors, 200);
    });
    standardizeDock();
    ensureZoomToolbar();
    initSliders();
    initStylePicker();
    initGenerationSettings();
    initButtonFeedback();
    initCutTool();
    initAgentPanel();
    initQuickProToggle();
    initLanguageToggle();
    initFloatingBatchGenerate();
    initQuickConnect();
    initMinimap();
    if (typeof lucide !== 'undefined') lucide.createIcons();
    /* Expose state for app-layer use */
    window.nfState = state;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
