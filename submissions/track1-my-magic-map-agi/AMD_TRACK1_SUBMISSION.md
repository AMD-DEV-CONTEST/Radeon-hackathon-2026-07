# AMD AI DevMaster Hackathon — Track 1 Project Profile

## Submission identity

- **Track:** Track 1 — Multimodal AI
- **Team:** Eimis Pacheco
- **Application:** My Magic Map AGI
- **Submission repository:** `EimisPacheco/my-magic-map-agi-adm`

## Project background

My Magic Map AGI turns Google Street View and photorealistic 3D Maps into a
body-controlled exploration environment. A webcam becomes a private local
sensor: walking in place advances through connected Street View panoramas,
body direction steers, deliberate arm poses start and control flight, and
face/hand/nose gestures animate a companion or indicate objects in the scene.

The experience combines live video perception, map imagery, speech, text,
personal place memories, visual discovery, and generative media. The Track 1
adaptation adds Radeon-accelerated image-to-image generation and semantic
vision: a user can transform the exact place they are viewing into artwork,
postcards, or virtual memories, and can identify a pointed-at object with the
same AMD service.

## Target users and scenarios

- People who want an accessible, playful way to explore the world from home.
- Travelers creating visual memories and postcards from mapped places.
- Families and students learning geography through embodied interaction.
- Users who benefit from hands-free navigation and large physical gestures.
- Creators turning recognizable real-world scenes into personal artwork.

## System architecture

```text
Webcam
  └─ TensorFlow.js MoveNet + FaceMesh + MediaPipe Hands (browser)
       ├─ gait and body steering ───────────────┐
       ├─ flight pose state machine             │
       └─ face/hand/nose pointing               │
                                                ▼
React application ───── Google Street View / Google Maps 3D
       │
       ├─ OpenAI Realtime speech interface
       ├─ Databricks-backed memories and discoveries
       └─ creative-image or object-vision request
              ▼
        Express security proxy
              ▼ authenticated HTTPS
        Radeon Cloud bridge (FastAPI)
              ├─ ComfyUI + SDXL image-to-image (loopback only)
              └─ Qwen2.5-VL scene + target-crop understanding
                         ▼
        AMD Radeon result + performance metadata
```

## Models and algorithms

- **MoveNet SinglePose Lightning:** low-latency browser pose landmarks.
- **MediaPipe FaceMesh and Hands:** opt-in face expression and hand pointing.
- **GaitEstimator:** normalized, confidence-gated alternating limb analysis.
- **FlyingDetector:** explicit takeoff, flap, bank, altitude, and landing state.
- **ComfyUI image-to-image workflow:** checkpoint-configurable latent diffusion
  using the Street View capture as the source latent and style/palette controls
  as text conditioning.
- **Qwen2.5-VL-3B-Instruct:** structured object identification from a complete
  Street View still and a crop centered on the user's gesture-derived target.

## AMD Radeon and ROCm adaptation

The original image generation route used hosted third-party image APIs. The
Track 1 build introduces an AMD-first provider with these properties:

1. The ComfyUI workload runs in the AMD OneClick ROCm 7.2.1 container.
2. The source image is uploaded to a loopback-only ComfyUI instance.
3. A repository-versioned API workflow performs image-to-image generation.
4. Only a bearer-token-protected FastAPI bridge is exposed through Radeon
   Cloud's HTTP tunnel; the ComfyUI administration interface remains private.
5. The application records bridge upload time, GPU generation time, complete
   round-trip time, checkpoint, GPU name, and detected ROCm/HIP version.
6. The UI visibly reports when AMD Radeon ROCm generation is online.
7. Paint a Place, ordinary postcards, virtual memories, and object vision use
   Radeon first. OpenAI remains an availability fallback and an explicit
   identity-preservation fallback for two-reference person compositions.
8. Gemini is not used and no Gemini credential is required.

This boundary is deliberate. Browser camera inference stays local for privacy
and immediate motion response; the expensive creative and semantic-vision
operations, where GPU throughput materially affects the experience, run on
Radeon/ROCm.

## AMD performance results

Verified on the live Radeon workspace on August 6, 2026. The image benchmark
used the repository's Street View demonstration frame and a fixed seed; the
vision benchmark used the same complete scene plus a 500×500 crop around the
pickup truck.

| Measurement | Result |
| --- | --- |
| Radeon GPU | AMD Radeon Graphics, gfx1100, 48 GiB VRAM |
| ROCm/HIP version | ROCm 7.2.1 container; HIP `7.2.53211-e1a6bc5663` |
| PyTorch | `2.9.1+rocm7.2.1` with GPU available |
| Image checkpoint | SDXL base 1.0, checksum-verified `sd_xl_base_1.0.safetensors` |
| Vision model | `Qwen/Qwen2.5-VL-3B-Instruct`, BF16 on the Radeon GPU |
| Image resolution | 1200×917 input; 1200×920 PNG output |
| Steps / sampler | 28 / Euler / normal scheduler; CFG 6.5; denoise 0.58 |
| Cold image generation | 17.665 s complete bridge round trip |
| Warm image generation | 11.981 s average across three runs (13.380, 11.283, 11.279 s) |
| Cold object vision | 176.884 s including first model load and kernel warm-up |
| Warm object vision | 7.089 s average across three uncached runs (7.096, 7.089, 7.081 s); pickup truck identified at 0.90 confidence |
| Peak VRAM | 24.00 GiB with the Qwen and ComfyUI services resident together |

Access verification also covered the external Radeon HTTPS path: `/health`
returned HTTP 401 without credentials and HTTP 200 with the private bearer
token. ComfyUI itself remained bound to `127.0.0.1`; only the authenticated
FastAPI bridge was tunneled.

## Reproduction

1. Configure and start the root React/Express project as documented in
   `README.md`.
2. Launch an AMD Radeon Cloud notebook with persistent storage and ROCm.
3. Follow `amd-service/README.md` to start ComfyUI and the authenticated bridge.
4. Set the four `AMD_COMFYUI_*` server environment variables.
5. Open Street View, indicate a visible place, choose **Bring view to life**,
   open **Paint a Place**, and create artwork.
6. Confirm the UI shows **AMD Radeon ROCm**, and inspect the server's
   `[PLACE_PAINTING]` structured timing record.

## Final deliverables

- Complete source code and dependency/configuration documentation.
- Project profile PDF: `output/pdf/My_Magic_Map_AGI_Track1_Project_Profile.pdf`.
- Supplementary poster: `output/pdf/My_Magic_Map_AGI_Track1_Poster.pdf`.
- 4:19 actual-operation demo video: `AMD-Magical-Map-AGI.mp4`.
