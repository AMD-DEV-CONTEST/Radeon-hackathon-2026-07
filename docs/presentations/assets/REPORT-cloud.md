# BotverseX 投资人 Deck 素材搜集报告

## 任务概述

本报告总结了为 BotverseX Seed 投资人 HTML deck 搜集、筛选、下载或生成可用图片/GIF 的工作。所有生成的素材均已放置在 `botversex-deck-assets/` 目录下，并附带了 `MANIFEST.md` 清单和 `LOCAL_ONLY_FOR_FOUNDER.md` 文件。

## 完成情况

### P0 优先级

*   **`pipeline-6steps.png`**: 已生成。通过 SVG 代码绘制了“连接→遥操作→录数据→训练→部署→技能”六步闭环信息图，并成功导出为 PNG 格式 (1920x1080)。
*   **`teleop-demo.gif` 或 `.mp4`**: 未能从公网获取。此素材需要 SO-101 Leader/Follower 遥操作实拍，已列入 `LOCAL_ONLY_FOR_FOUNDER.md`，需创始人提供。
*   **`team-ethan.jpg` (CEO 杨智超半身照)**: 未能从公网获取。已列入 `LOCAL_ONLY_FOR_FOUNDER.md`，需创始人提供。
*   **`team-liuqi.jpg` (CTO 刘琦半身照)**: 未能从公网获取。已列入 `LOCAL_ONLY_FOR_FOUNDER.md`，需创始人提供。

### P1 优先级

*   **`ecosystem-runtimes.png`**: 已生成。通过 SVG 代码绘制了机械臂、人形、四足机器人三格拼贴图，并成功导出为 PNG 格式 (1920x1080)。图中标注了“生态示意，非全部已接入”和“Building Integration”。
*   **`unitree-go2-reference.jpg`**: 已下载。从 Unitree 官方网站获取了 Unitree Go2 的参考图片。
*   **`reachy-demo-short.gif`**: 已下载。从 Pollen Robotics 官网获取了 Reachy Mini 的 GIF 演示图。
*   **`aihub-models-collage.png`**: 未能从公网获取。此素材需要 AI Hub + Models 两屏拼图，已列入 `LOCAL_ONLY_FOR_FOUNDER.md`，需创始人提供。
*   **`before-after-platform.png`**: 已生成。通过 SVG 代码绘制了 ROS/脚本碎片与 BotverseX 统一平台的对比信息图，并成功导出为 PNG 格式 (1920x1080)。

### P2 优先级

*   **`scene-factory.webp` / `scene-lab.webp`**: 已下载。从 StockSnap.io 获取了两张 CC0 授权的工厂和实验室氛围图，并已注明为“示例场景”。
*   **`marketplace-mockup.png`**: 已生成。通过 SVG 代码绘制了 Skill 商店线框图，并成功导出为 PNG 格式 (1920x1080)。图中标注了“Building”。
*   **`architecture-export.png`**: 未生成。由于没有提供 deck 架构 SVG 文件，无法导出。

## 版权风险说明

所有通过 `curl` 下载的图片均来自官方网站或明确标注为 CC0 授权的图库，已在 `MANIFEST.md` 中注明来源和授权类型。AI 生成的 SVG/PNG 信息图为 Manus AI 自有创作，无版权风险。

**重要提示**：请勿使用 `LOCAL_ONLY_FOR_FOUNDER.md` 中列出的素材进行公开展示，除非您已确认其版权和使用权限。

## 用户操作指南

请将 `botversex-deck-assets/` 目录下的所有文件（包括 `images/`、`diagrams/` 文件夹以及 `docs/MANIFEST.md`、`docs/LOCAL_ONLY_FOR_FOUNDER.md` 和 `docs/REPORT.md`）复制到您的项目目录 `docs/presentations/assets/` 中。

```bash
cp -r /home/ubuntu/botversex-deck-assets/* /home/amd/下载/dev/botversex/docs/presentations/assets/
```

然后，请根据 `MANIFEST.md` 中的建议，将图片路径更新到您的 `investor-seed-2026.html` 文件中。对于 `LOCAL_ONLY_FOR_FOUNDER.md` 中列出的素材，请您自行提供并放置到 `docs/presentations/assets/` 目录中。

## 总结

本次任务已成功搜集并生成了大部分所需素材，并严格遵守了版权和视觉规范。未能获取的素材已明确列出，并提供了获取建议。
