export type AddonStatus = "installed" | "available" | "beta" | "builtin";
export type AddonCategory = "llm" | "oracle" | "benchmark" | "privacy" | "integration" | "theme";

export type Addon = {
  id: string;
  name: string;
  author: string;
  category: AddonCategory;
  description: string;
  version: string;
  status: AddonStatus;
  icon: string;
  tags: string[];
  featured?: boolean;
  /**
   * Set when clicking Install cannot actually produce this capability.
   *
   * The Marketplace's `toggle()` only writes an id into localStorage -- nothing is provisioned. The
   * card then rendered "Installed", so a user could click Install on `kotlin-oracle` and be told the
   * Kotlin toolchain was present while `_ORACLE_IMAGES` (scripts/hive/compiler.py) contains only
   * rust, go, python and typescript and `validate_project` FAILS CLOSED for everything else. They
   * would hit that refusal after being told the oracle was installed.
   *
   * A planned addon still appears -- the roadmap is worth showing -- but it cannot be toggled into a
   * state that asserts it works. Guarded by lib/__tests__/addons.planned.test.ts.
   */
  planned?: boolean;
};

export const ADDONS: Addon[] = [
  // LLM Providers
  // Status values below are the pre-connection FALLBACK only. MarketplacePanel
  // overrides every "llm"-category card's installed/available state live from
  // useSettings().keyStatus (does this machine actually have that provider's
  // API key saved?) -- these were previously the ONLY source of truth, entirely
  // hardcoded and disconnected from whether a key was really configured.
  // Ryan, live, looking straight at fake "Installed" badges: "supposedly
  // installed? but not..." "DeepSeek V4" corrected to "DeepSeek V3" -- V4
  // doesn't exist among the real registered routes (aiRouting.ts).
  {
    id: "anthropic",
    name: "Anthropic Claude",
    author: "Anthropic",
    category: "llm",
    description: "Claude Opus 4.8 · Sonnet 4.6 · Haiku 4.5. Best reasoning + code generation.",
    version: "4.8.0",
    status: "available",
    icon: "🤖",
    tags: ["cloud", "reasoning", "code"],
    featured: true,
  },
  {
    id: "deepseek",
    name: "DeepSeek V3",
    author: "DeepSeek AI",
    category: "llm",
    description: "Frontier open-source model. Powers the default Builder in SWE-bench configs.",
    version: "3.0.0",
    status: "available",
    icon: "🔵",
    tags: ["cloud", "code", "fast"],
  },
  {
    id: "chatgpt",
    name: "ChatGPT",
    author: "OpenAI",
    category: "llm",
    description: "Fallback when Anthropic quota exceeded. Best for complex multi-step reasoning.",
    version: "5.5.0",
    status: "available",
    icon: "🟢",
    tags: ["cloud", "reasoning"],
  },
  {
    id: "gemini",
    name: "Google Gemini 3.1",
    author: "Google DeepMind",
    category: "llm",
    description: "Gemini 3.1 Pro Preview. Strong at UI/UX, visual reasoning, Python AI.",
    version: "3.1.0",
    status: "available",
    icon: "🔷",
    tags: ["cloud", "multimodal"],
  },
  {
    id: "ollama",
    name: "Ollama Local",
    author: "Ollama",
    category: "llm",
    description: "Run Determinex fine-tuned models (C1/C3/C7) and Qwen2.5-Coder locally.",
    version: "0.5.4",
    status: "builtin",
    icon: "🦙",
    tags: ["local", "private", "offline"],
    featured: true,
  },
  {
    id: "mistral",
    name: "Mistral AI",
    author: "Mistral",
    category: "llm",
    description: "C7 Sentinel base. Fast European-sovereign cloud option.",
    version: "7.2.0",
    status: "available",
    icon: "🌀",
    tags: ["cloud", "eu-sovereign"],
  },
  {
    id: "kimi",
    name: "Kimi K2",
    author: "Moonshot AI",
    category: "llm",
    description: "Long-context reasoning route.",
    version: "2.0.0",
    status: "available",
    icon: "🌙",
    tags: ["cloud", "long-context"],
  },
  // Oracles
  {
    id: "rust-oracle",
    name: "Rust / Cargo",
    author: "Determinex Core",
    category: "oracle",
    description:
      "cargo build in a network-isolated container. Real type check; does not run cargo test.",
    version: "1.83.0",
    status: "builtin",
    icon: "🦀",
    tags: ["rust", "compiled", "strict"],
    featured: true,
  },
  {
    id: "go-oracle",
    name: "Go Build",
    author: "Determinex Core",
    category: "oracle",
    description:
      "go build ./... in a network-isolated container. Real type check; does not run go test.",
    version: "1.22.3",
    status: "builtin",
    icon: "🐹",
    tags: ["go", "compiled"],
  },
  {
    id: "python-oracle",
    name: "Python pytest",
    author: "Determinex Core",
    category: "oracle",
    description:
      "compileall, then imports every module, then unittest discover. Stdlib only — the sandbox runs --network=none, so pytest and mypy are not available.",
    version: "3.11.9",
    status: "builtin",
    icon: "🐍",
    tags: ["python", "dynamic"],
  },
  {
    id: "ts-oracle",
    name: "TypeScript / tsc",
    author: "Determinex Core",
    category: "oracle",
    description:
      "tsc --noEmit with the project tsconfig, or --strict when none ships. Type check only; jest is not run.",
    version: "5.4.2",
    status: "builtin",
    icon: "📘",
    tags: ["typescript", "compiled"],
  },
  {
    id: "kotlin-oracle",
    name: "Kotlin / Gradle",
    author: "Community",
    category: "oracle",
    // Was "gradle test. JVM oracle for Android + backend Kotlin targets." -- present tense, as
    // though it ran. determinex_oracle.py has a Gradle entry, but the sandboxed oracle the IDE
    // actually uses (_ORACLE_IMAGES in scripts/hive/compiler.py) has no Kotlin image, so
    // validate_project fails closed. Same overstatement cpp-oracle already had corrected.
    description:
      "Planned. No sandboxed Kotlin oracle ships yet — the compiler oracle covers Rust, Go, " +
      "Python and TypeScript, and fails closed for Kotlin.",
    version: "2.0.0",
    status: "available",
    planned: true,
    icon: "🅺",
    tags: ["kotlin", "jvm"],
  },
  {
    id: "swift-oracle",
    name: "Swift / XCTest",
    author: "Community",
    category: "oracle",
    // Was "swift test. iOS/macOS oracle. Requires Xcode toolchain." determinex_oracle.py does
    // implement `swift test`, but via a DIRECT HOST SUBPROCESS, which validate_project deliberately
    // does not use -- buying verification by running model-generated code outside the sandbox would
    // trade a correctness gap for a security one. So there is no oracle the IDE will run for Swift.
    description:
      "Planned. No sandboxed Swift oracle ships yet — the compiler oracle covers Rust, Go, " +
      "Python and TypeScript, and fails closed for Swift.",
    version: "5.10.0",
    status: "available",
    planned: true,
    icon: "🐦",
    tags: ["swift", "apple"],
  },
  {
    id: "cpp-oracle",
    name: "C/C++ / CMake",
    author: "Determinex Core",
    // Was status: "installed" with a description promising "cmake + make + GTest". There is no
    // C/C++ oracle: `_ORACLE_IMAGES` in scripts/hive/compiler.py contains only rust, go, python and
    // typescript, and validate_project's final branch FAILS CLOSED for C/C++ with "No sandboxed
    // Compiler Oracle for lang ...". So the Marketplace advertised as installed the one thing the
    // oracle refuses to verify, and a user picking a C project would hit that refusal after being
    // told the toolchain was present.
    category: "oracle",
    description:
      "Planned. No sandboxed C/C++ oracle ships yet — the compiler oracle currently covers Rust, " +
      "Go, Python and TypeScript, and fails closed for C/C++.",
    version: "3.28.0",
    status: "available",
    planned: true,
    icon: "⚙️",
    tags: ["c", "cpp", "compiled"],
  },
  // Benchmarks
  {
    id: "programbench",
    name: "ProgramBench",
    author: "Determinex Core",
    category: "benchmark",
    description:
      "201-task CLI reimplementation. 0/200 legitimate locks (corrected 2026-06-30). 62 reference archives retained.",
    version: "2.1.0",
    status: "builtin",
    icon: "📊",
    tags: ["benchmark", "cli", "official"],
    featured: true,
  },
  {
    id: "swebench",
    name: "SWE-bench Lite",
    author: "Princeton NLP",
    category: "benchmark",
    description: "300 GitHub issues. B-Uncloaked: 14.0%. Privacy-sovereign run active.",
    version: "1.0.0",
    status: "installed",
    icon: "🐛",
    tags: ["benchmark", "github", "patches"],
  },
  {
    id: "humaneval",
    name: "HumanEval+",
    author: "OpenAI",
    category: "benchmark",
    description: "164 hand-written Python problems. Fast eval for model selection.",
    version: "1.0.0",
    status: "available",
    icon: "📝",
    tags: ["benchmark", "python", "generation"],
  },
  {
    id: "livecodebench",
    name: "LiveCodeBench Pro",
    author: "LCB Team",
    category: "benchmark",
    description: "Contamination-free. Rolling 6-month window. True generalization signal.",
    version: "2.0.0",
    status: "available",
    icon: "⚡",
    tags: ["benchmark", "live", "competition"],
  },
  {
    id: "bigcodebench",
    name: "BigCodeBench",
    author: "BigCode",
    category: "benchmark",
    description: "1140 diverse tasks. Better coverage than HumanEval for real use-cases.",
    version: "0.1.2",
    status: "available",
    icon: "🔬",
    tags: ["benchmark", "diverse"],
  },
  // Privacy
  {
    id: "cloak",
    name: "Project Cloak",
    author: "Determinex Core",
    category: "privacy",
    description:
      "AST-aware identifier obfuscation. Cloud-bound payloads use x_NNNN tokens; leakage claims require a current Cloak audit.",
    version: "3.1.0",
    status: "builtin",
    icon: "🎭",
    tags: ["privacy", "obfuscation", "ast"],
    featured: true,
  },
  {
    id: "rosetta",
    name: "Rosetta Stone",
    author: "Determinex Core",
    category: "privacy",
    description: "MLP encoder/decoder bridging C1/C3/C7 into shared 4096-dim latent space.",
    version: "1.0.0",
    status: "builtin",
    icon: "🪨",
    tags: ["latent", "communication", "mlp"],
  },
  {
    id: "hardened",
    name: "Hardened Runner",
    author: "Determinex Core",
    category: "privacy",
    description: "Sandboxed code execution. Workspace-bounded, env-scrubbed, network-denied.",
    version: "2.0.0",
    status: "builtin",
    icon: "🏰",
    tags: ["sandbox", "security", "isolation"],
  },
  // Integrations
  {
    id: "github",
    name: "GitHub Actions",
    author: "GitHub",
    category: "integration",
    description: "PR checks, CI status, issue sync. Watch runs without leaving the IDE.",
    version: "2.3.1",
    status: "available",
    icon: "🐙",
    tags: ["ci", "cd", "github"],
  },
  {
    id: "docker",
    name: "Docker / Compose",
    author: "Docker Inc",
    category: "integration",
    description: "Container management, compose up/down, log streaming. Eval runner integration.",
    version: "4.0.0",
    status: "installed",
    icon: "🐳",
    tags: ["docker", "containers"],
  },
  {
    id: "snyk",
    name: "Snyk Security",
    author: "Snyk",
    category: "integration",
    description: "Real-time vulnerability scanning. Pre-commit + CI gate. OWASP coverage.",
    version: "1.12.0",
    status: "available",
    icon: "🛡️",
    tags: ["security", "sca", "sast"],
  },
  {
    id: "jira",
    name: "Jira / Linear",
    author: "Community",
    category: "integration",
    description: "Link commits to tickets. Transition status from commit messages.",
    version: "0.9.2",
    status: "available",
    icon: "📋",
    tags: ["project", "tracking"],
  },
  {
    id: "slack",
    name: "Slack Notifications",
    author: "Community",
    category: "integration",
    description: "Push eval results, lock announcements, and gate escalations to Slack.",
    version: "0.8.0",
    status: "beta",
    icon: "💬",
    tags: ["notifications", "team"],
  },
  // Themes
  {
    id: "redlens",
    name: "Red Lens",
    author: "Ryan Gurganious",
    category: "theme",
    description: "Deep crimson precision. For the long compile sessions.",
    version: "1.2.0",
    status: "installed",
    icon: "🔴",
    tags: ["dark", "red"],
  },
  {
    id: "deepspace",
    name: "Deep Space",
    author: "Ryan Gurganious",
    category: "theme",
    description: "Midnight void with nebula accents.",
    version: "1.4.0",
    status: "installed",
    icon: "🌌",
    tags: ["dark", "blue"],
  },
  {
    id: "mechbay",
    name: "Mech Bay",
    author: "Ryan Gurganious",
    category: "theme",
    description: "Industrial amber on gunmetal. Utility-first.",
    version: "1.1.0",
    status: "available",
    icon: "🤖",
    tags: ["dark", "amber"],
  },
  {
    id: "neon",
    name: "Neon Grid",
    author: "Community",
    category: "theme",
    description: "Cyberpunk green on black. Terminal aesthetic.",
    version: "2.0.0",
    status: "available",
    icon: "💚",
    tags: ["dark", "green"],
  },
];
