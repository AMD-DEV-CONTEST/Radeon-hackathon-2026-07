#!/usr/bin/env python3
"""
Motus Agent + vLLM stress testing and performance metrics collector
"""

import requests
import time
import json
import csv
import argparse
import asyncio
import aiohttp
import statistics
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Callable
from datetime import datetime
from pathlib import Path
import threading
import re
import random
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, as_completed


# ==================== Data Models ====================

@dataclass
class VLLMMetrics:
    """vLLM key performance metrics"""
    timestamp: str
    
    # Request status
    num_requests_running: float = 0
    num_requests_waiting: float = 0
    num_requests_swapped: float = 0
    
    # GPU cache
    gpu_cache_usage_perc: float = 0
    
    # Throughput (tokens/s)
    avg_prompt_throughput: float = 0
    avg_generation_throughput: float = 0
    
    # Latency (seconds)
    request_queue_time: float = 0
    request_inference_time: float = 0
    request_prefill_time: float = 0
    request_decode_time: float = 0
    
    # Scheduling
    scheduling_time: float = 0
    
    # Model loading
    model_load_time: float = 0


@dataclass  
class AgentMetrics:
    """Agent API performance metrics"""
    timestamp: str
    
    # Basic status
    status: str = "unknown"
    uptime_seconds: float = 0
    
    # Request statistics (if Agent exposes)
    total_requests: int = 0
    active_requests: int = 0
    
    # End-to-end latency
    avg_response_time: float = 0


@dataclass
class LoadTestResult:
    """Single stress test result"""
    timestamp: str
    concurrency: int  # Concurrency level
    total_requests: int
    successful: int
    failed: int
    total_time: float
    
    # Latency statistics (ms)
    latency_min: float = 0
    latency_max: float = 0
    latency_avg: float = 0
    latency_p50: float = 0
    latency_p95: float = 0
    latency_p99: float = 0
    
    # Throughput
    requests_per_second: float = 0
    
    # Error information
    errors: List[str] = field(default_factory=list)


# ==================== Metrics Parser ====================

class PrometheusParser:
    """Prometheus text format parser"""
    
    @staticmethod
    def parse(text: str) -> Dict[str, List[Dict]]:
        """Parse Prometheus format"""
        result = {}
        lines = text.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            match = re.match(r'^([^{]+)(?:\{([^}]*)\})?\s+(\S+)(?:\s+(\S+))?$', line)
            if not match:
                continue
                
            name, labels_str, value_str, _ = match.groups()
            name = name.strip()
            
            labels = {}
            if labels_str:
                for pair in labels_str.split(','):
                    if '=' in pair:
                        k, v = pair.split('=', 1)
                        labels[k.strip()] = v.strip().strip('"')
            
            try:
                value = float(value_str)
            except ValueError:
                continue
            
            if name not in result:
                result[name] = []
            result[name].append({
                'labels': labels,
                'value': value
            })
        
        return result


# ==================== Metrics Collector ====================

class MetricsCollector:
    """Performance metrics collector"""
    
    def __init__(self, vllm_url: str = "http://localhost:8000", 
                 agent_url: str = "http://localhost:8080"):
        self.vllm_metrics_url = f"{vllm_url}/metrics"
        self.agent_health_url = f"{agent_url}/health"
        self.agent_metrics_url = f"{agent_url}/metrics"
        
        self.parser = PrometheusParser()
        self.history: List[Dict] = []
        
    def fetch_vllm(self) -> Optional[VLLMMetrics]:
        """Fetch vLLM metrics"""
        try:
            resp = requests.get(self.vllm_metrics_url, timeout=5)
            resp.raise_for_status()
            data = self.parser.parse(resp.text)
            return self._extract_vllm(data)
        except Exception as e:
            print(f" vLLM metrics fetch failed: {e}")
            return None
    
    def _extract_vllm(self, data: Dict) -> VLLMMetrics:
        """Extract key metrics from parsed data"""
        
        def get_value(metric_name: str, default: float = 0) -> float:
            if metric_name in data and len(data[metric_name]) > 0:
                return data[metric_name][0].get('value', default)
            return default
        
        return VLLMMetrics(
            timestamp=datetime.now().isoformat(),
            num_requests_running=get_value('vllm:num_requests_running'),
            num_requests_waiting=get_value('vllm:num_requests_waiting'),
            num_requests_swapped=get_value('vllm:num_requests_swapped'),
            gpu_cache_usage_perc=get_value('vllm:gpu_cache_usage_perc'),
            avg_prompt_throughput=get_value('vllm:avg_prompt_throughput_toks_per_s'),
            avg_generation_throughput=get_value('vllm:avg_generation_throughput_toks_per_s'),
            request_queue_time=get_value('vllm:request_queue_time_seconds_sum'),
            request_inference_time=get_value('vllm:request_inference_time_seconds_sum'),
            request_prefill_time=get_value('vllm:request_prefill_time_seconds_sum'),
            request_decode_time=get_value('vllm:request_decode_time_seconds_sum'),
            scheduling_time=get_value('vllm:scheduling_time_seconds_sum'),
            model_load_time=get_value('vllm:model_load_time_seconds'),
        )
    
    def fetch_agent(self) -> Optional[AgentMetrics]:
        """Fetch Agent health status"""
        try:
            resp = requests.get(self.agent_health_url, timeout=5)
            return AgentMetrics(
                timestamp=datetime.now().isoformat(),
                status="healthy" if resp.status_code == 200 else "unhealthy",
            )
        except Exception as e:
            return AgentMetrics(
                timestamp=datetime.now().isoformat(),
                status=f"error: {e}"
            )
    
    def collect_once(self) -> Dict:
        """Collect metrics once"""
        vllm = self.fetch_vllm()
        agent = self.fetch_agent()
        
        record = {
            "timestamp": datetime.now().isoformat(),
            "vllm": asdict(vllm) if vllm else None,
            "agent": asdict(agent) if agent else None,
        }
        
        self.history.append(record)
        return record
    
    def start_monitoring(self, interval: int = 5, callback: Optional[Callable] = None):
        """Start background monitoring thread"""
        def _monitor():
            while self._monitoring:
                record = self.collect_once()
                if callback:
                    callback(record)
                else:
                    self._print_record(record)
                time.sleep(interval)
        
        self._monitoring = True
        self._thread = threading.Thread(target=_monitor, daemon=True)
        self._thread.start()
        print(f" Monitoring started (interval={interval}s)")
    
    def stop_monitoring(self):
        """Stop monitoring"""
        self._monitoring = False
        if hasattr(self, '_thread'):
            self._thread.join(timeout=1)
        print(" Monitoring stopped")
    
    def _print_record(self, record: Dict):
        """Print metrics record"""
        vllm = record.get('vllm')
        if vllm:
            print(f"\n[{record['timestamp']}] "
                  f"Running: {vllm['num_requests_running']:.0f}, "
                  f"GPU Cache: {vllm['gpu_cache_usage_perc']*100:.1f}%, "
                  f"Gen: {vllm['avg_generation_throughput']:.1f} tok/s")
    
    def export_csv(self, filepath: str):
        """Export history to CSV"""
        if not self.history:
            print(" No data to export")
            return
        
        rows = []
        for record in self.history:
            row = {"timestamp": record["timestamp"]}
            if record.get("vllm"):
                for k, v in record["vllm"].items():
                    if k != "timestamp":
                        row[f"vllm_{k}"] = v
            if record.get("agent"):
                for k, v in record["agent"].items():
                    if k != "timestamp":
                        row[f"agent_{k}"] = v
            rows.append(row)
        
        if rows:
            keys = rows[0].keys()
            with open(filepath, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(rows)
            print(f" Exported {len(rows)} records to {filepath}")
    
    def export_json(self, filepath: str):
        """Export history to JSON"""
        with open(filepath, 'w') as f:
            json.dump(self.history, f, indent=2, default=str)
        print(f" Exported to {filepath}")


# ==================== Stress Testing Core ====================

class LoadTester:
    """Stress tester"""
    
    # Test prompts
    TEST_PROMPTS = [
        "Explain quantum computing in simple terms",
        "Write a Python function to sort a list",
        "What is the capital of France?",
        "Summarize the theory of relativity",
        "How do neural networks work?",
        "Write a haiku about technology",
        "Explain the difference between HTTP and HTTPS",
        "What are the benefits of renewable energy?",
        "Describe the process of photosynthesis",
        "How does blockchain technology work?",
    ]
    
    def __init__(self, base_url: str = "http://localhost:8080", 
                 model: str = "Qwen/Qwen2.5-0.5B-Instruct",
                 api_key: Optional[str] = None):
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
        
        self.results: List[LoadTestResult] = []
        
    def _make_request(self, session: requests.Session, prompt: str) -> tuple:
        """Send a single request, return (success, latency_ms, error)"""
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 100,
            "temperature": 0.7,
        }
        
        start = time.time()
        try:
            resp = session.post(
                f"{self.base_url}/v1/chat/completions",
                headers=self.headers,
                json=payload,
                timeout=120
            )
            resp.raise_for_status()
            latency = (time.time() - start) * 1000  # ms
            return True, latency, None
            
        except Exception as e:
            latency = (time.time() - start) * 1000
            return False, latency, str(e)
    
    def run_test(self, concurrency: int = 1, 
                 total_requests: int = 100,
                 ramp_up: bool = False) -> LoadTestResult:
        """
        Execute stress test

        Args:
            concurrency: concurrency level
            total_requests: total number of requests
            ramp_up: whether to gradually increase concurrency
        """
        print(f"\n{'='*60}")
        print(f"  LOAD TEST: concurrency={concurrency}, total={total_requests}")
        print(f"{'='*60}")
        
        latencies = []
        errors = []
        completed = 0
        
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            with requests.Session() as session:
                # Submit all tasks
                futures = []
                for i in range(total_requests):
                    prompt = random.choice(self.TEST_PROMPTS)
                    future = executor.submit(self._make_request, session, prompt)
                    futures.append(future)
                    
                    # Gradual loading
                    if ramp_up:
                        time.sleep(0.1)
                
                # Collect results
                for future in concurrent.futures.as_completed(futures):
                    success, latency, error = future.result()
                    completed += 1
                    
                    if success:
                        latencies.append(latency)
                    else:
                        errors.append(error)
                    
                    # Progress display
                    if completed % 10 == 0 or completed == total_requests:
                        print(f"  Progress: {completed}/{total_requests} "
                              f"({completed/total_requests*100:.1f}%)")
        
        total_time = time.time() - start_time
        
        # Calculate statistics
        result = LoadTestResult(
            timestamp=datetime.now().isoformat(),
            concurrency=concurrency,
            total_requests=total_requests,
            successful=len(latencies),
            failed=len(errors),
            total_time=total_time,
            errors=errors[:10],  # Only keep first 10 errors
        )
        
        if latencies:
            latencies.sort()
            result.latency_min = min(latencies)
            result.latency_max = max(latencies)
            result.latency_avg = statistics.mean(latencies)
            result.latency_p50 = self._percentile(latencies, 50)
            result.latency_p95 = self._percentile(latencies, 95)
            result.latency_p99 = self._percentile(latencies, 99)
            result.requests_per_second = len(latencies) / total_time
        
        self.results.append(result)
        self._print_result(result)
        
        return result
    
    @staticmethod
    def _percentile(data: List[float], p: float) -> float:
        """Calculate percentile"""
        k = (len(data) - 1) * (p / 100)
        f = int(k)
        c = f + 1 if f + 1 < len(data) else f
        if f == c:
            return data[f]
        return data[f] * (c - k) + data[c] * (k - f)
    
    def _print_result(self, result: LoadTestResult):
        """Print test results"""
        print(f"\n  Results:")
        print(f"    Total Time:      {result.total_time:.2f}s")
        print(f"    Successful:      {result.successful}/{result.total_requests}")
        print(f"    Failed:          {result.failed}")
        print(f"    RPS:             {result.requests_per_second:.2f}")
        print(f"\n  Latency (ms):")
        print(f"    Min:  {result.latency_min:.2f}")
        print(f"    Avg:  {result.latency_avg:.2f}")
        print(f"    P50:  {result.latency_p50:.2f}")
        print(f"    P95:  {result.latency_p95:.2f}")
        print(f"    P99:  {result.latency_p99:.2f}")
        print(f"    Max:  {result.latency_max:.2f}")
        
        if result.errors:
            print(f"\n  Sample Errors:")
            for err in result.errors[:3]:
                print(f"    - {err[:100]}")
    
    def run_stress_test(self, 
                        concurrency_levels: List[int] = [1, 5, 10, 20, 50],
                        requests_per_level: int = 100):
        """Execute step stress test"""
        print(f"\n{'#'*60}")
        print(f"#  STRESS TEST - Step Load")
        print(f"{'#'*60}")
        
        for conc in concurrency_levels:
            result = self.run_test(concurrency=conc, total_requests=requests_per_level)
            
            # If failure rate is too high, stop testing
            if result.failed / result.total_requests > 0.5:
                print(f"\n  ⚠️  Failure rate > 50%, stopping stress test")
                break
            
            # Interval to avoid cooldown
            time.sleep(2)
        
        self.export_results()
    
    def run_soak_test(self, duration_minutes: int = 30, concurrency: int = 10):
        """Execute soak test (long-term stability test)"""
        print(f"\n{'#'*60}")
        print(f"#  SOAK TEST - {duration_minutes}min @ {concurrency} concurrency")
        print(f"{'#'*60}")
        
        end_time = time.time() + duration_minutes * 60
        total_requests = 0
        all_latencies = []
        
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            while time.time() < end_time:
                # Send a batch of requests per round
                futures = []
                with requests.Session() as session:
                    for _ in range(concurrency):
                        prompt = random.choice(self.TEST_PROMPTS)
                        future = executor.submit(self._make_request, session, prompt)
                        futures.append(future)
                    
                    for future in concurrent.futures.as_completed(futures):
                        success, latency, _ = future.result()
                        if success:
                            all_latencies.append(latency)
                            total_requests += 1
                
                # Progress
                remaining = (end_time - time.time()) / 60
                print(f"  Remaining: {remaining:.1f}min, "
                      f"Total: {total_requests}, "
                      f"Avg Latency: {statistics.mean(all_latencies[-100:]):.2f}ms")
                
                time.sleep(1)  # Control rate
        
        print(f"\n  Soak test complete: {total_requests} requests")
    
    def export_results(self, filepath: Optional[str] = None):
        """Export test results"""
        if not filepath:
            filepath = f"load_test_{datetime.now():%Y%m%d_%H%M%S}.json"
        
        data = [asdict(r) for r in self.results]
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        
        print(f"\n  Results exported to: {filepath}")
        
        # Also export CSV summary
        csv_path = filepath.replace('.json', '.csv')
        with open(csv_path, 'w', newline='') as f:
            if self.results:
                writer = csv.DictWriter(f, fieldnames=[
                    'timestamp', 'concurrency', 'total_requests', 'successful',
                    'failed', 'total_time', 'requests_per_second',
                    'latency_min', 'latency_avg', 'latency_p95', 'latency_max'
                ])
                writer.writeheader()
                for r in self.results:
                    writer.writerow({
                        'timestamp': r.timestamp,
                        'concurrency': r.concurrency,
                        'total_requests': r.total_requests,
                        'successful': r.successful,
                        'failed': r.failed,
                        'total_time': r.total_time,
                        'requests_per_second': r.requests_per_second,
                        'latency_min': r.latency_min,
                        'latency_avg': r.latency_avg,
                        'latency_p95': r.latency_p95,
                        'latency_max': r.latency_max,
                    })
        print(f"  CSV summary: {csv_path}")


# ==================== CLI Entry ====================

def main():
    parser = argparse.ArgumentParser(description="Motus Agent 压力测试工具")
    parser.add_argument("--url", default="http://localhost:8080", 
                       help="Agent URL (default: http://localhost:8080)")
    parser.add_argument("--vllm-url", default="http://localhost:8000",
                       help="vLLM metrics URL")
    parser.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct",
                       help="Model name")
    parser.add_argument("--api-key", default=None,
                       help="API Key for authentication")
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Monitor command
    monitor_parser = subparsers.add_parser("monitor", help="Monitor metrics")
    monitor_parser.add_argument("--interval", type=int, default=5, help="Sampling interval (s)")
    monitor_parser.add_argument("--duration", type=int, default=60, help="Duration (s)")
    
    # Load test command
    load_parser = subparsers.add_parser("load", help="Run load test")
    load_parser.add_argument("-c", "--concurrency", type=int, default=10, help="Concurrent users")
    load_parser.add("-n", "--requests", type=int, default=100, help="Total requests")
    
    # Step stress test
    stress_parser = subparsers.add_parser("stress", help="Run stress test")
    stress_parser.add_argument("--levels", type=int, nargs="+", default=[1, 5, 10, 20, 50])
    stress_parser.add_argument("--per-level", type=int, default=100)
    
    #  Soak test
    soak_parser = subparsers.add_parser("soak", help="Run soak test")
    soak_parser.add_argument("--duration", type=int, default=30, help="Duration in minutes")
    soak_parser.add_argument("--concurrency", type=int, default=10)
    
    args = parser.parse_args()
    
    if args.command == "monitor":
        collector = MetricsCollector(vllm_url=args.vllm_url, agent_url=args.url)
        collector.start_monitoring(interval=args.interval)
        try:
            time.sleep(args.duration)
        finally:
            collector.stop_monitoring()
            collector.export_json("metrics.json")
            collector.export_csv("metrics.csv")
    
    elif args.command == "load":
        tester = LoadTester(base_url=args.url, model=args.model, api_key=args.api_key)
        tester.run_test(concurrency=args.concurrency, total_requests=args.requests)
    
    elif args.command == "stress":
        tester = LoadTester(base_url=args.url, model=args.model, api_key=args.api_key)
        tester.run_stress_test(
            concurrency_levels=args.levels,
            requests_per_level=args.per_level
        )
    
    elif args.command == "soak":
        tester = LoadTester(base_url=args.url, model=args.model, api_key=args.api_key)
        tester.run_soak_test(
            duration_minutes=args.duration,
            concurrency=args.concurrency
        )
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()