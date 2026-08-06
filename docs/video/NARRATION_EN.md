# English narration

The narration is embedded in `smolvla_success_failure_demo.mp4` using the English
Flite `slt` voice available in FFmpeg. The video covers:

1. the 600-episode domain-randomized imitation-learning dataset;
2. successful SmolVLA rollouts for banana, lemon, and plum;
3. measured success rates of 99%, 94%, and 34%;
4. saved lemon and plum failure examples;
5. approach, grasp, lift, and transport-drop failure causes;
6. HIP Graph and Targeted Compile performance and correctness tradeoffs.

The saved visualization set contains ten successful banana rollouts and no banana
failure. The narration states this explicitly rather than substituting a failure from
the older `fruit_pick_150ep` policy.

Rebuild with:

```bash
bash docs/video/build_success_failure_video.sh
```
