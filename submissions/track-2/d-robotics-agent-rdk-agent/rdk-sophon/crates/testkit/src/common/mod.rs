//! 测试公共工具：假 infra 实现，供集成/E2E 测试注入。
//! FakeSysfsReader/FakeProcReader/FakeHrutGateway/FakeShellRunner 用 HashMap 预设数据。
//! make_fake_* 构造典型板端数据。Mac 上无需真实 /proc /sys 即可跑全链路测试。

mod fakes;
mod fixtures;

pub use fakes::{FakeSysfsReader, FakeProcReader, FakeHrutGateway, FakeShellRunner, FakeCollector};
pub use fixtures::{make_fake_sysfs, make_fake_proc, make_fake_hrut, make_thermal_snap};
