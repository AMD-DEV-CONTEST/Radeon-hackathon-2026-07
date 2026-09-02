from __future__ import annotations

import argparse
import json
import platform
import sqlite3
import sys
from typing import Any

import uvicorn

from . import __version__
from .config import Settings
from .service import OpenAlphaService
from .worker import CollectorWorker


def _json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openalpha", description="OpenAlpha Sentinel local agent")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init", help="Initialize the local database")
    commands.add_parser("status", help="Show local service status")
    commands.add_parser("doctor", help="Check the local runtime")
    commands.add_parser("seed", help="Load deterministic demo strategy sources")

    serve = commands.add_parser("serve", help="Run the localhost web application")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)

    worker = commands.add_parser("worker", help="Run the persistent collection scheduler")
    worker.add_argument("--once", action="store_true", help="Run due rules once and exit")

    discover = commands.add_parser("discover", help="Search and ingest public GitHub repositories")
    discover.add_argument("query")
    discover.add_argument("--limit", type=int, default=5)

    rss = commands.add_parser("rss", help="Ingest entries embedded in an RSS/Atom feed")
    rss.add_argument("url")

    ask = commands.add_parser("ask", help="Ask the local strategy knowledge base")
    ask.add_argument("question")
    ask.add_argument("--session")

    watch_add = commands.add_parser("watch-add", help="Create a recurring GitHub or RSS rule")
    watch_add.add_argument("name")
    watch_add.add_argument("kind", choices=("github", "rss"))
    watch_add.add_argument("value", help="GitHub query or RSS URL")
    watch_add.add_argument("--interval", type=int, default=360)
    watch_add.add_argument("--limit", type=int, default=5)
    commands.add_parser("watch-list", help="List recurring collection rules")

    offline = commands.add_parser("offline", help="Enable or disable network collection")
    offline.add_argument("state", choices=("on", "off"))
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    service = OpenAlphaService(settings)

    if args.command == "init":
        print(f"Initialized {settings.db_path}")
    elif args.command == "status":
        _json(service.dashboard().model_dump())
    elif args.command == "doctor":
        fts = False
        with service.database.connect() as connection:
            try:
                connection.execute("CREATE VIRTUAL TABLE temp.fts_probe USING fts5(value)")
                fts = True
            except sqlite3.OperationalError:
                pass
        _json(
            {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "sqlite": sqlite3.sqlite_version,
                "fts5": fts,
                "database": str(settings.db_path),
                "database_writable": settings.data_dir.exists(),
                "llm_backend": service.models.name,
                "offline": service.permissions.is_offline(),
            }
        )
    elif args.command == "seed":
        _json(service.seed_demo().model_dump())
    elif args.command == "serve":
        uvicorn.run(
            "openalpha_sentinel.api:app",
            host=args.host or settings.host,
            port=args.port or settings.port,
            reload=False,
        )
    elif args.command == "worker":
        worker_process = CollectorWorker(service)
        if args.once:
            _json(worker_process.run_once())
        else:
            worker_process.run_forever()
    elif args.command == "discover":
        _json(service.discover_github(args.query, args.limit).model_dump())
    elif args.command == "rss":
        _json(service.ingest_rss(args.url).model_dump())
    elif args.command == "ask":
        _json(service.ask(args.question, args.session).model_dump())
    elif args.command == "watch-add":
        config = {"query": args.value, "limit": args.limit} if args.kind == "github" else {"url": args.value}
        _json(service.create_watch_rule(args.name, args.kind, config, args.interval))
    elif args.command == "watch-list":
        _json(service.database.list_watch_rules())
    elif args.command == "offline":
        service.permissions.set_offline(args.state == "on")
        _json({"offline": service.permissions.is_offline()})
    else:
        raise SystemExit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
