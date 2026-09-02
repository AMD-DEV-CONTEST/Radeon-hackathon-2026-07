"use client";

import React, { useState, useRef } from "react";

// ─────────────────────────────────────────────────────────────────────────────
// VOCABULARY
// ─────────────────────────────────────────────────────────────────────────────

export const GLOSSARY: Record<string, string> = {
  // ── Languages ──────────────────────────────────────────────────────────────
  rust: "Systems programming language. Memory-safe without a garbage collector — the compiler enforces safety rules at compile time. As fast as C. Best for daemons, CLI tools, and performance-critical APIs.",
  go: "Google's compiled language. Fast startup, built-in concurrency via goroutines. Excellent for APIs, CLIs, and network services. Simpler than Rust — less control, less complexity.",
  python:
    "Interpreted scripting language. Massive ecosystem (pip). Best for data pipelines, automation scripts, and AI/ML work. 10–100× slower at runtime than Rust/Go.",

  // ── Project types ──────────────────────────────────────────────────────────
  "api-service":
    "A server that exposes HTTP endpoints. Other applications call it over the network. Common patterns: REST (JSON over HTTP) or GraphQL. Starts up and runs continuously.",
  "cli-tool":
    "A command-line interface program. Run from a terminal, takes flags and arguments, produces output, then exits. Think git, grep, or cargo.",
  daemon:
    "A long-running background process with no UI. Starts at boot, listens for events or serves requests indefinitely. Examples: database engines, web servers, monitoring agents.",
  library:
    "Code other programs import and use. Has no main() entry point — just provides reusable functions, types, and abstractions. Published to crates.io (Rust), pkg.go.dev (Go), or PyPI (Python).",
  "grpc-service":
    "Like an api-service but uses Protocol Buffers (binary format) over HTTP/2. Faster and more type-safe than REST. Better for internal microservice communication where both sides are under your control.",
  "data-pipeline":
    "A program that reads data from a source, transforms it, and writes it to a destination. The ETL pattern: Extract → Transform → Load. Think log processors, data importers, report generators.",
  script:
    "A single-file Python program. No package structure required. Best for automation tasks, one-off data processing, or glue code that connects other tools.",
  package:
    "A Python library: structured, installable code with a pyproject.toml. Can be published to PyPI so others can install it with pip.",

  // ── Rust-specific ──────────────────────────────────────────────────────────
  "Arc<Mutex<T>>":
    "Rust pattern for sharing mutable data across threads safely. Arc = Atomic Reference Count (multiple owners). Mutex = lock ensuring only one thread accesses the data at a time. Required when multiple threads read and write the same state.",
  "Arc<RwLock<T>>":
    "Like Arc<Mutex<T>> but allows multiple simultaneous readers OR one exclusive writer. Better performance when reads heavily outnumber writes.",
  unsafe:
    "Rust block that bypasses the borrow checker. Allows raw pointers and manual memory management. Requires careful human review — the compiler will not protect you inside this block.",

  // ── Design constraints ─────────────────────────────────────────────────────
  threadsafe:
    "Code that works correctly when multiple threads execute it simultaneously. Requires coordinating any shared mutable state — typically with locks (Mutex) or atomic operations.",
  "no global state":
    "Design rule: all data is passed explicitly between functions rather than stored in global variables. Makes code testable (easy to inject different data), predictable, and easier to reason about.",
  async:
    "Non-blocking I/O. Instead of sitting idle waiting for network/disk operations, the program works on other tasks. Essential for high-concurrency servers that handle many simultaneous connections.",
  concurrent:
    "Multiple tasks progressing simultaneously on one machine. Different from parallel (separate CPUs). Requires careful state management to avoid race conditions.",

  // ── Hive pipeline roles ────────────────────────────────────────────────────
  Oracle:
    "First AI role. Reads your spec and encodes the full intent — what the software should do, why, and what constraints apply. All other roles inherit this semantic context.",
  Architect:
    "Second AI role. Takes the Oracle's intent and creates a dependency-ordered step plan (the DAG). Decides which files to create, in what order, and what each step produces.",
  Builder:
    "Third AI role. Executes one step at a time — generates the actual code for each step in the Architect's plan. Works against the current state of the file, not from scratch.",
  Monitor:
    "Fourth AI role. Reviews Builder output before it's written to disk. Catches logic errors, hallucinations, and drift from the original spec. Can submit a competing approach.",
  "Compiler Oracle":
    "Not an AI. The actual compiler — rustc, go build, or python. Zero hallucinations. If code doesn't compile, the step fails and retries regardless of what any model says. Final arbiter of correctness.",

  // ── DAG / session ──────────────────────────────────────────────────────────
  DAG: "Directed Acyclic Graph. A build plan where each step declares what it depends on. Step 3 won't start until Steps 1 and 2 succeed. Prevents partial builds and dependency conflicts.",
  manifest:
    "The session's source of truth on disk (manifest.json). Tracks every step: instruction, status, compiler output, retries, and training quality. Survives app restarts.",
  WAL: "Write-Ahead Log. Before each step starts, its intended state is written to disk. On crash or restart, the system knows exactly where to resume — no work is lost.",
  scaffolding:
    "The project skeleton generated before any code is written: Cargo.toml (Rust), go.mod (Go), or pyproject.toml (Python). If scaffolding is invalid, every subsequent compile step will fail.",
  DSL: "Domain-Specific Language. A compact, structured format models use to communicate between steps instead of verbose natural language prose. Reduces ambiguity and token usage.",

  // ── Write modes ────────────────────────────────────────────────────────────
  new_file:
    "Creates a new file from scratch at the specified path. Used the first time any source file is written. Fails if the file already exists.",
  replace_file:
    "Replaces the entire contents of an existing file. Used when a file needs a complete rewrite. Any manual edits to that file will be lost.",
  append_to_file:
    "Appends the generated code to the end of an existing file. Simple and safe for adding new functions at the bottom.",
  replace_function:
    "Uses the tree-sitter AST parser to find a specific function by name and swap only that function's body. Surgical edit — doesn't touch any other code in the file.",

  // ── Verdicts ───────────────────────────────────────────────────────────────
  PASS: "Compilation succeeded. No syntax errors, no type errors. The Compiler Oracle approved this step and the build proceeds to the next.",
  FAIL: "Compilation failed. The Builder retries up to 3 times with the compiler error added to its context. After 3 failures, the Architect is asked to re-plan the step.",
  training_ready:
    "This failure is valuable: the compiler error changed between attempts, meaning the model was making progress. Will be added to the fine-tune queue automatically.",
  inconclusive:
    "Same compiler error on every attempt — likely the task is impossible as specified or the spec is contradictory. Goes to human review rather than the training queue.",

  // ── Step statuses ──────────────────────────────────────────────────────────
  in_progress:
    "This step is actively being worked on — the Builder is generating code and the Compiler Oracle is validating it.",
  complete:
    "This step succeeded: code written, compiler passed, Monitor approved. The step's output is now part of the workspace.",
  failed:
    "This step exhausted all retries and Architect re-plan attempts without producing a passing build. Logged for human review.",
  pending:
    "This step is waiting for its declared dependencies (earlier steps) to complete before it can start.",
  stale_instruction:
    "A previously successful step changed its public API during a retry. This step's instruction has been flagged for refresh by the Architect before it runs.",
};

// ─────────────────────────────────────────────────────────────────────────────
// GLOSSARY TERM COMPONENT
// ─────────────────────────────────────────────────────────────────────────────

interface GlossaryTermProps {
  term: string;
  definition: string;
  children: React.ReactNode;
  className?: string;
}

export function GlossaryTerm({ term, definition, children, className = "" }: GlossaryTermProps) {
  const [show, setShow] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  const [flipUp, setFlipUp] = useState(true);

  const handleEnter = () => {
    if (ref.current) {
      const rect = ref.current.getBoundingClientRect();
      setFlipUp(rect.top > 160);
    }
    setShow(true);
  };

  return (
    <span
      ref={ref}
      className={`relative inline underline decoration-dotted decoration-cyan-500/50 cursor-help ${className}`}
      onMouseEnter={handleEnter}
      onMouseLeave={() => setShow(false)}
    >
      {children}
      {show && (
        <span
          className={`
            absolute z-50 left-0 w-64 p-3
            bg-[var(--dtx-code-bg)] border border-cyan-500/30 rounded-xl
            text-label text-gray-300 leading-relaxed
            shadow-[0_0_24px_rgba(0,0,0,0.9)]
            pointer-events-none
            ${flipUp ? "bottom-full mb-1.5" : "top-full mt-1.5"}
          `}
          style={{ whiteSpace: "normal", minWidth: "220px" }}
        >
          <span className="text-cyan-400 font-black text-label block mb-1">{term}</span>
          {definition}
        </span>
      )}
    </span>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// ANNOTATED TEXT — tokenizes a string and wraps known terms in GlossaryTerm
// ─────────────────────────────────────────────────────────────────────────────

// Build regex: longest terms first so "Compiler Oracle" beats "Oracle".
// Word boundaries for pure-alpha terms; bare pattern for compound terms.
const _sorted = Object.keys(GLOSSARY).sort((a, b) => b.length - a.length);
const _pattern = _sorted
  .map((t) => {
    const escaped = t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    // Pure alphabetic terms get word boundaries to avoid "go" inside "going"
    if (/^[a-zA-Z]+$/.test(t)) return `\\b${escaped}\\b`;
    return escaped;
  })
  .join("|");

const ANNOTATE_RE = new RegExp(`(${_pattern})`, "g");

interface AnnotatedTextProps {
  text: string;
  /** Extra className applied to each GlossaryTerm span */
  termClassName?: string;
}
