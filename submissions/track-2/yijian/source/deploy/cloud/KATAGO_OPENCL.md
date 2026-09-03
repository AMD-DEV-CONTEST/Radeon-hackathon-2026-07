# W7900 KataGo execution contract

This deployment keeps the existing GoMentor HTTP API and KataGo analysis JSON
protocol unchanged. Only the process transport can change from a local child
process to an encrypted SSH stdio process.

## Pinned artifacts

- KataGo: `v1.16.5`, source commit `ba938676d7f42d70950b3a535af2466fb642008c`
- Build source archive SHA-256: `7ba3ef402d64af1ca6e5c0560675e39cfa05ae4275087147187e53ba040c9998`
- Network: `kata1-zhizi-b40c768nbt-s11272M-d5935M.bin.gz`
- Network bytes: `863210287`
- Network SHA-256: `15fb3baf85cdb6578e6c19b65e6201ca906cec3ba5fee19039d05221d57eb0e8`

The source archive and network are installed on `/persistent/yijian`; neither
binary weights nor tuning output belong in Git.

## Build and verify

```bash
bash deploy/cloud/install_katago_opencl.sh
python3 deploy/cloud/download_katago_model.py
python3 deploy/cloud/benchmark_katago_analysis.py \
  --katago /persistent/yijian/katago-v1.16.5/build/katago \
  --model /persistent/yijian/katago-models/kata1-zhizi-b40c768nbt-s11272M-d5935M.bin.gz \
  --config deploy/cloud/katago_analysis_w7900.cfg \
  --output /persistent/yijian/benchmarks/katago-w7900-production.json
```

The benchmark uses a checked-in synthetic position. It does not discover or
read files from the private game library.

## Local application opt-in

Cloud analysis is disabled by default. After the production benchmark passes,
create the ignored marker `gomentor/runtime/cloud-katago.enabled` and restart
the workbench. Delete that marker and restart to return to local-only analysis.

When enabled, the long-running SSH process carries only KataGo analysis JSON.
The CPU SGF parser, phase detection, evidence assembly, LLM narrative step, and
SQLite cache remain controlled by the existing server workflow.

