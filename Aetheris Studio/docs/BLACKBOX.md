# Blackbox: Flight Recorder, Egress Monitor, Time-Travel, Cartographer

Four features under one name, all opt-out, all additive around the existing agent loop -- see the root [`PROJECT_SPECIFICATION.md`](../../PROJECT_SPECIFICATION.md#5-blackbox-verifiable-runtime-privacy) for the positioning and the judging-rubric mapping. This doc is the technical detail: log format, the hash chain, and -- in the style already established by [`VTE/docs/LIMITATIONS.md`](../../VTE/docs/LIMITATIONS.md) -- an honest account of what each piece does and doesn't actually protect against.

## Flight Recorder

`core/audit/flight_recorder.py`. Append-only JSONL, one file per session (`<DATA_DIR>/audit/<session_id>.jsonl`), each line:

```json
{"seq": 3, "ts": 1784754158.56, "session_id": "...", "type": "turn_end",
 "actor": "kyuubyN", "payload": {"reason": "completed"},
 "prev_hash": "84ac75e5...", "hash": "d418c74b..."}
```

`hash = sha256(canonical_json(entry without "hash"))`. `canonical_json` = `json.dumps(obj, sort_keys=True, separators=(",", ":"))` -- deterministic serialization, required for the hash to be reproducible by an independent verifier. Genesis (`entry[0].prev_hash`) is a fixed constant (`sha256(b"aetheris-flight-recorder-genesis-v1")`), not derived from the session id -- simpler, and doesn't weaken what the chain actually proves (see below).

**Entry types**: `turn_start`, `first_token`, `turn_end` (with `reason`: `completed`/`disconnected`/`error`), `tool_call`/`tool_result` (digest + length only, never raw content -- see Invariant I5 below), `confirm_request`/`confirm_decision` (`approved`/`declined`), `egress_sample` (state-change only, not per-tick), `rollback` (via the same `tool_call`/`tool_result` pair, `tool: "rollback_action"`).

**Verification**: `GET /api/audit/{session_id}/verify` re-walks the chain server-side. `scripts/audit_verify.py` does the identical walk standalone -- stdlib only (`json`/`hashlib`/`argparse`), zero imports from `core/`, so a client who received a session log (the freelancer-under-NDA scenario) can verify it with nothing but Python installed, no Aetheris checkout required. The two implementations are a deliberate duplication, not shared code, for exactly that portability reason -- if the entry shape ever changes, both need updating by hand.

### What the chain protects, and what it doesn't

**Protects**: retroactive tampering. Editing, deleting, or reordering any entry breaks the hash link to everything after it, detected in O(n) by either verifier, and the verifier reports the *exact* first broken entry, not just "something's wrong somewhere."

**Does not protect**: authenticity against an attacker with root/administrator access to the machine that produced the log. Someone who can rewrite the whole `.jsonl` file can also recompute every hash consistently -- the chain proves internal consistency, not that this specific file is *the* file this session actually produced. This is a real, known limitation of hash chains without external anchoring, not an oversight. A partial mitigation (not built, documented as v2 future work): periodically anchor the head hash into a signed git commit, or surface it in the UI at the end of a session for the user to note down externally, so a later dispute has an independent reference point outside the file itself.

Also explicitly out of scope by design: anything that happens outside the Aetheris process. If a developer edits a file directly in VS Code while Aetheris is also open, that edit is invisible to the Flight Recorder -- it audits *the agent*, not the machine.

## Egress Monitor

`core/audit/egress_monitor.py`. Samples `psutil.net_connections(kind="inet")` about once a second, filtered to this process's PID plus the `vte-server` subprocess's PID (via `vte_bridge.get_server_pid()`), classifies each connection's remote address as loopback (`127.0.0.0/8`, `::1`) or external. State changes -- not every tick -- are logged to the Flight Recorder as `egress_sample` entries, so the "0 B" claim in the UI is itself part of the auditable trail, not just a number that resets on refresh.

**Layered honesty**: connection *enumeration* is what's actually reliable across platforms and is what backs the demo and the indicator. Per-connection *byte counts* are best-effort; when unavailable the indicator reports a connection count instead of a fabricated byte figure. Externals are labeled by known cause when possible (`browser tool (read-only, initiated by you)`, `model download (vte pull)`) rather than shown as unlabeled alarm text -- an unrecognized external connection is labeled `unknown`, which is deliberately the one case that should look alarming, since it's exactly what this monitor exists to catch.

Validated live on the RX 7600 (2026-07-22): a real chat session, real project, reported `0` external connections throughout, `2-3` loopback (the UI-backend-vte-server hops), confirmed against the real process tree, not assumed.

## Time-Travel

`core/audit/timetravel.py`. Every approved `write_file`/`write_files`/`edit_file` snapshots the touched files immediately before and after the real write, as commits on a git ref outside the normal namespace (`refs/aetheris/session-<id>`, not `refs/heads/*` -- invisible to `git branch`). The snapshot mechanism uses an isolated `GIT_INDEX_FILE` (a throwaway temp file under `<DATA_DIR>/timetravel/`) for `read-tree`/`add --force`/`write-tree`/`commit-tree`, so the user's real `.git/index` is never read or written. Undo (`rollback_action`, gated exactly like any other write per invariant I4) restores content via `git cat-file -p <commit>:<path>` written directly to the working-tree file -- **never `git checkout`**, which would move the user's actual HEAD or current branch.

**Invariant I3** (the user's real repo state never changes, except what they explicitly approved and kept) is the one this feature can least afford to get wrong. Proven two ways: an automated test (`Aetheris Studio/tests/test_timetravel.py`) against a disposable git fixture -- never a real project -- runs a simulated session of multiple snapshots and rollbacks and asserts `git status`/`git branch`/`git stash list`/tracked-blob content (`git ls-files -s`, not raw index bytes -- git's own "racily clean" stat-cache refresh legitimately rewrites index bytes on any `status` call after a file's mtime changes, unrelated to Time-Travel) come back byte-identical. Confirmed again on real hardware: a real model-issued `write_file` call on the RX 7600, approved through the real confirm gate, produced real `pre:`/`post:` shadow-ref commits, confirmed present via `git for-each-ref` and absent from `git branch -a`.

**v1 scope, stated plainly**: git repositories only -- outside one, `snapshot()` silently no-ops and writes proceed unprotected (the no-git filesystem-snapshot fallback is explicitly deferred, first thing cut under time pressure by design). Undo restores *content*; it doesn't reconstruct the deletion of a file that didn't exist in the target snapshot (a brand-new file's "pre" snapshot has no entry for it at all -- confirmed directly, `preview_rollback` against such a snapshot correctly shows a full-file removal diff, but `rollback` has nothing to write back). No redo: reverting by mistake means asking the agent to make the change again, which has the context to do so -- redo would reintroduce a meaningful slice of general-VCS complexity for a case this project judged not worth it yet.

## Cartographer

`core/rag/cartographer.py`. A background worker maps the active project file-by-file: cheap regex-based structural extraction (function/class/import names, no tree-sitter dependency) always runs; a 2-sentence LLM-generated responsibility summary runs on the same chat model already resident in VRAM, only while the chat itself is idle. The idle signal reuses the existing `core/event_bus.py` singleton (`chat_turn_start`/`chat_turn_end`, published from `agent.py`) plus a small in-memory flag for point-in-time checks between files -- there is no generation lock anywhere in this codebase to contend on instead, confirmed directly before building this.

Indexed with BM25 (`rank_bm25`) over the generated `MAP/*.md` documents. **Additive, not a replacement**: the skill library's own TF-IDF search (`core/memory/tfidf.py`, `manage_skill`) is untouched. Two retrieval paths, both real:

- **`search_map` tool (D.1)**: on-demand, the model decides when to call it. Same shape as `manage_memory`/`manage_skill`, zero new architecture.
- **Automatic pre-turn injection (D.2)**, `AETHERIS_CARTOGRAPHER_AUTO_INJECT`, its own sub-flag independent of the parent `AETHERIS_CARTOGRAPHER_ENABLED`: the top-3 BM25 matches for the turn's own last user message are injected as a labeled system message (`[CARTOGRAPHER MAP]: ...`) before generation. This is genuinely new context-assembly plumbing -- no automatic memory/skill injection precedent exists anywhere else in this codebase, confirmed by reading it, not assumed. Built anyway, deliberately, because the on-demand tool alone is unlikely to fix the specific failure this project's own README already documents: a vague prompt with no tool named for it has historically produced zero tool calls at all.

**A real BM25 quirk found while testing, not hidden**: `rank_bm25`'s classic Okapi IDF formula can floor a term's score contribution to exactly zero in a small corpus where the term appears in most/all documents (confirmed directly with a minimal repro, not assumed) -- normal for an early-stage or small project's map, not a bug. `query_map()` does not filter results by `score > 0` for this reason; rank order stays meaningful even when raw scores are tiny or tied.

Validated on the RX 7600: both files in a real scratch project were mapped in the background using the same resident Qwen2.5 1.5B model, producing real, on-topic summaries; `search_map` returned the correct, BM25-ranked document for a real query. **The vague-prompt A/B this feature exists to fix** (`"what does this codebase do"`, D.1-only vs. D.1+D.2, against a real, freshly-mapped subset of this project) was also run for real: D.1 alone reproduced the README's documented failure mode exactly (wrong tool attempted, zero real tool calls dispatched); D.2 answered directly and correctly, with zero tool calls, citing real function names from the mapped files. Full transcript and analysis: [`docs/UX_METRICS.md`](UX_METRICS.md#done-the-vague-prompt-ab-cartographer-uc-04-real-result-on-the-rx-7600).

## Test suite

`Aetheris Studio/tests/` (47 tests as of this writing): hash-chain tamper/reorder detection, cancellation-still-writes-`turn_end`, disabled-flag-is-a-true-no-op for every one of the four components, the Time-Travel I3 invariant against a disposable repo, end-to-end Cartographer mapping with a monkeypatched LLM call (no live GPU needed to run the suite), and the `tools.py` <-> Time-Travel integration path (`write_file`/`edit_file`/`rollback_action` actually creating and restoring real snapshots). Run: `.venv/Scripts/python.exe -m pytest tests/` from `Aetheris Studio/`.
