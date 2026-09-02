"""Synthetic example generation, spec-driven: facet prompts, hard
validation, dedupe, and an inspectable reject pile.

Diversity is controlled by the facet sampler, not left to the model:
each request pins a target value of the spec's balance field plus
persona/tone/length facets, so class balance is a property of the code.
`focus` oversamples given balance values ~2:1 — the hook the agent's
targeted-regeneration loop uses after diagnosing weak classes.
"""

import json
import random
import re
import string
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import task
from .spec import TaskSpec
from .teacher import TeacherClient

MAX_SEED_DOC_BYTES = 256 * 1024

GEN_SYSTEM = (
    "You write realistic synthetic training examples and label them exactly "
    "according to the provided reference material. Respond with a single "
    "JSON object only."
)

GEN_USER_TEMPLATE = """Here is the reference material for the task:

---
{seeds}
---

Task: {description}

Write ONE realistic {example_noun} from: {persona}.
Tone: {tone}. Length: {length}. Wrinkle: {wrinkle}.
Situation: {situation}.

{guidance}
The example must genuinely require output "{balance_field}": "{target_value}"
under the reference material. Derive every other output field from the
reference material rules, not from surface urgency or phrasing.

Return JSON with exactly these keys:
{{"{input_field}": "<the {example_noun} text, no headers or signatures>",
  {output_keys},
  "rationale": "<one sentence citing the reference rule you applied>"}}"""


def load_seed_docs(paths: list, repo_root: Path) -> list[tuple[str, str]]:
    """Boundary check: seed docs are untrusted input. Returns (name, text)."""
    docs = []
    for p in paths:
        path = Path(p)
        if not path.is_absolute():
            path = repo_root / path
        if not path.exists():
            raise FileNotFoundError(f"seed doc not found: {path}")
        size = path.stat().st_size
        if size == 0 or size > MAX_SEED_DOC_BYTES:
            raise ValueError(
                f"seed doc size {size} bytes outside (0, {MAX_SEED_DOC_BYTES}]: {path}"
            )
        docs.append((path.name, path.read_text(encoding="utf-8", errors="strict")))
    return docs


def _normalize(text: str) -> str:
    text = text.lower().translate(str.maketrans("", "", string.punctuation))
    return re.sub(r"\s+", " ", text).strip()


def _shingles(norm: str, n: int = 3) -> set:
    words = norm.split()
    if len(words) < n:
        return {norm}
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


class Deduper:
    def __init__(self, jaccard_threshold: float = 0.6):
        self.threshold = jaccard_threshold
        self.exact = set()
        self.pool = []

    def check(self, text: str) -> str | None:
        norm = _normalize(text)
        if norm in self.exact:
            return "exact_duplicate"
        sh = _shingles(norm)
        for other in self.pool:
            inter = len(sh & other)
            union = len(sh | other)
            if union and inter / union > self.threshold:
                return "near_duplicate"
        self.exact.add(norm)
        self.pool.append(sh)
        return None


def _validate(spec: TaskSpec, raw: str):
    obj, reason = task._balanced_json(raw)
    if obj is None:
        return None, reason
    text = obj.get(spec.input_field, "")
    lo, hi = spec.input_length
    if not isinstance(text, str) or not (lo <= len(text) <= hi):
        return None, f"input_length:{len(text) if isinstance(text, str) else 'nonstr'}"
    example = {spec.input_field: text.strip()}
    for field, fs in spec.output_schema.items():
        if field not in obj:
            return None, f"missing_field:{field}"
        val = str(obj[field]).strip()
        if fs["type"] == "enum":
            match = next((v for v in fs["values"] if v.lower() == val.lower()), None)
            if match is None:
                return None, f"bad_value:{field}:{val}"
            example[field] = match
        else:
            if not val:
                return None, f"empty_field:{field}"
            example[field] = val
    return example, None


def _output_keys_line(spec: TaskSpec) -> str:
    parts = []
    for field, fs in spec.output_schema.items():
        if fs["type"] == "enum":
            parts.append(f'"{field}": "<one of: {", ".join(fs["values"])}>"')
        else:
            parts.append(f'"{field}": "<string>"')
    return ",\n  ".join(parts)


def _value_sequence(spec: TaskSpec, focus: list | None):
    """Infinite-ish generator of balance-field target values.

    Round-robin over all values; with focus, 2 of every 3 picks cycle
    the focus values instead (targeted regeneration).
    """
    all_vals, i, j = spec.balance_values, 0, 0
    while True:
        if focus and (i % 3) != 2:
            yield focus[j % len(focus)]
            j += 1
        else:
            yield all_vals[i % len(all_vals)]
        i += 1


def generate(cfg: dict, run_dir: Path, spec: TaskSpec,
             focus: list | None = None, augment: bool = False,
             progress_cb=None) -> dict:
    """Generate the dataset. Writes train.jsonl, holdout.jsonl, rejects.jsonl.

    augment=True appends n_train NEW examples to the existing train.jsonl
    (deduped against everything already in the run) and leaves holdout.jsonl
    untouched, so before/after evals stay comparable.
    """
    from .config import REPO_ROOT

    from .retrieval import build_chunks, render, select

    rng = random.Random(cfg["run"]["seed"])
    docs = load_seed_docs(spec.seed_docs, REPO_ROOT)
    corpus_chars = sum(len(t) for _, t in docs)
    budget = cfg["datagen"].get("context_budget_chars", 6000)
    retrieval_active = corpus_chars > budget
    if retrieval_active:
        chunks = build_chunks(docs)
        print(f"datagen: retrieval ON — corpus {corpus_chars} chars > "
              f"budget {budget}, {len(chunks)} chunks", flush=True)
    else:
        whole_corpus = "\n\n".join(t for _, t in docs)
    existing_train = []
    if augment:
        train_path = run_dir / "train.jsonl"
        if not train_path.exists():
            raise RuntimeError("augment requested but no train.jsonl exists yet")
        existing_train = [json.loads(l) for l in open(train_path, encoding="utf-8")]
        existing_holdout = [json.loads(l) for l in
                            open(run_dir / "holdout.jsonl", encoding="utf-8")]
        n_target = cfg["datagen"]["n_train"]
    else:
        n_target = cfg["datagen"]["n_train"] + cfg["datagen"]["n_holdout"]
    max_attempts = n_target * cfg["datagen"]["max_attempts_factor"]

    client = TeacherClient(cfg["teacher"]["base_url"])
    deduper = Deduper()
    if augment:
        for row in existing_train + existing_holdout:
            deduper.check(row[spec.input_field])
    accepted, n_attempts = [], 0
    rejects_path = run_dir / "rejects.jsonl"
    accepted_path = run_dir / "accepted.jsonl"
    values = _value_sequence(spec, focus)
    facets = spec.facets
    output_keys = _output_keys_line(spec)

    def one_request(i: int, target_value: str) -> tuple[str, list]:
        facet_rng = random.Random(cfg["run"]["seed"] * 100003 + i)
        situations = facets["situations"].get(
            target_value, ["as the target output implies"]
        )
        situation = facet_rng.choice(situations)
        if retrieval_active:
            enum_vocab = " ".join(
                v for vals in spec.enum_fields().values() for v in vals)
            query = (f"{target_value} {situation} {spec.balance_field} "
                     f"{spec.description} "
                     + " ".join(spec.output_fields()) + " " + enum_vocab)
            picked = select(chunks, query, budget)
            seeds_text = render(picked)
            sections = [f"{c['doc']}:{c['title']}" for c in picked]
        else:
            seeds_text, sections = whole_corpus, []
        prompt = GEN_USER_TEMPLATE.format(
            seeds=seeds_text,
            description=spec.description,
            example_noun=spec.example_noun,
            persona=facet_rng.choice(facets["personas"]),
            tone=facet_rng.choice(facets["tones"]),
            length=facet_rng.choice(facets["lengths"]),
            wrinkle=facet_rng.choice(facets["wrinkles"]),
            situation=situation,
            guidance=spec.datagen_guidance,
            balance_field=spec.balance_field,
            target_value=target_value,
            input_field=spec.input_field,
            output_keys=output_keys,
        )
        raw = client.chat(
            [{"role": "system", "content": GEN_SYSTEM},
             {"role": "user", "content": prompt}],
            temperature=cfg["teacher"]["temperature"],
            max_tokens=cfg["teacher"]["max_tokens"],
            json_mode=True,
            chat_template_kwargs=cfg["teacher"].get("chat_template_kwargs"),
        )
        return raw, sections

    with open(rejects_path, "w", encoding="utf-8") as rej, \
         open(accepted_path, "w", encoding="utf-8") as acc, \
         ThreadPoolExecutor(max_workers=cfg["teacher"]["parallel"]) as pool:
        while len(accepted) < n_target and n_attempts < max_attempts:
            remaining = n_target - len(accepted)
            batch = min(cfg["teacher"]["parallel"] * 4,
                        max(remaining, min(remaining + 8, cfg["teacher"]["parallel"])))
            futures = [
                pool.submit(one_request, n_attempts + j, next(values))
                for j in range(batch)
            ]
            n_attempts += batch
            for fut in as_completed(futures):
                raw, sections = fut.result()
                example, reason = _validate(spec, raw)
                if example is None:
                    rej.write(json.dumps({"reason": reason, "raw": raw}) + "\n")
                    continue
                dup = deduper.check(example[spec.input_field])
                if dup:
                    rej.write(json.dumps({"reason": dup, "raw": raw}) + "\n")
                    continue
                if sections:  # retrieval provenance, ignored by train/eval
                    example["_sections"] = sections
                accepted.append(example)
                acc.write(json.dumps(example) + "\n")
            line = (f"datagen: {len(accepted)}/{n_target} accepted, "
                    f"{n_attempts} attempts")
            print(line, flush=True)
            if progress_cb:
                progress_cb(line)

    if len(accepted) < n_target:
        raise RuntimeError(
            f"datagen exhausted {max_attempts} attempts with only "
            f"{len(accepted)}/{n_target} accepted — inspect {rejects_path}"
        )

    if augment:
        train = existing_train + accepted
        holdout = existing_holdout
        with open(run_dir / "train.jsonl", "w", encoding="utf-8") as f:
            for row in train:
                f.write(json.dumps(row) + "\n")
    else:
        rng.shuffle(accepted)
        holdout = accepted[: cfg["datagen"]["n_holdout"]]
        train = accepted[cfg["datagen"]["n_holdout"] :]
        for name, rows in (("train.jsonl", train), ("holdout.jsonl", holdout)):
            with open(run_dir / name, "w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row) + "\n")

    stats = {
        "mode": "augment" if augment else "fresh",
        "retrieval": {"active": retrieval_active, "corpus_chars": corpus_chars,
                      "budget_chars": budget,
                      **({"chunks": len(chunks)} if retrieval_active else {})},
        "attempts": n_attempts,
        "accepted": len(accepted),
        "train": len(train),
        "holdout": len(holdout),
        "acceptance_rate": len(accepted) / n_attempts,
        "focus": focus,
        "balance_counts": {
            v: sum(1 for e in accepted if e[spec.balance_field] == v)
            for v in spec.balance_values
        },
    }
    (run_dir / "datagen_stats.json").write_text(json.dumps(stats, indent=2))
    print(f"datagen: done — {json.dumps(stats, indent=2)}", flush=True)
    return stats
