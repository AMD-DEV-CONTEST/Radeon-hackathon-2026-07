# End-to-end architecture

```mermaid
flowchart TB
  subgraph Data[Data plane]
    D1[Authorized DL3DV archive]
    D2[Official BiGym demonstrations]
    D3[Public manifests and synthetic fixture]
  end

  subgraph Reconstruction[Cross-platform reference branch]
    R1[Safe extraction]
    R2[Known-pose COLMAP + SIFT]
    R3[default and MCMC 30k]
    R4[Quality-gated Graphdeco PLY]
    R5[Sim3 and room-layer export]
  end

  subgraph Runtime[AMD ROCm main branch]
    A1[ROCm gsplat native gate]
    A2[Gaussian background render]
    A3[MuJoCo segmentation foreground]
  end

  subgraph Inference[External inference boundary]
    I1[Model service outside this branch]
    I2[HTTP client contract v2]
    I3[Provider selected by URL]
  end

  subgraph Evaluation[Evaluation and recording plane]
    E1[BiGym closed loop]
    E2[3 synchronized camera MP4s]
    E3[Append-only transitions and atomic manifests]
    E4[Recording, result and visual validation]
  end

  subgraph Collection[Official demonstration replay plane]
    C1[20 Hz reward precheck]
    C2[32 unique replay UUIDs]
    C3[LeRobot v3 + 3 merged videos]
    C4[Hash, decode and visual acceptance]
  end

  D1 --> R1 --> R2 --> R3 --> R4 --> R5
  R5 --> A1 --> A2 --> A3
  I1 --> I2 --> I3 --> E1
  A3 --> E1 --> E2 --> E3 --> E4
  D2 --> C1 --> C2
  A3 --> C3
  C2 --> C3 --> C4
  D3 -. CI contract .-> R5
```

The code is delivered from one repository, but the runtime planes remain
deliberately separate. A valid PLY does not prove BiGym integration; a healthy
inference endpoint does not prove a complete transition sequence; a complete
recording does not prove task success; and a fully decoded dataset does not
prove photographic quality. Each boundary emits a machine-readable receipt.
