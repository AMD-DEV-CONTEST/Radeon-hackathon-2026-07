# Demo assets

`run_demo.py` writes rollout clips under `outputs/eval_videos/<repo>/`. Copy your
best clip here as `demo.mp4` for the submission:

```bash
python scripts/run_demo.py \
    --checkpoint outputs/train/smolvla_cube_pick/checkpoints/last/pretrained_model \
    --repo-id so101/cube_pick --dataset-root datasets/cube_pick \
    --episodes 3 --save-video
cp outputs/eval_videos/cube_pick/demo_ep00_success.mp4 demo/demo.mp4
```

The clip should show, in order: (1) the language instruction, (2) the camera
view, (3) the VLA action prediction driving the arm, (4) the SO-101 completing
the pick-and-place.
