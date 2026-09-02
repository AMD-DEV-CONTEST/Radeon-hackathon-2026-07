# UI-5 Operations Proxy Fix

- Level: S1
- Status: implemented

The Vite development proxy now forwards `/monitor` and `/admin`, in addition
to the existing API prefixes. Its default FastAPI target is corrected from
port 8000 (llama.cpp chat service) to the documented API port 9000.
