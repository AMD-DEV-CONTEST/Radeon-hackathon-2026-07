//! tests crate：测试公共工具 + 集成 + E2E。
//!
//! - `common`：FakeReader/FakeCollector/fixtures，供集成与 E2E 注入假 infra。
//! - `tests/`：集成测试（in-memory StubTransport）与 E2E 测试（真实端口）。
//!
//! 被 domain/daemon 等的 dev-dependencies 引用（用 `testkit::common::FakeSysfsReader` 等）。

pub mod common;
