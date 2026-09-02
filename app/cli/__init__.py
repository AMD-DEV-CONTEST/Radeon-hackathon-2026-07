"""Stage J — CLI entry points for admin/benchmark/health commands.

Provides the script entry points registered in pyproject.toml [project.scripts].
"""

from __future__ import annotations

import asyncio
import sys


def _cli_backup() -> None:
    """Create a backup via CLI: projectpack-backup"""
    from app.config import Settings
    from app.services.backup import BackupService

    settings = Settings()
    svc = BackupService(settings)
    manifest = svc.create_backup(label="cli")
    print(f"Backup created: {manifest['timestamp']}")


def _cli_health() -> None:
    """Run health check via CLI: projectpack-health"""
    from app.config import Settings
    from app.services.monitor import HealthMonitor
    from app.services.task_queue import get_task_queue
    from app.services.cache import get_cache

    settings = Settings()
    monitor = HealthMonitor(settings)
    queue = get_task_queue(settings)
    cache = get_cache(settings)

    async def _run() -> None:
        health = await monitor.health_check()
        qs = await queue.status()
        cs = cache.stats

        print(f"Status:   {health['status']}")
        print(f"Queue:    {qs['active_llm_calls']}/{qs['global_llm_capacity']} LLM active")
        print(f"Cache:    {cs['size']} entries, {cs['hit_rate']:.2%} hit rate")

        if health.get("issues"):
            print("Issues:")
            for issue in health["issues"]:
                print(f"  [{issue['severity']}] {issue['component']}: {issue['message']}")

        sys.exit(0 if health["status"] == "healthy" else 1)

    asyncio.run(_run())
