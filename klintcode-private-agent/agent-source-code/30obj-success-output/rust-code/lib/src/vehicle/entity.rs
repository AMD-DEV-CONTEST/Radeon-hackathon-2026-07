// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/vehicle
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "Vehicle", table = "vehicle_data", data_service = "sqlite")]
pub struct Vehicle {
#[teaql(id)]
    id: u64,

// @source asset_management.xml:20
    license_plate: String,

// @source asset_management.xml:20
    vehicle_type: String,

// @source asset_management.xml:20
    capacity_kg: rust_decimal::Decimal,

// @source asset_management.xml:20
    purchase_date: chrono::NaiveDate,

// @source asset_management.xml:20
    status: String,

// @source asset_management.xml:20
    create_time: chrono::DateTime<chrono::Utc>,

// @source asset_management.xml:20
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

impl Vehicle {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            license_plate: String::new(),
            vehicle_type: String::new(),
            capacity_kg: rust_decimal::Decimal::ZERO,
            purchase_date: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            status: String::new(),
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("Vehicle", self.id)
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

    pub fn license_plate(&self) -> String {
        self.changed_license_plate().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.license_plate.clone())
    }

    pub fn update_license_plate(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.license_plate = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.license_plate.clone());
        self.root.set(self.entity_key(), "license_plate", value);
        self
    }

    pub fn changed_license_plate(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "license_plate")
    }

    pub fn eval_license_plate(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("license_plate") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "license_plate".to_string(), attempted_path: "license_plate".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.license_plate())
                }}

    pub fn vehicle_type(&self) -> String {
        self.changed_vehicle_type().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.vehicle_type.clone())
    }

    pub fn update_vehicle_type(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.vehicle_type = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.vehicle_type.clone());
        self.root.set(self.entity_key(), "vehicle_type", value);
        self
    }

    pub fn changed_vehicle_type(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "vehicle_type")
    }

    pub fn eval_vehicle_type(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("vehicle_type") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "vehicle_type".to_string(), attempted_path: "vehicle_type".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.vehicle_type())
                }}

    pub fn capacity_kg(&self) -> rust_decimal::Decimal {
        self.changed_capacity_kg().and_then(|value| value.try_decimal()).unwrap_or(self.capacity_kg)
    }

    pub fn update_capacity_kg(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.capacity_kg = value.try_decimal().unwrap_or(self.capacity_kg.clone());
        self.root.set(self.entity_key(), "capacity_kg", value);
        self
    }

    pub fn changed_capacity_kg(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "capacity_kg")
    }

    pub fn eval_capacity_kg(&self) -> teaql_core::eval::EvalResult<rust_decimal::Decimal> {
        if !self.is_loaded("capacity_kg") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "capacity_kg".to_string(), attempted_path: "capacity_kg".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.capacity_kg())
                }}

    pub fn purchase_date(&self) -> chrono::NaiveDate {
        self.changed_purchase_date().and_then(|value| value.try_date()).unwrap_or(self.purchase_date)
    }

    pub fn update_purchase_date(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.purchase_date = value.try_date().unwrap_or(self.purchase_date.clone());
        self.root.set(self.entity_key(), "purchase_date", value);
        self
    }

    pub fn changed_purchase_date(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "purchase_date")
    }

    pub fn eval_purchase_date(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("purchase_date") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "purchase_date".to_string(), attempted_path: "purchase_date".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.purchase_date())
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
    ) -> Result<teaql_runtime::GraphNode, crate::TeaqlDataServiceError<C::VehicleRepository<'a>>>
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
            .vehicle_repository()
            .map_err(|err| teaql_runtime::DataServiceError::Runtime(teaql_runtime::RuntimeError::Graph(err.to_string())))?;
        if has_ledger_change {
            crate::TeaqlEntityRepository::save_entity_ledger(&repository, root.clone()).await?;
            return Ok(teaql_runtime::GraphNode::new("Vehicle"));
        }
        crate::TeaqlEntityRepository::save_entity_graph(&repository, self.clone()).await
    }
}

