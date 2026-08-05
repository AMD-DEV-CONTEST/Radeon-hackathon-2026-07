## Train
```bash
python legged_gym/scripts/train.py --task=go2 --num_envs 4096 --headless
python legged_gym/scripts/train.py --task=go2 --num_envs 128 --resume --load_run Nov13_11-14-22_wave_slope_rough_slope
python legged_gym/scripts/train.py --task=go2 --num_envs 8  # DEBUG
python legged_gym/scripts/train.py --task=go2 --num_envs 4090 --headless --robogauge  # Sim2Sim Evaluation
# CTS
python legged_gym/scripts/train.py --task=go2_cts --num_envs 8096 --headless --robogauge
# MoE CTS
python legged_gym/scripts/train.py --task=go2_moe_cts --num_envs 8096 --headless --robogauge
```
## Play
```bash
python legged_gym/scripts/play.py --task=go2 --num_envs 8  # load latest
python legged_gym/scripts/play.py --task=go2 --num_envs 8 --load_run Nov13_00-00-05_  # load specified run
# CTS
python legged_gym/scripts/play.py --task=go2_cts --num_envs 8
```