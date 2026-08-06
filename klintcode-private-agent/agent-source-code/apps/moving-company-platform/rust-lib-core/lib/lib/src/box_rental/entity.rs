
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/box_rental
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "BoxRental", table = "box_rental_data", data_service = "sqlite")]
pub struct BoxRental {
#[teaql(id)]
    id: u64,

// @source products.xml:41
    box_quantity: i64,

// @source products.xml:41
    rental_fee: rust_decimal::Decimal,

// @source products.xml:41
    return_date: chrono::NaiveDate,

// @source products.xml:41
    create_time: teaql_core::time::Timestamp,
#[teaql(version)]
    version: i64,
// @source products.xml:41
#[teaql(column = "move_order")]
    move_order_id: u64,

// @source products.xml:41
#[teaql(column = "service_catalog")]
    service_catalog_id: u64,
// @source products.xml:41
#[teaql(relation(target = "MoveOrder", local_key = "move_order_id", foreign_key = "id"))]
    move_order: Option<crate::MoveOrder>,

// @source products.xml:41
#[teaql(relation(target = "ServiceCatalog", local_key = "service_catalog_id", foreign_key = "id"))]
    service_catalog: Option<crate::ServiceCatalog>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl BoxRental {
    pub const ENTITY_NAME: &'static str = "Box Rental";

    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            box_quantity: 0_i64,
            rental_fee: rust_decimal::Decimal::ZERO,
            return_date: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            create_time: teaql_core::time::Timestamp::now(),
            version: 0_i64,
            move_order_id: 0_u64,
            service_catalog_id: 0_u64,
            move_order: None,
            service_catalog: None,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("BoxRental", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.move_order {
            entity.attach_root_recursive(root.clone());
        }
        if let Some(entity) = &mut self.service_catalog {
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

    pub fn box_quantity(&self) -> i64 {
        self.changed_box_quantity().and_then(|value| value.try_i64()).map(|value| value as i64).unwrap_or(self.box_quantity)
    }

    pub fn update_box_quantity(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.box_quantity = value.try_i64().map(|value| value as i64).unwrap_or(self.box_quantity.clone());
        self.root.set(self.entity_key(), "box_quantity", value);
        self
    }

    pub fn changed_box_quantity(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "box_quantity")
    }

    pub fn eval_box_quantity(&self) -> teaql_core::eval::EvalResult<i64> {
        if !self.is_loaded("box_quantity") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "box_quantity".to_string(), attempted_path: "box_quantity".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.box_quantity())
                }}

    pub fn rental_fee(&self) -> rust_decimal::Decimal {
        self.changed_rental_fee().and_then(|value| value.try_decimal()).unwrap_or(self.rental_fee)
    }

    pub fn update_rental_fee(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.rental_fee = value.try_decimal().unwrap_or(self.rental_fee.clone());
        self.root.set(self.entity_key(), "rental_fee", value);
        self
    }

    pub fn changed_rental_fee(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "rental_fee")
    }

    pub fn eval_rental_fee(&self) -> teaql_core::eval::EvalResult<rust_decimal::Decimal> {
        if !self.is_loaded("rental_fee") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "rental_fee".to_string(), attempted_path: "rental_fee".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.rental_fee())
                }}

    pub fn return_date(&self) -> chrono::NaiveDate {
        self.changed_return_date().and_then(|value| value.try_date()).unwrap_or(self.return_date)
    }

    pub fn update_return_date(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.return_date = value.try_date().unwrap_or(self.return_date.clone());
        self.root.set(self.entity_key(), "return_date", value);
        self
    }

    pub fn changed_return_date(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "return_date")
    }

    pub fn eval_return_date(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("return_date") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "return_date".to_string(), attempted_path: "return_date".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.return_date())
                }}

    pub fn create_time(&self) -> teaql_core::time::Timestamp {
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

    pub fn eval_create_time(&self) -> teaql_core::eval::EvalResult<teaql_core::time::Timestamp> {
        if !self.is_loaded("create_time") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "create_time".to_string(), attempted_path: "create_time".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.create_time())
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
    pub fn move_order_id(&self) -> u64 {
        self.changed_move_order_id().and_then(|value| value.try_u64()).unwrap_or(self.move_order_id)
    }

    pub fn update_move_order_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.move_order_id = value.try_u64().unwrap_or(self.move_order_id.clone());
        self.root.set(self.entity_key(), "move_order_id", value);
        self
    }

    pub fn changed_move_order_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "move_order_id")
    }

    pub fn eval_move_order_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("move_order_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "move_order_id".to_string(), attempted_path: "move_order_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.move_order_id())
                }}

    pub fn service_catalog_id(&self) -> u64 {
        self.changed_service_catalog_id().and_then(|value| value.try_u64()).unwrap_or(self.service_catalog_id)
    }

    pub fn update_service_catalog_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.service_catalog_id = value.try_u64().unwrap_or(self.service_catalog_id.clone());
        self.root.set(self.entity_key(), "service_catalog_id", value);
        self
    }

    pub fn changed_service_catalog_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "service_catalog_id")
    }

    pub fn eval_service_catalog_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("service_catalog_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "service_catalog_id".to_string(), attempted_path: "service_catalog_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.service_catalog_id())
                }}
    pub fn move_order(&self) -> Option<&crate::MoveOrder> {
        self.move_order.as_ref()
    }

    pub fn eval_move_order(&self) -> teaql_core::eval::EvalResult<&crate::MoveOrder> {
        if !self.is_loaded("move_order") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "move_order".to_string(), attempted_path: "move_order".to_string() }
        } else {
            match &self.move_order {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
        }
    }

    pub fn service_catalog(&self) -> Option<&crate::ServiceCatalog> {
        self.service_catalog.as_ref()
    }

    pub fn eval_service_catalog(&self) -> teaql_core::eval::EvalResult<&crate::ServiceCatalog> {
        if !self.is_loaded("service_catalog") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "service_catalog".to_string(), attempted_path: "service_catalog".to_string() }
        } else {
            match &self.service_catalog {
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
}

