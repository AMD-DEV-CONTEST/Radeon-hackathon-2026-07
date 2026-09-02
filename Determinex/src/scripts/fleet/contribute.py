"""
fleet.contribute -- consent-first client. Nothing leaves the machine un-obfuscated,
unencrypted, or unconfirmed.
====================================================================================
Pipeline (contributor side):

  raw verified item (lang, files, pair)
    -> Cloak obfuscation (every real identifier -> opaque token); FAIL CLOSED if it
       cannot fully obfuscate (we never fall back to sending plaintext)
    -> consent preview: print the EXACT obfuscated payload that would be sent
    -> explicit opt-in required (--yes); default is dry-run (seal to disk only)
    -> seal to the node's PUBLIC key (fleet.crypto)
    -> hand the sealed envelope to a transport (file / Cloudflare Worker URL)

Run `python -m fleet.contribute --help`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from determinex_cloak import CloakObfuscationError, build_cloak_context  # noqa: E402

from . import crypto  # noqa: E402
from .protocol import ContributionItem, Shard  # noqa: E402

CONSENT_TEXT = (
    "By contributing you confirm you have the right to share this code, that you opt in\n"
    "to its use for training Determinex models, and that you understand identifiers have\n"
    "been replaced by opaque tokens (Cloak) but logic/structure is preserved. See\n"
    "docs/fleet/CONTRIBUTING.md and docs/fleet/PRIVACY.md."
)


# Test-framework discovery contracts that must survive obfuscation, else the node
# cannot re-run the tests. Python: `test_*`/`Test*`; Go: `Test*`/`Benchmark*`. We keep
# the prefix (a framework contract, not proprietary) and hide the rest of the name.
_DISCOVERY_PREFIXES = {
    "python": (("test_", "test_"), ("Test", "Test")),
    "go": (("Test", "Test"), ("Benchmark", "Benchmark"), ("Example", "Example")),
}


def _discovery_safe_remap(lang: str, forward: dict[str, str]) -> dict[str, str]:
    """Map obf-token -> discovery-safe token for names the test runner keys on.
    e.g. python `test_my_secret` -> `x_0002` -> `test_x_0002` (discoverable, hidden)."""
    rules = _DISCOVERY_PREFIXES.get(lang.lower())
    if not rules:
        return {}
    remap: dict[str, str] = {}
    for original, obf in forward.items():
        for orig_prefix, keep_prefix in rules:
            if original.startswith(orig_prefix) and not obf.startswith(keep_prefix):
                remap[obf] = f"{keep_prefix}{obf}"
                break
    return remap


def _apply_remap(text: str, remap: dict[str, str]) -> str:
    for obf, safe in remap.items():
        text = re.sub(rf"\b{re.escape(obf)}\b", safe, text)
    return text


def cloak_item(
    lang: str, files: dict[str, str], pair: dict[str, Any], origin: str = "unknown"
) -> ContributionItem:
    """Obfuscate one item end to end. Raises CloakObfuscationError (fail closed)."""
    with tempfile.TemporaryDirectory(prefix="fleet_cloak_") as td:
        repo = Path(td)
        for rel, content in files.items():
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        ctx = build_cloak_context("fleet", repo, language=lang)
        obf_files = {
            rel: ctx.obfuscate_source_str(content, cache_key=rel) for rel, content in files.items()
        }
        # obfuscate any free-text turns in the training pair too
        obf_pair = json.loads(json.dumps(pair))  # deep copy
        for turn in obf_pair.get("conversations", []):
            if isinstance(turn.get("value"), str):
                turn["value"] = ctx.obfuscate_text(turn["value"])
        # preserve test-discovery contracts so the node can re-verify
        forward = getattr(ctx.symbol_map, "forward", {}) or {}
        remap = _discovery_safe_remap(lang, forward)
        if remap:
            obf_files = {rel: _apply_remap(c, remap) for rel, c in obf_files.items()}
            for turn in obf_pair.get("conversations", []):
                if isinstance(turn.get("value"), str):
                    turn["value"] = _apply_remap(turn["value"], remap)
    return ContributionItem(lang=lang, files=obf_files, pair=obf_pair, origin=origin)


def build_shard(raw_items: list[dict[str, Any]], handle: str = "anonymous") -> Shard:
    items: list[ContributionItem] = []
    for r in raw_items:
        items.append(cloak_item(r["lang"], r["files"], r["pair"], r.get("origin", "unknown")))
    return Shard(items=items, contributor_handle=handle, cloak_applied=True)


def render_preview(shard: Shard) -> str:
    out = [
        "=== EXACT PAYLOAD TO BE SENT (Cloak-obfuscated) ===",
        f"shard: {shard.summary()}  handle={shard.contributor_handle}",
        "",
    ]
    for i, item in enumerate(shard.items, 1):
        out.append(f"--- item {i}/{len(shard.items)}  [{item.lang}]  id={item.id[:12]} ---")
        for rel, content in item.files.items():
            out.append(f"  file {rel}:")
            out += ["    " + ln for ln in content.splitlines()]
        out.append("  pair.conversations:")
        for turn in item.pair.get("conversations", []):
            out.append(f"    [{turn.get('from')}] {str(turn.get('value'))[:200]}")
        out.append("")
    return "\n".join(out)


def contribute(
    raw_items: list[dict[str, Any]],
    node_pub_b64: str,
    *,
    handle: str = "anonymous",
    yes: bool = False,
    out_path: Path | None = None,
    post_url: str | None = None,
) -> dict[str, Any]:
    """Returns the sealed envelope. Sends it only with explicit opt-in (`yes`)."""
    shard = build_shard(raw_items, handle=handle)
    shard.consent = {"agreed": yes, "text": CONSENT_TEXT}
    print(render_preview(shard))
    print(CONSENT_TEXT)

    env = crypto.seal_json(node_pub_b64, shard.to_dict())

    if not yes:
        # dry-run: seal to disk for inspection, do NOT transmit
        dest = out_path or Path("fleet_shard.sealed.json")
        dest.write_text(json.dumps(env, indent=2), encoding="utf-8")
        print(f"\n[dry-run] sealed shard written to {dest} -- NOT sent.")
        print("Re-run with --yes to transmit (explicit opt-in).")
        return env

    if post_url:
        _post(post_url, env)
        print(f"\n[sent] sealed shard POSTed to {post_url}")
    else:
        dest = out_path or Path("fleet_shard.sealed.json")
        dest.write_text(json.dumps(env), encoding="utf-8")
        print(f"\n[sent] sealed shard written to {dest} (no transport URL configured)")
    return env


def _post(url: str, env: dict[str, Any]) -> None:
    import urllib.request

    data = json.dumps(env).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:  # nosec - contributor-initiated
        r.read()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Determinex fleet contribution client")
    ap.add_argument(
        "--items", type=Path, required=True, help="JSON file: list of {lang, files, pair, origin}"
    )
    ap.add_argument("--node-pub", required=True, help="node public key (base64)")
    ap.add_argument("--handle", default="anonymous")
    ap.add_argument("--yes", action="store_true", help="explicit opt-in: actually send")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--post-url", default=None, help="Cloudflare Worker ingest URL")
    a = ap.parse_args(argv)
    raw_items = json.loads(a.items.read_text(encoding="utf-8"))
    try:
        contribute(
            raw_items, a.node_pub, handle=a.handle, yes=a.yes, out_path=a.out, post_url=a.post_url
        )
    except CloakObfuscationError as e:
        print(f"REFUSED (fail closed): could not fully obfuscate -- {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
