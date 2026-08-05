"""The agent's tools: schemas + implementations.

Each tool wraps a proven pipeline stage. Train/eval/export run as
subprocesses (VRAM hygiene + the unsloth global-patch lesson); datagen
runs in-process since it only talks HTTP to the teacher. On GPUs where
teacher + training don't fit together (the 8GB dev box), the train tool
stops the teacher server, trains, and restarts it — conversation state
lives in the agent process, so nothing is lost.
"""

import json
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from .config import REPO_ROOT
from .registry import Registry
from .spec import TaskSpec

SCHEMAS = [
    {"type": "function", "function": {
        "name": "save_task_spec",
        "description": (
            "Save the task specification for the model to build. Call this "
            "after interviewing the user. Creates the build workspace. "
            "Returns validation errors if the spec is malformed — fix and retry."
        ),
        "parameters": {"type": "object", "properties": {
            "spec": {"type": "object", "description": (
                "The task spec object: {name (kebab-case), description, "
                "example_noun, input_field, input_length [min,max chars], "
                "seed_docs [paths], output_schema {field: {type: 'enum'|'string', "
                "values: [...]}}, balance_field (an enum output field), "
                "datagen_guidance, facets {personas[], tones[], lengths[], "
                "wrinkles[], situations {value: [...]}}}"
            )}}, "required": ["spec"]}}},
    {"type": "function", "function": {
        "name": "read_seed_document",
        "description": ("Read a seed/rules document so YOU can derive the "
                        "task schema (categories, priorities, field values) "
                        "from it instead of asking the user. Call with no "
                        "path to list the available documents in seeds/."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string",
                     "description": "e.g. seeds/triage_policy.md; omit to "
                                    "list available documents"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "preview_examples",
        "description": ("Generate a few sample training examples with the "
                        "teacher model so the user can sanity-check them "
                        "before committing to a full dataset."),
        "parameters": {"type": "object", "properties": {
            "n": {"type": "integer", "description": "How many samples (default 3)"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "generate_dataset",
        "description": ("Generate the full synthetic training dataset with the "
                        "teacher model, grounded in the seed documents. "
                        "Filtered, deduped, split into train/holdout."),
        "parameters": {"type": "object", "properties": {
            "n_train": {"type": "integer",
                        "description": "omit to use the loaded config's value"},
            "n_holdout": {"type": "integer",
                          "description": "omit to use the loaded config's value"},
            "focus": {"type": "array", "items": {"type": "string"},
                      "description": ("Optional: balance-field values to "
                                      "oversample ~2:1, for targeted "
                                      "regeneration after a diagnosis.")}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "augment_dataset",
        "description": ("Add NEW examples to the existing training set "
                        "(deduped against it) while keeping the holdout "
                        "frozen, so before/after evals stay comparable. "
                        "This is the tool for targeted regeneration after "
                        "diagnose_failures."),
        "parameters": {"type": "object", "properties": {
            "n_new": {"type": "integer",
                      "description": "How many new training examples to add"},
            "focus": {"type": "array", "items": {"type": "string"},
                      "description": ("Balance-field values to oversample "
                                      "~2:1 (the weak classes).")}},
            "required": ["n_new"]}}},
    {"type": "function", "function": {
        "name": "resume_build",
        "description": ("Resume a previous build: reload its task spec and "
                        "workspace so you can keep improving it (augment, "
                        "retrain, re-evaluate, export). Find builds with "
                        "list_experiments; pass any experiment id from the "
                        "build you want."),
        "parameters": {"type": "object", "properties": {
            "experiment_id": {"type": "string",
                              "description": "e.g. exp-0003"}},
            "required": ["experiment_id"]}}},
    {"type": "function", "function": {
        "name": "train_student",
        "description": ("LoRA fine-tune the student model on the generated "
                        "dataset. Frees the GPU first if needed (the teacher "
                        "restarts automatically)."),
        "parameters": {"type": "object", "properties": {
            "epochs": {"type": "integer", "description": "default 3"},
            "learning_rate": {"type": "number", "description": "default 1e-4"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "evaluate_student",
        "description": ("Evaluate BOTH the base (untrained) and tuned student "
                        "on the holdout set. Returns json validity, per-field "
                        "accuracy, and exact-match for each."),
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "diagnose_failures",
        "description": ("Analyze the tuned student's holdout mistakes: "
                        "per-class recall on the balance field, top confusion "
                        "pairs, and sample failures. Use it to decide targeted "
                        "data regeneration."),
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "export_model",
        "description": ("Convert the tuned student to a quantized GGUF and "
                        "smoke-test it by serving it and running one holdout "
                        "example through it."),
        "parameters": {"type": "object", "properties": {
            "quant": {"type": "string", "description": "default q8_0"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "benchmark_quants",
        "description": ("Produce the quantization ladder benchmark for the "
                        "current build: converts the tuned student to several "
                        "GGUF quantizations and measures file size, tok/s, "
                        "and served holdout accuracy for each, plus teacher "
                        "speed. Slow (many minutes). Writes a report + chart."),
        "parameters": {"type": "object", "properties": {
            "quants": {"type": "array", "items": {"type": "string"},
                       "description": "default Q4_K_M,Q5_K_M,Q6_K,Q8_0"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "list_experiments",
        "description": ("List past pipeline runs from the experiment registry "
                        "(memory across sessions): id, stage, metrics."),
        "parameters": {"type": "object", "properties": {
            "task": {"type": "string", "description": "Optional task-name filter"}},
            "required": []}}},
]


class ToolBox:
    def __init__(self, cfg: dict, config_path: str, teacher_ctl):
        """teacher_ctl: object with .stop() and .start() controlling the
        shared llama-server (owned by the chat CLI)."""
        self.cfg = cfg
        self.config_path = config_path
        self.teacher_ctl = teacher_ctl
        self.registry = Registry(Path(cfg["run"]["out_root"]) / "registry.json")
        self.spec: TaskSpec | None = None
        self.run_dir: Path | None = None
        # Live progress sink; the UI server points this at the event stream.
        self.progress = lambda detail: None
        # Consecutive identical failures per tool (reset on success).
        self._fail_streak: dict = {}
        # Approval gate: the agent loop increments user_turns each user
        # turn; a dataset build cannot start in the turn that drafted the
        # spec — the user must have replied in between.
        self.user_turns = 0
        self._spec_saved_turn: int | None = None

    # Stages the pipeline can proceed without. A failure here should be
    # reported and skipped, never block the build.
    OPTIONAL_TOOLS = frozenset(
        {"preview_examples", "diagnose_failures", "benchmark_quants"})

    # ---------- dispatch ----------

    def dispatch(self, name: str, args: dict) -> dict:
        handler = getattr(self, f"tool_{name}", None)
        if handler is None:
            return {"error": f"unknown tool: {name}"}
        streak = self._fail_streak.get(name)
        if streak and streak["count"] >= 2:
            # Mechanical retry brake: two identical failures means the
            # third attempt does not run — the brain must move on.
            return {"error": streak["error"], "skipped": True,
                    "guidance": ("this tool already failed twice with the "
                                 "same error and was not run again — "
                                 + ("continue the pipeline without it"
                                    if name in self.OPTIONAL_TOOLS else
                                    "report the failure to the user and stop"))}
        try:
            result = handler(**args)
            self._fail_streak.pop(name, None)
            return result
        except Exception as e:  # tool failures go back to the agent, not a crash
            err = f"{type(e).__name__}: {e}"
            prev = self._fail_streak.get(name)
            if prev and prev["error"] == err:
                prev["count"] += 1
            else:
                self._fail_streak[name] = {"error": err, "count": 1}
            result = {"error": err}
            if name in self.OPTIONAL_TOOLS:
                result["optional_stage"] = True
                result["guidance"] = ("this stage is optional — tell the user "
                                      "it failed and continue the pipeline "
                                      "without it")
                self.progress(f"optional stage {name} failed — continuing "
                              f"without it")
            return result

    def _require_spec(self):
        if self.spec is None or self.run_dir is None:
            raise RuntimeError(
                "no build loaded in this session — call resume_build with an "
                "experiment id (see list_experiments) to continue an existing "
                "build, or save_task_spec to start a new one")

    _PROGRESS_PREFIXES = ("datagen:", "train:", "eval[", "bench:",
                          "export:", "external eval:")

    def _stream_subprocess(self, cmd: list, label: str) -> str:
        """Run a subprocess, forwarding progress-looking lines live."""
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace",
                                cwd=str(REPO_ROOT), env=env)
        tail = []
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            tail.append(line)
            if len(tail) > 60:
                tail.pop(0)
            if line.startswith(self._PROGRESS_PREFIXES):
                self.progress(line)
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"{label} failed:\n" + "\n".join(tail[-25:]))
        return "\n".join(tail)

    def _stage_subprocess(self, stage: str) -> str:
        """Run one pipeline stage in a fresh process; stream its progress."""
        cmd = [sys.executable, str(REPO_ROOT / "run_slice.py"),
               "--config", self.config_path,
               "--stages", stage, "--run-dir", str(self.run_dir)]
        return self._stream_subprocess(cmd, stage)

    # ---------- tools ----------

    def tool_save_task_spec(self, spec: dict) -> dict:
        self.spec = TaskSpec(spec)  # raises ValueError with specifics if bad
        spec_path = REPO_ROOT / "specs" / f"{self.spec.name}.json"
        spec_path.parent.mkdir(exist_ok=True)
        self.spec.save(spec_path)
        self.run_dir = (Path(self.cfg["run"]["out_root"]) /
                        f"build-{self.spec.name}-{datetime.now():%Y%m%d-%H%M%S}")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.spec.save(self.run_dir / "spec.json")
        self._spec_saved_turn = self.user_turns
        return {"ok": True, "spec_path": str(spec_path),
                "workspace": str(self.run_dir),
                "summary": {"output_schema": self.spec.output_schema,
                            "balance_field": self.spec.balance_field,
                            "seed_docs": self.spec.seed_docs}}

    MAX_DOC_CHARS = 6000  # keep the doc within the brain's context budget

    def tool_read_seed_document(self, path: str | None = None) -> dict:
        from .datagen import load_seed_docs
        seeds_dir = REPO_ROOT / "seeds"
        if not path:
            docs = sorted(seeds_dir.glob("*.md")) if seeds_dir.is_dir() else []
            return {"available_documents": [
                {"path": f"seeds/{p.name}", "size_chars": p.stat().st_size}
                for p in docs],
                "guidance": ("titles only — before drafting a spec, read "
                             "every document relevant to the task (call this "
                             "tool again with each path); field names and "
                             "enum values must come from the documents, "
                             "never invented")}
        docs = load_seed_docs([path], REPO_ROOT)  # boundary-checks the file
        name, text = docs[0]
        truncated = len(text) > self.MAX_DOC_CHARS
        return {"path": path, "name": name,
                "content": text[:self.MAX_DOC_CHARS],
                "truncated": truncated,
                **({"note": "document truncated for reading; datagen always "
                            "uses the full text"} if truncated else {})}

    def tool_preview_examples(self, n: int = 3) -> dict:
        self._require_spec()
        n = int(n)
        from .datagen import generate
        preview_dir = self.run_dir / "preview"
        preview_dir.mkdir(exist_ok=True)
        cfg = json.loads(json.dumps(self.cfg, default=str))  # deep copy
        cfg["datagen"]["n_train"] = n
        cfg["datagen"]["n_holdout"] = 0
        stats = generate(cfg, preview_dir, self.spec,
                         progress_cb=self.progress)
        rows = [json.loads(l) for l in
                open(preview_dir / "train.jsonl", encoding="utf-8")]
        return {"examples": rows, "acceptance_rate": stats["acceptance_rate"]}

    def _check_focus(self, focus):
        if not focus:
            return None
        focus = [str(v) for v in focus]
        bad = [v for v in focus if v not in self.spec.balance_values]
        if bad:
            raise ValueError(
                f"focus values not in {self.spec.balance_field}: {bad}")
        return focus

    def tool_generate_dataset(self, n_train: int | None = None,
                              n_holdout: int | None = None,
                              focus: list | None = None) -> dict:
        self._require_spec()
        if self._spec_saved_turn == self.user_turns:
            raise RuntimeError(
                "approval gate: this spec was drafted in the current turn "
                "and the user has not approved it — present the derived "
                "fields, values, and preview samples, then END YOUR TURN "
                "and wait for the user's go-ahead")
        # Config is the default; explicit arguments (the user's ask) win.
        n_train = (int(n_train) if n_train is not None
                   else int(self.cfg["datagen"]["n_train"]))
        n_holdout = (int(n_holdout) if n_holdout is not None
                     else int(self.cfg["datagen"]["n_holdout"]))
        focus = self._check_focus(focus)
        from .datagen import generate
        cfg = json.loads(json.dumps(self.cfg, default=str))
        cfg["datagen"]["n_train"] = n_train
        cfg["datagen"]["n_holdout"] = n_holdout
        t0 = time.time()
        stats = generate(cfg, self.run_dir, self.spec, focus=focus,
                         progress_cb=self.progress)
        stats["seconds"] = round(time.time() - t0, 1)
        self.registry.append(self.spec.name, "datagen", str(self.run_dir),
                             {"n_train": n_train, "n_holdout": n_holdout,
                              "focus": focus}, stats)
        return stats

    def tool_augment_dataset(self, n_new: int, focus: list | None = None) -> dict:
        self._require_spec()
        n_new = int(n_new)
        focus = self._check_focus(focus)
        from .datagen import generate
        cfg = json.loads(json.dumps(self.cfg, default=str))
        cfg["datagen"]["n_train"] = n_new
        cfg["datagen"]["n_holdout"] = 0
        t0 = time.time()
        stats = generate(cfg, self.run_dir, self.spec, focus=focus,
                         augment=True, progress_cb=self.progress)
        stats["seconds"] = round(time.time() - t0, 1)
        self.registry.append(self.spec.name, "augment", str(self.run_dir),
                             {"n_new": n_new, "focus": focus}, stats)
        return stats

    def tool_resume_build(self, experiment_id: str) -> dict:
        entry = self.registry.get(str(experiment_id))
        if entry is None:
            raise ValueError(f"no experiment {experiment_id!r} in the registry")
        run_dir = Path(entry["run_dir"])
        spec_path = run_dir / "spec.json"
        if not spec_path.exists():
            raise RuntimeError(f"build workspace missing spec.json: {run_dir}")
        self.spec = TaskSpec.load(spec_path)
        self.run_dir = run_dir
        state = {
            "task": self.spec.name,
            "workspace": str(run_dir),
            "has_dataset": (run_dir / "train.jsonl").exists(),
            "has_model": (run_dir / "merged").exists(),
            "has_eval": (run_dir / "eval_report.json").exists(),
        }
        if state["has_eval"]:
            state["last_eval"] = json.loads(
                (run_dir / "eval_report.json").read_text(encoding="utf-8"))
        if state["has_dataset"]:
            state["train_examples"] = sum(
                1 for _ in open(run_dir / "train.jsonl", encoding="utf-8"))
        return state

    def tool_train_student(self, epochs: int = 3,
                           learning_rate: float = 1e-4) -> dict:
        self._require_spec()
        epochs, learning_rate = int(epochs), float(learning_rate)
        # Persist hyperparameters for the subprocess via a run-local config
        # override? Keep it simple: stage subprocess reads the session config;
        # epochs/lr deviations are written into it here.
        overrides = self.run_dir / "train_overrides.json"
        overrides.write_text(json.dumps(
            {"epochs": epochs, "lr": learning_rate}), encoding="utf-8")
        free_gpu = self.cfg.get("orchestration", {}).get(
            "free_gpu_for_training", False)
        t0 = time.time()
        if free_gpu:
            self.teacher_ctl.stop()
        try:
            tail = self._stage_subprocess("train")
        finally:
            if free_gpu:
                self.teacher_ctl.start()
        seconds = round(time.time() - t0, 1)
        final_loss = None
        log = self.run_dir / "train_log.jsonl"
        if log.exists():
            lines = log.read_text(encoding="utf-8").strip().splitlines()
            if lines:
                final_loss = json.loads(lines[-1])["loss"]
        metrics = {"seconds": seconds, "final_loss": final_loss,
                   "epochs": epochs, "lr": learning_rate}
        self.registry.append(self.spec.name, "train", str(self.run_dir),
                             {"epochs": epochs, "lr": learning_rate}, metrics)
        return metrics

    def tool_evaluate_student(self) -> dict:
        self._require_spec()
        free_gpu = self.cfg.get("orchestration", {}).get(
            "free_gpu_for_training", False)
        if free_gpu:
            self.teacher_ctl.stop()
        try:
            self._stage_subprocess("eval")
        finally:
            if free_gpu:
                self.teacher_ctl.start()
        report = json.loads(
            (self.run_dir / "eval_report.json").read_text(encoding="utf-8"))
        # Hand the agent the previous tuned score so before/after reporting
        # is structural, not dependent on conversation memory.
        prior = [e for e in self.registry.list(self.spec.name)
                 if e["stage"] == "eval"]
        if prior:
            report["previous_tuned"] = prior[-1]["metrics"]
        self.registry.append(self.spec.name, "eval", str(self.run_dir),
                             {}, report["tuned"])
        return report

    def tool_diagnose_failures(self) -> dict:
        self._require_spec()
        pred_path = self.run_dir / "predictions.jsonl"
        if not pred_path.exists():
            raise RuntimeError("no predictions yet — run evaluate_student first")
        bf = self.spec.balance_field
        rows = [json.loads(l) for l in open(pred_path, encoding="utf-8")
                if json.loads(l)["model"] == "tuned"]
        per_class = {}
        confusions = Counter()
        failures = []
        for v in self.spec.balance_values:
            in_class = [r for r in rows if r["reference"][bf] == v]
            if not in_class:
                per_class[v] = None
                continue
            ok = sum(1 for r in in_class
                     if r["prediction"] and r["prediction"][bf] == v)
            per_class[v] = round(ok / len(in_class), 3)
        other_field_errors = Counter()
        for r in rows:
            pred = r["prediction"]
            wrong = pred is None or any(
                pred[f] != r["reference"][f] for f in self.spec.output_fields())
            if wrong:
                if pred:
                    if pred[bf] != r["reference"][bf]:
                        confusions[(r["reference"][bf], pred[bf])] += 1
                    else:
                        for f in self.spec.output_fields():
                            if f != bf and pred[f] != r["reference"][f]:
                                other_field_errors[f] += 1
                if len(failures) < 5:
                    failures.append({
                        "input": r[self.spec.input_field][:200],
                        "expected": r["reference"],
                        "got": pred or f"PARSE_ERROR:{r['parse_error']}"})
        weak = [v for v, acc in per_class.items()
                if acc is not None and acc < 0.9]
        return {"per_class_recall": per_class,
                "top_confusions": [
                    {"expected": a, "predicted": b, "count": c}
                    for (a, b), c in confusions.most_common(5)],
                "errors_in_other_fields": dict(other_field_errors),
                "weak_classes": weak,
                "sample_failures": failures}

    def tool_export_model(self, quant: str = "q8_0") -> dict:
        self._require_spec()
        (self.run_dir / "export_overrides.json").write_text(
            json.dumps({"quant": quant}), encoding="utf-8")
        free_gpu = self.cfg.get("orchestration", {}).get(
            "free_gpu_for_training", False)
        if free_gpu:
            self.teacher_ctl.stop()   # smoke test serves the student GGUF
        try:
            self._stage_subprocess("export")
        finally:
            if free_gpu:
                self.teacher_ctl.start()
        summary = json.loads(
            (self.run_dir / "slice_summary.json").read_text(encoding="utf-8"))
        result = summary.get("export", {})
        self.registry.append(self.spec.name, "export", str(self.run_dir),
                             {"quant": quant}, result)
        return result

    def tool_benchmark_quants(self, quants: list | None = None) -> dict:
        self._require_spec()
        if not (self.run_dir / "merged").exists():
            raise RuntimeError("no trained model in this build yet")
        cmd = [sys.executable, str(REPO_ROOT / "run_bench.py"),
               "--config", self.config_path, "--run-dir", str(self.run_dir)]
        if quants:
            cmd += ["--quants", ",".join(str(q) for q in quants)]
        self.teacher_ctl.stop()  # bench owns the GPU and serves its own models
        try:
            self._stream_subprocess(cmd, "bench")
        finally:
            self.teacher_ctl.start()
        report = json.loads(
            (self.run_dir / "bench_report.json").read_text(encoding="utf-8"))
        summary = {
            "device": report["device"],
            "holdout_n": report["holdout_n"],
            "quants": [{"quant": q["quant"], "size_mb": q["size_mb"],
                        "tg_ts": q.get("tg_ts"),
                        "exact_match": q["accuracy"]["exact_match"]}
                       for q in report["quants"]],
            "teacher_tg_ts": report.get("teacher", {}).get("tg_ts"),
            "chart": str(self.run_dir / "bench_chart.png"),
        }
        self.registry.append(self.spec.name, "bench", str(self.run_dir),
                             {"quants": quants}, summary)
        return summary

    def tool_list_experiments(self, task: str | None = None) -> dict:
        experiments = self.registry.list(task)
        if task and not experiments:
            known = sorted({e["task"] for e in self.registry.list()})
            return {"experiments": [],
                    "note": f"no experiments match task {task!r}",
                    "known_tasks": known}
        result = {"experiments": experiments}
        if self.spec is None and experiments:
            result["note"] = ("no build is loaded in this session yet — to "
                              "operate on one of these, call resume_build "
                              "with its experiment id")
        return result
