// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/notification
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "Notification", table = "notification_data", data_service = "sqlite")]
pub struct Notification {
#[teaql(id)]
    id: u64,

// @source platform_modules.xml:89
    subject: String,

// @source platform_modules.xml:89
    body: String,

// @source platform_modules.xml:89
    notification_type: String,

// @source platform_modules.xml:89
    status: String,

// @source platform_modules.xml:89
    scheduled_time: chrono::DateTime<chrono::Utc>,

// @source platform_modules.xml:89
    sent_time: chrono::DateTime<chrono::Utc>,

// @source platform_modules.xml:89
    create_time: chrono::DateTime<chrono::Utc>,

// @source platform_modules.xml:89
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source platform_modules.xml:89
#[teaql(column = "recipient")]
    recipient_id: u64,
// @source platform_modules.xml:89
#[teaql(relation(target = "User", local_key = "recipient_id", foreign_key = "id"))]
    recipient: Option<crate::User>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl Notification {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            subject: String::new(),
            body: String::new(),
            notification_type: String::new(),
            status: String::new(),
            scheduled_time: chrono::Utc::now(),
            sent_time: chrono::Utc::now(),
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            recipient_id: 0_u64,
            recipient: None,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("Notification", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.recipient {
            entity.attach_root_recursive(root.clone());
        }
    }

    pub fn is_loaded(&self, field_or_relation: &str) -> bool {
        self.__load_state.is_loaded(field_or_relation)
    }

    pub fn set_load_state(&mut self, state: teaql_core::eval::LoadState) {
        self.__load_state = state;
    }

    pub fn id(&self) -> u64 {
        self.changed_id().and_then(|value| value.try_u64()).unwrap_or(self.id)
    }

    pub fn update_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.id = value.try_u64().unwrap_or(self.id.clone());
        self.root.set(self.entity_key(), "id", value);
        self
    }

    pub fn changed_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "id")
    }

    pub fn eval_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "id".to_string(), attempted_path: "id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.id())
                }}

    pub fn subject(&self) -> String {
        self.changed_subject().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.subject.clone())
    }

    pub fn update_subject(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.subject = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.subject.clone());
        self.root.set(self.entity_key(), "subject", value);
        self
    }

    pub fn changed_subject(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "subject")
    }

    pub fn eval_subject(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("subject") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "subject".to_string(), attempted_path: "subject".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.subject())
                }}

    pub fn body(&self) -> String {
        self.changed_body().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.body.clone())
    }

    pub fn update_body(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.body = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.body.clone());
        self.root.set(self.entity_key(), "body", value);
        self
    }

    pub fn changed_body(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "body")
    }

    pub fn eval_body(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("body") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "body".to_string(), attempted_path: "body".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.body())
                }}

    pub fn notification_type(&self) -> String {
        self.changed_notification_type().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.notification_type.clone())
    }

    pub fn update_notification_type(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.notification_type = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.notification_type.clone());
        self.root.set(self.entity_key(), "notification_type", value);
        self
    }

    pub fn changed_notification_type(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "notification_type")
    }

    pub fn eval_notification_type(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("notification_type") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "notification_type".to_string(), attempted_path: "notification_type".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.notification_type())
                }}

    pub fn status(&self) -> String {
        self.changed_status().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.status.clone())
    }

    pub fn update_status(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.status = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.status.clone());
        self.root.set(self.entity_key(), "status", value);
        self
    }

    pub fn changed_status(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "status")
    }

    pub fn eval_status(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("status") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "status".to_string(), attempted_path: "status".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.status())
                }}

    pub fn scheduled_time(&self) -> chrono::DateTime<chrono::Utc> {
        self.changed_scheduled_time().and_then(|value| value.try_timestamp()).unwrap_or(self.scheduled_time)
    }

    pub fn update_scheduled_time(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.scheduled_time = value.try_timestamp().unwrap_or(self.scheduled_time.clone());
        self.root.set(self.entity_key(), "scheduled_time", value);
        self
    }

    pub fn changed_scheduled_time(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "scheduled_time")
    }

    pub fn eval_scheduled_time(&self) -> teaql_core::eval::EvalResult<chrono::DateTime<chrono::Utc>> {
        if !self.is_loaded("scheduled_time") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "scheduled_time".to_string(), attempted_path: "scheduled_time".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.scheduled_time())
                }}

    pub fn sent_time(&self) -> chrono::DateTime<chrono::Utc> {
        self.changed_sent_time().and_then(|value| value.try_timestamp()).unwrap_or(self.sent_time)
    }

    pub fn update_sent_time(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.sent_time = value.try_timestamp().unwrap_or(self.sent_time.clone());
        self.root.set(self.entity_key(), "sent_time", value);
        self
    }

    pub fn changed_sent_time(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "sent_time")
    }

    pub fn eval_sent_time(&self) -> teaql_core::eval::EvalResult<chrono::DateTime<chrono::Utc>> {
        if !self.is_loaded("sent_time") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "sent_time".to_string(), attempted_path: "sent_time".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.sent_time())
                }}

    pub fn create_time(&self) -> chrono::DateTime<chrono::Utc> {
        self.changed_create_time().and_then(|value| value.try_timestamp()).unwrap_or(self.create_time)
    }

    pub fn update_create_time(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.create_time = value.try_timestamp().unwrap_or(self.create_time.clone());
        self.root.set(self.entity_key(), "create_time", value);
        self
    }

    pub fn changed_create_time(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "create_time")
    }

    pub fn eval_create_time(&self) -> teaql_core::eval::EvalResult<chrono::DateTime<chrono::Utc>> {
        if !self.is_loaded("create_time") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "create_time".to_string(), attempted_path: "create_time".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.create_time())
                }}

    pub fn update_time(&self) -> chrono::DateTime<chrono::Utc> {
        self.changed_update_time().and_then(|value| value.try_timestamp()).unwrap_or(self.update_time)
    }

    pub fn update_update_time(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.update_time = value.try_timestamp().unwrap_or(self.update_time.clone());
        self.root.set(self.entity_key(), "update_time", value);
        self
    }

    pub fn changed_update_time(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "update_time")
    }

    pub fn eval_update_time(&self) -> teaql_core::eval::EvalResult<chrono::DateTime<chrono::Utc>> {
        if !self.is_loaded("update_time") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "update_time".to_string(), attempted_path: "update_time".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.update_time())
                }}

    pub fn version(&self) -> i64 {
        self.changed_version().and_then(|value| value.try_i64()).unwrap_or(self.version)
    }

    pub fn update_version(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.version = value.try_i64().unwrap_or(self.version.clone());
        self.root.set(self.entity_key(), "version", value);
        self
    }

    pub fn changed_version(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "version")
    }

    pub fn eval_version(&self) -> teaql_core::eval::EvalResult<i64> {
        if !self.is_loaded("version") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "version".to_string(), attempted_path: "version".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.version())
                }}
    pub fn recipient_id(&self) -> u64 {
        self.changed_recipient_id().and_then(|value| value.try_u64()).unwrap_or(self.recipient_id)
    }

    pub fn update_recipient_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.recipient_id = value.try_u64().unwrap_or(self.recipient_id.clone());
        self.root.set(self.entity_key(), "recipient_id", value);
        self
    }

    pub fn changed_recipient_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "recipient_id")
    }

    pub fn eval_recipient_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("recipient_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "recipient_id".to_string(), attempted_path: "recipient_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.recipient_id())
                }}
    pub fn recipient(&self) -> Option<&crate::User> {
        self.recipient.as_ref()
    }

    pub fn eval_recipient(&self) -> teaql_core::eval::EvalResult<&crate::User> {
        if !self.is_loaded("recipient") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "recipient".to_string(), attempted_path: "recipient".to_string() }
        } else {
            match &self.recipient {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
        }
    }

    pub fn mark_as_delete(&mut self) -> &mut Self {
        self.root.mark_as_delete(self.entity_key());
        self
    }

    pub fn set_comment(&mut self, comment: impl Into<String>) -> &mut Self {
        self.root.set_comment(comment);
        self
    }

    pub(crate) async fn save<'a, C>(
        &self,
        ctx: &'a C,
    ) -> Result<teaql_runtime::GraphNode, crate::TeaqlDataServiceError<C::NotificationRepository<'a>>>
    where
        C: crate::TeaqlRepositoryProvider + ?Sized,
    {
        let root = ctx.user_context().entity_root();
        let key = self.entity_key();
        let has_ledger_change = (self.id != 0)
            && (root.current_change_set().changes().contains_key(&key)
                || root.is_marked_as_delete(&key)
                || root.is_new(&key));
        let repository = ctx
            .notification_repository()
            .map_err(|err| teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(err.to_string())))?;
        if has_ledger_change {
            crate::TeaqlEntityRepository::save_entity_ledger(&repository, root.clone()).await?;
            return Ok(teaql_runtime::GraphNode::new("Notification"));
        }
        crate::TeaqlEntityRepository::save_entity_graph(&repository, self.clone()).await
    }
}

