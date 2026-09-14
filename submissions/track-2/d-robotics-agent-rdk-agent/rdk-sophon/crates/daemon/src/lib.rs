//! daemon 库：依赖注入装配与运行时编排。
//!
//! 暴露两个装配函数：
//! - build_production_app：用真实 infra（RealSysfsReader 等）构造 App，供 main 生产用。
//! - build_test_app：用假 infra（FakeReader 等）构造 App，供 E2E 测试在 Mac 上跑。
//!
//! 这样 E2E 测试能注入假 /proc /sys 数据，但 TCP/Unix transport 仍是真实的，
//! 测的是传输层真实行为，采集器数据源真假不影响传输正确性。

mod bootstrap;

pub use bootstrap::{App, AppHandles, build_production_app, build_test_app, build_test_app_with_collectors, accept_tcp_loop, accept_unix_loop};
pub use config::Config;

pub mod config;
