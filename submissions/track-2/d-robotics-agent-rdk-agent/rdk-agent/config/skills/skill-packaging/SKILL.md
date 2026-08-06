---
name: skill-packaging
description: 将已交付的 sophonctl 能力封装为可发现、可执行的 Skill。
---

# Skill 打包

Skill 使用 `SKILL.md`，且必须采用 Pi 可发现的完整格式：

```markdown
---
name: servo-control
description: 一句非空的能力描述
---

# 正文标题
```

第一行和 frontmatter 的闭合行都必须精确为 `---`；`name` 使用合法的小写连字符名称，`description` 必须非空，正文也不能为空。缺少这段元数据的 Markdown 普通文档不是可加载的 Skill。

更新已有 Skill 时，必须先读取现有 `SKILL.md`，保留全部既有能力、安全规则和结果报告，再增量加入新动作；不得用只描述新动作的文档覆盖整个 Skill。正文应覆盖：何时使用、前置条件、准确命令、参数说明、失败处理和验收示例。命令应调用已经存在的 `sophonctl <plugin> <args...>` 接口，不能绕过 sophonctl 或假设 shell 权限。
