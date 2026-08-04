# Roadmap

1. **Foundation:** product shell, validated uploads, mock campaign workflow, review states, and honest system status.
2. **Hardware validation (verified):** Radeon Cloud, persistent storage, ROCm,
   PyTorch device discovery, and safe telemetry passed in session 1.
3. **Model evaluation (baseline verified):** SDXL base image-to-image compatibility
   is measured; license clearance, IP-Adapter, preservation, and quality review remain.
4. **Real inference (partial verification):** the authenticated single-job
   FastAPI-to-Radeon path passed on loopback; official browser transport, TLS,
   authentication, and CORS passed in session 2b.
5. **Browser E2E and evidence (blocked; fallback active):** Session 3 performed
   the final bounded official retry. Fresh-pod bootstrap, authenticated loopback
   startup, installer/identity prerequisites, and `rc-tunnel 0.3.0` activation
   passed, but public DNS failed in Python, PowerShell, and Chrome before model
   loading. No further paid retry is planned for this submission. Browser
   rendering/persistence QA remains open pending an official resolution or
   approved transport; the submission uses the verified local and earlier
   Radeon evidence with explicit boundaries.
6. **Preservation and optimization:** validate IP-Adapter or mask/compositing
   approaches, quality, text/logo distortion, repeatability, and warm-run reuse.
7. **Product readiness:** authentication, retention controls, export, accessibility audit, deployment documentation, and demo.
