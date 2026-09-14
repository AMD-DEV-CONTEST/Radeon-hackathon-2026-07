//! CollectionOrchestrator：采集编排用例。遍历 Vec<Box<dyn Collector>>，
//! 用各 Collector 返回的片段组装成完整 StateSnapshot。
//! 从原 executor::methods::collect_all 移入，消除硬编码 6 调用——新增采集器只改注册表。

use std::sync::Arc;

use shared::ports::Collector;
use shared::protocol::StateSnapshot;

use crate::audit::{AuditEntry, AuditLog};
use domain::StateService;

pub struct CollectionOrchestrator {
    collectors: Vec<Box<dyn Collector>>,
    state: Arc<StateService>,
}

impl CollectionOrchestrator {
    pub fn new(collectors: Vec<Box<dyn Collector>>, state: Arc<StateService>) -> Self {
        Self { collectors, state }
    }

    /// 执行一轮采集，组装快照并原子替换 StateService 持有的快照。
    /// 各 Collector 失败返回 None 被跳过，不影响其他采集器。
    pub async fn collect_once(&self) {
        let mut snap = StateSnapshot::empty();
        snap.timestamp = Some(now_iso());
        for c in &self.collectors {
            match c.collect().await {
                Some(frag) => snap.merge_fragment(frag),
                None => tracing::debug!(collector = c.name(), "collector returned None"),
            }
        }
        self.state.replace(snap).await;
    }

    /// 暴露给 telemetry/告警循环：读取当前快照副本。
    pub async fn current_snapshot(&self) -> StateSnapshot {
        self.state.get_state().await
    }

    /// 暴露给 RPC refresh_state 用例：立即采集并返回时间戳。
    pub async fn refresh(&self, audit: &AuditLog, source: &str) -> Option<String> {
        let started = std::time::Instant::now();
        self.collect_once().await;
        let ts = self.state.get_state().await.timestamp.clone();
        audit.record(AuditEntry {
            ts: AuditLog::now_ts(),
            source: source.to_string(),
            method: "refresh_state".into(),
            args: String::new(),
            outcome: "ok".into(),
            duration_ms: started.elapsed().as_millis() as u64,
        });
        ts
    }
}

/// 当前 UTC 时间戳。本函数是横切工具，放这里是因为 Orchestrator 是唯一消费者。
/// 若未来其他 application 用例也需要，再提到 shared。
fn now_iso() -> String {
    chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

#[cfg(test)]
mod tests {
    use super::*;
    use async_trait::async_trait;
    use shared::protocol::StateSnapshotFragment;

    /// 假采集器：返回固定片段。
    struct FixedCollector {
        n: &'static str,
        frag: Option<StateSnapshotFragment>,
    }
    #[async_trait]
    impl Collector for FixedCollector {
        fn name(&self) -> &'static str {
            self.n
        }
        async fn collect(&self) -> Option<StateSnapshotFragment> {
            // 克隆需要 StateSnapshotFragment: Clone，已 derive。
            self.frag.clone()
        }
    }

    #[tokio::test]
    async fn orchestrator_assembles_and_skips_none() {
        // 两个采集器：一个返回片段，一个返回 None。组装后只应有前者的字段。
        let snap = Arc::new(tokio::sync::RwLock::new(StateSnapshot::default()));
        let state = Arc::new(StateService::new(snap));
        let collectors: Vec<Box<dyn Collector>> = vec![
            Box::new(FixedCollector {
                n: "hostname",
                frag: Some(StateSnapshotFragment::Hostname("board".into())),
            }),
            Box::new(FixedCollector { n: "bpu", frag: None }),
        ];
        let orch = CollectionOrchestrator::new(collectors, state.clone());
        orch.collect_once().await;
        let s = state.get_state().await;
        assert_eq!(s.hostname.as_deref(), Some("board"));
        assert!(s.bpu.is_none()); // None 被跳过
    }
}
