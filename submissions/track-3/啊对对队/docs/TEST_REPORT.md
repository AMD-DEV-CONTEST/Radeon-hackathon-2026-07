# Test Report / 测试报告

Local submission checks were run on 2026-08-05 with the bundled Python 3.12
runtime. The Radeon simulation and training paths still require the documented
Linux ROCm container.

本地提交检查于 2026-08-05 使用 Python 3.12 运行。Radeon 仿真与训练仍需使用文档中
说明的 Linux ROCm 容器。

| Check | Result |
| --- | --- |
| Python compilation for `src`, `scripts`, and `tests` | passed |
| Expert CLI plus Genesis environment tests | **39/39 passed** |
| Final video source audit | 8 required successes, 8 overview streams, 2 wrist streams; passed |
| Final MP4 decode | 1920x1080 H.264, 59.0 s, sampled frames nonblank; passed |
| Final MP4 SHA-256 | `8327326166624e4de0c8dcea80703f6ebd4535b360768cb0416111d831aa56fd` |
| Video concat manifest | 8 sources and output fully decoded; frame count and duration matched |
| Radeon activation script syntax | `scripts/activate_radeon_env.sh`; passed with Git Bash `bash -n` |
| File-size audit | no file over 100 MB |
| Focused credential-pattern scan | no credential-shaped secret found |

The broad historical suite has 738 discovered tests on the submission branch.
It reports 8 failures, 13 errors, and 8 skips in this non-ROCm Windows runtime.
The untouched `a0c2a49` baseline reports the same 8 failures, 13 errors, and 8
skips across 737 tests. The additional wrist-camera test passes, so this
submission change adds no broad-suite regression. Existing failures are frozen
source/evidence hash assertions already present at the baseline; existing
errors are missing optional PyTorch, PyArrow, or PyAV dependencies plus one
baseline preregistration file absent from the tracked commit.

The final container review also fixed environment discovery before `CMD`:
`activate_radeon_env.sh` now accepts the already active ROCm `sys.prefix`, while
only sourcing `bin/activate` when that file exists. The existing project `.venv`
and `/workspace/rdna` candidates remain supported.

提交分支共发现 738 项历史测试；在非 ROCm Windows 环境中为 8 个失败、13 个错误和
8 个跳过。未修改的 `a0c2a49` 基线在 737 项测试中具有完全相同的失败、错误和跳过
数量。新增腕部相机测试通过，因此本次提交未增加全量测试回归。既有失败来自基线中
已经存在的冻结源码/证据哈希断言；既有错误来自缺少可选的 PyTorch、PyArrow、PyAV
依赖，以及基线提交未跟踪的一个预注册文件。

最终容器审查还修复了 `CMD` 启动前的环境发现：`activate_radeon_env.sh` 现在能够
沿用当前已生效的 ROCm `sys.prefix`，并且仅在 `bin/activate` 确实存在时执行
激活；原有项目 `.venv` 与 `/workspace/rdna` 候选路径保持兼容。
