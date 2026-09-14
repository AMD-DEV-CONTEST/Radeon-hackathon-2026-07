# 赛道 2 交付清单 — RDK Agent

验证日期：**2026-08-06**。

## 主要交付物

| 交付物 | 文件 | SHA-256 |
| --- | --- | --- |
| 项目说明书 | [RDK_Agent_Project_Specification.pdf](deliverables/RDK_Agent_Project_Specification.pdf) | `d99f78fc2be72c3032df2cc5915870c134d0c0897f819c684e9bde56c371a72e` |
| 路演演示文稿 | [RDK_Agent_Track2_Pitch_Deck.pptx](deliverables/RDK_Agent_Track2_Pitch_Deck.pptx) | `b67ce13cc099480ea9c6a47f882380e81f209005d80fd2f79cf538edcc2ac976` |
| 演示视频 | [B 站主地址](https://www.bilibili.com/video/BV1t3up6iEhy/) · [百度云 MP4 备用地址](https://dagent-platform.bj.bcebos.com/amd-hackathon/amd-hackathon-2026-07.mp4?authorization=bce-auth-v1/ALTAKYR0nFJFHMGlFjuontyVVP/2026-08-06T12%3A43%3A01Z/-1/host/1a12970cc4c9439caa28199256b028f90e82ba41ac92c68fb921b271be0b0acd) | `0cba7eec725a4c8d7e76a3b762c56ce1c96cc8edd9321daf0a2342c0cd0a0a4f` |

## 提交材料源文件

- [提交材料索引](README.md)
- [项目说明书源文件](PROJECT_SPECIFICATION.md)
- [评审复现指南](REPRODUCIBILITY.md)
- [AMD Radeon/ROCm 部署与证据指南](AMD_RADEON_ROCM.md)
- [验证日志](evidence/verification-2026-08-05.md)
- [演示视频占位页与镜头清单](VIDEO.md)
- [Pull Request 文案](PR_DESCRIPTION.md)
- [最终提交检查清单](SUBMISSION_CHECKLIST.md)

## 验证结果

- PDF 是可读、未加密的 12 页 A4 文档，不包含表单或 JavaScript。
- PPTX 压缩包结构有效，包含 12 张幻灯片及演讲者备注源内容，并已通过渲染后的溢出检查。
- 所有本地 Markdown 链接均可解析。
- 面向公众的提交材料源文件中，未检测到常见凭据模式、私有隧道 URL 或开发板内网 IP 地址。
- 可编辑 SVG 图表均为有效 XML。
- 基准测试工具与示例 JSON 配置均通过语法验证。
- 本地视频母版为 3 分 07.2 秒、1920x1080、H.264/AAC、174,000,121 字节，时长符合 3–5 分钟要求。
- B 站主页面和百度云 MP4 备用地址已于 2026-08-06 从外网验证可访问；165.9 MiB 本地母版不进入普通 Git。

## 仍需由参赛者提供的项目

1. 替换团队或参赛者姓名占位符。
2. 附上经脱敏的 AMD Radeon GPU、ROCm、vLLM、模型精度，以及基线与优化配置对比的基准测试证据。
3. 复核 worktree，然后明确批准提交和发布。
