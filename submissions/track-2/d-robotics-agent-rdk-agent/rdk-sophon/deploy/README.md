# 1. deploy 目录总览

> 编译与部署的脚本与文档。本目录面向**部署者/运维**。
> 守护进程的设计见 `docs/design/`，对外接口契约见 `docs/contracts/`。

## 1.1 目录结构

```
deploy/
├── README.md                      # 本文件
├── scripts/                       # 编译与部署脚本
│   ├── build-release.sh           # Mac 交叉编译 aarch64 release 二进制
│   ├── deploy-to-board.sh         # 推到板子 + 远程安装 + 起服务
│   └── install-on-board.sh        # 板端安装（systemd + 配置 + 二进制，远程触发）
└── docs/                          # 编译/部署文档
    ├── build.md                   # 编译说明（本地 release / 交叉编译 / 板上直编）
    └── deploy.md                  # 部署说明（systemd 安装 / 运行 / 升级 / 回滚 / 日志）
```

## 1.2 快速路径

最常用的一键路径（开发机→板子）：

```sh
# 1. 在 Mac 上交叉编译
./deploy/scripts/build-release.sh

# 2. 推到板子并起服务（board-host 是 ssh alias 或 IP）
./deploy/scripts/deploy-to-board.sh x5-root

# 3. 验证（Mac 上）
sophonctl --host 192.168.128.10:7777 state
```

## 1.3 何时用哪条路径

| 场景 | 路径 | 文档 |
|------|------|------|
| 开发机编译 + 推板子（最常用） | `build-release.sh` + `deploy-to-board.sh` | [build.md](docs/build.md)、[deploy.md](docs/deploy.md) |
| 板上直接编译（无交叉环境） | 板上 `cargo build --release` | [build.md](docs/build.md) |
| 手动安装/升级单个二进制 | `install-on-board.sh` + systemctl | [deploy.md](docs/deploy.md) |
| 仅本机调试 | `cargo build --release`（本机 aarch64-apple-darwin） | [build.md](docs/build.md) |

## 1.4 前置条件

- 开发机：Rust 工具链（`rustup`）、`cargo-zigbuild` + `zig`（Mac 交叉编译链接器，见 build.md）、ssh 能连板子。
- 板子：Ubuntu（已验证 22.04 aarch64）、root 权限（装二进制/systemd unit）、`/usr/local/bin` 可写。
- 板子 ssh 别名（如 `~/.ssh/config` 里的 `x5-root`）或 IP，无密码登录更顺。

## 1.5 与 systemd unit / config 的关系

- systemd unit 源在 `systemd/probe-daemon.service`，部署时复制到板子 `/etc/systemd/system/`。
- 默认配置源在 `config/config.toml`，部署时复制到板子 `/etc/probe-daemon/config.toml`。
- 这两个文件随仓库版本管理，部署脚本自动推送最新版。
