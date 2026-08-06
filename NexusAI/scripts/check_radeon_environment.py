import json
from nexus.embeddings.device import detect_device
d=detect_device();print(json.dumps(d.__dict__,indent=2));print("\nNexusAI Radeon status: READY" if d.backend=="rocm" and d.accelerator_available else "\nNexusAI Radeon status: CPU FALLBACK")
