# workflows/

本目录存放 ComfyUI 工作流文件（**API 格式** JSON），命名规则：

- `W1_concept.json` 概念原画
- `W2_depth.json` 深度图
- `W3_material.json` 3D 贴图材质
- `W4_music.json` 背景音乐
- `W5_sfx.json` 环境音效
- `W6_sprite.json` 序列帧图集
- `W7_model.json` 2D 角色图 → 3D 模型（TripoSR，GLB/OBJ）

如何导出 API 格式：在 ComfyUI 中编辑好工作流后，菜单 `Workflow → Export (API)`。

每个工作流文件内应记录默认参数；任务提交时由后端覆盖 prompt / seed 等可变量。

> P1~P4 已生成 W1~W6 六个工作流（概念原画/深度图/材质/音乐/音效/序列帧图集）并验证通过。
> W7（2D→3D）需要先运行 `bash scripts/setup_3d.sh` 安装 TripoSR 节点，
> 再用 `bash scripts/download_3d_model.sh` 下载模型权重。
