# Changelog

All notable changes to the XAI project are documented in this file.

格式基于 [Keep a Changelog](https://keepachangelog.com/)，
版本号遵循 [SemVer](https://semver.org/)。

---

## [Unreleased]

### Added
- 视觉多模态对话：聊天上传图片经 `@file:` 引用路由到支持视觉的模型，自动构造 OpenAI 兼容 `image_url` 多模态 content（纯标准库，替代已移除的 `imghdr` 用魔数探测图片类型）
- 聊天上传按钮分类：图片（`image/*`）/ 文件 两类菜单，视觉模型显示紫色「视觉」徽标 + 上传提示
- Settings 后端 URL 实时生效：`apiBase()` 前缀所有 `/api` 请求（含 changelog 拉取），不再只存不用
- `model_registry` 新增 `vision` 字段与 `is_vision()` 启发式识别（vision/vl-/qwen-vl/gpt-4o/grok-4/pixtral/llava/internvl/minicpm-v/cogvlm/glm-4v）

### Changed
- 模型不支持视觉时，图片作为附件记录提示，模型看不见图片内容（优雅降级）

### Fixed
- 修复 legacy `/api/models/list` 未序列化 `vision` 字段，导致前端 `vision` 恒为 `None`、视觉分支永不触发的回归

### Removed

---

## [v4.0.0] - 2026-07-19

### Added

- V4 双引擎并列架构（Hermes 通用推理 + Grok Build 代码工程）
- 8 层记忆体系（工作/短期/长期/锚点/反思/因果/用户画像/错误修正）
- P0/P1/P2 安全治理闸门（Guardian + ApprovalQueue）
- 意图路由器（IntentRouter）自动任务分类分发
- ControlLoop 认知控制环（Reason → Meta → Guardian → Execute）
- OpenClaw 执行网关（文件/终端/浏览器/扫描/MCP）
- GEPA 自进化蒸馏管道
- 前端统一操作台（React + ReactFlow 工作流画布）
- 73+ 单元测试覆盖

### Security

- Guardian P0 操作强制审批（delete_file, rm_rf, force_push 等）
- 路径穿越防护（_safe_path）
- 风险操作内容级识别（rm -rf / mkfs / drop table 等自动升级 P0）
