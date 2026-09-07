# 在 AMD Radeon 上跑 JAX 强化学习,我踩中了一个藏在 profiler 里的段错误

> 知乎技术文草稿。发布前记得:①替换文末仓库/联系方式为你的真实链接;②配图建议放 rocgdb 栈截图和 `ldd` 输出截图(文中已标注位置);③知乎发布时把一级标题填到"标题"栏,正文从"起因"开始。

## 起因:一个「时灵时不灵」的段错误

这次 AMD Physical AI 黑客松,我的目标是用 PPO 在一块 AMD Radeon(gfx1100)上训练宇树 Go1 四足机器狗行走。技术栈是 MuJoCo Playground(MJX)做 GPU 并行物理仿真、JAX 做计算,ROCm 7.2.1 + JAX 0.11.0。

环境装好、仿真跑通、PPO 也写完了。然后训练开始随机崩溃:

```
Thread ... received signal SIGSEGV
#0  0x0000000100000001 in ?? ()      ← 跳到一个非法地址
```

注意这个崩溃地址 `0x0000000100000001`——它不是一个正常的函数地址,更像是一个被写坏的函数指针或 vtable。更让人头疼的是:**同样的代码、同样的种子、同样的配置,这次崩、下次就 EXIT=0 跑完了**。这种「时灵时不灵」基本排除了普通的越界或显存耗尽,指向一个**竞态条件(race condition)**。

## 定位:rocgdb 把真凶揪了出来

段错误最怕看不到调用栈。我用 `rocgdb` 抓了一次崩溃现场:

```bash
rocgdb -q -batch -ex run -ex bt -ex quit --args python3 scripts/gpu_stress.py 2>&1 | tail -60
```

> 【配图建议 1:这里放 rocgdb 完整栈的截图】

栈从下往上读,关键几帧是这样的:

```
#11 LaunchRocmKernel        (xla_rocm_plugin.so)   ← JAX 的 XLA ROCm 插件发射 kernel
#10 librocprofiler-sdk.so.1                        ← 被 profiler 拦截!
#9  librocprofiler-sdk.so.1
#8  libamdhip64.so.7
 ...
#1  libhsa-runtime64.so.1                          ← 最终在 HSA 运行时里炸了
#0  0x0000000100000001 in ?? ()
```

正常情况下,`LaunchRocmKernel` 应该**直接**下到 `libamdhip64.so.7`(HIP 运行时)。但这里凭空多出了 `#9`、`#10` 两帧 `librocprofiler-sdk.so.1`——**一个性能分析器(profiler)插在了每一次 kernel 发射的路径中间**,然后在 HSA 层把整个进程带崩了。

问题是:我从头到尾**没有开任何 profiling**。这个 profiler 是怎么混进来的?

## 真凶:profiler 被「静态焊死」在了 XLA 插件里

一条 `ldd` 命令揭晓答案:

```bash
$ ldd .../jax_plugins/xla_rocm7/xla_rocm_plugin.so | grep rocprof
librocprofiler-sdk.so.1 => /opt/rocm/lib/librocprofiler-sdk.so.1
librocprofiler-register.so.0 => /opt/rocm/lib/librocprofiler-register.so.0
```

> 【配图建议 2:这里放 ldd 输出的截图】

`jax-rocm7-plugin` 的 `xla_rocm_plugin.so`,把 `librocprofiler-sdk.so.1` 作为一个 **`DT_NEEDED` 依赖**直接链进去了。这不是可选的软链接——插件里实打实调用了 `rocprofiler_force_configure` 这个符号。

而 rocprofiler-sdk 的工作方式,是通过 GOTCHA 机制(`/opt/rocm/lib/rocprofiler-sdk/libgotcha.so`)**拦截每一次 HIP kernel launch**,在 `libamdhip64` 之前插进去做性能采集。这本是设计如此。但在 gfx1100 上,这个注入到 `libhsa-runtime64` 的路径**存在一个竞态**,偶尔会跳到一个非法地址而崩溃。

于是逻辑就闭环了:
1. 我的 PPO 用 `jax.jit` + `lax.scan`,每一步 rollout 发射大量 GPU kernel;
2. profiler 拦截每一次发射;
3. 拦截次数越多、`lax.scan` 嵌套越深,撞上那个竞态的概率越高;
4. 但概率**永远不为零**——哪怕只跑 256 envs × 20 步,也可能一发入魂。

## 我试过的所有「关掉它」的办法,全都无效

这是最折磨人的部分。既然是 profiler 的锅,那把它关掉不就行了?我几乎试遍了所有能想到的手段:

| 尝试 | 结果 |
|---|---|
| `unset HSA_TOOLS_LIB` | ❌ 照崩——它是 NEEDED 链进来的,不走这个环境变量 |
| `unset ROCP_TOOL_LIB` | ❌ 照崩 |
| `ROCPROFILER_DISABLE=1` | ❌ 照崩 |
| `ROCPROFILER_REGISTER_FORCE_LOAD=0` | ❌ 照崩 |
| `XLA_FLAGS=--xla_gpu_enable_command_buffer=`(各种组合) | ❌ 照崩 |
| `--xla_gpu_autotune_level=0` / `--xla_gpu_triton_gemm=false` | ❌ 照崩 |
| 减小 batch / env 数量 | ❌ 竞态还在,只是概率变低 |
| `patchelf --remove-needed librocprofiler-sdk.so.1` | ❌ 报未定义符号 `rocprofiler_force_configure`,JAX 直接退回 CPU |
| 卸载 `rocprofiler-sdk` 包 | ❌ 不可逆地毁掉 JAX 的 GPU 能力 |

核心症结在于:**profiler 是编译期通过 `DT_NEEDED` 焊进插件的,不是运行时按需加载的**。所以任何运行时的环境变量、XLA flag 都碰不到它;而想用 `patchelf` 硬摘,又因为插件依赖它的符号而失败。这是个死结。

## 唯一有点用的缓解,和真正的修法

唯一让我「多活一会儿」的办法,是换训练器的执行路径:brax 自带的 PPO 走 `pmap` + `device_put_replicated`(多设备复制),几乎一启动就撞上竞态;我改成从零手写的单卡 `jax.jit` + `lax.scan` PPO,避开了最快触发崩溃的复制路径,能撑到跑出有限的 reward/loss。但这只是**降低了概率,没有根治**——底层那个 profiler 竞态还在。

真正的修法在上游,我把它写成了一份可复现的 bug 报告,核心建议是:

> **rocprofiler-sdk 应该按需 `dlopen` 动态加载,而不是在构建期静态链进 `xla_rocm_plugin.so`。**

这样一来,那些根本没请求 profiling 的 RL/训练负载,就不必为一个 profiler 的竞态买单。这个改动对 ROCm/JAX 团队是直接可执行的,能解锁一大批受影响配置上的 JAX GPU 训练。

## 写在最后

如果你也在 AMD Radeon 上跑 JAX 的强化学习或大批量迭代计算,遇到了 `libhsa-runtime64` 里莫名其妙、时有时无的段错误,大概率就是这个原因。排查思路可以复用:**先用 rocgdb 抓栈看有没有 profiler 帧,再用 ldd 确认它是不是被静态链进了插件。**

完整的 rocgdb 栈、ldd 证据、试错记录和最小复现脚本,我都整理在了项目仓库里(见文末链接)。踩坑不可怕,把坑标清楚、能让下一个人绕过去,才是开源该有的样子。

---

- 项目仓库:<在这里填你的 GitHub 仓库链接>
- Bug 报告原文(含完整 rocgdb 栈 + 复现脚本):仓库内 `docs/ROCM_BUG_REPORT.md`
- 环境:AMD Radeon gfx1100 · ROCm 7.2.1 · JAX 0.11.0 · jax-rocm7-plugin 0.11.0 · Python 3.12

#AMD #ROCm #JAX #强化学习 #GPU编程
