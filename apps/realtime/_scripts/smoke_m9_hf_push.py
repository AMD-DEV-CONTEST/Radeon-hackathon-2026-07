"""M9.5 smoke — push a local LeRobot dataset to HF Hub end-to-end.

Covers:
  1. GET  /api/v1/datasets/hf/status     — token + whoami ok
  2. POST /api/v1/datasets/{id}/push_to_hub
       - targets the smallest on-disk recording so we don't upload GBs
       - private=True so the smoke artefact isn't public
  3. GET  /api/v1/datasets/{id}           — hf_repo_id persisted in meta
  4. CLEAN — delete the HF repo we just created so smoke runs are idempotent
             and don't leave a trail of "botversex-smoke-*" repos in the user's
             HF account.

Re-uses the M9.4 smoke user (smoke_m94@botversex.dev) so we stay under
/auth/register rate limits.
"""
from __future__ import annotations

import os
import sys
import time

import httpx

API = os.environ.get("BOTVERSEX_API", "http://127.0.0.1:8000")
SMOKE_EMAIL = "smoke_m94@botversex.dev"
SMOKE_PASSWORD = "smoke-password-123!"
SMOKE_REPO_PREFIX = "botversex-smoke-hf-"


def _client() -> httpx.Client:
    # trust_env=False keeps SOCKS proxies from hijacking our loopback call.
    return httpx.Client(base_url=API, timeout=120.0, trust_env=False)


def _auth(c: httpx.Client) -> str:
    r = c.post(
        "/api/v1/auth/login",
        json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD},
    )
    if r.status_code != 200:
        r = c.post(
            "/api/v1/auth/register",
            json={
                "email": SMOKE_EMAIL,
                "password": SMOKE_PASSWORD,
                "display_name": "smoke m9",
            },
        )
        r.raise_for_status()
        r = c.post(
            "/api/v1/auth/login",
            json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD},
        )
        r.raise_for_status()
    return r.json()["access_token"]


def _smallest_local_dataset(c: httpx.Client, headers: dict) -> dict:
    """Pick the dataset with the fewest frames — keeps the upload cheap."""
    r = c.get("/api/v1/datasets?rescan=true&limit=500", headers=headers)
    r.raise_for_status()
    items = r.json().get("items") or []
    if not items:
        raise RuntimeError(
            "no local datasets found. record one first via the UI or "
            "apps/realtime/_scripts/smoke_m2_* helpers."
        )
    items.sort(key=lambda d: d.get("frame_count") or 0)
    return items[0]


def _cleanup_hf(repo_id: str) -> None:
    """Best-effort delete of the smoke HF repo so we don't pile up garbage.

    Pulls the token straight from apps/api/.env the same way the service
    does, so the smoke script doesn't need any extra env setup.
    """
    from pathlib import Path

    token = os.environ.get("HF_TOKEN", "")
    if not token:
        here = Path(__file__).resolve()
        env_path = here.parents[3] / "apps" / "api" / ".env"
        if env_path.is_file():
            for line in env_path.read_text().splitlines():
                if line.startswith("HF_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not token:
        print(f"  [cleanup] HF_TOKEN not found — leaving {repo_id} in place")
        return
    # Scrub SOCKS proxy before importing huggingface_hub so httpx doesn't
    # demand socksio.
    for k in ("ALL_PROXY", "all_proxy", "SOCKS_PROXY", "socks_proxy"):
        os.environ.pop(k, None)
    try:
        from huggingface_hub import HfApi  # type: ignore

        HfApi(token=token).delete_repo(repo_id=repo_id, repo_type="dataset")
        print(f"  [cleanup] deleted HF repo {repo_id}")
    except Exception as e:
        print(f"  [cleanup] failed to delete {repo_id}: {e}")


def main() -> int:
    with _client() as c:
        tok = _auth(c)
        H = {"Authorization": f"Bearer {tok}"}

        # 1. hf/status
        print("[1/4] GET /datasets/hf/status")
        r = c.get("/api/v1/datasets/hf/status", headers=H)
        r.raise_for_status()
        st = r.json()
        print(f"      ok={st['ok']} user={st.get('username')!r}  msg={st.get('message')}")
        if not st.get("ok"):
            print("ABORT: HF token not valid — set HF_TOKEN in apps/api/.env")
            return 2

        # 2. pick dataset + push
        ds = _smallest_local_dataset(c, H)
        print(
            f"[2/4] POST /datasets/{ds['dataset_id']}/push_to_hub  "
            f"(frames={ds.get('frame_count')})"
        )
        # Use a unique, timestamped repo name so consecutive smoke runs
        # don't step on each other before cleanup.
        stamp = int(time.time())
        repo_name = f"{SMOKE_REPO_PREFIX}{stamp}"
        r = c.post(
            f"/api/v1/datasets/{ds['dataset_id']}/push_to_hub",
            headers=H,
            json={"repo_name": repo_name, "private": True},
        )
        r.raise_for_status()
        push = r.json()
        print(
            f"      ok={push.get('ok')} repo={push.get('repo_id')}  "
            f"bytes={push.get('bytes_uploaded')}  private={push.get('private')}"
        )
        if not push.get("ok"):
            print(f"ABORT: push failed — {push.get('error')}")
            return 3
        repo_id = push["repo_id"]

        # 3. verify persisted meta
        print(f"[3/4] GET  /datasets/{ds['dataset_id']} — verify hf_repo_id persisted")
        r = c.get(f"/api/v1/datasets/{ds['dataset_id']}", headers=H)
        r.raise_for_status()
        after = r.json()
        if after.get("hf_repo_id") != repo_id:
            print(f"ABORT: expected hf_repo_id={repo_id}, got {after.get('hf_repo_id')!r}")
            _cleanup_hf(repo_id)
            return 4
        print(f"      hf_repo_id persisted ✓  hf_url={after.get('hf_url')}")

        # 4. cleanup — delete the smoke repo on HF side
        print(f"[4/4] cleanup: delete {repo_id}")
        _cleanup_hf(repo_id)

    print("\nM9.5 smoke PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
