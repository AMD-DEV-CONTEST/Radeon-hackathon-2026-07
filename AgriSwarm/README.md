## AgriSwarm

Give a drone swarm an order in plain English. If it cannot see the plant it was
asked to remove, it trains itself a detector in about two minutes and shares the
weights with the rest of the squad, mid-mission.

Built and measured on a single **AMD Radeon PRO W7900** under ROCm 7.2.

The order names the weed to remove and the plant to leave standing. Each drone
reads it with its own Gemma 4 model, and all of them report they cannot detect
the named species. So one renders its own training images, takes the labels from
the simulator geometry, fine tunes a YOLO26 detector on the GPU, and broadcasts
it to the others. Nothing about that plant was prepared in advance.

### Deliverables

| Item | Link |
| --- | --- |
| Demo video | https://youtu.be/zncShGR-ufE |
| Technical report | `AgriSwarm/AgriSwarm_Technical_Report.pdf` |
| Source code | https://github.com/0xAthkot/AgriSwarm (`fe06ee3`) |
| Reproducibility README | in that repository |

### On the Radeon

Four workloads share one card during a mission: Gemma 4 reasoning at 100 tokens/s
(96% GPU), on demand detector training (85 to 100% GPU), YOLO26 detection at
8.2 ms a frame, and EGL rendering of five cameras in 10.2 ms. An accidental CPU
build of torch gave a like for like comparison on the same data and settings:
**13.6 times faster on the W7900**.

### Results

Four seeded fields, three drones, scored against simulator ground truth.

| Metric | Average | Range |
| --- | --- | --- |
| Recall | 78.5% | 60 to 100% |
| Precision | 89.6% | 75 to 100% |
| Field coverage | 100% | 100% |
| Chemical vs blanket spraying | 2.0% | a 98% reduction |

Four fields is a small sample, so the range matters more than the average.

Measured in simulation against ground truth. Full limitations are in the
technical report.

### Team

aionVIS Tech, three members. MIT licensed.
