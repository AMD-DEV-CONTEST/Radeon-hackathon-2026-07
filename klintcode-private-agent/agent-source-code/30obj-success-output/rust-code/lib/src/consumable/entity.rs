// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/consumable
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "Consumable", table = "consumable_data", data_service = "sqlite")]
pub struct Consumable {
#[teaql(id)]
    id: u64,

// @source asset_management.xml:42
    name: String,

// @source asset_management.xml:42
    item_type: String,

// @source asset_management.xml:42
    unit_cost: rust_decimal::Decimal,

// @source asset_management.xml:42
    quantity_in_stock: i64,

// @source asset_management.xml:42
    reorder_level: i64,

// @source asset_management.xml:42
    create_time: chrono::DateTime<chrono::Utc>,

// @source asset_management.xml:42
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl Consumable {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            name: String::new(),
            item_type: String::new(),
            unit_cost: rust_decimal::Decimal::ZERO,
            quantity_in_stock: 0_i64,
            reorder_level: 0_i64,
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("Consumable", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
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

    pub fn item_type(&self) -> String {
        self.changed_item_type().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.item_type.clone())
    }

    pub fn update_item_type(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.item_type = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.item_type.clone());
        self.root.set(self.entity_key(), "item_type", value);
        self
    }

    pub fn changed_item_type(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "item_type")
    }

    pub fn eval_item_type(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("item_type") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "item_type".to_string(), attempted_path: "item_type".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.item_type())
                }}

    pub fn unit_cost(&self) -> rust_decimal::Decimal {
        self.changed_unit_cost().and_then(|value| value.try_decimal()).unwrap_or(self.unit_cost)
    }

    pub fn update_unit_cost(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.unit_cost = value.try_decimal().unwrap_or(self.unit_cost.clone());
        self.root.set(self.entity_key(), "unit_cost", value);
        self
    }

    pub fn changed_unit_cost(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "unit_cost")
    }

    pub fn eval_unit_cost(&self) -> teaql_core::eval::EvalResult<rust_decimal::Decimal> {
        if !self.is_loaded("unit_cost") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "unit_cost".to_string(), attempted_path: "unit_cost".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.unit_cost())
                }}

    pub fn quantity_in_stock(&self) -> i64 {
        self.changed_quantity_in_stock().and_then(|value| value.try_i64()).map(|value| value as i64).unwrap_or(self.quantity_in_stock)
    }

    pub fn update_quantity_in_stock(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.quantity_in_stock = value.try_i64().map(|value| value as i64).unwrap_or(self.quantity_in_stock.clone());
        self.root.set(self.entity_key(), "quantity_in_stock", value);
        self
    }

    pub fn changed_quantity_in_stock(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "quantity_in_stock")
    }

    pub fn eval_quantity_in_stock(&self) -> teaql_core::eval::EvalResult<i64> {
        if !self.is_loaded("quantity_in_stock") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "quantity_in_stock".to_string(), attempted_path: "quantity_in_stock".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.quantity_in_stock())
                }}

    pub fn reorder_level(&self) -> i64 {
        self.changed_reorder_level().and_then(|value| value.try_i64()).map(|value| value as i64).unwrap_or(self.reorder_level)
    }

    pub fn update_reorder_level(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.reorder_level = value.try_i64().map(|value| value as i64).unwrap_or(self.reorder_level.clone());
        self.root.set(self.entity_key(), "reorder_level", value);
        self
    }

    pub fn changed_reorder_level(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "reorder_level")
    }

    pub fn eval_reorder_level(&self) -> teaql_core::eval::EvalResult<i64> {
        if !self.is_loaded("reorder_level") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "reorder_level".to_string(), attempted_path: "reorder_level".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.reorder_level())
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
    ) -> Result<teaql_runtime::GraphNode, crate::TeaqlDataServiceError<C::ConsumableRepository<'a>>>
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
            .consumable_repository()
            .map_err(|err| teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(err.to_string())))?;
        if has_ledger_change {
            crate::TeaqlEntityRepository::save_entity_ledger(&repository, root.clone()).await?;
            return Ok(teaql_runtime::GraphNode::new("Consumable"));
        }
        crate::TeaqlEntityRepository::save_entity_graph(&repository, self.clone()).await
    }
}

