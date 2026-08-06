from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from cortex.bench.embed_probe import EmbedProbe
from cortex.bench.gpu_sensor import GpuSensor
from cortex.bench.metrics import BenchMetrics, to_envelope
from cortex.bench.query_probe import QueryProbe
from cortex.bench.targets import (
    BENCH_EMBED_BATCH,
    BENCH_QUERY_COUNT,
    BENCH_TICK_INTERVAL_SEC,
)
from cortex.core.article import ArticleType, MemoryArticle, Provenance
from cortex.node.broker_client import BrokerClient
from cortex.node.node import CortexNode

log = logging.getLogger("cortex.bench")


def _default_broker_client(url: str) -> BrokerClient:
    return BrokerClient(url)


def _make_bench_node(node_id: str, embed_backend: str, tmp_root: Path,
                     broker_url: str = "ws://localhost:7432") -> CortexNode:
    keys_dir = tmp_root / node_id
    keys_dir.mkdir(parents=True, exist_ok=True)
    from cortex.node.keys import ensure_keys
    keys = {"org": ensure_keys(keys_dir / "org.pem"),
            "agent": ensure_keys(keys_dir / "agent.pem", kind="agent")}
    reg = tmp_root / "reg.json"
    if not reg.exists():
        reg.write_text('{}')
    cfg = tmp_root / f"{node_id}.yaml"
    if not cfg.exists():
        cfg.write_text(f"""\
node:
  org_did: {node_id}
  agent_did: did:percq:agent:bench
  key_paths:
    org: {keys['org']}
    agent: {keys['agent']}
broker:
  url: {broker_url}
  registry: {reg}
  replay_window_sec: 600
embedder:
  model: BAAI/bge-small-en-v1.5
  backend: {embed_backend}
  batch_size: 4
vector_index:
  backend: hnswlib
  metric: cosine
  hnsw:
    M: 16
    ef_construction: 100
    ef_search: 32
trust:
  default_org_reputation: 0.85
  half_life_days: 90
  min_trust_default: 0.3
query:
  default_top_k: 5
  deadline_ms: 400
  min_trust: 0.0
logging:
  level: WARNING
""")
    return CortexNode(
        org_did=node_id,
        agent_did="did:percq:agent:bench",
        key_paths=keys,
        broker_url=broker_url,
        config_path=cfg,
        embedder_backend_override=embed_backend,
    )


def _default_probe_factory(node_id: str):
    import os
    import tempfile
    tmp_root = Path(tempfile.mkdtemp(prefix="cortex-bench-"))
    broker_url = os.environ.get("CORTEX_BROKER_URL", "ws://localhost:7432")
    text_pool = [
        "APT29 leveraged encoded PowerShell T1059.001",
        "Lateral movement via WMI T1021.006",
        "Credential dumping with LSASS T1003.001",
    ] * 8
    query_pool = [
        "TTPs tied to APT29 in 2026",
        "credential access techniques",
        "lateral movement evidence",
    ] * 4

    embed_radeon = EmbedProbe(text_pool, batch_size=BENCH_EMBED_BATCH, mode="radeon")
    embed_cpu = EmbedProbe(text_pool, batch_size=BENCH_EMBED_BATCH, mode="cpu")
    node_radeon = _make_bench_node(node_id, "gpu", tmp_root, broker_url)
    node_cpu = _make_bench_node(node_id, "cpu", tmp_root, broker_url)
    _seed_synthetic_store(node_radeon, text_pool)
    _seed_synthetic_store(node_cpu, text_pool)
    query_radeon = QueryProbe(node_radeon, query_pool, top_k=5, count=BENCH_QUERY_COUNT)
    query_cpu = QueryProbe(node_cpu, query_pool, top_k=5, count=BENCH_QUERY_COUNT)
    return {
        "embed_radeon": embed_radeon,
        "embed_cpu": embed_cpu,
        "query_radeon": query_radeon,
        "query_cpu": query_cpu,
    }


def _seed_synthetic_store(node: CortexNode, texts: list[str]) -> None:
    try:
        for t in texts[:8]:
            art = MemoryArticle(
                id="", type=ArticleType.FINDING, content=t,
                payload={}, embedding=None, embedding_model=None,
                provenance=Provenance(
                    producer_agent="did:percq:agent:bench",
                    producer_org=node.org_did,
                    run_id="bench-seed",
                    timestamp=datetime.now(UTC),
                ),
                scope="public", agent_signature=b"",
                cites=[], trust_score=None, trust_expiration=None,
            )
            node.publish(art)
    except Exception:
        pass


class _Probes:
    def __init__(self, factory_result: dict[str, Any]) -> None:
        self.embed_radeon: EmbedProbe = factory_result["embed_radeon"]
        self.embed_cpu: EmbedProbe = factory_result["embed_cpu"]
        self.query_radeon: QueryProbe = factory_result["query_radeon"]
        self.query_cpu: QueryProbe = factory_result["query_cpu"]


class _PrometheusHandler(BaseHTTPRequestHandler):
    metrics_text = "# cortex-bench metrics not yet available\n"
    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(type(self).metrics_text.encode("utf-8"))
    def log_message(self, fmt: str, *args: Any) -> None:
        pass


class BenchRunner:
    def __init__(
        self,
        node_id: str,
        broker_url: str,
        config_path: str,
        tick_interval: float = BENCH_TICK_INTERVAL_SEC,
        broker_client_factory: Callable[[str], Any] | None = None,
        probe_factory: Callable[[str], Any] | None = None,
        gpu_sensor: GpuSensor | None = None,
        prometheus_port: int = 9464,
    ) -> None:
        self.node_id = node_id
        self.broker_url = broker_url
        self.config_path = config_path
        self.tick_interval = tick_interval
        self.prometheus_port = prometheus_port
        self._broker_factory = broker_client_factory or _default_broker_client
        self._probe_factory = probe_factory or _default_probe_factory
        self._gpu_sensor = gpu_sensor or GpuSensor()
        self._broker = None
        self._probes: _Probes | None = None
        self._stop = asyncio.Event()
        self._httpd: HTTPServer | None = None

    async def _start_prometheus(self) -> None:
        try:
            self._httpd = HTTPServer(("0.0.0.0", self.prometheus_port), _PrometheusHandler)
            import threading
            t = threading.Thread(target=self._httpd.serve_forever, daemon=True)
            t.start()
            log.info("prometheus /metrics on :%d", self.prometheus_port)
        except Exception as exc:
            log.warning("prometheus server failed: %s", exc)

    async def run(self) -> None:
        logging.basicConfig(level=logging.INFO, stream=sys.stderr)
        self._broker = self._broker_factory(self.broker_url)
        if hasattr(self._broker, "connect"):
            await self._broker.connect()
        self._probes = _Probes(self._probe_factory(self.node_id))
        await self._start_prometheus()
        log.info("cortex-bench started for %s", self.node_id)
        try:
            while not self._stop.is_set():
                await self._tick()
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.tick_interval)
                except TimeoutError:
                    continue
        except (KeyboardInterrupt, asyncio.CancelledError):
            log.info("cortex-bench received interrupt, shutting down")
        finally:
            await self._cleanup()

    async def _tick(self) -> None:
        await asyncio.sleep(0)
        p = self._probes

        def _safe(fn, *args, **kw):
            try:
                return fn(*args, **kw)
            except Exception as e:
                log.warning("probe %s failed: %s", getattr(fn, "__name__", fn), e)
                return None

        er = _safe(p.embed_radeon.probe_once)
        ec = _safe(p.embed_cpu.probe_once)
        qr = _safe(p.query_radeon.probe_once)
        qc = _safe(p.query_cpu.probe_once)
        ec_r, et_r = er if er else (0, 0.0)
        ec_c, et_c = ec if ec else (0, 0.0)
        qc_r, qt_r, qp95_r = qr if qr else (0, 0.0, 0.0)
        qc_c, qt_c, qp95_c = qc if qc else (0, 0.0, 0.0)
        embeds_radeon = ec_r / et_r if et_r > 0 else 0.0
        embeds_cpu = ec_c / et_c if et_c > 0 else 0.0
        queries_radeon = qc_r / qt_r if qt_r > 0 else 0.0
        queries_cpu = qc_c / qt_c if qt_c > 0 else 0.0
        try:
            gpu = (
                self._gpu_sensor.snapshot()
                if self._gpu_sensor is not None
                else {"mem_util_pct": 0.0}
            )
        except Exception:
            gpu = {"mem_util_pct": 0.0}
        metrics = BenchMetrics(
            node=self.node_id,
            embeds_per_sec_radeon=embeds_radeon,
            embeds_per_sec_cpu=embeds_cpu,
            queries_per_sec_radeon=queries_radeon,
            queries_per_sec_cpu=queries_cpu,
            gpu_mem_util_pct=gpu["mem_util_pct"],
            gpu_device_name=gpu.get("device_name", "unknown"),
            gpu_sensor_backend=gpu.get("backend", "none"),
            p95_query_latency_ms=qp95_r,
            ts=datetime.now(UTC),
        )
        env = to_envelope(metrics)
        if self._broker is not None:
            try:
                await self._broker.publish_envelope(env)
            except Exception as e:
                log.warning("publish_envelope failed: %s", e)
        log.info(
            "bench radeon=%.1f embeds/s cpu=%.1f embeds/s radeon_q=%.1f q/s cpu_q=%.1f q/s "
            "gpu=%s p95=%.1fms",
            embeds_radeon, embeds_cpu, queries_radeon, queries_cpu,
            gpu["mem_util_pct"], qp95_r,
        )
        nid = self.node_id
        gpu_mem = gpu["mem_util_pct"]
        _PrometheusHandler.metrics_text = "\n".join([
            "# HELP cortex_embeds_per_sec Embedding throughput",
            "# TYPE cortex_embeds_per_sec gauge",
            f"cortex_embeds_per_sec{{backend=\"radeon\",node=\"{nid}\"}} {embeds_radeon:.3f}",
            f"cortex_embeds_per_sec{{backend=\"cpu\",node=\"{nid}\"}} {embeds_cpu:.3f}",
            "# HELP cortex_queries_per_sec Query throughput",
            "# TYPE cortex_queries_per_sec gauge",
            f"cortex_queries_per_sec{{backend=\"radeon\",node=\"{nid}\"}} {queries_radeon:.3f}",
            f"cortex_queries_per_sec{{backend=\"cpu\",node=\"{nid}\"}} {queries_cpu:.3f}",
            "# HELP cortex_gpu_mem_util_pct GPU memory utilization",
            "# TYPE cortex_gpu_mem_util_pct gauge",
            f"cortex_gpu_mem_util_pct{{node=\"{nid}\"}} {gpu_mem:.1f}",
            "# HELP cortex_p95_query_latency_ms P95 query latency",
            "# TYPE cortex_p95_query_latency_ms gauge",
            f"cortex_p95_query_latency_ms{{node=\"{nid}\"}} {qp95_r:.1f}",
        ]) + "\n"

    async def _cleanup(self) -> None:
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for t in pending:
            if t.get_name() == "cortex-bench-tick":
                t.cancel()
        if self._httpd is not None:
            self._httpd.shutdown()
        if self._broker is not None and hasattr(self._broker, "close"):
            with contextlib.suppress(Exception):
                await self._broker.close()

    async def stop(self) -> None:
        self._stop.set()
        await self._cleanup()
