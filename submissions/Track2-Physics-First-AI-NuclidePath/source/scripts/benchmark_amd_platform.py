#!/usr/bin/env python3
"""ROCm application benchmark for the exact primary GCS and tensor transport pipeline."""
from __future__ import annotations
import argparse, json, math, platform, random, statistics, subprocess, time
from pathlib import Path

import torch
from nuclear_agent.gcs import PrimaryGCSState, calculate_primary_kd, load_primary_gcs_parameters
from nuclear_agent.gcs_primary_accelerated import calculate_primary_kd_tensor
from nuclear_agent.gpu_analysis import evaluate_scenarios_torch
from nuclear_agent.transport import TransportParameters, simulate_transport


def timed(fn, repeats, device):
    values=[]; result=None
    for _ in range(3): result=fn()
    if device == "cuda": torch.cuda.synchronize()
    for _ in range(repeats):
        if device == "cuda": torch.cuda.synchronize()
        start=time.perf_counter(); result=fn()
        if device == "cuda": torch.cuda.synchronize()
        values.append(time.perf_counter()-start)
    return result,values


def main():
    p=argparse.ArgumentParser(); p.add_argument("--output",required=True); p.add_argument("--device",default="cuda",choices=("cpu","cuda")); p.add_argument("--dtype",default="float64",choices=("float32","float64")); p.add_argument("--scenarios",type=int,default=2048); p.add_argument("--repeats",type=int,default=9); a=p.parse_args()
    if a.scenarios < 1 or a.repeats < 1: p.error("scenarios/repeats must be positive")
    if a.device == "cuda" and not torch.cuda.is_available(): p.error("CUDA/ROCm unavailable")
    root=Path(__file__).parents[1]; params=load_primary_gcs_parameters(root/"src/nuclear_agent/data/parameters/bradbury_baeyens_gcs_v2.json")
    rng=random.Random(20260728)
    rows=[[10**rng.uniform(-12,-3),10**rng.uniform(-6,-1),10**rng.uniform(-5,0),10**rng.uniform(-8,-1),rng.uniform(.01,1)] for _ in range(a.scenarios)]
    td={"float64":torch.float64,"float32":torch.float32}[a.dtype]; tensor=torch.tensor(rows,device=a.device,dtype=td)
    (kd_tensor,_),gcs_kernel_times=timed(lambda:calculate_primary_kd_tensor(params,tensor,device=a.device,dtype=a.dtype),a.repeats,a.device)
    scalar_kd=[calculate_primary_kd(params,PrimaryGCSState(*row)).bulk_kd_l_kg for row in rows]
    kd_host=kd_tensor.detach().cpu().tolist(); kd_errors=[abs(x/y-1) for x,y in zip(kd_host,scalar_kd)]

    base=TransportParameters(1000,0,1700,.35,1e-5,1e-5,0,0,30.018); receptors=[0.,2.,5.,10.,20.,50.]; times=[0.,1e5,5e5,1e6,5e6,1e7,5e7,1e8,2e8,5e8,1e9,2e9]
    if a.device == "cuda": torch.cuda.reset_peak_memory_stats()
    gpu_result,pipeline_times=timed(lambda:evaluate_scenarios_torch(base,params,tensor,receptors,times,device=a.device,dtype=a.dtype),a.repeats,a.device)
    peak_memory=torch.cuda.max_memory_allocated() if a.device == "cuda" else None
    start=time.perf_counter(); scalar=[]
    for kd in scalar_kd:
        tp=TransportParameters(1000,kd/1000,1700,.35,1e-5,1e-5,0,0,30.018)
        scalar.append([[simulate_transport(tp,x,t)["concentration_bq_m3"] for t in times] for x in receptors])
    scalar_time=time.perf_counter()-start
    gpu_host=gpu_result["concentration_bq_m3"].detach().cpu().tolist(); errors=[]
    for ga,sa in zip(gpu_host,scalar):
        for gr,sr in zip(ga,sa):
            for x,y in zip(gr,sr): errors.append(abs(x-y)/max(abs(y),1e-30))
    props=torch.cuda.get_device_properties(0) if a.device=="cuda" else None
    revision=(root/".source-revision").read_text().strip() if (root/".source-revision").exists() else "archive-without-git-metadata"
    result={"schema":"nuclidepath-amd-platform-benchmark-1.0","source_revision":revision,"device":a.device,"dtype":a.dtype,"torch":torch.__version__,"hip":torch.version.hip,"device_name":torch.cuda.get_device_name(0) if props else platform.machine(),"vram_bytes":getattr(props,"total_memory",getattr(props,"total_mem",None)) if props else None,"scenarios":a.scenarios,"receptors":len(receptors),"times":len(times),"repeats":a.repeats,"gcs_tensor_kernel":{"scope":"device-resident tensor input/output; excludes host construction/transfer","times_s":gcs_kernel_times,"median_s":statistics.median(gcs_kernel_times),"throughput_scenarios_s":a.scenarios/statistics.median(gcs_kernel_times),"max_relative_error":max(kd_errors),"median_relative_error":statistics.median(kd_errors)},"pipeline":{"scope":"device-resident chemistry input and outputs; GCS plus receptor-time reactive transport","evaluations":a.scenarios*len(receptors)*len(times),"times_s":pipeline_times,"median_s":statistics.median(pipeline_times),"throughput_evaluations_s":a.scenarios*len(receptors)*len(times)/statistics.median(pipeline_times),"peak_memory_allocated_bytes":peak_memory,"scalar_reference_s":scalar_time,"speedup_vs_scalar":scalar_time/statistics.median(pipeline_times),"max_relative_error":max(errors),"median_relative_error":statistics.median(errors)}}
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2)+"\n");print(json.dumps(result,indent=2))
if __name__=="__main__": main()
