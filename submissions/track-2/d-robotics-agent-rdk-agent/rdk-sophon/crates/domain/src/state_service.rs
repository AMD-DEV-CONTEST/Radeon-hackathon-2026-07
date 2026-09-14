//! StateService：硬件状态快照的读写领域服务。
//! 持 Arc<RwLock<StateSnapshot>>，提供各片段的领域类型读取（不碰 serde_json::Value）。
//! Value 转换在 application 层完成。Orchestrator 采集后用 replace 原子替换。

use std::sync::Arc;

use shared::protocol::{CpuInfo, DiskInfo, MemoryInfo, NetInfo, StateSnapshot, Thermal, BpuInfo};
use tokio::sync::RwLock;

pub struct StateService {
    snapshot: Arc<RwLock<StateSnapshot>>,
}

impl StateService {
    pub fn new(snapshot: Arc<RwLock<StateSnapshot>>) -> Self {
        Self { snapshot }
    }

    /// 暴露底层 snapshot Arc，供 Orchestrator 写入用。
    pub fn snapshot_handle(&self) -> Arc<RwLock<StateSnapshot>> {
        Arc::clone(&self.snapshot)
    }

    /// 读完整快照副本（领域类型）。
    pub async fn get_state(&self) -> StateSnapshot {
        self.snapshot.read().await.clone()
    }

    pub async fn get_thermal(&self) -> Option<Thermal> {
        self.snapshot.read().await.thermal.clone()
    }
    pub async fn get_cpu(&self) -> Option<CpuInfo> {
        self.snapshot.read().await.cpu.clone()
    }
    pub async fn get_memory(&self) -> Option<MemoryInfo> {
        self.snapshot.read().await.memory.clone()
    }
    pub async fn get_disk(&self) -> Option<Vec<DiskInfo>> {
        self.snapshot.read().await.disks.clone()
    }
    pub async fn get_net(&self) -> Option<Vec<NetInfo>> {
        self.snapshot.read().await.net.clone()
    }
    pub async fn get_bpu(&self) -> Option<BpuInfo> {
        self.snapshot.read().await.bpu.clone()
    }

    /// 原子替换整个快照。Orchestrator 应先在锁外 collect 完再调本方法，
    /// 避免采集期间持有写锁阻塞所有读。
    pub async fn replace(&self, snap: StateSnapshot) {
        *self.snapshot.write().await = snap;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use shared::protocol::{Thermal, ThermalZone};

    #[tokio::test]
    async fn replace_and_get_thermal() {
        // 替换快照后，get_thermal 返回新值。
        let svc = StateService::new(Arc::new(RwLock::new(StateSnapshot::default())));
        assert!(svc.get_thermal().await.is_none());
        svc.replace(StateSnapshot {
            thermal: Some(Thermal {
                zones: vec![ThermalZone { name: "cpu".into(), temp_c: 55.0 }],
            }),
            ..Default::default()
        })
        .await;
        let t = svc.get_thermal().await.unwrap();
        assert_eq!(t.zones[0].temp_c, 55.0);
    }
}
