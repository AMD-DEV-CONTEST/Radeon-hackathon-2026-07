import uvicorn
import os
import sys
from pathlib import Path

# Ensure the parent directory of 'server' is in PYTHONPATH so 'server.main' works
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if __name__ == "__main__":
    uvicorn.run("server.main:app", host="0.0.0.0", port=8000, reload=True)
