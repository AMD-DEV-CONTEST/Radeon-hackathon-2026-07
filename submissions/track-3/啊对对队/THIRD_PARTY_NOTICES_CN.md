# 第三方开源软件说明

以下开源项目是本项目的运行时依赖。bootstrap 脚本和 Docker 构建会下载锁定提交的
源码；本仓库不直接包含这些上游源码。

| 项目 | 锁定提交 | 许可证 | 用途 |
| --- | --- | --- | --- |
| Genesis World | `ec0efcc0daf9b9932920e6b73f5f810961330997` | Apache-2.0 | ROCm 物理仿真、传感器、渲染和机器人控制 |
| LeRobot | `73dbb6f43a5088583706c91fb73c6957bca5f806` | Apache-2.0 | 数据集格式、ACT、Diffusion 和 SmolVLA 策略路径 |
| PyTorch | 云端镜像所带版本 | BSD 类许可证 | ROCm 模型训练与推理 |

本项目未提交任何第三方源码。下载到 `third_party/` 的源码不会进入 Git，并继续保留
各上游项目自己的许可证和版权说明。

`scripts/smoke_genesis.py` 是本项目原创的集成冒烟测试，其 API 用法参考了以下
Apache-2.0 Genesis World 示例：

- `examples/rigid/franka_cube.py`
- `examples/tutorials/control_your_robot.py`
- `examples/sensors/depth_camera_custom_vverts.py`

本中文文件用于阅读辅助；许可证效力和准确条款以各上游项目原始许可证为准。
