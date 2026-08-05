"""Enumerate every third-party project vendored under corpus/, and whether we may redistribute it.

WHY THIS EXISTS. `corpus/` is not Determinex's own code: it carries complete upstream checkouts of
~200 CLI tools, because the Native Reimplementation Loop feeds real source and real test oracles to
a model. That is the product. It also means publishing `corpus/` is REDISTRIBUTION of other
people's software, and MIT, BSD, ISC and Apache-2.0 all require the copyright notice and the
license text to travel with the code. Measured 2026-07-31: **409 of 457 vendored entries had no
LICENSE/COPYING at their root**, so publishing as-is would have breached the terms of most of them.

The repo also carries GPL-2.0-only (`stgit`) alongside Determinex's AGPL-3.0-or-later. That is not
a conflict here: they are separate programs in separate directories, distributed together — mere
aggregation, which both licenses permit. It would only become a conflict if the code were combined
into a single work, which nothing does.

WHAT THIS DOES NOT DO. It reports and it can fetch missing license texts from the pinned upstream
commit. It does not decide whether redistribution is lawful — the SPDX id is read from the
project's own manifest and the notice index is generated from that, so a human can review a list of
200 rows instead of 200 repositories.

    python scripts/release/third_party_corpus_audit.py                  # report the gap
    python scripts/release/third_party_corpus_audit.py --notices        # write THIRD_PARTY_NOTICES.md
    python scripts/release/third_party_corpus_audit.py --fetch-missing  # pull absent LICENSE texts
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

CORPUS = Path("corpus")
CANONICAL_TASKS = CORPUS / "programbench" / "canonical_tasks.json"
NOTICES_PATH = CORPUS / "THIRD_PARTY_NOTICES.md"

#: Where a vendored upstream tree can sit. Each glob's match is the tree ROOT.
VENDORED_ROOTS = (
    "programbench/per_tool_overrides/*",
    "programbench/locked/*/source",
    "programbench/locked/_superseded/*/source",
    "programbench/locked/tier_2_upstream_skips/*/source",
    "programbench/pending_unlock/*/*/source",
    "swebench/locked/*/source",
)

#: Filenames that count as the project's own license text.
LICENSE_NAMES = (
    "LICENSE",
    "LICENSE.txt",
    "LICENSE.md",
    "LICENSE-MIT",
    "LICENSE-APACHE",
    "COPYING",
    "COPYING.txt",
    "LICENCE",
    "LICENCE.txt",
    "UNLICENSE",
    "NOTICE",
)

#: Manifests we can read an SPDX identifier out of, in priority order.
_MANIFEST_LICENSE = (
    ("Cargo.toml", re.compile(r'^\s*license\s*=\s*"([^"]+)"', re.MULTILINE)),
    ("package.json", re.compile(r'"license"\s*:\s*"([^"]+)"')),
    (
        "pyproject.toml",
        re.compile(r'^\s*license\s*=\s*(?:\{\s*text\s*=\s*)?"([^"]+)"', re.MULTILINE),
    ),
    ("setup.py", re.compile(r'license\s*=\s*["\']([^"\']+)["\']')),
    ("go.mod", re.compile(r"^$", re.MULTILINE)),  # go.mod carries no license field; presence only
)

#: `owner__repo.commit` -> upstream identity, which is how nearly every tool dir is named.
_DIR_PROVENANCE = re.compile(
    r"^(?P<owner>[A-Za-z0-9_.-]+)__(?P<repo>[A-Za-z0-9_.-]+?)(?:\.(?P<commit>[0-9a-f]{7,40}))?$"
)


@dataclass
class Vendored:
    path: Path  # repo-relative tree root
    name: str
    spdx: str = ""
    license_files: list[str] = field(default_factory=list)
    owner: str = ""
    repo: str = ""
    commit: str = ""

    @property
    def upstream_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}" if self.owner and self.repo else ""

    @property
    def compliant(self) -> bool:
        """We may redistribute this tree as it stands."""
        return bool(self.license_files)


def _tracked(root: Path) -> set[str]:
    """Tracked paths under `root`.

    Read as BYTES and decoded explicitly. With `text=True` Python decodes using the console
    codepage (cp1252 here) and the corpus contains vendored filenames with bytes that codepage has
    no mapping for, so the reader thread dies with UnicodeDecodeError and stdout comes back None.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z", str(root)], cwd=_ROOT, capture_output=True, timeout=900
    )
    return {p for p in out.stdout.decode("utf-8", errors="replace").split("\0") if p}


def _load_canonical_provenance() -> dict[str, tuple[str, str]]:
    """task-ish key -> (repository, commit) from canonical_tasks.json.

    The manifest is authoritative where a directory name is ambiguous (a `.tar.gz` entry, or a dir
    with no commit suffix), which is why provenance is not taken from the path alone.
    """
    path = _ROOT / CANONICAL_TASKS
    if not path.is_file():
        return {}
    try:
        rows = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {}
    if isinstance(rows, dict):
        rows = rows.get("tasks") or list(rows.values())
    out: dict[str, tuple[str, str]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        repository = str(row.get("repository") or "").strip()
        commit = str(row.get("commit") or "").strip()
        if not repository:
            continue
        slug = repository.rstrip("/").removesuffix(".git").split("/")[-2:]
        if len(slug) == 2:
            out[f"{slug[0]}__{slug[1]}".lower()] = (repository, commit)
            out[slug[1].lower()] = (repository, commit)
    return out


def discover(tracked: set[str], provenance: dict[str, tuple[str, str]]) -> list[Vendored]:
    found: dict[str, Vendored] = {}
    for pattern in VENDORED_ROOTS:
        for tree in sorted((_ROOT / CORPUS).glob(pattern)):
            if not tree.is_dir():
                continue
            # `per_tool_overrides/*` also matches our own scaffolding (.vscode, _superseded, ...).
            # A vendored project is a third-party checkout, not every directory that sits there.
            if tree.name.startswith((".", "_")):
                continue
            rel = tree.relative_to(_ROOT).as_posix()
            if rel in found:
                continue
            # Only trees git actually tracks: an untracked scratch dir is not being published.
            if not any(t.startswith(rel + "/") for t in tracked):
                continue
            # `locked/<tool>/source` and `pending_unlock/<tier>/<tool>/source` name the tree
            # "source"; the project identity is the PARENT. Reading `tree.name` there gave 199
            # entries all called "source" with no resolvable provenance, so none of their licenses
            # could be fetched.
            identity = tree.parent.name if tree.name == "source" else tree.name
            entry = Vendored(path=tree.relative_to(_ROOT), name=identity)

            for fname, pattern_re in _MANIFEST_LICENSE:
                manifest = tree / fname
                if not manifest.is_file():
                    continue
                match = pattern_re.search(manifest.read_text(encoding="utf-8", errors="replace"))
                if match and match.group(0).strip():
                    try:
                        entry.spdx = match.group(1).strip()
                    except IndexError:
                        pass
                    if entry.spdx:
                        break

            entry.license_files = sorted(
                p.name
                for p in tree.iterdir()
                if p.is_file() and any(p.name.upper().startswith(n) for n in LICENSE_NAMES)
            )

            # Provenance: the directory name first, the canonical manifest as the fallback.
            m = _DIR_PROVENANCE.match(identity)
            if m:
                entry.owner = m.group("owner")
                entry.repo = m.group("repo")
                entry.commit = m.group("commit") or ""
            key = identity.lower().removesuffix(".tar.gz")
            if (not entry.owner or not entry.commit) and key in provenance:
                repository, commit = provenance[key]
                parts = repository.rstrip("/").removesuffix(".git").split("/")
                if len(parts) >= 2 and not entry.owner:
                    entry.owner, entry.repo = parts[-2], parts[-1]
                entry.commit = entry.commit or commit

            found[rel] = entry
    return list(found.values())


def publishable_manifest(entries: list[Vendored]) -> dict:
    """The redistribution boundary, as data the publish tooling can enforce.

    A tree with no license text is NOT published — not to GitHub, not to the dataset. That is the
    only defensible default: MIT, BSD, ISC and Apache-2.0 each require the copyright notice and
    license to accompany a redistribution, and we cannot supply what we do not have.

    Withholding costs little, because `determinex corpus fetch` reconstructs any tree from its own
    upstream at the pinned commit. The dataset is a convenience, not the only route to the source.
    """
    publishable, withheld = [], []
    for entry in sorted(entries, key=lambda e: e.name.lower()):
        row = {
            "name": entry.name,
            "path": entry.path.as_posix(),
            "spdx": entry.spdx,
            "upstream": entry.upstream_url,
            "commit": entry.commit,
            "license_files": entry.license_files,
        }
        (publishable if entry.compliant else withheld).append(row)
    return {
        "schema_version": "determinex-corpus-redistribution-boundary-v1",
        "rule": "a vendored tree is published only if it carries its own license text",
        "publishable_count": len(publishable),
        "withheld_count": len(withheld),
        "publishable": publishable,
        "withheld": withheld,
    }


def render_notices(entries: list[Vendored]) -> str:
    lines = [
        "# Third-Party Notices — `corpus/`",
        "",
        "Determinex itself is licensed **AGPL-3.0-or-later** (see [`LICENSE`](../LICENSE)). This",
        "directory is different: it carries complete upstream checkouts of the tools the Native",
        "Reimplementation Loop learns from, and **each one remains under its own license, held by its",
        "own copyright holders**. Nothing here is relicensed by inclusion.",
        "",
        "These are separate programs distributed alongside Determinex — *mere aggregation*, which",
        "both the GPL family and Determinex's AGPL permit. No vendored source is linked into, or",
        "combined with, Determinex's own code.",
        "",
        "Generated by `scripts/release/third_party_corpus_audit.py --notices`. Do not hand-edit.",
        "",
        f"**{sum(1 for e in entries if e.compliant)} vendored projects published** of "
        f"{len(entries)} present in this working tree; the remainder are withheld and listed at "
        "the end with the reason.",
        "",
        "| Project | License | Upstream | Pinned commit | License text |",
        "| --- | --- | --- | --- | --- |",
    ]
    published = [e for e in entries if e.compliant]
    withheld = [e for e in entries if not e.compliant]
    for e in sorted(published, key=lambda x: x.name.lower()):
        url = f"[{e.owner}/{e.repo}]({e.upstream_url})" if e.upstream_url else "—"
        commit = f"`{e.commit[:12]}`" if e.commit else "—"
        texts = ", ".join(f"`{f}`" for f in e.license_files)
        lines.append(f"| `{e.name}` | {e.spdx or '_undeclared_'} | {url} | {commit} | {texts} |")

    if withheld:
        lines += [
            "",
            f"## Withheld from redistribution ({len(withheld)})",
            "",
            "These vendored trees carry **no license text**, so they are not published — not here",
            "and not in the dataset. MIT, BSD, ISC and Apache-2.0 each require the copyright notice",
            "and the license to accompany a redistribution, and we cannot supply what we do not",
            "have.",
            "",
            "Withholding them costs little: `determinex corpus fetch <tool>` reconstructs any tree",
            "from its own upstream at the pinned commit, so the source stays reachable from the",
            "people who own it.",
            "",
            "| Project | Declared license | Why withheld |",
            "| --- | --- | --- |",
        ]
        for e in sorted(withheld, key=lambda x: x.name.lower()):
            why = (
                "no license file in the tree, and no upstream provenance to fetch one from"
                if not e.upstream_url
                else f"no license file found upstream at {e.owner}/{e.repo}"
            )
            lines.append(f"| `{e.name}` | {e.spdx or '_undeclared_'} | {why} |")
    lines.append("")
    return "\n".join(lines)


def fetch_license(entry: Vendored, timeout: int = 60) -> tuple[bool, str]:
    """Retrieve the project's own license text from its pinned upstream commit.

    The license that must travel with a redistributed tree is the one that tree shipped with, so
    this reads it from the exact commit rather than substituting a canonical SPDX body — an SPDX
    template carries no copyright line, and the copyright line is precisely what MIT and BSD
    require to be preserved.
    """
    if not entry.owner or not entry.repo:
        return False, "no upstream provenance"
    ref = entry.commit or "HEAD"
    # Projects do not agree on where the license lives. The first pass tried six names and left 40
    # projects "missing" that plainly ship one: pandoc uses COPYRIGHT, 7zip uses License.txt, lua
    # puts it under doc/, several Rust crates dual-license via LICENSE-MIT + LICENSE-APACHE. Raw
    # GitHub is case-sensitive, so the casings are enumerated rather than assumed.
    for name in (
        "LICENSE",
        "LICENSE.txt",
        "LICENSE.md",
        "LICENSE.rst",
        "License.txt",
        "License",
        "license",
        "license.txt",
        "COPYING",
        "COPYING.txt",
        "Copying",
        "COPYRIGHT",
        "COPYRIGHT.txt",
        "Copyright",
        "LICENCE",
        "LICENCE.txt",
        "UNLICENSE",
        "LICENSE-MIT",
        "LICENSE-APACHE",
        "LICENSE.APACHE2",
        "LICENSE.MIT",
        "doc/COPYRIGHT",
        "docs/LICENSE",
        "LICENSES/LICENSE",
        "legal/LICENSE",
    ):
        url = f"https://raw.githubusercontent.com/{entry.owner}/{entry.repo}/{ref}/{name}"
        try:
            # Bytes, not text: a license file can carry non-cp1252 characters (accented copyright
            # holders are common) and Python would otherwise decode with the console codepage and
            # hand back None. Written through verbatim so the notice is byte-identical to upstream.
            proc = subprocess.run(
                ["curl", "-fsSL", "--max-time", str(timeout), url],
                capture_output=True,
                timeout=timeout + 15,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0 and proc.stdout and proc.stdout.strip():
            # Nested upstream paths (doc/COPYRIGHT) are written flat at the tree root, because
            # that is where the redistribution notice has to be visible and where the audit looks.
            dest = _ROOT / entry.path / Path(name).name
            dest.write_bytes(proc.stdout)
            return True, name
    return False, f"no license file found upstream at {entry.owner}/{entry.repo}@{ref[:12]}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--notices", action="store_true", help=f"write {NOTICES_PATH}")
    parser.add_argument(
        "--fetch-missing",
        action="store_true",
        help="download absent LICENSE texts from the pinned upstream commit",
    )
    parser.add_argument("--limit", type=int, default=0, help="with --fetch-missing, stop after N")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="write the publish/withhold boundary as JSON for the publish tooling",
    )
    args = parser.parse_args()

    print("enumerating tracked corpus files ...")
    tracked = _tracked(CORPUS)
    provenance = _load_canonical_provenance()
    entries = discover(tracked, provenance)
    print(f"  {len(entries)} vendored project trees, {len(provenance)} provenance records\n")

    missing = [e for e in entries if not e.compliant]
    no_provenance = [e for e in missing if not e.upstream_url]
    undeclared = [e for e in entries if not e.spdx]

    print(f"  license text present : {len(entries) - len(missing)}/{len(entries)}")
    print(f"  license text MISSING : {len(missing)}")
    print(f"    of which no upstream provenance to fetch from: {len(no_provenance)}")
    print(f"  SPDX undeclared      : {len(undeclared)}")

    if args.fetch_missing:
        print("\nfetching missing license texts from pinned upstream commits ...")
        ok = failed = 0
        for i, entry in enumerate(missing):
            if args.limit and i >= args.limit:
                break
            got, detail = fetch_license(entry)
            if got:
                ok += 1
                print(f"  OK   {entry.name} <- {detail}")
            else:
                failed += 1
                print(f"  MISS {entry.name}: {detail}")
        print(f"\nfetched {ok}, still missing {failed}")
        entries = discover(tracked, provenance)
        missing = [e for e in entries if not e.compliant]

    if args.manifest:
        out = args.manifest if args.manifest.is_absolute() else _ROOT / args.manifest
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(publishable_manifest(entries), indent=2) + "\n", encoding="utf-8")
        print(f"\nwrote {args.manifest}")

    if args.notices:
        out = _ROOT / NOTICES_PATH
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_notices(entries), encoding="utf-8")
        print(f"\nwrote {NOTICES_PATH} ({len(entries)} projects)")

    if missing:
        # A withheld tree is a HANDLED case, not a failure: the boundary manifest excludes it from
        # publication and THIRD_PARTY_NOTICES.md records why. Reporting it as a hard error would
        # make the release gate unsatisfiable for a corpus that is behaving correctly.
        print(
            f"\n{len(missing)} project(s) carry no license text and are WITHHELD from "
            "publication (listed in corpus/THIRD_PARTY_NOTICES.md)."
        )
        for entry in missing[:10]:
            print(f"  {entry.name}  (declared: {entry.spdx or 'undeclared'})")
        if len(missing) > 10:
            print(f"  ... and {len(missing) - 10} more")
        return 1
    print("\nEvery vendored project carries its own license text.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
