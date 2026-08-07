/* ═══════════════════════════════════════════════════════════════
 * NodeFlow Mock API Layer
 * Implements all 16 backend endpoints per spec §13.
 * Swap NF_API_BASE to point at real backend when deploying.
 * ═══════════════════════════════════════════════════════════════ */

(function () {
  var USE_REAL_API = true; /* set to false to fall back to mock data */
  var API_BASE = '/api';

  /* ── 本地 ComfyUI 配置 ────────────────────────────────────────
   * 视频节点按官方 MiniMax H3 ComfyUI 工作流驱动本地 ComfyUI:
   *   UNETLoader + CLIPLoader + 双VAE + MiniMaxH3ImageToVideo
   *   + SamplerCustomAdvanced + CreateVideo + SaveVideo,
   *   加速 = 插入 Patch Sage Attention KJ 节点 (Sage Attention)。
   * 默认 http://localhost:8188, 可用 NF.api.setComfyUIBase(url) 修改。
   * ComfyUI 不可达时回退到 mock 占位预览。 */
  var COMFYUI_BASE = 'http://localhost:8188';
  var COMFYUI_CLIENT_ID = 'nf-' + Date.now() + '-' + Math.floor(Math.random() * 1e6);
  var USE_COMFYUI = true; /* 优先驱动本地 ComfyUI, 不可达时回退 mock */

  /* ── Mock data ─────────────────────────────────────────────── */

  var MOCK_STYLES = [
    { key: 'cyberpunk',     label: 'Cyberpunk',    prompt_prefix: 'cyberpunk style, ' },
    { key: 'anime',         label: 'Anime',        prompt_prefix: 'anime style, ' },
    { key: 'watercolor',    label: 'Watercolor',   prompt_prefix: 'watercolor painting, ' },
    { key: 'oil_painting',  label: 'Oil Painting', prompt_prefix: 'oil painting, ' },
    { key: '3d_render',     label: '3D Render',    prompt_prefix: '3d render, octane, ' },
    { key: 'pixel_art',     label: 'Pixel Art',    prompt_prefix: 'pixel art, ' },
    { key: 'concept_art',   label: 'Concept Art',  prompt_prefix: 'concept art, ' },
    { key: 'minimalist',    label: 'Minimalist',   prompt_prefix: 'minimalist, clean, ' }
  ];

  var MOCK_MODELS = {
    fast: [
      { id: 'sdxl_lightning_4step', name: 'SDXL Lightning 4-Step',  architecture: 'SDXL', vram_gb: 6.8, license: 'OpenRAIL++M', commercial_use: true },
      { id: 'sdxl_lightning_8step', name: 'SDXL Lightning 8-Step',  architecture: 'SDXL', vram_gb: 7.0, license: 'OpenRAIL++M', commercial_use: true }
    ],
    expert: [
      { id: 'flux2klein_base',        name: 'FLUX.2 Klein Base',       architecture: 'FLUX', vram_gb: 12.4, license: 'Apache 2.0',  commercial_use: true },
      { id: 'flux2klein_distilled',   name: 'FLUX.2 Klein Distilled',  architecture: 'FLUX', vram_gb: 11.8, license: 'Apache 2.0',  commercial_use: true },
      { id: 'noobai_xl',              name: 'NoobAI XL 1.0',           architecture: 'SDXL', vram_gb: 6.9,  license: 'Fair AI',     commercial_use: false },
      { id: 'animagine_xl',           name: 'Animagine XL 4.0',        architecture: 'SDXL', vram_gb: 6.8,  license: 'SDXL License',commercial_use: true },
      { id: 'illustrious_xl',         name: 'Illustrious XL',          architecture: 'SDXL', vram_gb: 7.0,  license: 'Fair AI',     commercial_use: false }
    ]
  };

  var MOCK_MODEL_CONFIGS = {
    sdxl_lightning_4step: {
      param_ranges: {
        num_inference_steps: { min: 1, max: 8,   step: 1, default: 4, locked: true },
        guidance_scale:      { min: 0, max: 2,   step: 0.1, default: 1.0, locked: true }
      },
      recommended_aspect_ratios: ['1:1', '3:4', '4:3', '16:9'],
      ratio_details: {
        '1:1':   { width: 1024, height: 1024, recommended: true },
        '3:4':   { width: 768,  height: 1024, recommended: true },
        '4:3':   { width: 1024, height: 768,  recommended: true },
        '16:9':  { width: 1152, height: 648,  recommended: true },
        '9:16':  { width: 648,  height: 1152, recommended: false }
      }
    },
    sdxl_lightning_8step: {
      param_ranges: {
        num_inference_steps: { min: 1, max: 12,  step: 1, default: 8, locked: true },
        guidance_scale:      { min: 0, max: 3,   step: 0.1, default: 1.5, locked: true }
      },
      recommended_aspect_ratios: ['1:1', '3:4', '4:3', '16:9'],
      ratio_details: {
        '1:1':   { width: 1024, height: 1024, recommended: true },
        '3:4':   { width: 768,  height: 1024, recommended: true },
        '4:3':   { width: 1024, height: 768,  recommended: true },
        '16:9':  { width: 1152, height: 648,  recommended: true },
        '9:16':  { width: 648,  height: 1152, recommended: false }
      }
    },
    flux2klein_base: {
      param_ranges: {
        num_inference_steps: { min: 10,  max: 60,  step: 1, default: 28, locked: false },
        guidance_scale:      { min: 1.0, max: 7.0, step: 0.1, default: 3.5, locked: false }
      },
      recommended_aspect_ratios: ['1:1', '3:4', '4:3', '16:9', '9:16'],
      ratio_details: {
        '1:1':   { width: 1024, height: 1024, recommended: true },
        '3:4':   { width: 768,  height: 1024, recommended: true },
        '4:3':   { width: 1024, height: 768,  recommended: true },
        '16:9':  { width: 1216, height: 680,  recommended: true },
        '9:16':  { width: 680,  height: 1216, recommended: true }
      }
    },
    flux2klein_distilled: {
      param_ranges: {
        num_inference_steps: { min: 4,  max: 20, step: 1, default: 8,  locked: false },
        guidance_scale:      { min: 1,  max: 5,  step: 0.1, default: 2.0, locked: false }
      },
      recommended_aspect_ratios: ['1:1', '3:4', '4:3', '16:9', '9:16'],
      ratio_details: {
        '1:1':   { width: 1024, height: 1024, recommended: true },
        '3:4':   { width: 768,  height: 1024, recommended: true },
        '4:3':   { width: 1024, height: 768,  recommended: true },
        '16:9':  { width: 1216, height: 680,  recommended: true },
        '9:16':  { width: 680,  height: 1216, recommended: true }
      }
    },
    noobai_xl: {
      param_ranges: {
        num_inference_steps: { min: 10, max: 50, step: 1, default: 25, locked: false },
        guidance_scale:      { min: 3,  max: 12, step: 0.5, default: 7,  locked: false }
      },
      recommended_aspect_ratios: ['1:1', '3:4', '4:3', '3:2', '16:9'],
      ratio_details: {
        '1:1':   { width: 1024, height: 1024, recommended: true },
        '3:4':   { width: 768,  height: 1024, recommended: true },
        '4:3':   { width: 1024, height: 768,  recommended: true },
        '3:2':   { width: 1152, height: 768,  recommended: true },
        '16:9':  { width: 1152, height: 648,  recommended: true }
      }
    },
    animagine_xl: {
      param_ranges: {
        num_inference_steps: { min: 10, max: 50, step: 1, default: 28, locked: false },
        guidance_scale:      { min: 4,  max: 12, step: 0.5, default: 7,  locked: false }
      },
      recommended_aspect_ratios: ['1:1', '3:4', '4:3', '3:2', '16:9'],
      ratio_details: {
        '1:1':   { width: 1024, height: 1024, recommended: true },
        '3:4':   { width: 768,  height: 1024, recommended: true },
        '4:3':   { width: 1024, height: 768,  recommended: true },
        '3:2':   { width: 1152, height: 768,  recommended: true },
        '16:9':  { width: 1152, height: 648,  recommended: true }
      }
    },
    illustrious_xl: {
      param_ranges: {
        num_inference_steps: { min: 10, max: 50, step: 1, default: 30, locked: false },
        guidance_scale:      { min: 3,  max: 12, step: 0.5, default: 7.5, locked: false }
      },
      recommended_aspect_ratios: ['1:1', '3:4', '4:3', '3:2', '16:9'],
      ratio_details: {
        '1:1':   { width: 1024, height: 1024, recommended: true },
        '3:4':   { width: 768,  height: 1024, recommended: true },
        '4:3':   { width: 1024, height: 768,  recommended: true },
        '3:2':   { width: 1152, height: 768,  recommended: true },
        '16:9':  { width: 1152, height: 648,  recommended: true }
      }
    }
  };

  var MOCK_LORAS = [
    { id: 'lora_001', name: 'Detail Enhancer',  category: 'Quality',    architecture: 'SDXL', weight: 0.6, loaded: true  },
    { id: 'lora_002', name: 'Cinematic Lights', category: 'Style',      architecture: 'SDXL', weight: 0.8, loaded: true  },
    { id: 'lora_003', name: 'Portrait Pro',     category: 'Style',      architecture: 'FLUX', weight: 1.0, loaded: false },
    { id: 'lora_004', name: 'Anime Lineart',    category: 'Style',      architecture: 'SDXL', weight: 0.5, loaded: false }
  ];

  var MOCK_STORE_MODELS = [
    { id: 'store_m_01', name: 'Realistic Vision v6', source: 'HuggingFace', architecture: 'SDXL', downloads: 1280000, license: 'CreativeML Open RAIL-M', commercial_use: true,  thumbnail: '' },
    { id: 'store_m_02', name: 'DreamShaper XL',    source: 'Civitai',     architecture: 'SDXL', downloads: 890000,  license: 'SDXL License',         commercial_use: true,  thumbnail: '' },
    { id: 'store_m_03', name: 'FLUX.1-dev',        source: 'HuggingFace', architecture: 'FLUX', downloads: 2100000, license: 'FLUX.1-dev Non-Commercial', commercial_use: false, thumbnail: '' },
    { id: 'store_m_04', name: 'Juggernaut XL',     source: 'Civitai',     architecture: 'SDXL', downloads: 560000,  license: 'Fair AI',              commercial_use: false, thumbnail: '' }
  ];

  var MOCK_STORE_LORAS = [
    { id: 'store_l_01', name: 'More Details',         source: 'Civitai', base_model: 'SDXL 1.0', downloads: 420000, license: 'OpenRAIL',      commercial_use: true,  thumbnail: '' },
    { id: 'store_l_02', name: 'Epic Lighting',        source: 'Civitai', base_model: 'SDXL 1.0', downloads: 310000, license: 'CC BY-SA 4.0', commercial_use: true,  thumbnail: '' },
    { id: 'store_l_03', name: 'Add More Details',     source: 'Civitai', base_model: 'FLUX',     downloads: 180000, license: 'Non-Commercial', commercial_use: false, thumbnail: '' },
    { id: 'store_l_04', name: 'Perfect Skin',         source: 'Civitai', base_model: 'SDXL 1.0', downloads: 250000, license: 'OpenRAIL',      commercial_use: true,  thumbnail: '' }
  ];

  var MOCK_HISTORY = []; /* populated by generate calls */

  /* ── Mock helpers ──────────────────────────────────────────── */

  function delay(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function ok(data) { return Promise.resolve({ ok: true, data: data }); }

  function err(msg, code) {
    return Promise.resolve({ ok: false, error: { message: msg, code: code || 500 } });
  }

  var currentModelId = 'sdxl_lightning_4step';
  var currentMode = 'fast';

  /* ── Mock endpoint implementations ─────────────────────────── */

  var mockEndpoints = {
    'GET /api/info': function () {
      return delay(80).then(function () {
        return ok({
          version: '1.0.0-mock',
          backend: 'mock',
          gpu: { name: 'Mock ROCm GPU', vram_total_gb: 24, vram_used_gb: 4.2 },
          current_model: currentModelId,
          current_mode: currentMode
        });
      });
    },

    'GET /api/health': function () {
      return delay(60).then(function () {
        return ok({
          status: 'ready',
          gpu: { utilization: 12, vram_used_gb: 4.2, vram_total_gb: 24, temperature: 58 },
          current_model: currentModelId,
          available_styles: MOCK_STYLES.map(function (s) { return s.key; })
        });
      });
    },

    'GET /api/styles': function () {
      return delay(40).then(function () {
        return ok({ styles: MOCK_STYLES });
      });
    },

    'GET /api/models': function (params) {
      var mode = (params && params.mode) || currentMode;
      var list = MOCK_MODELS[mode] || [];
      return delay(80).then(function () {
        return ok({ models: list.map(function (m) { return Object.assign({}, m, { is_current: m.id === currentModelId }); }) });
      });
    },

    'GET /api/models/current': function () {
      var model = findModel(currentModelId);
      return delay(40).then(function () {
        return ok({ model: model });
      });
    },

    'GET /api/models/{id}/config': function (_, params) {
      var id = params.id;
      var cfg = MOCK_MODEL_CONFIGS[id];
      if (!cfg) return err('Model not found: ' + id, 404);
      return delay(60).then(function () {
        return ok(cfg);
      });
    },

    'POST /api/models/switch': function (body) {
      var id = body.model_id;
      var model = findModel(id);
      if (!model) return err('Model not found: ' + id, 404);
      return delay(1200).then(function () {
        currentModelId = id;
        /* auto-switch mode if needed */
        if (MOCK_MODELS.fast.some(function (m) { return m.id === id; })) currentMode = 'fast';
        else currentMode = 'expert';
        return ok({ model: model });
      });
    },

    'GET /api/loras': function () {
      var loaded = MOCK_LORAS.filter(function (l) { return l.loaded; });
      return delay(50).then(function () {
        return ok({ loras: loaded });
      });
    },

    'POST /api/loras/load': function (body) {
      var target = MOCK_LORAS.find(function (l) { return l.id === body.lora_id || l.name === body.path; });
      if (!target) return err('LoRA not found', 404);
      target.loaded = true;
      if (typeof body.weight === 'number') target.weight = body.weight;
      return delay(600).then(function () { return ok({ lora: target }); });
    },

    'POST /api/loras/unload': function (body) {
      var target = MOCK_LORAS.find(function (l) { return l.id === body.lora_id; });
      if (!target) return err('LoRA not found', 404);
      target.loaded = false;
      return delay(300).then(function () { return ok({ success: true }); });
    },

    'GET /api/store/models': function (params) {
      var limit = (params && params.limit) ? parseInt(params.limit) : 20;
      return delay(200).then(function () {
        return ok({ items: MOCK_STORE_MODELS.slice(0, limit), total: MOCK_STORE_MODELS.length });
      });
    },

    'GET /api/store/loras': function (params) {
      var limit = (params && params.limit) ? parseInt(params.limit) : 20;
      return delay(200).then(function () {
        return ok({ items: MOCK_STORE_LORAS.slice(0, limit), total: MOCK_STORE_LORAS.length });
      });
    },

    'POST /api/store/download': function (body) {
      return delay(1500).then(function () {
        return ok({ success: true, downloaded_path: body.target_path || '/models/downloaded.safetensors' });
      });
    },

    'GET /api/gpu/status': function () {
      return delay(40).then(function () {
        return ok({
          vram_total_gb: 24,
          vram_used_gb: 4.2 + Math.random() * 0.5,
          utilization: 12 + Math.floor(Math.random() * 6),
          temperature: 58 + Math.floor(Math.random() * 4)
        });
      });
    },

    'POST /api/generate/text2img': function (body) {
      /* 优先驱动本地 ComfyUI (SDXL Lightning), 不可达时回退 mock */
      var b = buildText2ImgWorkflow(body);
      return runComfyUIImages(b.graph, b.result).then(function (comfy) {
        if (comfy) {
          MOCK_HISTORY.unshift({
            id: 'gen_' + Date.now(),
            image: comfy.image,
            prompt: body.prompt || '',
            mode: currentMode,
            model: currentModelId,
            style: body.style || '',
            timestamp: Date.now(),
            width: comfy.width,
            height: comfy.height
          });
          if (MOCK_HISTORY.length > 30) MOCK_HISTORY.length = 30;
          return ok(comfy);
        }
        /* ── 回退: mock 占位预览 ── */
        return delay(1500 + Math.random() * 800).then(function () {
          var warnings = [];
          var cfg = MOCK_MODEL_CONFIGS[currentModelId];
          if (cfg && body.aspect_ratio && cfg.recommended_aspect_ratios.indexOf(body.aspect_ratio) === -1) {
            warnings.push('该比例非当前模型推荐比例，可能效果不佳');
          }
          var dims = ratioToDims(body.aspect_ratio, cfg);
          var result = {
            image: generatePlaceholderImage(dims.width, dims.height, body.style || 'none'),
            width: dims.width,
            height: dims.height,
            generation_time_sec: 1.6 + Math.random(),
            warnings: warnings,
            seed: body.seed || Math.floor(Math.random() * 99999999)
          };
          MOCK_HISTORY.unshift({
            id: 'gen_' + Date.now(),
            image: result.image,
            prompt: body.prompt || '',
            mode: currentMode,
            model: currentModelId,
            style: body.style || '',
            timestamp: Date.now(),
            width: result.width,
            height: result.height
          });
          if (MOCK_HISTORY.length > 30) MOCK_HISTORY.length = 30;
          return ok(result);
        });
      });
    },

    'POST /api/generate/img2img': function (body) {
      return delay(1800 + Math.random() * 800).then(function () {
        var warnings = [];
        var cfg = MOCK_MODEL_CONFIGS[currentModelId];
        if (cfg && body.aspect_ratio && cfg.recommended_aspect_ratios.indexOf(body.aspect_ratio) === -1) {
          warnings.push('该比例非当前模型推荐比例，可能效果不佳');
        }
        var dims = ratioToDims(body.aspect_ratio, cfg);
        var result = {
          image: generatePlaceholderImage(dims.width, dims.height, body.style || 'img2img'),
          width: dims.width,
          height: dims.height,
          generation_time_sec: 2.0 + Math.random(),
          warnings: warnings,
          seed: body.seed || Math.floor(Math.random() * 99999999)
        };
        MOCK_HISTORY.unshift({
          id: 'gen_' + Date.now(),
          image: result.image,
          prompt: body.prompt || '[img2img]',
          mode: currentMode,
          model: currentModelId,
          style: body.style || '',
          timestamp: Date.now(),
          width: result.width,
          height: result.height
        });
        if (MOCK_HISTORY.length > 30) MOCK_HISTORY.length = 30;
        return ok(result);
      });
    },

    /* 高清图生成 (HD) — 优先驱动本地 ComfyUI (褶皱 SDXL 生成 + 超分放大) */
    'POST /api/generate/hd': function (body) {
      var b = buildHDWorkflow(body);
      return runComfyUIImages(b.graph, b.result).then(function (comfy) {
        if (comfy) {
          MOCK_HISTORY.unshift({
            id: 'gen_' + Date.now(),
            image: comfy.image,
            prompt: body.prompt || '',
            mode: currentMode,
            model: currentModelId,
            style: body.style || '',
            timestamp: Date.now(),
            width: comfy.width,
            height: comfy.height
          });
          if (MOCK_HISTORY.length > 30) MOCK_HISTORY.length = 30;
          return ok(comfy);
        }
        /* ── 回退: mock 占位预览 ── */
        return delay(2000 + Math.random() * 1000).then(function () {
          var sizeMap = { '1K': 1440, '2K': 2048, '4K': 2880 };
          var side = sizeMap[body.size] || 2048;
          var w = side, h = side;
          if (body.aspect_ratio === '16:9') { w = Math.round(side * 16 / 9); h = side; }
          else if (body.aspect_ratio === '9:16') { w = side; h = Math.round(side * 16 / 9); }
          else if (body.aspect_ratio === '3:4') { w = Math.round(side * 3 / 4); h = side; }
          else if (body.aspect_ratio === '4:3') { w = side; h = Math.round(side * 3 / 4); }
          var result = {
            image: generatePlaceholderImage(w, h, 'HD ' + (body.size || '2K')),
            width: w, height: h,
            generation_time_sec: 2.4 + Math.random(),
            warnings: [],
            seed: Math.floor(Math.random() * 99999999)
          };
          MOCK_HISTORY.unshift({
            id: 'gen_' + Date.now(),
            image: result.image,
            prompt: body.prompt || '',
            mode: currentMode,
            model: currentModelId,
            style: body.style || '',
            timestamp: Date.now(),
            width: result.width,
            height: result.height
          });
          if (MOCK_HISTORY.length > 30) MOCK_HISTORY.length = 30;
          return ok(result);
        });
      });
    },

    /* 视频生成 (MinMax H3) — 优先驱动本地 ComfyUI, 不可达时回退 mock */
    'POST /api/generate/video': function (body) {
      return runComfyUIVideo(body).then(function (comfy) {
        if (comfy) {
          MOCK_HISTORY.unshift({
            id: 'gen_' + Date.now(),
            video: comfy.video,
            prompt: body.prompt || '',
            mode: currentMode,
            model: 'MiniMax-H3',
            style: '',
            timestamp: Date.now(),
            width: comfy.width,
            height: comfy.height
          });
          if (MOCK_HISTORY.length > 30) MOCK_HISTORY.length = 30;
          return ok(comfy);
        }
        /* ── 回退: mock 占位预览 ── */
        var pollMs = (body.accelerate === false) ? 4000 : 2000; /* 加速模式更快返回 */
        var ratio = body.ratio || '16:9';
        var dims = { '16:9': '1280×720', '9:16': '720×1280', '1:1': '960×960', '4:3': '1024×768', '21:9': '1344×576' };
        return delay(pollMs + Math.random() * 800).then(function () {
          var label = 'H3 视频 ' + (body.resolution || '768P') + ' · ' + (body.duration || 5) + 's · ' + (ratio) +
            (body.accelerate !== false ? ' · 加速' : '') + ' · (未连接ComfyUI)';
          var mp4 = generatePlaceholderVideo(dims[ratio] || '1280×720', label);
          var result = {
            video: mp4,
            width: 1280, height: 720,
            duration_sec: body.duration || 5,
            generation_time_sec: (body.accelerate === false ? 6.0 : 3.0) + Math.random(),
            warnings: [],
            model: 'MiniMax-H3'
          };
          MOCK_HISTORY.unshift({
            id: 'gen_' + Date.now(),
            video: result.video,
            prompt: body.prompt || '',
            mode: currentMode,
            model: 'MiniMax-H3',
            style: '',
            timestamp: Date.now(),
            width: result.width,
            height: result.height
          });
          if (MOCK_HISTORY.length > 30) MOCK_HISTORY.length = 30;
          return ok(result);
        });
      });
    },

    /* 超分修复 — 优先驱动本地 ComfyUI (LoadImage → RealESRGAN → Save) */
    'POST /api/generate/upscale': function (body) {
      var scale = body.scale || 2;
      return uploadComfyUIImage(body.image).then(function (inputRef) {
        if (!inputRef) return null; /* 输入图片无法上传 → 回退 */
        var b = buildUpscaleWorkflow(body, inputRef);
        return runComfyUIImages(b.graph, b.result).then(function (comfy) {
          if (comfy) {
            comfy.width = 1024 * scale;
            comfy.height = 1024 * scale;
            comfy.warnings = [];
            MOCK_HISTORY.unshift({
              id: 'gen_' + Date.now(),
              image: comfy.image,
              prompt: '[upscale ' + scale + 'x]',
              mode: currentMode,
              model: 'RealESRGAN_x4plus',
              style: '',
              timestamp: Date.now(),
              width: comfy.width,
              height: comfy.height
            });
            if (MOCK_HISTORY.length > 30) MOCK_HISTORY.length = 30;
            return ok(comfy);
          }
          return null;
        });
      }).then(function (comfy) {
        if (comfy) return comfy;
        /* ── 回退: mock 占位预览 ── */
        return delay(2200 + Math.random() * 1000).then(function () {
          var result = {
            image: generatePlaceholderImage(1024 * scale, 1024 * scale, '超分 ' + scale + 'x' + (body.face_enhance ? ' · 人脸修复' : '')),
            width: 1024 * scale, height: 1024 * scale,
            generation_time_sec: 2.6 + Math.random(),
            warnings: [],
            seed: Math.floor(Math.random() * 99999999)
          };
          return ok(result);
        });
      });
    }
  };

  /* Helper: find model across both modes */
  function findModel(id) {
    var all = MOCK_MODELS.fast.concat(MOCK_MODELS.expert);
    return all.find(function (m) { return m.id === id; }) || null;
  }

  /* Helper: aspect ratio → pixel dims */
  function ratioToDims(ratio, cfg) {
    if (cfg && cfg.ratio_details && cfg.ratio_details[ratio]) {
      return { width: cfg.ratio_details[ratio].width, height: cfg.ratio_details[ratio].height };
    }
    return { width: 1024, height: 1024 };
  }

  /* Helper: generate SVG placeholder data URL */
  function generatePlaceholderImage(w, h, label) {
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + w + '" height="' + h + '">' +
      '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">' +
      '<stop offset="0%" stop-color="#2a2a2a"/><stop offset="100%" stop-color="#1a1a1a"/></linearGradient></defs>' +
      '<rect width="100%" height="100%" fill="url(#g)"/>' +
      '<text x="50%" y="50%" fill="#666" font-family="Inter,sans-serif" font-size="16" text-anchor="middle" dominant-baseline="middle">' +
      (label || 'generated') + ' · ' + w + '×' + h + '</text></svg>';
    return 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svg)));
  }

  /* Helper: generate a tiny animated SVG placeholder pretending to be a video.
     Browsers can't play SVG as <video>, so we return an SVG that the app
     renders inside a <video> fallback is not possible — therefore we produce
     a short animated placeholder gif-like data URL via SVG + <img> path is
     covered by image; for video we simply return a data:image/svg+xml that the
     <video> element shows as poster. To keep mock simple, we return a
     data URL the app can also display as an image. */
  function generatePlaceholderVideo(dimLabel, label) {
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360">' +
      '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">' +
      '<stop offset="0%" stop-color="#1e2630"/><stop offset="100%" stop-color="#10151c"/></linearGradient></defs>' +
      '<rect width="100%" height="100%" fill="url(#g)"/>' +
      '<rect x="270" y="130" width="100" height="60" rx="8" fill="#4a5a6a" opacity="0.9">' +
      '<animate attributeName="ry" values="8;30;8" dur="2s" repeatCount="indefinite"/></rect>' +
      '<circle cx="320" cy="160" r="8" fill="#ffffff" opacity="0.7"/>' +
      '<text x="50%" y="240" fill="#8899aa" font-family="Inter,sans-serif" font-size="16" text-anchor="middle">' +
      (label || 'video') + '</text>' +
      '<text x="50%" y="262" fill="#556677" font-family="Inter,sans-serif" font-size="12" text-anchor="middle">' +
      (dimLabel || '') + '</text></svg>';
    return 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svg)));
  }

  /* ── 本地 ComfyUI 引擎 (MiniMax H3 T2V) ──────────────────────
   * 视频节点按官方 MiniMax H3 T2V 工作流驱动本地 ComfyUI:
   *   UNETLoader + CLIPLoader + 双VAE(视频/音频) + MiniMaxH3ImageToVideo
   *   + BasicGuider + SamplerCustomAdvanced + 双VAEDecode
   *   + CreateVideo + SaveVideo。
   * 加速 = 在 UNETLoader 与 BasicGuider 之间插入
   *   Patch Sage Attention KJ 节点 (Sage Attention), 官方推荐约 2x 提速。
   * 参考: https://docs.comfy.org/tutorials/video/minimax/minimax-h3
   * ComfyUI 不可达时自动回退到 mock 占位预览。 */

  function isComfyUIReachable(timeoutMs) {
    timeoutMs = timeoutMs || 1200;
    var ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, timeoutMs);
    return fetch(COMFYUI_BASE + '/system_stats', { signal: ctrl && ctrl.signal })
      .then(function (r) {
        clearTimeout(timer);
        return r.ok;
      })
      .catch(function () {
        clearTimeout(timer);
        return false;
      });
  }

  /* H3 时长(秒) → 帧数 length: 对齐模型 17帧/块(17k+5) 网格 @24fps */
  function h3FrameLength(seconds) {
    var f = Math.max(5, Math.round(seconds * 24));
    return f + (5 - (f % 17)) % 17;
  }

  /* 分辨率档位 + 比例 → 像素宽高 (短边 768, 对齐 H3 画布) */
  function h3Dims(resolution, ratio) {
    var r = ratio === '9:16' ? '9:16' : (ratio === '1:1' ? '1:1' : '16:9');
    if (String(resolution).indexOf('2K') !== -1) {
      if (r === '9:16') return { width: 1088, height: 1920 };
      if (r === '1:1') return { width: 1088, height: 1088 };
      return { width: 1920, height: 1088 };
    }
    if (r === '9:16') return { width: 768, height: 1344 };
    if (r === '1:1') return { width: 768, height: 768 };
    return { width: 1344, height: 768 };
  }

  function base64ToBlob(b64, mime) {
    var bin = atob(b64);
    var arr = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    return new Blob([arr], { type: mime });
  }

  /* 上传首帧图片到 ComfyUI input 目录, 返回 IMAGE 引用 (如 "xxx.png [input]") */
  function uploadComfyUIImage(dataUrl) {
    if (!dataUrl || dataUrl.indexOf('data:image') !== 0) return Promise.resolve(null);
    var m = dataUrl.match(/^data:([^;,]+);base64,(.*)$/);
    if (!m) return Promise.resolve(null);
    var ext = (m[1].indexOf('png') !== -1) ? 'png' : ((m[1].indexOf('webp') !== -1) ? 'webp' : 'jpg');
    var fd = new FormData();
    fd.append('image', base64ToBlob(m[2], m[1]), 'nf_first_frame.' + ext);
    fd.append('overwrite', 'false');
    fd.append('type', 'input');
    return fetch(COMFYUI_BASE + '/upload/image', { method: 'POST', body: fd })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        return (j && j.name) ? j.name + ' [input]' : null;
      })
      .catch(function () { return null; });
  }

  /* 构建官方 MiniMax H3 T2V 的 API 格式工作流 (ComfyUI /prompt) */
  function buildH3Workflow(payload, firstFrameRef) {
    var prompt = payload.prompt || '';
    var dims = h3Dims(payload.resolution, payload.ratio);
    var length = h3FrameLength(payload.duration || 5);
    var seed = payload.seed || Math.floor(Math.random() * 999999999);

    var graph = {};
    graph[1] = { class_type: 'UNETLoader', inputs: { unet_name: 'minimax_h3_fl2va_pruned_int8_convrot.safetensors' } };
    graph[2] = { class_type: 'CLIPLoader', inputs: { clip_name: 'qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors', type: 'minimax' } };
    graph[3] = { class_type: 'VAELoader', inputs: { vae_name: 'minimax_h3_video_vae_fp16.safetensors' } };
    graph[4] = { class_type: 'VAELoader', inputs: { vae_name: 'minimax_h3_audio_vae_fp32.safetensors' } };
    graph[5] = { class_type: 'RandomNoise', inputs: { noise_seed: seed } };
    graph[6] = { class_type: 'KSamplerSelect', inputs: { sampler_name: 'res_multistep' } };
    graph[7] = { class_type: 'BasicScheduler', inputs: { scheduler: 'simple', steps: 20, denoise: 1.0, model: [1, 0] } };

    var modelRef = [1, 0];
    if (payload.accelerate !== false) {
      /* Sage Attention 包裹 UNET (官方推荐约 2x 提速) */
      graph[15] = { class_type: 'PatchSageAttentionKJ', inputs: { model: [1, 0], sage_attention: 'auto' } };
      modelRef = [15, 0];
    }

    graph[8] = {
      class_type: 'MiniMaxH3ImageToVideo',
      inputs: {
        clip: [2, 0],
        vae: [3, 0],
        first_frame: firstFrameRef || null,
        last_frame: null,
        prompt: prompt,
        width: dims.width,
        height: dims.height,
        length: length
      }
    };
    graph[9] = { class_type: 'BasicGuider', inputs: { model: modelRef, conditioning: [8, 0] } };
    graph[10] = { class_type: 'SamplerCustomAdvanced', inputs: { noise: [5, 0], guider: [9, 0], sampler: [6, 0], sigmas: [7, 0], latent_image: [8, 1] } };
    graph[11] = { class_type: 'VAEDecode', inputs: { samples: [10, 0], vae: [3, 0] } };
    graph[12] = { class_type: 'VAEDecodeAudio', inputs: { samples: [10, 0], vae: [4, 0] } };
    graph[13] = { class_type: 'CreateVideo', inputs: { images: [11, 0], audio: [12, 0], frame_rate: 24, loop_count: 8 } };
    graph[14] = { class_type: 'SaveVideo', inputs: { video: [13, 0], filename_prefix: 'MiniMax_H3' } };

    return graph;
  }

  function submitComfyUIPrompt(graph) {
    return fetch(COMFYUI_BASE + '/prompt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: graph, client_id: COMFYUI_CLIENT_ID })
    }).then(function (r) { return r.json(); });
  }

  function extractComfyVideos(outputs) {
    if (!outputs) return null;
    for (var k in outputs) {
      var o = outputs[k];
      if (!o) continue;
      var arr = o.videos || o.gifs || (o.video ? [o.video] : null) || null;
      if (!arr || !arr.length) continue;
      var f = arr[0];
      if (!f || !(f.filename || f.name)) continue;
      var name = f.filename || f.name;
      var sub = f.subfolder || '';
      var type = f.type || 'output';
      return COMFYUI_BASE + '/view?filename=' + encodeURIComponent(name) +
        '&subfolder=' + encodeURIComponent(sub) + '&type=' + encodeURIComponent(type);
    }
    return null;
  }

  function pollComfyUIHistory(promptId, kind, maxWaitMs) {
    kind = kind || 'video';
    maxWaitMs = maxWaitMs || 900000; /* 视频较慢, 默认最多等 15 分钟 */
    var start = Date.now();
    return new Promise(function (resolve, reject) {
      (function tick() {
        fetch(COMFYUI_BASE + '/history/' + promptId)
          .then(function (r) { return r.json(); })
          .then(function (h) {
            var rec = (h && h[promptId]) || null;
            if (rec && rec.outputs) {
              var url = (kind === 'image') ? extractComfyImages(rec.outputs) : extractComfyVideos(rec.outputs);
              if (url) { resolve(url); return; }
            }
            if (rec && rec.status && rec.status.completed) {
              reject(new Error('ComfyUI 已结束但未找到输出'));
              return;
            }
            if (Date.now() - start > maxWaitMs) { reject(new Error('ComfyUI 生成超时')); return; }
            setTimeout(tick, 2000);
          })
          .catch(function () {
            if (Date.now() - start > maxWaitMs) { reject(new Error('轮询 ComfyUI 失败')); return; }
            setTimeout(tick, 2000);
          });
      })();
    });
  }

  function extractComfyImages(outputs) {
    if (!outputs) return null;
    for (var k in outputs) {
      var o = outputs[k];
      if (!o || !o.images || !o.images.length) continue;
      var f = o.images[0];
      if (!f || !(f.filename || f.name)) continue;
      var name = f.filename || f.name;
      var sub = f.subfolder || '';
      var type = f.type || 'output';
      return COMFYUI_BASE + '/view?filename=' + encodeURIComponent(name) +
        '&subfolder=' + encodeURIComponent(sub) + '&type=' + encodeURIComponent(type);
    }
    return null;
  }

  /* 检查 Sage Attention 加速节点 (PatchSageAttentionKJ) 是否可用。
   * ComfyUI 对不存在的节点类返回 4xx, 对存在的返回 200。 */
  function sageAttentionAvailable() {
    return fetch(COMFYUI_BASE + '/object_info/PatchSageAttentionKJ')
      .then(function (r) { return r.ok; })
      .catch(function () { return false; });
  }

  /* ── 本地 ComfyUI 引擎: 视频 (MiniMax H3 T2V) ──────────────── */
  function runComfyUIVideo(body) {
    return isComfyUIReachable().then(function (ok) {
      if (!ok || !USE_COMFYUI) return null;
      /* 加速节点不可用时自动降级为不加速, 避免工作流校验失败 */
      return sageAttentionAvailable().then(function (hasSage) {
        var effective = Object.assign({}, body);
        if (!hasSage && effective.accelerate) {
          effective.accelerate = false;
        }
        return uploadComfyUIImage(effective.first_frame_image).then(function (ref) {
        var graph = buildH3Workflow(effective, ref);
        return submitComfyUIPrompt(graph).then(function (res) {
          if (!res || !res.prompt_id) {
            var msg = (res && res.error) ? (res.error.message || JSON.stringify(res.error)) : 'ComfyUI 提交失败';
            throw new Error(msg);
          }
          var dims = h3Dims(body.resolution, body.ratio);
          return pollComfyUIHistory(res.prompt_id, 'video', 900000).then(function (videoUrl) {
            return {
              video: videoUrl,
              width: dims.width,
              height: dims.height,
              duration_sec: body.duration || 5,
              generation_time_sec: 0,
              warnings: [],
              model: 'MiniMax-H3',
              seed: body.seed
            };
          });
        });
      });
      });
    }).catch(function () {
      return null; /* 回退 mock 占位 */
    });
  }

  /* ── 本地 ComfyUI 引擎: 图片 (文生图 / 高清 / 超分) ─────────── */
  function runComfyUIImages(graph, result) {
    return isComfyUIReachable(800).then(function (ok) {
      if (!ok || !USE_COMFYUI) return null;
      return submitComfyUIPrompt(graph).then(function (res) {
        if (!res || !res.prompt_id) {
          var msg = (res && res.error) ? (res.error.message || JSON.stringify(res.error)) : 'ComfyUI 提交失败';
          throw new Error(msg);
        }
        return pollComfyUIHistory(res.prompt_id, 'image', 300000).then(function (url) {
          result.image = url;
          result.generation_time_sec = 0;
          return result;
        });
      });
    }).catch(function () {
      return null; /* 回退 mock 占位 */
    });
  }

  /* 文生图: SDXL Lightning 原生工作流 (UNETLoader + DualCLIPLoader + KSampler) */
  function buildText2ImgWorkflow(body) {
    var cfg = MOCK_MODEL_CONFIGS[currentModelId];
    var dims = ratioToDims(body.aspect_ratio, cfg);
    var steps = 4, cfgVal = 1.0;
    if (cfg && cfg.param_ranges) {
      var pr = cfg.param_ranges;
      if (pr.num_inference_steps && pr.num_inference_steps.default != null) steps = pr.num_inference_steps.default;
      if (pr.guidance_scale && pr.guidance_scale.default != null) cfgVal = pr.guidance_scale.default;
    }
    var seed = body.seed || Math.floor(Math.random() * 999999999);
    var style = null;
    if (body.style) style = MOCK_STYLES.find(function (s) { return s.key === body.style; });
    var prompt = ((style && style.prompt_prefix) ? style.prompt_prefix : '') + (body.prompt || '');
    var graph = {};
    graph[1] = { class_type: 'UNETLoader', inputs: { unet_name: 'sdxl_lightning_4step.safetensors' } };
    graph[2] = { class_type: 'DualCLIPLoader', inputs: { clip_name1: 'clip_l.safetensors', clip_name2: 'clip_g.safetensors', type: 'sdxl' } };
    graph[3] = { class_type: 'VAELoader', inputs: { vae_name: 'sdxl_vae.safetensors' } };
    graph[4] = { class_type: 'EmptyLatentImage', inputs: { width: dims.width, height: dims.height, batch_size: 1 } };
    graph[5] = { class_type: 'CLIPTextEncode', inputs: { text: prompt, clip: [2, 0] } };
    graph[6] = { class_type: 'CLIPTextEncode', inputs: { text: '', clip: [2, 0] } };
    graph[7] = { class_type: 'KSampler', inputs: { model: [1, 0], positive: [5, 0], negative: [6, 0], latent_image: [4, 0], seed: seed, steps: steps, cfg: cfgVal, sampler_name: 'dpmpp_sde', scheduler: 'karras', denoise: 1.0 } };
    graph[8] = { class_type: 'VAEDecode', inputs: { samples: [7, 0], vae: [3, 0] } };
    graph[9] = { class_type: 'SaveImage', inputs: { images: [8, 0], filename_prefix: 'nf_text2img' } };
    return { graph: graph, result: { width: dims.width, height: dims.height, warnings: [], model: currentModelId, seed: seed } };
  }

  /* 高清图: 基础 SDXL 生成 → RealESRGAN×4 放大 → 缩放到目标尺寸 */
  function buildHDWorkflow(body) {
    var sizeMap = { '1K': 1440, '2K': 2048, '4K': 2880 };
    var side = sizeMap[body.size] || 2048;
    var w = side, h = side;
    var ar = body.aspect_ratio;
    if (ar === '16:9') { w = Math.round(side * 16 / 9); h = side; }
    else if (ar === '9:16') { w = side; h = Math.round(side * 16 / 9); }
    else if (ar === '3:4') { w = Math.round(side * 3 / 4); h = side; }
    else if (ar === '4:3') { w = side; h = Math.round(side * 3 / 4); }
    var seed = body.seed || Math.floor(Math.random() * 999999999);
    var style = null;
    if (body.style) style = MOCK_STYLES.find(function (s) { return s.key === body.style; });
    var prompt = ((style && style.prompt_prefix) ? style.prompt_prefix : '') + (body.prompt || '');
    var graph = {};
    graph[1] = { class_type: 'UNETLoader', inputs: { unet_name: 'sdxl_lightning_4step.safetensors' } };
    graph[2] = { class_type: 'DualCLIPLoader', inputs: { clip_name1: 'clip_l.safetensors', clip_name2: 'clip_g.safetensors', type: 'sdxl' } };
    graph[3] = { class_type: 'VAELoader', inputs: { vae_name: 'sdxl_vae.safetensors' } };
    graph[4] = { class_type: 'EmptyLatentImage', inputs: { width: 1024, height: 1024, batch_size: 1 } };
    graph[5] = { class_type: 'CLIPTextEncode', inputs: { text: prompt, clip: [2, 0] } };
    graph[6] = { class_type: 'CLIPTextEncode', inputs: { text: 'lowres, blurry, jpeg artifacts', clip: [2, 0] } };
    graph[7] = { class_type: 'KSampler', inputs: { model: [1, 0], positive: [5, 0], negative: [6, 0], latent_image: [4, 0], seed: seed, steps: 4, cfg: 1.0, sampler_name: 'dpmpp_sde', scheduler: 'karras', denoise: 1.0 } };
    graph[8] = { class_type: 'VAEDecode', inputs: { samples: [7, 0], vae: [3, 0] } };
    graph[9] = { class_type: 'UpscaleModelLoader', inputs: { model_name: 'RealESRGAN_x4plus.pth' } };
    graph[10] = { class_type: 'ImageUpscaleWithModel', inputs: { upscale_model: [9, 0], image: [8, 0] } };
    graph[11] = { class_type: 'ImageScale', inputs: { image: [10, 0], width: w, height: h, upscale_method: 'lanczos', crop: 'disabled' } };
    graph[12] = { class_type: 'SaveImage', inputs: { images: [11, 0], filename_prefix: 'nf_hd' } };
    return { graph: graph, result: { width: w, height: h, warnings: [], model: currentModelId, seed: seed } };
  }

  /* 超分修复: LoadImage → RealESRGAN×4 → 按倍数缩放 → SaveImage */
  function buildUpscaleWorkflow(body, inputRef) {
    var scale = body.scale || 2;
    var graph = {};
    graph[1] = { class_type: 'LoadImage', inputs: { image: inputRef } };
    graph[2] = { class_type: 'UpscaleModelLoader', inputs: { model_name: 'RealESRGAN_x4plus.pth' } };
    graph[3] = { class_type: 'ImageUpscaleWithModel', inputs: { upscale_model: [2, 0], image: [1, 0] } };
    graph[4] = { class_type: 'ImageScaleBy', inputs: { image: [3, 0], upscale_by: scale, upscale_method: 'lanczos' } };
    graph[5] = { class_type: 'SaveImage', inputs: { images: [4, 0], filename_prefix: 'nf_upscale' } };
    return { graph: graph, result: { warnings: [], model: 'RealESRGAN_x4plus', seed: body.seed || Math.floor(Math.random() * 999999999) } };
  }

  /* ── HTTP transport (real API) ─────────────────────────────── */

  function httpRequest(method, path, body, params, isForm) {
    var url = API_BASE + path;
    if (params && Object.keys(params).length) {
      var qs = Object.keys(params).map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(params[k]); }).join('&');
      url += '?' + qs;
    }
    var opts = { method: method };
    if (isForm && typeof FormData !== 'undefined' && body instanceof FormData) {
      /* FormData: 不手动设置 Content-Type (浏览器自动带 boundary) */
      opts.body = body;
    } else {
      opts.headers = { 'Content-Type': 'application/json' };
      if (body) opts.body = JSON.stringify(body);
    }
    return fetch(url, opts).then(function (r) {
      return r.json().then(function (data) {
        return { ok: r.ok, data: data, status: r.status };
      });
    }).catch(function (e) {
      return { ok: false, error: { message: 'Network error: ' + e.message, code: 0 } };
    });
  }

  /* ── Real-backend field adapters ───────────────────────────── */

  /* 架构小写转原稿期望的大写标签 */
  function archLabel(arch) {
    var a = String(arch || '').toLowerCase();
    if (a.indexOf('flux') !== -1) return 'FLUX';
    if (a.indexOf('sdxl') !== -1 || a === 'sd') return 'SDXL';
    return arch || '';
  }

  /* 真后端 models 条目 → 原稿期望结构 */
  function adaptModel(m) {
    return {
      id: m.id,
      name: m.name,
      architecture: archLabel(m.architecture),
      vram_gb: m.vram_gb,
      license: (m.license_info && m.license_info.name) || m.license || '',
      commercial_use: !!m.commercial_use,
      license_info: m.license_info || {},
    };
  }

  /* 真后端 config → 原稿期望 (补充 default/step, ratio_details 转对象) */
  function adaptConfig(cfg) {
    var src = cfg || {};
    var pr = src.param_ranges || {};
    function fillRange(r, def) {
      r = r || {};
      return {
        min: r.min != null ? r.min : 0,
        max: r.max != null ? r.max : 100,
        step: r.step != null ? r.step : 1,
        default: r.default != null ? r.default : (def != null ? def : (r.max != null ? r.max : 4)),
        locked: !!r.locked,
      };
    }
    var defaults = src.default_params || {};
    /* 真后端用 supported_ratios;mock 用 recommended_aspect_ratios,两者都兜底 */
    var ratios = src.supported_ratios || src.recommended_aspect_ratios || [];
    var ratioObj = {};
    var rd = src.ratio_details;
    if (Array.isArray(rd)) {
      /* 真后端: ratio_details 是数组 */
      rd.forEach(function (r) {
        if (r && r.ratio) ratioObj[r.ratio] = { width: r.width, height: r.height, recommended: r.recommended };
      });
    } else if (rd && typeof rd === 'object') {
      /* mock: ratio_details 已是 { ratio: {width,height,recommended} } */
      ratioObj = rd;
    }
    /* 若 ratio_details 数组缺失,用 supported_ratios 兜底 */
    if (Object.keys(ratioObj).length === 0) {
      var RATIO_DIMS = { '1:1':[1024,1024], '3:4':[768,1024], '4:3':[1024,768], '3:2':[1152,768], '16:9':[1152,648], '9:16':[648,1152] };
      ratios.forEach(function (r) {
        var d = RATIO_DIMS[r] || [1024, 1024];
        ratioObj[r] = { width: d[0], height: d[1], recommended: true };
      });
    }
    /* 推荐比例: 优先从 ratio_details 的 recommended 标志推导 (真后端数组含此标志);
       若均无标志(mock 纯列表场景),退回 supported/recommended 列表本身 */
    var recList = Object.keys(ratioObj).filter(function (k) {
      return ratioObj[k] && ratioObj[k].recommended !== false;
    });
    if (recList.length === 0) recList = ratios.slice();
    return {
      param_ranges: {
        num_inference_steps: fillRange(pr.num_inference_steps, defaults.num_inference_steps),
        guidance_scale: fillRange(pr.guidance_scale, defaults.guidance_scale),
        strength: fillRange(pr.strength, defaults.strength != null ? defaults.strength : 0.8),
      },
      recommended_aspect_ratios: recList,
      ratio_details: ratioObj,
    };
  }

  /* 真后端 loras 字典 → 原稿期望数组 */
  function adaptLoras(loras) {
    /* loras 形如 { id: {path, weight} } */
    if (!loras || typeof loras !== 'object') return [];
    return Object.keys(loras).map(function (id) {
      var info = loras[id] || {};
      var path = info.path || id;
      var name = path.split('/').pop() || id;
      var lower = path.toLowerCase();
      return {
        id: id,
        name: name,
        path: path,
        weight: info.weight != null ? info.weight : 0.8,
        architecture: lower.indexOf('flux') !== -1 ? 'FLUX' : 'SDXL',
        category: 'general_quality',
        loaded: true,
      };
    });
  }

  /* 真后端生成响应 → 原稿期望 (补 seed) */
  function adaptGen(resp) {
    return {
      image: resp.image,
      video: resp.video,
      model: resp.model,
      duration_sec: resp.duration_sec,
      seed: resp.seed != null ? resp.seed : Math.floor(Math.random() * 99999999),
      generation_time_sec: resp.generation_time_sec,
      warnings: resp.warnings || [],
      width: resp.width,
      height: resp.height,
    };
  }

  /* ── Public API ────────────────────────────────────────────── */

  var NF = window.NF || (window.NF = {});

  function apiCall(method, path, body, params) {
    if (USE_REAL_API) return httpRequest(method, path, body, params);
    return mockCall(method, path, body, params);
  }

  function mockCall(method, path, body, params) {
    var key = method + ' ' + API_BASE + path;
    var handler = mockEndpoints[key];
    if (!handler) {
      var fullPath = API_BASE + path;
      for (var pattern in mockEndpoints) {
        var parts = pattern.split(' ');
        var m = parts[0], p = parts[1];
        if (m !== method) continue;
        var regex = new RegExp('^' + p.replace(/\{(\w+)\}/g, '([^/]+)') + '$');
        var match = fullPath.match(regex);
        if (match) {
          var paramNames = (p.match(/\{\w+\}/g) || []).map(function (s) { return s.slice(1, -1); });
          var pathParams = {};
          paramNames.forEach(function (name, i) { pathParams[name] = match[i + 1]; });
          return mockEndpoints[pattern](body, pathParams, params);
        }
      }
      return err('Endpoint not found: ' + method + ' ' + path, 404);
    }
    return handler(body, {}, params);
  }

  NF.api = {
    getInfo: function () {
      return apiCall('GET', '/info');
    },
    getHealth: function () {
      return apiCall('GET', '/health');
    },
    getStyles: function () {
      return apiCall('GET', '/styles');
    },
    getModels: function (mode) {
      return apiCall('GET', '/models', null, { mode: mode }).then(function (res) {
        if (!res.ok || !res.data) return res;
        var models = (res.data.models || []).map(adaptModel);
        return { ok: true, data: { models: models } };
      });
    },
    getCurrentModel: function () {
      return apiCall('GET', '/models/current').then(function (res) {
        if (!res.ok || !res.data) return res;
        var cur = res.data.current || res.data.model_id || {};
        var model = typeof cur === 'object' ? adaptModel(cur) : { id: res.data.current || res.data.model_id };
        return { ok: true, data: { model: model } };
      });
    },
    getModelConfig: function (id) {
      return apiCall('GET', '/models/' + id + '/config').then(function (res) {
        if (!res.ok || !res.data) return res;
        var cfg = res.data.config || res.data;
        return { ok: true, data: adaptConfig(cfg) };
      });
    },
    switchModel: function (id) {
      return apiCall('POST', '/models/switch', { model_id: id }).then(function (res) {
        if (!res.ok) return res;
        return { ok: true, data: { model: { id: id } } };
      });
    },
    getLoras: function () {
      return apiCall('GET', '/loras').then(function (res) {
        if (!res.ok || !res.data) return res;
        return { ok: true, data: { loras: adaptLoras(res.data.loras) } };
      });
    },
    loadLora: function (path, w) {
      return apiCall('POST', '/loras/load', { path: path, weight: w });
    },
    unloadLora: function (loraId) {
      return apiCall('POST', '/loras/unload', { lora_id: loraId });
    },
    getStoreModels: function (src, limit) {
      return apiCall('GET', '/store/models', null, { source: src || 'hf', limit: limit || 20 }).then(function (res) {
        if (!res.ok || !res.data) return res;
        var items = (res.data.models || res.data.items || []).map(function (m) {
          var lic = (m.license_info && m.license_info.name) || m.license;
          var commercial = m.commercial_use;
          if (commercial === 'conditional') commercial = true;
          return {
            id: m.id || m.name,
            name: m.name || '',
            source: res.data.source || m.source || src || 'hf',
            architecture: archLabel(m.architecture),
            downloads: m.downloads || 0,
            license: lic,
            commercial_use: !!commercial,
            thumbnail: '',
          };
        });
        return { ok: true, data: { items: items } };
      });
    },
    getStoreLoras: function (base, limit) {
      return apiCall('GET', '/store/loras', null, { source: 'civitai', base_model: base || 'SDXL 1.0', limit: limit || 20 }).then(function (res) {
        if (!res.ok || !res.data) return res;
        var items = (res.data.loras || res.data.items || []).map(function (l) {
          var commercial = l.commercial_use;
          if (commercial === 'conditional') commercial = true;
          return {
            id: l.id || l.name,
            name: l.name || '',
            source: 'Civitai',
            base_model: l.base_model || base || 'SDXL 1.0',
            downloads: l.downloads || 0,
            license: l.license,
            commercial_use: !!commercial,
            thumbnail: '',
          };
        });
        return { ok: true, data: { items: items } };
      });
    },
    downloadStore: function (url, tp, ty) {
      return apiCall('POST', '/store/download', { url: url, target_path: tp, type: ty });
    },
    getGpuStatus: function () {
      return apiCall('GET', '/gpu/status');
    },
    generateText2Img: function (payload) {
      return apiCall('POST', '/generate/text2img', payload).then(function (res) {
        if (!res.ok) return res;
        return { ok: true, data: adaptGen(res.data) };
      });
    },
    generateImg2Img: function (payload) {
      if (payload instanceof FormData) {
        if (!USE_REAL_API) {
          /* mock 模式: 从 FormData 提取字段,返回占位图 (本地预览也能出图) */
          var style = payload.get('style') || 'img2img';
          var ratio = payload.get('aspect_ratio') || '1:1';
          var mode = payload.get('mode') || currentMode;
          return delay(1800 + Math.random() * 800).then(function () {
            var cfg = MOCK_MODEL_CONFIGS[currentModelId];
            var dims = ratioToDims(ratio, cfg);
            var result = {
              image: generatePlaceholderImage(dims.width, dims.height, style),
              width: dims.width,
              height: dims.height,
              generation_time_sec: 2.0 + Math.random(),
              warnings: [],
              seed: Math.floor(Math.random() * 99999999)
            };
            MOCK_HISTORY.unshift({
              id: 'gen_' + Date.now(),
              image: result.image,
              prompt: '[img2img]',
              mode: mode,
              model: currentModelId,
              style: style,
              timestamp: Date.now(),
              width: result.width,
              height: result.height
            });
            if (MOCK_HISTORY.length > 30) MOCK_HISTORY.length = 30;
            return { ok: true, data: result };
          });
        }
        return httpRequest('POST', '/generate/img2img', payload, null, true).then(function (res) {
          if (!res.ok) return res;
          return { ok: true, data: adaptGen(res.data) };
        });
      }
      return Promise.reject(new Error('img2img requires a FormData payload'));
    },
    generateHd: function (payload) {
      return apiCall('POST', '/generate/hd', payload).then(function (res) {
        if (!res.ok) return res;
        return { ok: true, data: adaptGen(res.data) };
      });
    },
    generateVideo: function (payload) {
      return apiCall('POST', '/generate/video', payload).then(function (res) {
        if (!res.ok) return res;
        return { ok: true, data: adaptGen(res.data) };
      });
    },
    generateUpscale: function (payload) {
      return apiCall('POST', '/generate/upscale', payload).then(function (res) {
        if (!res.ok) return res;
        return { ok: true, data: adaptGen(res.data) };
      });
    },
    getHistory: function () {
      return Promise.resolve({ ok: true, data: { items: MOCK_HISTORY } });
    },

    /* ── 本地 ComfyUI 配置 ─────────────────────────────────────── */
    setComfyUIBase: function (url) {
      if (url) COMFYUI_BASE = String(url).replace(/\/+$/, '');
      return COMFYUI_BASE;
    },
    getComfyUIBase: function () { return COMFYUI_BASE; },
    setComfyUIEnabled: function (on) { USE_COMFYUI = !!on; return USE_COMFYUI; },
    isComfyUIReachable: isComfyUIReachable
  };

  NF.api.useRealBackend = function (baseUrl) {
    USE_REAL_API = true;
    API_BASE = baseUrl || '/api';
  };

  NF.api.useMock = function () {
    USE_REAL_API = false;
  };

  /* 自动探测后端: 可达则用真实,否则回退 mock (本地无后端时也能预览完整功能) */
  NF.api.autoDetect = function (timeoutMs) {
    timeoutMs = timeoutMs || 1500;
    var ctrl;
    if (typeof AbortController !== 'undefined') ctrl = new AbortController();
    var timer = setTimeout(function () {
      if (ctrl) ctrl.abort();
    }, timeoutMs);
    return fetch(API_BASE + '/health', { signal: ctrl && ctrl.signal })
      .then(function (r) {
        clearTimeout(timer);
        USE_REAL_API = r.ok;
        return r.ok;
      })
      .catch(function () {
        clearTimeout(timer);
        USE_REAL_API = false;
        return false;
      });
  };

  NF.api.setMode = function (mode) { currentMode = mode; };
  NF.api.getMode = function () { return currentMode; };
})();
