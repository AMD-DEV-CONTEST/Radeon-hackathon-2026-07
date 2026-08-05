#!/usr/bin/env python3
"""determinex_queue.py — Redis/Postgres-backed work queue (replaces text files).

Replaces /root/queue/*.txt + claim_next.sh + mark_done.sh.

Backends: redis://... or postgresql://... (auto-detected from QUEUE_URL).

Commands:
  enqueue --tier light --priority 1 INSTANCE...
  enqueue-from-file FILE
  claim WORKER [--tier light|heavy|any]
  done INSTANCE --score "X/Y=Z%" --rc 0 --dur 600
  stats
  status   # alias for stats
  reset
  list pending|claimed|done

Postgres uses SKIP LOCKED for atomic atomic claim_next.
Redis uses BLPOP for atomic claim (simpler but no priority).
"""

from __future__ import annotations

import argparse
import os
import time


def _redis():
    import redis  # type: ignore[import-not-found]

    url = os.environ.get("QUEUE_URL", "redis://localhost:6379/0")
    return redis.from_url(url, decode_responses=True)


def _pg():
    import psycopg  # type: ignore[import-not-found]

    url = os.environ.get(
        "QUEUE_URL", "postgresql://determinex:determinex@localhost:5432/determinex"
    )
    return psycopg.connect(url, autocommit=True)


def _backend() -> str:
    url = os.environ.get("QUEUE_URL", "redis://")
    if url.startswith("postgres"):
        return "pg"
    return "redis"


# ── Redis impl ─────────────────────────────────────────────────────────────
def redis_enqueue(insts: list[str], tier: str, priority: int):
    r = _redis()
    queue_key = f"determinex:queue:{tier}"
    for inst in insts:
        r.rpush(queue_key, inst)
        r.hset(
            f"determinex:tool:{inst}",
            mapping={
                "tier": tier,
                "priority": priority,
                "status": "pending",
                "enqueued_at": time.time(),
            },
        )
    print(f"enqueued {len(insts)} into {tier}")


def redis_claim(worker: str, tier: str) -> str | None:
    r = _redis()
    candidates = (
        [f"determinex:queue:{tier}"]
        if tier != "any"
        else ["determinex:queue:heavy", "determinex:queue:light"]
    )
    for q in candidates:
        inst = r.lpop(q)
        if inst:
            r.hset(
                f"determinex:tool:{inst}",
                mapping={
                    "status": "claimed",
                    "claimed_by": worker,
                    "claimed_at": time.time(),
                },
            )
            return inst
    return None


def redis_done(inst: str, score: str, rc: int, dur: int):
    r = _redis()
    r.hset(
        f"determinex:tool:{inst}",
        mapping={
            "status": "done",
            "score": score,
            "rc": rc,
            "duration_s": dur,
            "done_at": time.time(),
        },
    )
    r.rpush("determinex:queue:done", inst)


def redis_stats():
    r = _redis()
    return {
        "pending_light": r.llen("determinex:queue:light"),
        "pending_heavy": r.llen("determinex:queue:heavy"),
        "done": r.llen("determinex:queue:done"),
    }


# ── Postgres impl ──────────────────────────────────────────────────────────
def pg_enqueue(insts: list[str], tier: str, priority: int):
    c = _pg()
    cur = c.cursor()
    for inst in insts:
        cur.execute(
            """
            INSERT INTO tools(instance_id) VALUES (%s) ON CONFLICT DO NOTHING
        """,
            (inst,),
        )
        cur.execute(
            """
            INSERT INTO work_queue(instance_id, tier, priority)
            VALUES (%s, %s, %s)
            ON CONFLICT (instance_id) DO UPDATE
              SET status='pending', claimed_by=NULL, claimed_at=NULL,
                  tier=EXCLUDED.tier, priority=EXCLUDED.priority,
                  enqueued_at=now()
        """,
            (inst, tier, priority),
        )
    c.close()
    print(f"enqueued {len(insts)} into {tier}")


def pg_claim(worker: str, tier: str) -> str | None:
    c = _pg()
    cur = c.cursor()
    cur.execute("SELECT claim_next(%s, %s)", (worker, tier))
    row = cur.fetchone()
    c.close()
    return row[0] if row and row[0] else None


def pg_done(inst: str, score: str, rc: int, dur: int):
    c = _pg()
    cur = c.cursor()
    # Parse "P/T=PCT%"
    passed, total = None, None
    if "/" in score and "=" in score:
        try:
            left = score.split("=", 1)[0]
            passed, total = (int(x) for x in left.split("/"))
        except ValueError:
            pass
    cur.execute(
        """
        UPDATE work_queue SET status='done' WHERE instance_id=%s
    """,
        (inst,),
    )
    cur.execute(
        """
        INSERT INTO evals(instance_id, ran_at, passed, total, duration_s, rc)
        VALUES (%s, now(), %s, %s, %s, %s)
        ON CONFLICT (instance_id, ran_at) DO NOTHING
    """,
        (inst, passed, total, dur, rc),
    )
    c.close()


def pg_stats():
    c = _pg()
    cur = c.cursor()
    cur.execute("""
        SELECT status, tier, COUNT(*) FROM work_queue GROUP BY status, tier
    """)
    out = {}
    for status, tier, n in cur.fetchall():
        out[f"{status}_{tier}"] = n
    c.close()
    return out


# ── CLI ────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("enqueue")
    e.add_argument("instances", nargs="+")
    e.add_argument("--tier", default="light")
    e.add_argument("--priority", type=int, default=0)
    ef = sub.add_parser("enqueue-from-file")
    ef.add_argument("file")
    ef.add_argument("--tier", default="light")
    ef.add_argument("--priority", type=int, default=0)
    cl = sub.add_parser("claim")
    cl.add_argument("worker")
    cl.add_argument("--tier", default="any")
    d = sub.add_parser("done")
    d.add_argument("instance")
    d.add_argument("--score", default="-")
    d.add_argument("--rc", type=int, default=0)
    d.add_argument("--dur", type=int, default=0)
    sub.add_parser("stats")
    sub.add_parser("status")
    args = ap.parse_args()

    backend = _backend()

    if args.cmd == "enqueue":
        (pg_enqueue if backend == "pg" else redis_enqueue)(args.instances, args.tier, args.priority)
    elif args.cmd == "enqueue-from-file":
        with open(args.file) as f:
            insts = [ln.strip() for ln in f if ln.strip()]
        (pg_enqueue if backend == "pg" else redis_enqueue)(insts, args.tier, args.priority)
    elif args.cmd == "claim":
        inst = (pg_claim if backend == "pg" else redis_claim)(args.worker, args.tier)
        if inst:
            print(inst)
    elif args.cmd == "done":
        (pg_done if backend == "pg" else redis_done)(args.instance, args.score, args.rc, args.dur)
    elif args.cmd in {"stats", "status"}:
        s = (pg_stats if backend == "pg" else redis_stats)()
        for k, v in s.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
