#!/usr/bin/env python3
"""MTP speculative decoding benchmark v2 - parses server log for accuracy"""
import os, subprocess, time, re, requests

HOST="127.0.0.1"; PORT=8080; API_KEY=os.getenv("LLM_API_KEY", "")
LLAMA_DIR="/opt/llama.cpp"; MODEL="/workspace/Qwopus3.6-27B-v2-MTP-Q4_K_M.gguf"
LOG="/workspace/llama-server.log"
MSG=[{"role":"system","content":"you are a helpful expert"},{"role":"user","content":"Describe 5 challenges in Hadoop cluster operations with scenarios and solutions, about 800 words"}]
CFGS=[
    ("baseline",["--spec-type","none"]),
    ("n_max=1",["--spec-type","draft-mtp","--spec-draft-n-max","1"]),
    ("n_max=2",["--spec-type","draft-mtp","--spec-draft-n-max","2"]),
    ("n_max=3",["--spec-type","draft-mtp","--spec-draft-n-max","3"]),
    ("n_max=4",["--spec-type","draft-mtp","--spec-draft-n-max","4"]),
    ("n_max=5",["--spec-type","draft-mtp","--spec-draft-n-max","5"]),
    ("n_max=8",["--spec-type","draft-mtp","--spec-draft-n-max","8"]),
]

def kill():
    subprocess.run("pkill -f llama-server",shell=True,capture_output=True)
    time.sleep(2)

def start(args):
    cmd=f"cd {LLAMA_DIR} && HIP_VISIBLE_DEVICES=0 ./llama-server -m {MODEL} -c 131072 -ngl 999 -ctk q8_0 -ctv q8_0 -fa on --jinja {' '.join(args)} -t 16 -b 512 -ub 512 -np 1 --host 0.0.0.0 --port {PORT} --api-key {API_KEY} > {LOG} 2>&1 &"
    subprocess.run(cmd,shell=True,capture_output=True)
    for _ in range(60):
        try:
            r=requests.get(f"http://{HOST}:{PORT}/v1/models",headers={"Authorization":f"Bearer {API_KEY}"},timeout=2)
            if r.status_code==200: return True
        except: pass
        time.sleep(0.5)
    return False

def bench():
    """Send non-streaming request, return usage stats"""
    t0=time.time()
    r=requests.post(f"http://{HOST}:{PORT}/v1/chat/completions",
        headers={"Authorization":f"Bearer {API_KEY}","Content-Type":"application/json"},
        json={"model":MODEL,"messages":MSG,"max_tokens":1024,"temperature":0.7,"stream":False},
        timeout=180)
    t1=time.time()
    data=r.json()
    usage=data.get("usage",{})
    return {
        "total_s":round(t1-t0,2),
        "prompt_tokens":usage.get("prompt_tokens",0),
        "completion_tokens":usage.get("completion_tokens",0),
        "tps":round(usage.get("completion_tokens",0)/(t1-t0),1) if t1>t0 else 0,
    }

def parse_log():
    """Extract spec stats from llama-server log"""
    try:
        out=subprocess.run(f"grep -E 'print_timing|statistics.*draft' {LOG}|tail -2",shell=True,capture_output=True,text=True,timeout=5).stdout.strip()
        m=re.search(r'draft acceptance = ([\d.]+) \(\s*(\d+) accepted /\s*(\d+) generated\)',out)
        acc_rate=float(m.group(1)) if m else 0
        acc=int(m.group(2)) if m else 0
        gen=int(m.group(3)) if m else 0
        m2=re.search(r'mean acceptance length = ([\d.]+)',out)
        mean_len=float(m2.group(1)) if m2 else 0
        m3=re.search(r'dur\(b,g,a\) = ([\d.]+), ([\d.]+), ([\d.]+) ms',out)
        gen_ms=float(m3.group(2)) if m3 else 0
        server_tps=round(gen/gen_ms*1000,1) if gen_ms>0 else 0
        return {"acc_rate":acc_rate,"acc":acc,"gen":gen,"mean_len":mean_len,"server_tps":server_tps}
    except: return {}

def main():
    print("="*80)
    print("MTP Speculative Decoding Benchmark")
    print("="*80)
    hdr=f"{'config':<15}{'tokens':>8}{'t/s(client)':>12}{'t/s(server)':>12}{'acc_rate':>10}{'mean_len':>10}{'time(s)':>8}"
    print(hdr); print("-"*80)
    results=[]
    for label,args in CFGS:
        print(f"\n>>> {label}")
        kill()
        if not start(args):
            print("  FAILED to start"); continue
        time.sleep(2)
        try:
            m=bench()
        except Exception as e:
            print(f"  bench error: {e}"); continue
        s=parse_log()
        results.append((label,m,s))
        print(f"  {label:<15}{m['completion_tokens']:>8}{m['tps']:>12}{s.get('server_tps',0):>12}{s.get('acc_rate',0):>10}{s.get('mean_len',0):>10}{m['total_s']:>8}")
    print("\n"+"="*80); print("SUMMARY"); print("="*80)
    print(hdr); print("-"*80)
    best_tps=0; best=""
    for label,m,s in results:
        tps=s.get('server_tps',0) or m['tps']
        print(f"{label:<15}{m['completion_tokens']:>8}{m['tps']:>12}{s.get('server_tps',0):>12}{s.get('acc_rate',0):>10}{s.get('mean_len',0):>10}{m['total_s']:>8}")
        if tps>best_tps: best_tps=tps; best=label
    print("-"*80)
    print(f"Best: {best} @ {best_tps} t/s")

if __name__=="__main__":
    main()
