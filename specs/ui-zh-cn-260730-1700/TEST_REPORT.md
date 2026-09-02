# Web 工作台中文化测试报告

- Level: S2
- Status: verified
- Spec: `ui-zh-cn-260730-1700`

## 自动化结果

| 命令 | 结果 |
| --- | --- |
| `cd web && npm test -- --run` | 通过：92 项前端测试通过 |
| `cd web && npm run build` | 通过：TypeScript 检查和 Vite 生产构建通过 |
| `.venv\\Scripts\\python.exe scripts\\validate_specs.py --strict` | 通过：严格规格校验无错误 |

## 验收范围

- 登录、项目工作台、任务、风险报告、协作、受控集成和系统运维页的静态用户文案已改为中文；
- 角色、任务状态和常见运维健康状态采用中文显示，不改变 API 枚举值；
- 不翻译运行 ID、文件名、模型名、审计 JSON、GitHub/Jira 等外部产品名称，以保留精确追溯能力；
- 管理员运维页可将模型不可达等常见状态以中文说明展示。
