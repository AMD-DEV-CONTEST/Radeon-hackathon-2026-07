// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/customer_contact
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "CustomerContact", table = "customer_contact_data", data_service = "sqlite")]
pub struct CustomerContact {
#[teaql(id)]
    id: u64,

// @source customers.xml:45
    name: String,

// @source customers.xml:45
    first_name: String,

// @source customers.xml:45
    last_name: String,

// @source customers.xml:45
    email: String,

// @source customers.xml:45
    phone: String,

// @source customers.xml:45
    relationship: String,

// @source customers.xml:45
    create_time: chrono::DateTime<chrono::Utc>,

// @source customers.xml:45
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source customers.xml:45
#[teaql(column = "private_customer")]
    private_customer_id: u64,

// @source customers.xml:45
#[teaql(column = "corporate_customer")]
    corporate_customer_id: u64,
// @source customers.xml:45
#[teaql(relation(target = "PrivateCustomer", local_key = "private_customer_id", foreign_key = "id"))]
    private_customer: Option<crate::PrivateCustomer>,

// @source customers.xml:45
#[teaql(relation(target = "CorporateCustomer", local_key = "corporate_customer_id", foreign_key = "id"))]
    corporate_customer: Option<crate::CorporateCustomer>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl CustomerContact {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            name: String::new(),
            first_name: String::new(),
            last_name: String::new(),
            email: String::new(),
            phone: String::new(),
            relationship: String::new(),
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            private_customer_id: 0_u64,
            corporate_customer_id: 0_u64,
            private_customer: None,
            corporate_customer: None,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("CustomerContact", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.private_customer {
            entity.attach_root_recursive(root.clone());
        }
        if let Some(entity) = &mut self.corporate_customer {
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

    pub fn name(&self) -> String {
        self.changed_name().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.name.clone())
    }

    pub fn update_name(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.name = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.name.clone());
        self.root.set(self.entity_key(), "name", value);
        self
    }

    pub fn changed_name(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "name")
    }

    pub fn eval_name(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("name") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "name".to_string(), attempted_path: "name".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.name())
                }}

    pub fn first_name(&self) -> String {
        self.changed_first_name().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.first_name.clone())
    }

    pub fn update_first_name(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.first_name = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.first_name.clone());
        self.root.set(self.entity_key(), "first_name", value);
        self
    }

    pub fn changed_first_name(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "first_name")
    }

    pub fn eval_first_name(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("first_name") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "first_name".to_string(), attempted_path: "first_name".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.first_name())
                }}

    pub fn last_name(&self) -> String {
        self.changed_last_name().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.last_name.clone())
    }

    pub fn update_last_name(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.last_name = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.last_name.clone());
        self.root.set(self.entity_key(), "last_name", value);
        self
    }

    pub fn changed_last_name(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "last_name")
    }

    pub fn eval_last_name(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("last_name") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "last_name".to_string(), attempted_path: "last_name".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.last_name())
                }}

    pub fn email(&self) -> String {
        self.changed_email().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.email.clone())
    }

    pub fn update_email(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.email = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.email.clone());
        self.root.set(self.entity_key(), "email", value);
        self
    }

    pub fn changed_email(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "email")
    }

    pub fn eval_email(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("email") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "email".to_string(), attempted_path: "email".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.email())
                }}

    pub fn phone(&self) -> String {
        self.changed_phone().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.phone.clone())
    }

    pub fn update_phone(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.phone = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.phone.clone());
        self.root.set(self.entity_key(), "phone", value);
        self
    }

    pub fn changed_phone(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "phone")
    }

    pub fn eval_phone(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("phone") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "phone".to_string(), attempted_path: "phone".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.phone())
                }}

    pub fn relationship(&self) -> String {
        self.changed_relationship().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.relationship.clone())
    }

    pub fn update_relationship(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.relationship = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.relationship.clone());
        self.root.set(self.entity_key(), "relationship", value);
        self
    }

    pub fn changed_relationship(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "relationship")
    }

    pub fn eval_relationship(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("relationship") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "relationship".to_string(), attempted_path: "relationship".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.relationship())
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
    pub fn private_customer_id(&self) -> u64 {
        self.changed_private_customer_id().and_then(|value| value.try_u64()).unwrap_or(self.private_customer_id)
    }

    pub fn update_private_customer_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.private_customer_id = value.try_u64().unwrap_or(self.private_customer_id.clone());
        self.root.set(self.entity_key(), "private_customer_id", value);
        self
    }

    pub fn changed_private_customer_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "private_customer_id")
    }

    pub fn eval_private_customer_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("private_customer_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "private_customer_id".to_string(), attempted_path: "private_customer_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.private_customer_id())
                }}

    pub fn corporate_customer_id(&self) -> u64 {
        self.changed_corporate_customer_id().and_then(|value| value.try_u64()).unwrap_or(self.corporate_customer_id)
    }

    pub fn update_corporate_customer_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.corporate_customer_id = value.try_u64().unwrap_or(self.corporate_customer_id.clone());
        self.root.set(self.entity_key(), "corporate_customer_id", value);
        self
    }

    pub fn changed_corporate_customer_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "corporate_customer_id")
    }

    pub fn eval_corporate_customer_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("corporate_customer_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "corporate_customer_id".to_string(), attempted_path: "corporate_customer_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.corporate_customer_id())
                }}
    pub fn private_customer(&self) -> Option<&crate::PrivateCustomer> {
        self.private_customer.as_ref()
    }

    pub fn eval_private_customer(&self) -> teaql_core::eval::EvalResult<&crate::PrivateCustomer> {
        if !self.is_loaded("private_customer") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "private_customer".to_string(), attempted_path: "private_customer".to_string() }
        } else {
            match &self.private_customer {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
        }
    }

    pub fn corporate_customer(&self) -> Option<&crate::CorporateCustomer> {
        self.corporate_customer.as_ref()
    }

    pub fn eval_corporate_customer(&self) -> teaql_core::eval::EvalResult<&crate::CorporateCustomer> {
        if !self.is_loaded("corporate_customer") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "corporate_customer".to_string(), attempted_path: "corporate_customer".to_string() }
        } else {
            match &self.corporate_customer {
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
    ) -> Result<teaql_runtime::GraphNode, crate::TeaqlDataServiceError<C::CustomerContactRepository<'a>>>
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
            .customer_contact_repository()
            .map_err(|err| teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(err.to_string())))?;
        if has_ledger_change {
            crate::TeaqlEntityRepository::save_entity_ledger(&repository, root.clone()).await?;
            return Ok(teaql_runtime::GraphNode::new("CustomerContact"));
        }
        crate::TeaqlEntityRepository::save_entity_graph(&repository, self.clone()).await
    }
}

