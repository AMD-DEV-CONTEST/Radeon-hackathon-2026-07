"""embed_bench.py — embedding CPU vs GPU 独立测试，不依赖 config 修改"""
import sys, time, statistics

QUERIES = [
    "头孢克肟分散片", "盐酸氨溴索口服液", "布洛芬缓释胶囊",
    "阿奇霉素干混悬剂", "复方甘草片", "维生素B12注射液",
    "氯雷他定片", "对乙酰氨基酚片", "奥美拉唑肠溶胶囊",
    "硝苯地平控释片", "二甲双胍缓释片", "瑞舒伐他汀钙片",
    "厄贝沙坦片", "格列美脲片", "氨氯地平阿托伐他汀钙片",
]


def bench(device):
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("BAAI/bge-small-zh-v1.5", device=device)
    for _ in range(3):
        model.encode([QUERIES[0]])
    latencies = []
    for q in QUERIES:
        t0 = time.perf_counter()
        model.encode([q])
        latencies.append((time.perf_counter() - t0) * 1000)
    return latencies


if __name__ == "__main__":
    device = sys.argv[1] if len(sys.argv) > 1 else "cpu"
    lat = bench(device)
    print(f"[{device.upper()}] avg={statistics.mean(lat):.1f}ms "
          f"median={statistics.median(lat):.1f}ms "
          f"min={min(lat):.1f}ms max={max(lat):.1f}ms "
          f"total={sum(lat):.0f}ms ({len(QUERIES)} queries)")
