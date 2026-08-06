# 1. 编译说明

> rdk-sophon 是 Rust workspace，4 个二进制：`probe-daemon`（守护进程）、`sophonctl`（CLI）、`probe-http-gateway`（REST 网关）、`probe-ws-outbound`（WS 出站）。
> 板端目标是 aarch64 Linux（Ubuntu）。本文档说明三种编译方式。

## 1.1 方式一：开发机交叉编译（推荐，最常用）

在 Mac 上交叉编译到 aarch64，产物 scp 到板子。**不需要在板子上装 Rust**，速度也比板上直编快。

### 脚本

```sh
./deploy/scripts/build-release.sh
```

脚本流程（见 `deploy/scripts/build-release.sh`）：
1. `rustup target add aarch64-unknown-linux-gnu`（幂等）。
2. 跑 `./scripts/full_test.sh`（check + clippy + test + release build），确保出包前全绿。`--skip-checks` 可跳过（不建议）。
3. 用 `cargo zigbuild` 交叉编译 4 个 bin（Mac 上免配交叉链接器；若无 zigbuild 则回退 `cargo build`，需系统有 aarch64-linux-gnu 链接器）。
4. 打印产物清单（路径 + 大小）。

产物：`target/aarch64-unknown-linux-gnu/release/{probe-daemon,sophonctl,probe-http-gateway,probe-ws-outbound}`。

### 一次性装交叉编译环境（Mac）

```sh
# zigbuild + zig：Mac 上交叉编译 aarch64-linux-gnu 的最省事方案
cargo install cargo-zigbuild
brew install zig
```

装好后 `build-release.sh` 会自动检测并使用 zigbuild。

### 手动交叉编译（不用脚本）

```sh
rustup target add aarch64-unknown-linux-gnu
cargo zigbuild --release --target aarch64-unknown-linux-gnu --bin probe-daemon --bin sophonctl
```

## 1.2 方式二：板上直接编译

板子性能够时（已验证 RDK X5：8 核 6.9G 内存，release 约 3 分钟）可直接在板上编译。适合无交叉环境、或想用板子的 gcc 直接链接的场景。

### 前置：板上装 Rust（用国内镜像加速）

```sh
# 在板子上
export RUSTUP_DIST_SERVER=https://mirrors.tuna.tsinghua.edu.cn/rustup
export RUSTUP_UPDATE_ROOT=https://mirrors.tuna.tsinghua.edu.cn/rustup/rustup
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable --profile minimal
source ~/.cargo/env
rustup default stable  # 若 manifest 缺失，用国内镜像重装（见 deploy.md 故障排查）

# crates.io 用清华镜像加速依赖下载
mkdir -p ~/.cargo
cat > ~/.cargo/config.toml <<'EOF'
[source.crates-io]
replace-with = "tuna"
[source.tuna]
registry = "sparse+https://mirrors.tuna.tsinghua.edu.cn/crates.io-index/"
[net]
retry = 5
EOF
```

### 编译

```sh
# 把源码推到板子（开发机）
rsync -az --exclude='target' --exclude='.git' ./ x5-root:/root/rdk-sophon/

# 板上编译
ssh x5-root 'cd /root/rdk-sophon && cargo build --release --bin probe-daemon --bin sophonctl'
# 产物：/root/rdk-sophon/target/release/{probe-daemon,sophonctl}
```

板上编译产物在 `target/release/`（板子原生 aarch64，无需 target 指定）。

## 1.3 方式三：本机调试编译（开发机原生）

本机调试用，产物是开发机架构（如 aarch64-apple-darwin），**不能**跑在板子上。

```sh
cargo build --release          # 全部
cargo build --release --bin probe-daemon   # 单个
```

本机跑 daemon 测试协议/控制流（非真实硬件，采集器返回 None）：
```sh
./target/release/probe-daemon --config config/config.toml --dry-run
```

## 1.4 编译产物一览

| 二进制 | 用途 | 默认监听 |
|--------|------|---------|
| `probe-daemon` | 板端守护进程 | TCP `0.0.0.0:7777`、Unix `/run/probe-daemon/probe.sock` |
| `sophonctl` | CLI（本地/远程） | — |
| `probe-http-gateway` | REST 网关 | `0.0.0.0:8080` |
| `probe-ws-outbound` | WebSocket 出站 | —（主动外连云端） |

## 1.5 release profile 特性

根 `Cargo.toml` 的 `[profile.release]`：`opt-level=3`、`lto="thin"`、`codegen-units=1`、`strip=true`、`panic="abort"`。
- `strip` 减小体积；`panic="abort"` 不影响测试（cargo 自动给 test profile 用 unwind）。
- `lto` 牺牲编译时间换体积与优化，板上 release 约 3 分钟主要花在此。

## 1.6 故障排查

- **交叉编译链接失败**：Mac 上务必用 zigbuild（自带链接器），别手动配 aarch64-linux-gnu-gcc。
- **rustup manifest 缺失/下载中断**：换国内镜像（tuna），`rustup toolchain install stable --profile minimal` 重试，见 deploy.md「故障排查」。
- **crate 下载慢**：配置 crates.io 镜像（tuna/sparse）。
- **编译报 libc/statvfs**：`infra/src/statvfs.rs` 的 FFI 仅 Linux 编译，Mac 上交叉编译到 linux target 没问题；本机原生编译（apple-darwin）会编成空实现（返回 None），不影响其它。
