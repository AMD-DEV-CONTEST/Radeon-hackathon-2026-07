/* ═══════════════════════════════════════════════════════════════
 * NodeFlow App — main application logic
 * Sits on top of canvas-runtime.js (canvas primitives)
 * and mock-api.js (data layer)
 * ═══════════════════════════════════════════════════════════════ */

(function () {
  var NF = window.NF || (window.NF = {});

  /* ── App State ─────────────────────────────────────────────── */

  var state = {
    mode: 'fast',
    currentModelId: 'sdxl_lightning_4step',
    currentModel: null,
    modelConfig: null,
    currentStyle: 'cyberpunk',
    currentStyleLabel: 'Cyberpunk',
    aspectRatio: '1:1',
    nodes: [],
    connections: [],
    selectedNodeId: null,
    loras: [],
    styles: [],
    nodeCounter: 0
  };

  NF.app = { state: state };

  /* ── Init ──────────────────────────────────────────────────── */

  function init() {
    /* 先自动探测后端: 可达则用真实,否则用 mock (便于本地预览) */
    var detect = NF.api.autoDetect ? NF.api.autoDetect() : Promise.resolve(false);
    detect.then(function (real) {
      if (state) state._backendReal = real;
      loadInitialData();
    }).catch(function () {
      loadInitialData();
    });
  }

  function loadInitialData() {
    /* Load initial data in parallel */
    Promise.all([
      NF.api.getStyles(),
      NF.api.getModels('fast'),
      NF.api.getCurrentModel(),
      NF.api.getLoras()
    ]).then(function (results) {
      var stylesRes = results[0];
      var modelsRes = results[1];
      var modelRes = results[2];
      var lorasRes = results[3];

      if (stylesRes.ok && stylesRes.data.styles) {
        state.styles = stylesRes.data.styles;
        var s = state.styles.find(function (x) { return x.key === state.currentStyle; });
        if (s) state.currentStyleLabel = s.label;
      }
      if (modelRes.ok && modelRes.data.model) {
        state.currentModel = modelRes.data.model;
        state.currentModelId = modelRes.data.model.id;
      }
      if (lorasRes.ok && lorasRes.data.loras) {
        state.loras = lorasRes.data.loras;
      }

      /* Load model config */
      return NF.api.getModelConfig(state.currentModelId);
    }).then(function (cfgRes) {
      if (cfgRes.ok) {
        state.modelConfig = cfgRes.data;
        if (state.modelConfig.recommended_aspect_ratios &&
            state.modelConfig.recommended_aspect_ratios.length > 0) {
          state.aspectRatio = state.modelConfig.recommended_aspect_ratios[0];
        }
      }
      bootstrap();
    }).catch(function (e) {
      console.error('App init failed:', e);
      bootstrap(); /* still render UI even if API fails */
    });
  }

  function bootstrap() {
    buildTopBar();
    buildBottomDock();
    setupCanvasToolbar();
    setupContextMenu();
    setupKeyboard();
    /* Add a default text node so the canvas isn't empty */
    addNode('text', 200, 200);
    /* Re-run fixStaticConnectors if it exists (from runtime) */
    if (typeof window.fixStaticConnectors === 'function') {
      /* skip — we use dynamic connections now */
    }
    /* Notify UI is ready */
    document.dispatchEvent(new CustomEvent('nf-app-ready'));
  }

  /* ── Top Bar ───────────────────────────────────────────────── */

  function buildTopBar() {
    var toggle = document.querySelector('.mode-toggle');
    if (!toggle) return;

    toggle.innerHTML =
      '<button type="button" class="mode-btn ' + (state.mode === 'fast' ? 'is-active' : '') + '" data-mode="fast" role="tab" aria-selected="' + (state.mode === 'fast') + '">Fast</button>' +
      '<button type="button" class="mode-btn ' + (state.mode === 'expert' ? 'is-active' : '') + '" data-mode="expert" role="tab" aria-selected="' + (state.mode === 'expert') + '">Expert</button>';

    toggle.querySelectorAll('.mode-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        switchMode(btn.getAttribute('data-mode'));
      });
    });

    /* Add Store button to top-actions if not present, and always bind it */
    var topActions = document.querySelector('.top-actions');
    if (topActions) {
      var storeBtn = topActions.querySelector('[aria-label="Store"]');
      if (!storeBtn) {
        storeBtn = document.createElement('button');
        storeBtn.type = 'button';
        storeBtn.className = 'icon-btn';
        storeBtn.setAttribute('aria-label', 'Store');
        storeBtn.setAttribute('title', '模型商店');
        storeBtn.innerHTML = '<i data-lucide="package" width="17" height="17"></i>';
        /* Insert before settings */
        var settings = topActions.querySelector('[aria-label="Settings"]');
        if (settings) topActions.insertBefore(storeBtn, settings);
        else topActions.appendChild(storeBtn);
        if (typeof lucide !== 'undefined') lucide.createIcons();
      }
      storeBtn.addEventListener('click', function () { openPanel('store'); });
    }

    /* History button → open history panel */
    var histBtn = topActions.querySelector('[aria-label="History"]');
    if (histBtn) {
      histBtn.addEventListener('click', function () { openPanel('history'); });
    }
  }

  function switchMode(mode) {
    if (state.mode === mode) return;
    state.mode = mode;
    NF.api.setMode(mode);

    /* Update top bar */
    document.querySelectorAll('.mode-btn').forEach(function (b) {
      var isActive = b.getAttribute('data-mode') === mode;
      b.classList.toggle('is-active', isActive);
      b.setAttribute('aria-selected', isActive);
    });

    /* Load models for this mode and switch to first */
    NF.api.getModels(mode).then(function (res) {
      if (res.ok && res.data.models && res.data.models.length > 0) {
        var first = res.data.models[0];
        state.currentModelId = first.id;
        state.currentModel = first;
        /* Load config for new model */
        return NF.api.getModelConfig(first.id);
      }
      return { ok: false };
    }).then(function (cfgRes) {
      if (cfgRes.ok) {
        state.modelConfig = cfgRes.data;
        if (state.modelConfig.recommended_aspect_ratios &&
            state.modelConfig.recommended_aspect_ratios.length > 0) {
          state.aspectRatio = state.modelConfig.recommended_aspect_ratios[0];
        }
      }
      rebuildDock();
      refreshNodesForMode();
    });
  }

  /* ── Bottom Dock ───────────────────────────────────────────── */

  function buildBottomDock() {
    var dock = document.getElementById('floating-control-dock');
    if (!dock) return;
    rebuildDock();
  }

  function rebuildDock() {
    var dock = document.getElementById('floating-control-dock');
    if (!dock) return;

    var ratioChips = buildRatioChips();

    var html =
      /* Style picker */
      '<button type="button" class="nf-dock-style" data-action="style" aria-label="选择风格">' +
        '<span class="nf-dock-style-swatch" aria-hidden="true"></span>' +
        '<span class="nf-dock-style-name">' + state.currentStyleLabel + '</span>' +
        '<i data-lucide="chevron-down" width="14" height="14" style="color:var(--nf-text-3)"></i>' +
      '</button>' +
      '<div class="dock-sep" aria-hidden="true"></div>' +
      /* Aspect ratio chips */
      '<div class="nf-dock-ratios">' + ratioChips + '</div>';

    if (state.mode === 'expert') {
      html +=
        '<div class="dock-sep" aria-hidden="true"></div>' +
        '<button type="button" class="nf-dock-btn" data-action="params">' +
          '<i data-lucide="sliders-horizontal" width="15" height="15"></i>' +
          '<span>参数</span>' +
        '</button>' +
        '<div class="dock-sep" aria-hidden="true"></div>' +
        '<button type="button" class="nf-dock-btn" data-action="lora">' +
          '<i data-lucide="layers" width="15" height="15"></i>' +
          '<span>LoRA</span>' +
          '<span class="nf-dock-badge">' + state.loras.length + '</span>' +
        '</button>';
    }

    html +=
      '<div class="dock-sep" aria-hidden="true"></div>' +
      '<button type="button" class="generate-btn" data-action="generate">' +
        '<i data-lucide="sparkles" width="16" height="16"></i><span>Generate</span>' +
      '</button>';

    dock.innerHTML = html;

    /* Bind actions */
    dock.querySelector('[data-action="style"]').addEventListener('click', function () { openPanel('style'); });
    dock.querySelector('[data-action="generate"]').addEventListener('click', function () { generateSelected(); });
    if (state.mode === 'expert') {
      dock.querySelector('[data-action="params"]').addEventListener('click', function () { openPanel('params'); });
      dock.querySelector('[data-action="lora"]').addEventListener('click', function () { openPanel('lora'); });
    }
    /* Ratio chip clicks */
    dock.querySelectorAll('.nf-ratio-chip').forEach(function (chip) {
      chip.addEventListener('click', function () {
        state.aspectRatio = chip.getAttribute('data-ratio');
        rebuildDock();
      });
    });

    if (typeof lucide !== 'undefined') lucide.createIcons();
  }

  function buildRatioChips() {
    var ratios = [];
    if (state.modelConfig && state.modelConfig.ratio_details) {
      ratios = Object.keys(state.modelConfig.ratio_details);
    } else {
      ratios = ['1:1', '3:4', '4:3', '16:9'];
    }
    return ratios.map(function (r) {
      var isActive = r === state.aspectRatio;
      var notRec = state.modelConfig && state.modelConfig.recommended_aspect_ratios &&
        state.modelConfig.recommended_aspect_ratios.indexOf(r) === -1;
      return '<button type="button" class="nf-ratio-chip' + (isActive ? ' is-active' : '') +
        (notRec ? ' nf-ratio-nonrec' : '') + '" data-ratio="' + r + '" title="' +
        (notRec ? '非推荐比例，可能效果不佳' : r) + '">' + r + '</button>';
    }).join('');
  }

  /* ── Canvas Toolbar ────────────────────────────────────────── */

  function setupCanvasToolbar() {
    /* The toolbar already exists; we add a "+" add-node button if not present */
    var tb = document.querySelector('.canvas-toolbar');
    if (!tb) return;

    /* Add add-node button */
    if (!tb.querySelector('.nf-add-node-btn')) {
      var sep = document.createElement('div');
      sep.className = 'tool-sep';
      sep.setAttribute('aria-hidden', 'true');

      var addBtn = document.createElement('button');
      addBtn.type = 'button';
      addBtn.className = 'tool-btn nf-add-node-btn';
      addBtn.setAttribute('aria-label', 'Add Node');
      addBtn.setAttribute('title', '添加节点');
      addBtn.innerHTML = '<i data-lucide="plus" width="17" height="17"></i>';
      addBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        showAddNodeMenu(e.clientX, e.clientY);
      });
      tb.appendChild(sep);
      tb.appendChild(addBtn);
      if (typeof lucide !== 'undefined') lucide.createIcons();
    }
  }

  /* ── Context Menu (right-click + add node) ────────────────── */

  function setupContextMenu() {
    var region = document.getElementById('excalidraw-canvas-region');
    if (!region) return;

    region.addEventListener('contextmenu', function (e) {
      e.preventDefault();
      e.stopPropagation();
      showAddNodeMenu(e.clientX, e.clientY);
    });

    /* 双击空白处同样打开统一菜单（与右键一致） */
    region.addEventListener('dblclick', function (e) {
      if (e.target.closest('.nf-canvas-node') || e.target.closest('button') || e.target.closest('input') || e.target.closest('[contenteditable]')) return;
      e.preventDefault();
      showAddNodeMenu(e.clientX, e.clientY);
    });
  }

  function showAddNodeMenu(x, y, fromId, reverse) {
    /* Remove existing */
    var old = document.querySelector('.nf-add-node-menu');
    if (old) old.remove();

    /* 屏蔽紧随释放产生的 click，否则菜单一打开就被"点击外部关闭"逻辑关掉 */
    window.__nfSuppressClick = Date.now();

    var menu = document.createElement('div');
    menu.className = 'nf-context-menu nf-add-node-menu';
    menu.style.cssText = 'position:fixed;left:' + x + 'px;top:' + y + 'px;display:flex;max-height:78vh;overflow-y:auto;';
    menu.innerHTML =
      '<div class="nf-ctx-header">添加节点</div>' +
      '<button class="nf-ctx-item" data-type="text"><i data-lucide="type" width="15" height="15"></i><span>文生图节点</span></button>' +
      '<button class="nf-ctx-item" data-type="sketch"><i data-lucide="pencil" width="15" height="15"></i><span>草图节点</span></button>' +
      '<button class="nf-ctx-item" data-type="hd"><i data-lucide="sparkles" width="15" height="15"></i><span>高清图节点</span></button>' +
      '<button class="nf-ctx-item" data-type="video"><i data-lucide="video" width="15" height="15"></i><span>视频生成节点</span></button>' +
      '<button class="nf-ctx-item" data-type="upscale"><i data-lucide="maximize" width="15" height="15"></i><span>超分修复节点</span></button>';

    /* 若从连接点拖出打开的，额外提示会自动连线 */
    if (fromId) {
      var hint = document.createElement('div');
      hint.style.cssText = 'font-size:10px;color:var(--nf-text-3);padding:6px 10px 2px;';
      hint.textContent = '新节点将自动连线';
      menu.insertBefore(hint, menu.firstChild);
    }

    document.body.appendChild(menu);
    if (typeof lucide !== 'undefined') lucide.createIcons();

    menu.querySelectorAll('.nf-ctx-item').forEach(function (item) {
      item.addEventListener('click', function () {
        var region = document.getElementById('excalidraw-canvas-region');
        if (!region) { menu.remove(); return; }
        var r = region.getBoundingClientRect();
        var content = region.querySelector('.canvas-content-layer');
        var cx = x - r.left, cy = y - r.top;
        if (content) {
          var zoom = 1;
          var panX = 0, panY = 0;
          if (window.nfState) {
            zoom = window.nfState.zoom || 1;
            panX = window.nfState.panX || 0;
            panY = window.nfState.panY || 0;
          }
          cx = (cx - panX) / zoom - 160;
          cy = (cy - panY) / zoom - 60;
        }
        var node = addNode(item.getAttribute('data-type'), cx, cy);
        /* 若由连接点拖出打开，自动连线 */
        if (fromId && node && node.id !== fromId) {
          if (reverse) addConnection(node.id, fromId);
          else addConnection(fromId, node.id);
        }
        menu.remove();
      });
    });

    /* 关闭逻辑：点击外部关闭；但屏蔽释放菜单那一刻紧随的 click */
    setTimeout(function () {
      document.addEventListener('click', function closeMenu(e) {
        if (window.__nfSuppressClick && (Date.now() - window.__nfSuppressClick) < 350) return;
        if (!menu.contains(e.target)) {
          menu.remove();
          document.removeEventListener('click', closeMenu);
        }
      });
    }, 10);
  }

  /* ── Nodes ─────────────────────────────────────────────────── */

  function addNode(type, x, y) {
    state.nodeCounter++;
    var id = 'node_' + state.nodeCounter;
    var node = {
      id: id,
      type: type,
      x: x || 200,
      y: y || 200,
      width: 320,
      height: nodeTypeHeight(type),
      prompt: '',
      strength: 0.8,
      resultImage: null,
      resultVideo: null,
      status: 'idle',
      seed: null,
      generationTime: null,
      error: null,
      /* 高清图节点 */
      hdSize: '2K',
      /* 视频节点：MinMax H3 */
      videoDuration: 5,
      videoResolution: '768P',
      videoRatio: '16:9',
      videoAccelerate: true,
      /* 超分节点 */
      upscaleScale: 2,
      upscaleFaceEnhance: true
    };
    state.nodes.push(node);
    renderNode(node);
    /* Auto-select new node */
    selectNode(id);
    return node;
  }

  function nodeTypeHeight(type) {
    switch (type) {
      case 'sketch': return 380;
      case 'video': return 360;
      case 'upscale': return 300;
      case 'hd': return 300;
      default: return 280;
    }
  }

  function nodeMeta(type) {
    switch (type) {
      case 'text': return { label: '文生图', icon: 'type' };
      case 'sketch': return { label: '草图', icon: 'pencil' };
      case 'hd': return { label: '高清图', icon: 'sparkles' };
      case 'video': return { label: '视频生成', icon: 'video' };
      case 'upscale': return { label: '超分修复', icon: 'maximize' };
      default: return { label: '节点', icon: 'square' };
    }
  }

  function renderNode(node) {
    var region = document.getElementById('excalidraw-canvas-region');
    if (!region) return;
    var content = region.querySelector('.canvas-content-layer');
    if (!content) return;

    var el = document.createElement('div');
    el.className = 'nf-canvas-node nf-node-' + node.type;
    el.setAttribute('data-node-id', node.id);
    el.setAttribute('data-type', node.type);
    el.style.cssText = 'position:absolute;left:' + node.x + 'px;top:' + node.y + 'px;width:' + node.width + 'px;';

    var meta = nodeMeta(node.type);
    var typeLabel = meta.label;
    var typeIcon = meta.icon;

    var bodyHtml = '';
    if (node.type === 'text') {
      bodyHtml =
        '<div class="nf-node-body">' +
          '<textarea class="nf-node-prompt" placeholder="描述你想要生成的画面内容，按 Enter 生成..." rows="3">' + node.prompt + '</textarea>' +
        '</div>';
    } else if (node.type === 'sketch') {
      bodyHtml =
        '<div class="nf-node-body">' +
          '<div class="nf-node-sketch-area" data-sketch-for="' + node.id + '">' +
            '<canvas class="nf-sketch-canvas" width="280" height="150"></canvas>' +
          '</div>' +
          '<div class="nf-node-strength">' +
            '<div class="nf-strength-row"><span>强度</span><span class="nf-strength-val">' + node.strength.toFixed(1) + '</span></div>' +
            '<input type="range" class="nf-strength-slider" min="0" max="1" step="0.1" value="' + node.strength + '">' +
          '</div>' +
        '</div>';
    } else if (node.type === 'hd') {
      bodyHtml =
        '<div class="nf-node-body">' +
          '<textarea class="nf-node-prompt" placeholder="描述画面内容，生成高清图..." rows="3">' + node.prompt + '</textarea>' +
          '<div class="nf-node-strength">' +
            '<div class="nf-strength-row"><span>分辨率</span></div>' +
            '<div class="nf-res-row">' +
              '<button type="button" class="nf-chip' + (node.hdSize === '1K' ? ' is-active' : '') + '" data-v="1K">1K</button>' +
              '<button type="button" class="nf-chip' + (node.hdSize === '2K' ? ' is-active' : '') + '" data-v="2K">2K</button>' +
              '<button type="button" class="nf-chip' + (node.hdSize === '4K' ? ' is-active' : '') + '" data-v="4K">4K</button>' +
            '</div>' +
          '</div>' +
        '</div>';
    } else if (node.type === 'video') {
      bodyHtml =
        '<div class="nf-node-body">' +
          '<textarea class="nf-node-prompt" placeholder="描述视频画面内容（支持分镜、镜头运动、音效）..." rows="3">' + node.prompt + '</textarea>' +
          '<div class="nf-node-strength">' +
            '<div class="nf-strength-row"><span>时长</span><span class="nf-strength-val">' + node.videoDuration + 's</span></div>' +
            '<input type="range" class="nf-video-slider" min="4" max="15" step="1" value="' + node.videoDuration + '">' +
          '</div>' +
          '<div class="nf-strength-row" style="margin-top:6px;"><span>分辨率</span></div>' +
          '<div class="nf-res-row">' +
            '<button type="button" class="nf-chip' + (node.videoResolution === '768P' ? ' is-active' : '') + '" data-v="768P">768P</button>' +
            '<button type="button" class="nf-chip' + (node.videoResolution === '2K' ? ' is-active' : '') + '" data-v="2K">2K</button>' +
          '</div>' +
          '<div class="nf-strength-row" style="margin-top:6px;"><span>画幅</span></div>' +
          '<div class="nf-res-row">' +
            '<button type="button" class="nf-chip' + (node.videoRatio === '16:9' ? ' is-active' : '') + '" data-v="16:9">16:9</button>' +
            '<button type="button" class="nf-chip' + (node.videoRatio === '9:16' ? ' is-active' : '') + '" data-v="9:16">9:16</button>' +
            '<button type="button" class="nf-chip' + (node.videoRatio === '1:1' ? ' is-active' : '') + '" data-v="1:1">1:1</button>' +
          '</div>' +
          '<div class="nf-strength-row" style="margin-top:8px;">' +
            '<span>加速生成</span>' +
            '<label class="nf-switch"><input type="checkbox" class="nf-accel-toggle"' + (node.videoAccelerate !== false ? ' checked' : '') + '><i></i></label>' +
          '</div>' +
        '</div>';
    } else if (node.type === 'upscale') {
      bodyHtml =
        '<div class="nf-node-body">' +
          '<div class="nf-strength-row"><span>放大倍数</span></div>' +
          '<div class="nf-res-row">' +
            '<button type="button" class="nf-chip' + (node.upscaleScale === 2 ? ' is-active' : '') + '" data-v="2">2x</button>' +
            '<button type="button" class="nf-chip' + (node.upscaleScale === 4 ? ' is-active' : '') + '" data-v="4">4x</button>' +
          '</div>' +
          '<div class="nf-strength-row" style="margin-top:6px;">' +
            '<span>人脸修复</span>' +
            '<label class="nf-switch"><input type="checkbox" class="nf-face-toggle"' + (node.upscaleFaceEnhance ? ' checked' : '') + '><i></i></label>' +
          '</div>' +
          '<div class="nf-upscale-hint">输入左侧上游节点图片，生成超分修复结果</div>' +
        '</div>';
    }

    var resultHtml = '';
    if (node.resultVideo) {
      if (node.resultVideo.indexOf('data:image/svg') === 0) {
        resultHtml = '<div class="nf-node-result"><img src="' + node.resultVideo + '" alt="video-result" /></div>';
      } else {
        resultHtml = '<div class="nf-node-result"><video src="' + node.resultVideo + '" controls muted loop autoplay playsinline></video></div>';
      }
    } else if (node.resultImage) {
      resultHtml = '<div class="nf-node-result"><img src="' + node.resultImage + '" alt="result" /></div>';
    }

    var foot = '<div class="nf-node-foot">' +
        '<button type="button" class="nf-node-stylebtn" data-action="style">' +
          '<span class="nf-node-styledot"></span>' +
          '<span class="nf-node-stylename">' + state.currentStyleLabel + '</span>' +
        '</button>' +
        '<button type="button" class="nf-node-generate" data-action="generate">' +
          '<i data-lucide="sparkles" width="14" height="14"></i>' +
          '<span>生成</span>' +
        '</button>' +
      '</div>';

    el.innerHTML =
      '<div class="nf-node-head">' +
        '<i data-lucide="' + typeIcon + '" width="14" height="14" class="nf-node-icon"></i>' +
        '<span class="nf-node-label">' + typeLabel + ' 节点</span>' +
        '<button type="button" class="nf-node-delete" aria-label="删除节点" title="删除"><i data-lucide="x" width="14" height="14"></i></button>' +
      '</div>' +
      bodyHtml +
      resultHtml +
      foot +
      /* ports */
      '<div class="nf-node-port nf-port-in" data-port="in"></div>' +
      '<div class="nf-node-port nf-port-out" data-port="out"></div>';

    content.appendChild(el);
    if (typeof lucide !== 'undefined') lucide.createIcons();

    /* Bind interactions */
    bindNodeInteractions(el, node);

    /* If sketch node, init canvas */
    if (node.type === 'sketch') {
      initSketchCanvas(el, node);
    }

    return el;
  }

  function bindNodeInteractions(el, node) {
    var usePointer = typeof window.PointerEvent === 'function';
    /* Delete */
    el.querySelector('.nf-node-delete').addEventListener('click', function (e) {
      e.stopPropagation();
      deleteNode(node.id);
    });

    /* Generate button */
    el.querySelector('[data-action="generate"]').addEventListener('click', function (e) {
      e.stopPropagation();
      generateNode(node.id);
    });

    /* Style button → open style panel */
    el.querySelector('[data-action="style"]').addEventListener('click', function (e) {
      e.stopPropagation();
      selectNode(node.id);
      openPanel('style');
    });

    /* Prompt update */
    var ta = el.querySelector('.nf-node-prompt');
    if (ta) {
      ta.addEventListener('input', function () { node.prompt = ta.value; });
      ta.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          generateNode(node.id);
        }
      });
      ta.addEventListener('click', function (e) { e.stopPropagation(); });
    }

    /* Strength slider */
    var slider = el.querySelector('.nf-strength-slider');
    if (slider) {
      slider.addEventListener('input', function () {
        node.strength = parseFloat(slider.value);
        var val = el.querySelector('.nf-strength-val');
        if (val) val.textContent = node.strength.toFixed(1);
      });
      slider.addEventListener('click', function (e) { e.stopPropagation(); });
    }

    /* Video duration slider */
    var vSlider = el.querySelector('.nf-video-slider');
    if (vSlider) {
      vSlider.addEventListener('input', function () {
        node.videoDuration = parseInt(vSlider.value, 10);
        var val = el.querySelector('.nf-strength-val');
        if (val) val.textContent = node.videoDuration + 's';
      });
      vSlider.addEventListener('click', function (e) { e.stopPropagation(); });
    }

    /* Chip selectors (resolution / scale / ratio) */
    el.querySelectorAll('.nf-chip').forEach(function (chip) {
      chip.addEventListener('click', function (e) {
        e.stopPropagation();
        var v = chip.getAttribute('data-v');
        var row = chip.parentElement;
        row.querySelectorAll('.nf-chip').forEach(function (c) { c.classList.remove('is-active'); });
        chip.classList.add('is-active');
        if (node.type === 'hd') {
          if (v === '1K' || v === '2K' || v === '4K') node.hdSize = v;
        } else if (node.type === 'video') {
          if (v === '768P' || v === '2K') node.videoResolution = v;
          if (v === '16:9' || v === '9:16' || v === '1:1') node.videoRatio = v;
        } else if (node.type === 'upscale') {
          if (v === '2' || v === '4') node.upscaleScale = parseInt(v, 10);
        }
      });
    });

    /* Face enhance toggle */
    var faceToggle = el.querySelector('.nf-face-toggle');
    if (faceToggle) {
      faceToggle.addEventListener('change', function () {
        node.upscaleFaceEnhance = faceToggle.checked;
      });
      faceToggle.addEventListener('click', function (e) { e.stopPropagation(); });
    }

    /* Video accelerate toggle */
    var accelToggle = el.querySelector('.nf-accel-toggle');
    if (accelToggle) {
      accelToggle.addEventListener('change', function () {
        node.videoAccelerate = accelToggle.checked;
      });
      accelToggle.addEventListener('click', function (e) { e.stopPropagation(); });
    }

    /* Select on click */
    el.addEventListener('mousedown', function (e) {
      selectNode(node.id);
    });

    /* Drag node by header — uses Pointer Events + pointer capture so the drag
       keeps working even if the cursor strays outside the node, and is more
       resilient to the preview environment intercepting plain mouse events. */
    var head = el.querySelector('.nf-node-head');
    if (head) {
      var usePointer = typeof window.PointerEvent === 'function';
      function beginDrag(e) {
        if (e.target.closest('.nf-node-delete')) return;
        if (e.button !== undefined && e.button !== 0) return;
        e.preventDefault();
        e.stopPropagation();
        var startX = e.clientX;
        var startY = e.clientY;
        var origX = node.x;
        var origY = node.y;
        var zoom = getCanvasZoom();
        var active = true;

        function onMove(ev) {
          if (!active) return;
          var dx = (ev.clientX - startX) / zoom;
          var dy = (ev.clientY - startY) / zoom;
          node.x = origX + dx;
          node.y = origY + dy;
          el.style.left = node.x + 'px';
          el.style.top = node.y + 'px';
          redrawConnections();
          updateMinimap();
        }
        function onUp() {
          if (!active) return;
          active = false;
          if (usePointer) {
            try { head.releasePointerCapture(e.pointerId); } catch (err) { /* noop */ }
            head.removeEventListener('pointermove', onMove);
            head.removeEventListener('pointerup', onUp);
            head.removeEventListener('pointercancel', onUp);
          } else {
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
          }
        }

        if (usePointer) {
          try { head.setPointerCapture(e.pointerId); } catch (err) { /* noop */ }
          head.addEventListener('pointermove', onMove);
          head.addEventListener('pointerup', onUp);
          head.addEventListener('pointercancel', onUp);
        } else {
          document.addEventListener('mousemove', onMove);
          document.addEventListener('mouseup', onUp);
        }
      }
      head.addEventListener(usePointer ? 'pointerdown' : 'mousedown', beginDrag);
    }

    /* Port interactions */
    var outPort = el.querySelector('.nf-port-out');
    var inPort = el.querySelector('.nf-port-in');
    if (outPort) {
      outPort.addEventListener(usePointer ? 'pointerdown' : 'mousedown', function (e) {
        e.stopPropagation();
        e.preventDefault();
        startConnectionDrag(node.id, e.clientX, e.clientY, e, false);
      });
    }
    if (inPort) {
      /* Dragging outward from the input port also opens the add-node menu,
         and the new node connects INTO this node (new → this). */
      inPort.addEventListener(usePointer ? 'pointerdown' : 'mousedown', function (e) {
        e.stopPropagation();
        e.preventDefault();
        startConnectionDrag(node.id, e.clientX, e.clientY, e, true);
      });
      /* Legacy: dropping a dragged connection onto this input port */
      inPort.addEventListener(usePointer ? 'pointerup' : 'mouseup', function (e) {
        e.stopPropagation();
        e.preventDefault();
        finishConnectionDrag(node.id);
      });
    }
  }

  function getCanvasZoom() {
    var cs = window.nfState || {};
    return cs.zoom || 1;
  }

  /* ── Connection System ─────────────────────────────────────── */

  var _connectionSvg = null;
  var _draggingConn = null; // { fromNodeId, x, y }

  function ensureConnectionLayer() {
    if (_connectionSvg) return _connectionSvg;
    var region = document.getElementById('excalidraw-canvas-region');
    if (!region) return null;
    var content = region.querySelector('.canvas-content-layer');
    if (!content) return null;

    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'nf-connections-svg');
    svg.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;overflow:visible;z-index:4;';
    content.insertBefore(svg, content.firstChild);
    _connectionSvg = svg;
    return svg;
  }

  function getPortPos(nodeId, portType) {
    var el = document.querySelector('[data-node-id="' + nodeId + '"]');
    if (!el) return null;
    var node = state.nodes.find(function (n) { return n.id === nodeId; });
    if (!node) return null;
    var w = node.width || 320;
    var h = el.offsetHeight || 200;
    if (portType === 'out') {
      return { x: node.x + w, y: node.y + h / 2 };
    } else {
      return { x: node.x, y: node.y + h / 2 };
    }
  }

  function bezierPath(x1, y1, x2, y2) {
    var dx = Math.max(40, Math.abs(x2 - x1) * 0.5);
    return 'M ' + x1 + ' ' + y1 + ' C ' + (x1 + dx) + ' ' + y1 + ', ' + (x2 - dx) + ' ' + y2 + ', ' + x2 + ' ' + y2;
  }

  function redrawConnections() {
    var svg = ensureConnectionLayer();
    if (!svg) return;
    /* Clear existing paths */
    while (svg.firstChild) svg.removeChild(svg.firstChild);

    /* Draw existing connections */
    state.connections.forEach(function (conn) {
      var from = getPortPos(conn.from, 'out');
      var to = getPortPos(conn.to, 'in');
      if (!from || !to) return;
      var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', bezierPath(from.x, from.y, to.x, to.y));
      path.setAttribute('fill', 'none');
      path.setAttribute('stroke', 'rgba(255,255,255,0.3)');
      path.setAttribute('stroke-width', '2');
      path.setAttribute('stroke-linecap', 'round');
      svg.appendChild(path);
    });

    /* Draw dragging connection */
    if (_draggingConn) {
      var fromPos = getPortPos(_draggingConn.fromNodeId, _draggingConn.port || 'out');
      if (fromPos) {
        var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', bezierPath(fromPos.x, fromPos.y, _draggingConn.x, _draggingConn.y));
        path.setAttribute('fill', 'none');
        path.setAttribute('stroke', 'rgba(255,255,255,0.6)');
        path.setAttribute('stroke-width', '2');
        path.setAttribute('stroke-dasharray', '6,4');
        path.setAttribute('stroke-linecap', 'round');
        svg.appendChild(path);
      }
    }
  }

  function startConnectionDrag(fromId, clientX, clientY, evt, reverse) {
    var region = document.getElementById('excalidraw-canvas-region');
    if (!region) return;
    var r = region.getBoundingClientRect();
    var zoom = getCanvasZoom();
    var pan = window.nfState || {};
    var srcPort = region.querySelector('[data-node-id="' + fromId + '"] .nf-port-' + (reverse ? 'in' : 'out'));
    var usePointer = typeof window.PointerEvent === 'function' && evt && evt.pointerId !== undefined;

    _draggingConn = {
      fromNodeId: fromId,
      port: reverse ? 'in' : 'out',
      x: (clientX - r.left - (pan.panX || 0)) / zoom,
      y: (clientY - r.top - (pan.panY || 0)) / zoom
    };

    function onMove(ev) {
      if (!_draggingConn) return;
      _draggingConn.x = (ev.clientX - r.left - (pan.panX || 0)) / zoom;
      _draggingConn.y = (ev.clientY - r.top - (pan.panY || 0)) / zoom;
      redrawConnections();
    }
    function onUp(ev) {
      if (usePointer && srcPort) {
        try { srcPort.releasePointerCapture(ev.pointerId); } catch (err) { /* noop */ }
        srcPort.removeEventListener('pointermove', onMove);
        srcPort.removeEventListener('pointerup', onUp);
        srcPort.removeEventListener('pointercancel', onUp);
      } else {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      }
      /* Check if dropped on an input port (only for output-port drags) */
      var target = document.elementFromPoint(ev.clientX, ev.clientY);
      var connected = false;
      if (!reverse && target && target.classList.contains('nf-port-in')) {
        var nodeEl = target.closest('[data-node-id]');
        if (nodeEl) {
          var toId = nodeEl.getAttribute('data-node-id');
          if (toId && toId !== fromId) {
            addConnection(fromId, toId);
            connected = true;
          }
        }
      }
      /* If released on empty canvas (not on an input port), show add node menu */
      var onNode = target && target.closest('.nf-canvas-node');
      if (!connected && !onNode) {
        setTimeout(function () {
          showAddNodeMenu(ev.clientX, ev.clientY, fromId, reverse);
        }, 10);
      }
      _draggingConn = null;
      redrawConnections();
      updateMinimap();
    }

    if (usePointer && srcPort) {
      try { srcPort.setPointerCapture(evt.pointerId); } catch (err) { /* noop */ }
      srcPort.addEventListener('pointermove', onMove);
      srcPort.addEventListener('pointerup', onUp);
      srcPort.addEventListener('pointercancel', onUp);
    } else {
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    }
    redrawConnections();
  }

  function finishConnectionDrag(toId) {
    if (!_draggingConn) return;
    if (_draggingConn.fromNodeId === toId) return;
    addConnection(_draggingConn.fromNodeId, toId);
    _draggingConn = null;
    redrawConnections();
  }

  function addConnection(fromId, toId) {
    /* Check if already exists */
    var exists = state.connections.some(function (c) { return c.from === fromId && c.to === toId; });
    if (exists) return;
    /* Prevent simple cycles */
    if (fromId === toId) return;
    state.connections.push({ from: fromId, to: toId });
    redrawConnections();
    updateMinimap();
  }

  /* 返回 id 的直接上游节点 (to === id), 取最近的连接 */
  function getUpstreamNode(id) {
    var conn = null;
    /* 找最后一条指向 id 的连接 */
    for (var i = state.connections.length - 1; i >= 0; i--) {
      if (state.connections[i].to === id) { conn = state.connections[i]; break; }
    }
    if (!conn) return null;
    return state.nodes.find(function (n) { return n.id === conn.from; }) || null;
  }

  /* 返回上游节点生成的第一张可用图片 (图生视频首帧 / 超分输入) */
  function getUpstreamImage(id) {
    var up = getUpstreamNode(id);
    if (!up) return null;
    if (up.resultImage) return up.resultImage;
    /* 递归向上找更上游的图片 */
    return getUpstreamImage(up.id);
  }

  function initSketchCanvas(el, node) {
    var canvas = el.querySelector('.nf-sketch-canvas');
    if (!canvas) return;
    var ctx = canvas.getContext('2d');
    var drawing = false;

    /* Fill with light gray background */
    ctx.fillStyle = '#2a2a2a';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    canvas.addEventListener('mousedown', function (e) {
      e.stopPropagation();
      drawing = true;
      var rect = canvas.getBoundingClientRect();
      ctx.beginPath();
      ctx.moveTo(e.clientX - rect.left, e.clientY - rect.top);
    });
    canvas.addEventListener('mousemove', function (e) {
      if (!drawing) return;
      var rect = canvas.getBoundingClientRect();
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 2.5;
      ctx.lineCap = 'round';
      ctx.lineTo(e.clientX - rect.left, e.clientY - rect.top);
      ctx.stroke();
    });
    canvas.addEventListener('mouseup', function () { drawing = false; });
    canvas.addEventListener('mouseleave', function () { drawing = false; });

    node.sketchCanvas = canvas;
  }

  function deleteNode(id) {
    var el = document.querySelector('[data-node-id="' + id + '"]');
    if (el) el.remove();
    state.nodes = state.nodes.filter(function (n) { return n.id !== id; });
    state.connections = state.connections.filter(function (c) { return c.from !== id && c.to !== id; });
    if (state.selectedNodeId === id) state.selectedNodeId = null;
    if (typeof redrawConnections === 'function') redrawConnections();
  }

  function selectNode(id) {
    state.selectedNodeId = id;
    document.querySelectorAll('.nf-canvas-node').forEach(function (el) {
      el.classList.toggle('is-selected', el.getAttribute('data-node-id') === id);
    });
  }

  function refreshNodesForMode() {
    /* Update style labels on all nodes */
    document.querySelectorAll('.nf-node-stylename').forEach(function (el) {
      el.textContent = state.currentStyleLabel;
    });
  }

  /* ── Generation ────────────────────────────────────────────── */

  function generateNode(id) {
    var node = state.nodes.find(function (n) { return n.id === id; });
    if (!node) return;
    if (node.status === 'generating') return;

    node.status = 'generating';
    node.error = null;

    var el = document.querySelector('[data-node-id="' + id + '"]');
    if (el) {
      el.classList.add('is-generating');
      /* Remove old result */
      var oldResult = el.querySelector('.nf-node-result');
      if (oldResult) oldResult.remove();
      /* Add loading indicator */
      var loader = document.createElement('div');
      loader.className = 'nf-node-loading';
      loader.innerHTML = '<div class="nf-loader-spinner"></div><span>生成中...</span>';
      var body = el.querySelector('.nf-node-body');
      if (body) body.appendChild(loader);
    }

    var payload = {
      prompt: node.prompt || 'a beautiful scene',
      mode: state.mode,
      style: state.currentStyle,
      aspect_ratio: state.aspectRatio
    };

    if (state.mode === 'expert') {
      if (state.modelConfig) {
        payload.num_inference_steps = state.modelConfig.param_ranges.num_inference_steps.default;
        payload.guidance_scale = state.modelConfig.param_ranges.guidance_scale.default;
      }
      payload.seed = node.seed || undefined;
      payload.negative_prompt = '';
      payload.loras = state.loras.map(function (l) { return { id: l.id, weight: l.weight }; });
    }

    var apiCall;
    if (node.type === 'sketch' && node.sketchCanvas) {
      /* 图生图: 草图 canvas 转 PNG 经 multipart 上传到真实后端 */
      apiCall = new Promise(function (resolve, reject) {
        node.sketchCanvas.toBlob(function (blob) {
          if (!blob) { reject(new Error('无法读取草图')); return; }
          var fd = new FormData();
          fd.append('file', blob, 'sketch.png');
          fd.append('mode', payload.mode || 'fast');
          fd.append('style', payload.style || 'cyberpunk');
          fd.append('aspect_ratio', payload.aspect_ratio || '1:1');
          fd.append('strength', String(node.strength != null ? node.strength : 0.8));
          if (payload.num_inference_steps != null) fd.append('num_inference_steps', String(payload.num_inference_steps));
          if (payload.guidance_scale != null) fd.append('guidance_scale', String(payload.guidance_scale));
          if (payload.seed != null) fd.append('seed', String(payload.seed));
          if (payload.negative_prompt) fd.append('negative_prompt', payload.negative_prompt);
          if (payload.loras && payload.loras.length) {
            var loraIds = payload.loras.map(function (l) { return l.id; });
            var loraW = payload.loras.map(function (l) { return l.weight; }).join(',');
            loraIds.forEach(function (id) { fd.append('loras', id); });
            fd.append('lora_weights', loraW);
          }
          NF.api.generateImg2Img(fd).then(resolve, reject);
        }, 'image/png');
      });
    } else if (node.type === 'hd') {
      /* 高清图: 用高清模型 (HD) 生成高分辨率图像 */
      apiCall = NF.api.generateHd({
        prompt: payload.prompt,
        size: node.hdSize || '2K',
        aspect_ratio: payload.aspect_ratio,
        style: payload.style,
        mode: payload.mode
      });
    } else if (node.type === 'video') {
      /* 视频生成: MinMax H3, 支持文生视频与上游图生视频(首帧) */
      var videoPayload = {
        prompt: payload.prompt,
        duration: node.videoDuration || 5,
        resolution: node.videoResolution || '768P',
        ratio: node.videoRatio || '16:9',
        accelerate: node.videoAccelerate != null ? node.videoAccelerate : true
      };
      /* 若有上游图片节点, 用它作为首帧 (图生视频) */
      var upstream = getUpstreamNode(node.id);
      if (upstream && upstream.resultImage) {
        videoPayload.first_frame_image = upstream.resultImage;
      }
      apiCall = NF.api.generateVideo(videoPayload);
    } else if (node.type === 'upscale') {
      /* 超分修复: 以上游节点图片为输入做放大/修复 */
      var upInput = getUpstreamImage(node.id);
      if (!upInput) {
        node.status = 'idle';
        el.classList.remove('is-generating');
        var loader = el.querySelector('.nf-node-loading');
        if (loader) loader.remove();
        showToast('请先在上游节点生成一张图片');
        return;
      }
      apiCall = NF.api.generateUpscale({
        image: upInput,
        scale: node.upscaleScale || 2,
        face_enhance: node.upscaleFaceEnhance != null ? node.upscaleFaceEnhance : true
      });
    } else {
      apiCall = NF.api.generateText2Img(payload);
    }

    apiCall.then(function (res) {
      node.status = res.ok ? 'done' : 'error';
      if (res.ok) {
        if (res.data.video) {
          node.resultVideo = res.data.video;
          node.resultImage = null;
        } else {
          node.resultImage = res.data.image;
          node.resultVideo = null;
        }
        node.seed = res.data.seed;
        node.generationTime = res.data.generation_time_sec;
        /* Show warnings */
        if (res.data.warnings && res.data.warnings.length > 0) {
          showToast(res.data.warnings[0]);
        }
      } else {
        node.error = res.error ? res.error.message : '生成失败';
        showToast(node.error);
      }
      updateNodeResult(node);
    }).catch(function (e) {
      node.status = 'error';
      node.error = e.message;
      showToast('生成失败: ' + e.message);
      updateNodeResult(node);
    });
  }

  function updateNodeResult(node) {
    var el = document.querySelector('[data-node-id="' + node.id + '"]');
    if (!el) return;
    el.classList.remove('is-generating');

    /* Remove loader */
    var loader = el.querySelector('.nf-node-loading');
    if (loader) loader.remove();

    /* Remove old result */
    var oldResult = el.querySelector('.nf-node-result');
    if (oldResult) oldResult.remove();

    if (node.resultImage) {
      var resultDiv = document.createElement('div');
      resultDiv.className = 'nf-node-result';
      resultDiv.innerHTML = '<img src="' + node.resultImage + '" alt="result" />';
      var body = el.querySelector('.nf-node-body');
      if (body) body.appendChild(resultDiv);
    } else if (node.resultVideo) {
      var vDiv = document.createElement('div');
      vDiv.className = 'nf-node-result';
      /* mock 返回的是 SVG 占位图(非真实 mp4), 用 img 展示; 真实后端返回 mp4 用 video 播放 */
      if (node.resultVideo.indexOf('data:image/svg') === 0) {
        vDiv.innerHTML = '<img src="' + node.resultVideo + '" alt="video-result" />';
      } else {
        vDiv.innerHTML = '<video src="' + node.resultVideo + '" controls muted loop autoplay playsinline></video>';
      }
      var vBody = el.querySelector('.nf-node-body');
      if (vBody) vBody.appendChild(vDiv);
    }

    /* Node height changed — update connections */
    if (typeof redrawConnections === 'function') redrawConnections();
    updateMinimap();
  }

  /* ── Minimap helper ────────────────────────────────────────── */
  function updateMinimap() {
    /* Canvas-runtime minimap uses MutationObserver, so DOM changes auto-trigger redraw.
       We just nudge a style attribute to force a refresh if needed. */
    var region = document.getElementById('excalidraw-canvas-region');
    if (!region) return;
    try {
      region.dispatchEvent(new CustomEvent('nf-nodes-changed'));
    } catch (e) { /* ignore */ }
  }

  function generateSelected() {
    if (state.selectedNodeId) {
      generateNode(state.selectedNodeId);
    } else if (state.nodes.length > 0) {
      generateNode(state.nodes[0].id);
    } else {
      showToast('请先添加一个节点');
    }
  }

  /* ── Panels ────────────────────────────────────────────────── */

  var openPanels = {};

  function openPanel(name) {
    if (openPanels[name]) { closePanel(name); return; }

    var overlay = document.createElement('div');
    overlay.className = 'nf-panel-overlay';
    overlay.setAttribute('data-panel', name);
    overlay.innerHTML = '<div class="nf-panel-container"><div class="nf-panel-content" data-panel-body="' + name + '"></div></div>';

    document.body.appendChild(overlay);

    /* Close on overlay click */
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay || e.target.classList.contains('nf-panel-container')) {
        closePanel(name);
      }
    });

    /* Render panel content */
    renderPanelContent(name, overlay.querySelector('[data-panel-body]'));

    openPanels[name] = overlay;
  }

  function closePanel(name) {
    if (openPanels[name]) {
      openPanels[name].remove();
      delete openPanels[name];
    }
  }

  function renderPanelContent(name, container) {
    var title = '';
    switch (name) {
      case 'style': title = '选择风格'; break;
      case 'params': title = '生成参数'; break;
      case 'lora': title = 'LoRA 管理'; break;
      case 'store': title = '模型商店'; break;
      case 'history': title = '历史记录'; break;
      default: title = '';
    }

    var header = '<div class="nf-panel-head">' +
      '<span class="nf-panel-title">' + title + '</span>' +
      '<button type="button" class="nf-panel-close" aria-label="关闭"><i data-lucide="x" width="16" height="16"></i></button>' +
      '</div>';

    container.innerHTML = header + '<div class="nf-panel-body" data-panel-scroll></div>';
    container.querySelector('.nf-panel-close').addEventListener('click', function () { closePanel(name); });

    var body = container.querySelector('[data-panel-scroll]');

    if (name === 'style') renderStylePanel(body);
    else if (name === 'params') renderParamsPanel(body);
    else if (name === 'lora') renderLoraPanel(body);
    else if (name === 'store') renderStorePanel(body);
    else if (name === 'history') renderHistoryPanel(body);

    if (typeof lucide !== 'undefined') lucide.createIcons();
  }

  function renderStylePanel(body) {
    var styles = state.styles.length > 0 ? state.styles : [
      { key: 'cyberpunk', label: 'Cyberpunk' },
      { key: 'anime', label: 'Anime' },
      { key: 'watercolor', label: 'Watercolor' },
      { key: 'oil_painting', label: 'Oil Painting' },
      { key: '3d_render', label: '3D Render' },
      { key: 'pixel_art', label: 'Pixel Art' },
      { key: 'concept_art', label: 'Concept Art' },
      { key: 'minimalist', label: 'Minimalist' }
    ];

    var grid = document.createElement('div');
    grid.className = 'nf-style-grid';
    styles.forEach(function (s) {
      var isActive = s.key === state.currentStyle;
      var card = document.createElement('button');
      card.type = 'button';
      card.className = 'nf-style-card' + (isActive ? ' is-selected' : '');
      card.setAttribute('data-key', s.key);
      card.innerHTML =
        '<div class="nf-style-swatch-lg"></div>' +
        '<span class="nf-style-label">' + s.label + '</span>';
      card.addEventListener('click', function () {
        state.currentStyle = s.key;
        state.currentStyleLabel = s.label;
        rebuildDock();
        refreshNodesForMode();
        closePanel('style');
        showToast('已选择风格: ' + s.label);
      });
      grid.appendChild(card);
    });
    body.appendChild(grid);
  }

  function renderParamsPanel(body) {
    if (!state.modelConfig) {
      body.innerHTML = '<p style="color:var(--nf-text-3);padding:20px;">加载参数中...</p>';
      return;
    }
    var cfg = state.modelConfig;
    var steps = cfg.param_ranges.num_inference_steps;
    var cfg_ = cfg.param_ranges.guidance_scale;

    var html =
      '<div class="nf-param-section">' +
        '<div class="nf-param-modelinfo">' +
          '<span class="nf-param-modelname">' + (state.currentModel ? state.currentModel.name : state.currentModelId) + '</span>' +
          '<span class="nf-param-archtag">' + (state.currentModel ? state.currentModel.architecture : '') + '</span>' +
        '</div>' +
      '</div>' +
      '<div class="nf-param-section">' +
        '<div class="nf-param-label-row"><span>步数</span><span class="nf-param-value" id="nf-steps-val">' + steps.default + '</span></div>' +
        '<input type="range" class="nf-param-slider" id="nf-steps-slider" min="' + steps.min + '" max="' + steps.max + '" step="' + steps.step + '" value="' + steps.default + '"' + (steps.locked ? ' disabled' : '') + '>' +
        (steps.locked ? '<div class="nf-param-locked"><i data-lucide="lock" width="12" height="12"></i>Fast 模式已锁定</div>' : '') +
      '</div>' +
      '<div class="nf-param-section">' +
        '<div class="nf-param-label-row"><span>CFG Scale</span><span class="nf-param-value" id="nf-cfg-val">' + cfg_.default + '</span></div>' +
        '<input type="range" class="nf-param-slider" id="nf-cfg-slider" min="' + cfg_.min + '" max="' + cfg_.max + '" step="' + cfg_.step + '" value="' + cfg_.default + '"' + (cfg_.locked ? ' disabled' : '') + '>' +
        (cfg_.locked ? '<div class="nf-param-locked"><i data-lucide="lock" width="12" height="12"></i>Fast 模式已锁定</div>' : '') +
      '</div>' +
      '<div class="nf-param-section">' +
        '<div class="nf-param-label-row"><span>种子</span><button class="nf-param-btn-small" id="nf-seed-rand"><i data-lucide="shuffle" width="12" height="12"></i>随机</button></div>' +
        '<input type="number" class="nf-param-input" id="nf-seed-input" placeholder="留空为随机">' +
      '</div>' +
      '<div class="nf-param-section">' +
        '<div class="nf-param-label-row"><span>负向提示</span></div>' +
        '<textarea class="nf-param-textarea" id="nf-neg-input" placeholder="不想出现的内容..." rows="2"></textarea>' +
      '</div>' +
      '<div class="nf-param-section">' +
        '<div class="nf-param-label-row"><span>比例</span></div>' +
        '<div class="nf-ratio-chip-row">';

    var ratios = cfg.ratio_details ? Object.keys(cfg.ratio_details) : [];
    ratios.forEach(function (r) {
      var isActive = r === state.aspectRatio;
      var notRec = cfg.recommended_aspect_ratios.indexOf(r) === -1;
      html += '<button class="nf-ratio-chip' + (isActive ? ' is-active' : '') +
        (notRec ? ' nf-ratio-nonrec' : '') + '" data-ratio="' + r + '">' + r + '</button>';
    });
    html += '</div>';
    html += '<div class="nf-param-hint">非推荐比例可能效果不佳</div>';
    html += '</div>';

    body.innerHTML = html;

    /* Bind interactions */
    var stepsSlider = body.querySelector('#nf-steps-slider');
    var stepsVal = body.querySelector('#nf-steps-val');
    if (stepsSlider) stepsSlider.addEventListener('input', function () { stepsVal.textContent = stepsSlider.value; });

    var cfgSlider = body.querySelector('#nf-cfg-slider');
    var cfgVal = body.querySelector('#nf-cfg-val');
    if (cfgSlider) cfgSlider.addEventListener('input', function () { cfgVal.textContent = cfgSlider.value; });

    body.querySelectorAll('.nf-ratio-chip').forEach(function (chip) {
      chip.addEventListener('click', function () {
        state.aspectRatio = chip.getAttribute('data-ratio');
        body.querySelectorAll('.nf-ratio-chip').forEach(function (c) {
          c.classList.toggle('is-active', c.getAttribute('data-ratio') === state.aspectRatio);
        });
        rebuildDock();
      });
    });

    var seedRand = body.querySelector('#nf-seed-rand');
    var seedInput = body.querySelector('#nf-seed-input');
    if (seedRand && seedInput) {
      seedRand.addEventListener('click', function () {
        seedInput.value = Math.floor(Math.random() * 99999999);
      });
    }
  }

  function renderLoraPanel(body) {
    var loaded = state.loras;
    var html =
      '<div class="nf-lora-section">' +
        '<div class="nf-lora-section-title">已加载</div>';
    if (loaded.length === 0) {
      html += '<div class="nf-empty-hint">暂无已加载 LoRA</div>';
    } else {
      loaded.forEach(function (l) {
        var mismatch = state.currentModel && l.architecture !== state.currentModel.architecture;
        html +=
          '<div class="nf-lora-item' + (mismatch ? ' is-mismatch' : '') + '">' +
            '<div class="nf-lora-item-head">' +
              '<span class="nf-lora-name">' + l.name + '</span>' +
              '<span class="nf-lora-archtag">' + l.architecture + '</span>' +
            '</div>' +
            '<div class="nf-lora-sliderow">' +
              '<input type="range" class="nf-lora-slider" min="0" max="2" step="0.1" value="' + l.weight + '"' + (mismatch ? ' disabled' : '') + '>' +
              '<span class="nf-lora-weight">' + l.weight.toFixed(1) + '</span>' +
            '</div>' +
            (mismatch ? '<div class="nf-lora-warn">架构不匹配</div>' : '') +
            '<button class="nf-lora-unload" data-lora-id="' + l.id + '">卸载</button>' +
          '</div>';
      });
    }
    html += '</div>';

    html +=
      '<div class="nf-lora-section">' +
        '<div class="nf-lora-section-title">加载新 LoRA</div>' +
        '<div class="nf-lora-loadrow">' +
          '<input type="text" class="nf-lora-pathinput" placeholder="LoRA 文件路径或名称">' +
          '<button class="nf-lora-loadbtn">加载</button>' +
        '</div>' +
        '<div class="nf-lora-storelink">或 <a href="#" id="nf-lora-openstore">从商店选择</a></div>' +
      '</div>';

    body.innerHTML = html;

    /* Unload buttons */
    body.querySelectorAll('.nf-lora-unload').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var id = btn.getAttribute('data-lora-id');
        NF.api.unloadLora(id).then(function () {
          state.loras = state.loras.filter(function (l) { return l.id !== id; });
          renderLoraPanel(body);
          rebuildDock();
          showToast('已卸载 LoRA');
        });
      });
    });

    var openStore = body.querySelector('#nf-lora-openstore');
    if (openStore) {
      openStore.addEventListener('click', function (e) {
        e.preventDefault();
        closePanel('lora');
        openPanel('store');
      });
    }
  }

  function renderStorePanel(body) {
    var html =
      '<div class="nf-store-tabs">' +
        '<button class="nf-store-tab is-active" data-tab="models">Checkpoint</button>' +
        '<button class="nf-store-tab" data-tab="loras">LoRA</button>' +
      '</div>' +
      '<div class="nf-store-search">' +
        '<i data-lucide="search" width="14" height="14"></i>' +
        '<input type="text" placeholder="搜索模型或 LoRA...">' +
      '</div>' +
      '<div class="nf-store-grid" data-store-grid></div>';
    body.innerHTML = html;

    var grid = body.querySelector('[data-store-grid]');
    var currentTab = 'models';

    function loadItems() {
      grid.innerHTML = '<div class="nf-loading">加载中...</div>';
      var api = currentTab === 'models' ? NF.api.getStoreModels('hf', 8) : NF.api.getStoreLoras('SDXL 1.0', 8);
      api.then(function (res) {
        if (!res.ok) { grid.innerHTML = '<div class="nf-empty-hint">加载失败</div>'; return; }
        var items = res.data.items || [];
        grid.innerHTML = '';
        items.forEach(function (item) {
          var name = item.name || '';
          var source = item.source || '';
          var downloads = item.downloads || 0;
          var dlText = downloads > 1000000 ? (downloads / 1000000).toFixed(1) + 'M' :
                        downloads > 1000 ? (downloads / 1000).toFixed(0) + 'K' : String(downloads);
          var commercial = item.commercial_use;

          var card = document.createElement('div');
          card.className = 'nf-store-card';
          card.innerHTML =
            '<div class="nf-store-thumb"><i data-lucide="image" width="28" height="28"></i></div>' +
            '<div class="nf-store-info">' +
              '<div class="nf-store-name">' + name + '</div>' +
              '<div class="nf-store-meta">' +
                '<span class="nf-store-source">' + source + '</span>' +
                '<span class="nf-store-downloads"><i data-lucide="download" width="11" height="11"></i>' + dlText + '</span>' +
              '</div>' +
            '</div>' +
            '<div class="nf-store-bottom">' +
              '<span class="nf-license-badge ' + (commercial ? 'is-ok' : 'is-nocom') + '">' +
                '<span class="nf-license-dot"></span>' +
                (commercial ? '可商用' : '仅非商用') +
              '</span>' +
              '<button class="nf-store-download" data-id="' + item.id + '">下载</button>' +
            '</div>';
          grid.appendChild(card);
        });
        if (typeof lucide !== 'undefined') lucide.createIcons();

        /* Download buttons */
        grid.querySelectorAll('.nf-store-download').forEach(function (btn) {
          btn.addEventListener('click', function () {
            btn.textContent = '下载中...';
            btn.disabled = true;
            NF.api.downloadStore('https://example.com/' + btn.getAttribute('data-id'), '/models/test.safetensors', 'model').then(function () {
              btn.textContent = '已下载';
              showToast('下载完成');
            });
          });
        });
      });
    }

    body.querySelectorAll('.nf-store-tab').forEach(function (tab) {
      tab.addEventListener('click', function () {
        body.querySelectorAll('.nf-store-tab').forEach(function (t) { t.classList.remove('is-active'); });
        tab.classList.add('is-active');
        currentTab = tab.getAttribute('data-tab');
        loadItems();
      });
    });

    loadItems();
  }

  function renderHistoryPanel(body) {
    NF.api.getHistory().then(function (res) {
      var items = (res.ok && res.data && res.data.items) ? res.data.items : [];
      if (items.length === 0) {
        body.innerHTML = '<div class="nf-empty-hist"><i data-lucide="history" width="32" height="32"></i><span>暂无生成记录</span></div>';
        if (typeof lucide !== 'undefined') lucide.createIcons();
        return;
      }
      var html = '<div class="nf-hist-list">';
      items.forEach(function (item) {
        var timeStr = new Date(item.timestamp).toLocaleString('zh-CN', { hour12: false });
        html +=
          '<div class="nf-hist-item" data-id="' + item.id + '">' +
            '<div class="nf-hist-thumb"><img src="' + item.image + '" alt=""></div>' +
            '<div class="nf-hist-body">' +
              '<div class="nf-hist-prompt">' + (item.prompt || '(无提示词)') + '</div>' +
              '<div class="nf-hist-meta">' +
                '<span class="nf-hist-mode">' + item.mode + '</span>' +
                '<span class="nf-hist-model">' + (item.model || '') + '</span>' +
                '<span class="nf-hist-time">' + timeStr + '</span>' +
              '</div>' +
            '</div>' +
          '</div>';
      });
      html += '</div>';
      body.innerHTML = html;

      body.querySelectorAll('.nf-hist-item').forEach(function (el) {
        el.addEventListener('click', function () {
          showToast('定位到节点');
        });
      });
    });
    body.innerHTML = '<div class="nf-loading">加载中...</div>';
  }

  /* ── Keyboard shortcuts ────────────────────────────────────── */

  function setupKeyboard() {
    document.addEventListener('keydown', function (e) {
      if (e.target.matches('input, textarea, [contenteditable]')) return;
      /* Generate */
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        generateSelected();
      }
      /* Close panels on Escape */
      if (e.key === 'Escape') {
        Object.keys(openPanels).forEach(closePanel);
      }
    });
  }

  /* ── Expose ───────────────────────────────────────────────── */

  NF.app.init = init;
  NF.app.addNode = addNode;
  NF.app.deleteNode = deleteNode;
  NF.app.generateNode = generateNode;
  NF.app.switchMode = switchMode;
  NF.app.openPanel = openPanel;
  NF.app.closePanel = closePanel;
  NF.app.selectNode = selectNode;
  NF.app.redrawConnections = redrawConnections;
  NF.app.addConnection = addConnection;
  NF.app.showAddNodeMenu = showAddNodeMenu;

  /* Auto-init when DOM is ready */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
