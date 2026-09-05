# Deployment Guide

## Docker
```dockerfile
FROM ubuntu:22.04
COPY aisearch /usr/local/bin/
CMD ["aisearch", "index", "/data"]
```

## Kubernetes
Deploy as a sidecar container for AI agents to query file contents.
