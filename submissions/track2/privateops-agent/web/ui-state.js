(function (root) {
  const THEME_KEY = "privateops.theme";
  const PROVIDER_KEY = "privateops.provider";
  const PROVIDERS_KEY = "privateops.providers";
  const EMPTY_PROVIDER = Object.freeze({endpoint: "", model: "", apiKey: "", remember: false});
  const LOCAL_PROVIDER = Object.freeze({
    endpoint: "http://127.0.0.1:8000/v1/chat/completions",
    model: "Qwen/Qwen2.5-7B-Instruct",
    apiKey: "",
  });

  function normalizeTheme(theme) {
    return theme === "light" ? "light" : "dark";
  }

  function readTheme(storage) {
    try {
      return normalizeTheme(storage?.getItem(THEME_KEY));
    } catch (_error) {
      return "dark";
    }
  }

  function writeTheme(storage, theme) {
    const normalized = normalizeTheme(theme);
    try {
      storage?.setItem(THEME_KEY, normalized);
    } catch (_error) {
      // Hardened browser contexts keep the selected theme for this session only.
    }
    return normalized;
  }

  function normalizeProvider(config = {}) {
    return {
      endpoint: typeof config.endpoint === "string" ? config.endpoint : "",
      model: typeof config.model === "string" ? config.model : "",
      apiKey: typeof config.apiKey === "string" ? config.apiKey : "",
    };
  }

  function readProviderConfig(storage) {
    try {
      const raw = storage?.getItem(PROVIDER_KEY);
      if (!raw) return {...EMPTY_PROVIDER};
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return {...EMPTY_PROVIDER};
      return {...normalizeProvider(parsed), remember: true};
    } catch (_error) {
      return {...EMPTY_PROVIDER};
    }
  }

  function writeProviderConfig(storage, config, remember) {
    const normalized = normalizeProvider(config);
    if (!remember) {
      try {
        storage?.removeItem(PROVIDER_KEY);
      } catch (_error) {
        // The active page can still use the session-only values.
      }
      return {...normalized, remember: false};
    }
    try {
      storage?.setItem(PROVIDER_KEY, JSON.stringify(normalized));
      return {...normalized, remember: true};
    } catch (_error) {
      return {...normalized, remember: false};
    }
  }

  function normalizeProviderProfiles(profiles = {}) {
    const local = normalizeProvider(profiles.local);
    return {
      activeMode: profiles.activeMode === "rocm-local" ? "rocm-local" : "remote",
      remote: normalizeProvider(profiles.remote),
      local: {
        endpoint: local.endpoint || LOCAL_PROVIDER.endpoint,
        model: local.model || LOCAL_PROVIDER.model,
        apiKey: local.apiKey,
      },
    };
  }

  function readProviderProfiles(storage) {
    try {
      const raw = storage?.getItem(PROVIDERS_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === "object") {
          return {...normalizeProviderProfiles(parsed), remember: true};
        }
      }
      const legacy = storage?.getItem(PROVIDER_KEY);
      if (legacy) {
        const parsed = JSON.parse(legacy);
        if (parsed && typeof parsed === "object") {
          return {
            ...normalizeProviderProfiles({activeMode: "remote", remote: parsed}),
            remember: true,
          };
        }
      }
    } catch (_error) {
      // Hardened browser contexts use safe session-only defaults.
    }
    return {...normalizeProviderProfiles(), remember: false};
  }

  function writeProviderProfiles(storage, profiles, remember) {
    const normalized = normalizeProviderProfiles(profiles);
    if (!remember) {
      try {
        storage?.removeItem(PROVIDERS_KEY);
        storage?.removeItem(PROVIDER_KEY);
      } catch (_error) {
        // The active page can still use the session-only values.
      }
      return {...normalized, remember: false};
    }
    try {
      storage?.setItem(PROVIDERS_KEY, JSON.stringify(normalized));
      storage?.removeItem(PROVIDER_KEY);
      return {...normalized, remember: true};
    } catch (_error) {
      return {...normalized, remember: false};
    }
  }

  function initialProviderMode(profiles = {}, status = {}) {
    const configured = profiles.activeMode === "rocm-local" ? "rocm-local" : "remote";
    if (!profiles.remember && (status.runtime_mode === "rocm-local" || status.provider_mode === "rocm-local")) {
      return "rocm-local";
    }
    return configured;
  }

  function classifyEvidence(evidence = [], tools = []) {
    if (evidence.length) return {kind: "rag", items: evidence};
    const successful = tools.filter((tool) => tool?.status === "completed" || tool?.status === "attention");
    if (successful.length) return {kind: "tools", items: successful};
    return {kind: "general", items: []};
  }

  function activeSection(sectionRects = [], readingLine = 0, currentId = "") {
    if (!sectionRects.length) return "";
    const eligible = sectionRects.filter((section) => section.top <= readingLine);
    if (!eligible.length) return sectionRects[0].id;
    const activeTop = Math.max(...eligible.map((section) => section.top));
    const peers = eligible.filter((section) => Math.abs(section.top - activeTop) < 24);
    if (peers.some((section) => section.id === currentId)) return currentId;
    return peers[0].id;
  }

  root.PrivateOpsUiState = {
    readTheme,
    writeTheme,
    readProviderConfig,
    writeProviderConfig,
    readProviderProfiles,
    writeProviderProfiles,
    initialProviderMode,
    classifyEvidence,
    activeSection,
  };
})(globalThis);
