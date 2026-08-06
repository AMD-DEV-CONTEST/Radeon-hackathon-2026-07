import subprocess, time, os, sys
t0 = time.time()
os.makedirs("/workspace/kick_live", exist_ok=True)
logf = open("/workspace/kick_live/run.log", "w")
def emit(s):
    line = "[%7.1fs] %s" % (time.time()-t0, s)
    print(line, flush=True)
    logf.write(line + "\n"); logf.flush()
emit("CMD: /opt/venv/bin/python3.12 -u /workspace/render_kick_live.py")
emit("PARAMS: " + open("/workspace/kick_params.json").read().replace("\n", " "))
p = subprocess.Popen(["/opt/venv/bin/python3.12", "-u", "/workspace/render_kick_live.py"],
                     cwd="/workspace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
for line in p.stdout:
    emit(line.rstrip())
p.wait()
emit("EXIT %d" % p.returncode)
logf.close()
print("ALL DONE", flush=True)
