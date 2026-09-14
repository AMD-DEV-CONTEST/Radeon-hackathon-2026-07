//! Hardware state snapshot data model.
//!
//! A `StateSnapshot` is the single source of truth that collectors write and
//! that telemetry push / pull / alert paths all read. Keeping one shape avoids
//! drift between the three reporting modes.

use serde::{Deserialize, Serialize};

/// One point-in-time view of all tracked hardware state on the board.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct StateSnapshot {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub timestamp: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hostname: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub uptime_secs: Option<f64>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub thermal: Option<Thermal>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cpu: Option<CpuInfo>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub memory: Option<MemoryInfo>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub disks: Option<Vec<DiskInfo>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub net: Option<Vec<NetInfo>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub bpu: Option<BpuInfo>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub power: Option<PowerInfo>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Thermal {
    /// Zone label → temperature in °C (milli-celsius stored as float for clarity).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub zones: Vec<ThermalZone>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ThermalZone {
    pub name: String,
    #[serde(rename = "tempC")]
    pub temp_c: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct CpuInfo {
    /// Aggregate load averages over 1/5/15 minutes, where available.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub load_avg: Option<Vec<f64>>,
    /// Per-core utilisation 0..100.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub core_usage: Vec<f64>,
    /// Per-core frequency in MHz, if exposed.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub core_freq_mhz: Vec<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct MemoryInfo {
    #[serde(rename = "totalBytes")]
    pub total_bytes: u64,
    #[serde(rename = "usedBytes")]
    pub used_bytes: u64,
    #[serde(rename = "freeBytes")]
    pub free_bytes: u64,
    /// Swap, in bytes. 0 if absent.
    #[serde(rename = "swapTotalBytes", default)]
    pub swap_total_bytes: u64,
    #[serde(rename = "swapUsedBytes", default)]
    pub swap_used_bytes: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct DiskInfo {
    pub mount: String,
    pub fs_type: String,
    #[serde(rename = "totalBytes")]
    pub total_bytes: u64,
    #[serde(rename = "usedBytes")]
    pub used_bytes: u64,
    #[serde(rename = "freeBytes")]
    pub free_bytes: u64,
    /// 0..100.
    pub usage_pct: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct NetInfo {
    pub name: String,
    pub up: bool,
    #[serde(rename = "mac")]
    pub mac: Option<String>,
    #[serde(skip_serializing_if = "Vec::is_empty", default)]
    pub addrs: Vec<String>,
    #[serde(rename = "rxBytes")]
    pub rx_bytes: u64,
    #[serde(rename = "txBytes")]
    pub tx_bytes: u64,
}

/// Horizon RDK BPU (Brain Processing Unit) utilisation. Fields may be absent
/// when the board is not an RDK unit or the `hrut` tool is unavailable.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct BpuInfo {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub utilisation_pct: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub temp_c: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub freq_mhz: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct PowerInfo {
    /// Millivolts; collected when a rail node is exposed.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub voltages_mv: Vec<PowerRail>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub battery_pct: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub online: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct PowerRail {
    pub name: String,
    #[serde(rename = "mV")]
    pub mv: f64,
}

impl StateSnapshot {
    pub fn empty() -> Self {
        Self::default()
    }

    /// 合并一个采集片段到本快照。供 CollectionOrchestrator 逐个 Collector 调用后组装。
    /// 同一字段后写覆盖先写，因此各 Collector 应只返回自己负责的片段。
    pub fn merge_fragment(&mut self, frag: StateSnapshotFragment) {
        match frag {
            StateSnapshotFragment::Hostname(v) => self.hostname = Some(v),
            StateSnapshotFragment::Uptime(v) => self.uptime_secs = Some(v),
            StateSnapshotFragment::Thermal(v) => self.thermal = Some(v),
            StateSnapshotFragment::Cpu(v) => self.cpu = Some(v),
            StateSnapshotFragment::Memory(v) => self.memory = Some(v),
            StateSnapshotFragment::Disks(v) => self.disks = Some(v),
            StateSnapshotFragment::Net(v) => self.net = Some(v),
            StateSnapshotFragment::Bpu(v) => self.bpu = Some(v),
        }
    }
}

/// 单个采集器返回的状态片段。Orchestrator 遍历各 Collector 后用 merge_fragment 组装成完整快照。
/// 用枚举而非 Box<dyn Any>：保留类型安全，序列化时无需擦除。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum StateSnapshotFragment {
    Hostname(String),
    Uptime(f64),
    Thermal(Thermal),
    Cpu(CpuInfo),
    Memory(MemoryInfo),
    Disks(Vec<DiskInfo>),
    Net(Vec<NetInfo>),
    Bpu(BpuInfo),
}
