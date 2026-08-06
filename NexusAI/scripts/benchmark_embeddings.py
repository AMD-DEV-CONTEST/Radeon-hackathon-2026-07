import argparse,json,platform,statistics,time
from datetime import datetime,timezone
from pathlib import Path
from nexus.embeddings.local_provider import LocalEmbeddingProvider
from nexus.embeddings.rocm_provider import ROCmEmbeddingProvider
from nexus.embeddings.device import detect_device
SAMPLES=["Aria lives in Kochi and leads NexusAI.","Noah maintains the NexusAI backend.","The Nexus Research Lab is in Bengaluru.","Maya advises NexusAI.","Aurora is connected to NexusAI."]*200
def measure(p,texts,runs):
    ts=[]
    for _ in range(runs):
        s=time.perf_counter();b=p.encode(texts);ts.append(time.perf_counter()-s)
    m=statistics.mean(ts);return {"provider":p.health(),"documents":len(texts),"runs":runs,"mean_seconds":m,"min_seconds":min(ts),"max_seconds":max(ts),"documents_per_second":len(texts)/m,"dimension":b.dimension}
def main():
    a=argparse.ArgumentParser();a.add_argument("--output",default="benchmarks/radeon_embedding_benchmark.json");a.add_argument("--runs",type=int,default=5);x=a.parse_args();d=detect_device()
    out={"timestamp":datetime.now(timezone.utc).isoformat(),"system":{"platform":platform.platform(),"python":platform.python_version(),"device":d.__dict__},"cpu_baseline":measure(LocalEmbeddingProvider(),SAMPLES,x.runs)}
    r=ROCmEmbeddingProvider()
    if r.health()["available"]:
        r.encode(SAMPLES[:32]);out["rocm_gpu"]=measure(r,SAMPLES,x.runs);out["throughput_ratio_gpu_vs_cpu"]=out["rocm_gpu"]["documents_per_second"]/out["cpu_baseline"]["documents_per_second"]
    else:out["rocm_gpu"]={"available":False,"reason":"ROCm accelerator not detected"}
    p=Path(x.output);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
if __name__=="__main__":main()
