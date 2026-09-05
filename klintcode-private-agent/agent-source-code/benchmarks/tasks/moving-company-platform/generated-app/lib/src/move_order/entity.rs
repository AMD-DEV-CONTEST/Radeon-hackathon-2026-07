
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/move_order
use std::collections::BTreeMap;

use teaql_core::SmartList;
use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "MoveOrder", table = "move_order_data", data_service = "sqlite")]
pub struct MoveOrder {
#[teaql(id)]
    id: u64,

// @source moving-company.xml:252
    move_date: chrono::NaiveDate,

// @source moving-company.xml:252
    create_time: chrono::DateTime<chrono::Utc>,

// @source moving-company.xml:252
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source moving-company.xml:252
#[teaql(column = "customer_profile")]
    customer_profile_id: u64,

// @source moving-company.xml:252
#[teaql(column = "origin_address")]
    origin_address_id: u64,

// @source moving-company.xml:252
#[teaql(column = "destination_address")]
    destination_address_id: u64,

// @source moving-company.xml:252
#[teaql(column = "asset_vehicle")]
    asset_vehicle_id: u64,

// @source moving-company.xml:252
#[teaql(column = "order_status")]
    order_status_id: u64,
// @source moving-company.xml:252
#[teaql(relation(target = "CustomerProfile", local_key = "customer_profile_id", foreign_key = "id"))]
    customer_profile: Option<crate::CustomerProfile>,

// @source moving-company.xml:252
#[teaql(relation(target = "LocationAddress", local_key = "origin_address_id", foreign_key = "id"))]
    origin_address: Option<crate::LocationAddress>,

// @source moving-company.xml:252
#[teaql(relation(target = "LocationAddress", local_key = "destination_address_id", foreign_key = "id"))]
    destination_address: Option<crate::LocationAddress>,

// @source moving-company.xml:252
#[teaql(relation(target = "FleetVehicle", local_key = "asset_vehicle_id", foreign_key = "id"))]
    asset_vehicle: Option<crate::FleetVehicle>,

// @source moving-company.xml:252
#[teaql(relation(target = "OrderStatus", local_key = "order_status_id", foreign_key = "id"))]
    order_status: Option<crate::OrderStatus>,
    #[teaql(boxed_relations)]
    pub _relations: Box<MoveOrderReverseRelations>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl MoveOrder {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            move_date: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            customer_profile_id: 0_u64,
            origin_address_id: 0_u64,
            destination_address_id: 0_u64,
            asset_vehicle_id: 0_u64,
            order_status_id: 0_u64,
            customer_profile: None,
            origin_address: None,
            destination_address: None,
            asset_vehicle: None,
            order_status: None,
            _relations: Box::new(MoveOrderReverseRelations::new()),
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("MoveOrder", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.customer_profile {
            entity.attach_root_recursive(root.clone());
        }
        if let Some(entity) = &mut self.origin_address {
            entity.attach_root_recursive(root.clone());
        }
        if let Some(entity) = &mut self.destination_address {
            entity.attach_root_recursive(root.clone());
        }
        if let Some(entity) = &mut self.asset_vehicle {
            entity.attach_root_recursive(root.clone());
        }
        if let Some(entity) = &mut self.order_status {
            entity.attach_root_recursive(root.clone());
        }
        self._relations.attach_root_recursive(root.clone());
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

    pub fn move_date(&self) -> chrono::NaiveDate {
        self.changed_move_date().and_then(|value| value.try_date()).unwrap_or(self.move_date)
    }

    pub fn update_move_date(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.move_date = value.try_date().unwrap_or(self.move_date.clone());
        self.root.set(self.entity_key(), "move_date", value);
        self
    }

    pub fn changed_move_date(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "move_date")
    }

    pub fn eval_move_date(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("move_date") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "move_date".to_string(), attempted_path: "move_date".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.move_date())
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
    pub fn customer_profile_id(&self) -> u64 {
        self.changed_customer_profile_id().and_then(|value| value.try_u64()).unwrap_or(self.customer_profile_id)
    }

    pub fn update_customer_profile_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.customer_profile_id = value.try_u64().unwrap_or(self.customer_profile_id.clone());
        self.root.set(self.entity_key(), "customer_profile_id", value);
        self
    }

    pub fn changed_customer_profile_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "customer_profile_id")
    }

    pub fn eval_customer_profile_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("customer_profile_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "customer_profile_id".to_string(), attempted_path: "customer_profile_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.customer_profile_id())
                }}

    pub fn origin_address_id(&self) -> u64 {
        self.changed_origin_address_id().and_then(|value| value.try_u64()).unwrap_or(self.origin_address_id)
    }

    pub fn update_origin_address_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.origin_address_id = value.try_u64().unwrap_or(self.origin_address_id.clone());
        self.root.set(self.entity_key(), "origin_address_id", value);
        self
    }

    pub fn changed_origin_address_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "origin_address_id")
    }

    pub fn eval_origin_address_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("origin_address_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "origin_address_id".to_string(), attempted_path: "origin_address_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.origin_address_id())
                }}

    pub fn destination_address_id(&self) -> u64 {
        self.changed_destination_address_id().and_then(|value| value.try_u64()).unwrap_or(self.destination_address_id)
    }

    pub fn update_destination_address_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.destination_address_id = value.try_u64().unwrap_or(self.destination_address_id.clone());
        self.root.set(self.entity_key(), "destination_address_id", value);
        self
    }

    pub fn changed_destination_address_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "destination_address_id")
    }

    pub fn eval_destination_address_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("destination_address_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "destination_address_id".to_string(), attempted_path: "destination_address_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.destination_address_id())
                }}

    pub fn asset_vehicle_id(&self) -> u64 {
        self.changed_asset_vehicle_id().and_then(|value| value.try_u64()).unwrap_or(self.asset_vehicle_id)
    }

    pub fn update_asset_vehicle_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.asset_vehicle_id = value.try_u64().unwrap_or(self.asset_vehicle_id.clone());
        self.root.set(self.entity_key(), "asset_vehicle_id", value);
        self
    }

    pub fn changed_asset_vehicle_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "asset_vehicle_id")
    }

    pub fn eval_asset_vehicle_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("asset_vehicle_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "asset_vehicle_id".to_string(), attempted_path: "asset_vehicle_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.asset_vehicle_id())
                }}

    pub fn order_status_id(&self) -> u64 {
        self.changed_order_status_id().and_then(|value| value.try_u64()).unwrap_or(self.order_status_id)
    }

    pub(crate) fn update_order_status_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.order_status_id = value.try_u64().unwrap_or(self.order_status_id.clone());
        self.root.set(self.entity_key(), "order_status_id", value);
        self
    }

    pub fn changed_order_status_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "order_status_id")
    }

    pub fn eval_order_status_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("order_status_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "order_status_id".to_string(), attempted_path: "order_status_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.order_status_id())
                }}
    pub fn update_order_status_to_scheduled(&mut self) -> &mut Self {
        self.update_order_status_id(1001_u64)
    }

    pub fn order_status_is_scheduled(&self) -> bool {
        self.order_status_id() == 1001_u64
    }
    pub fn update_order_status_to_in_progress(&mut self) -> &mut Self {
        self.update_order_status_id(1002_u64)
    }

    pub fn order_status_is_in_progress(&self) -> bool {
        self.order_status_id() == 1002_u64
    }
    pub fn update_order_status_to_completed(&mut self) -> &mut Self {
        self.update_order_status_id(1003_u64)
    }

    pub fn order_status_is_completed(&self) -> bool {
        self.order_status_id() == 1003_u64
    }
    pub fn customer_profile(&self) -> Option<&crate::CustomerProfile> {
        self.customer_profile.as_ref()
    }

    pub fn eval_customer_profile(&self) -> teaql_core::eval::EvalResult<&crate::CustomerProfile> {
        if !self.is_loaded("customer_profile") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "customer_profile".to_string(), attempted_path: "customer_profile".to_string() }
        } else {
            match &self.customer_profile {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
        }
    }

    pub fn origin_address(&self) -> Option<&crate::LocationAddress> {
        self.origin_address.as_ref()
    }

    pub fn eval_origin_address(&self) -> teaql_core::eval::EvalResult<&crate::LocationAddress> {
        if !self.is_loaded("origin_address") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "origin_address".to_string(), attempted_path: "origin_address".to_string() }
        } else {
            match &self.origin_address {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
        }
    }

    pub fn destination_address(&self) -> Option<&crate::LocationAddress> {
        self.destination_address.as_ref()
    }

    pub fn eval_destination_address(&self) -> teaql_core::eval::EvalResult<&crate::LocationAddress> {
        if !self.is_loaded("destination_address") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "destination_address".to_string(), attempted_path: "destination_address".to_string() }
        } else {
            match &self.destination_address {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
        }
    }

    pub fn asset_vehicle(&self) -> Option<&crate::FleetVehicle> {
        self.asset_vehicle.as_ref()
    }

    pub fn eval_asset_vehicle(&self) -> teaql_core::eval::EvalResult<&crate::FleetVehicle> {
        if !self.is_loaded("asset_vehicle") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "asset_vehicle".to_string(), attempted_path: "asset_vehicle".to_string() }
        } else {
            match &self.asset_vehicle {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
        }
    }

    pub fn order_status(&self) -> Option<&crate::OrderStatus> {
        self.order_status.as_ref()
    }

    pub fn eval_order_status(&self) -> teaql_core::eval::EvalResult<&crate::OrderStatus> {
        if !self.is_loaded("order_status") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "order_status".to_string(), attempted_path: "order_status".to_string() }
        } else {
            match &self.order_status {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
        }
    }
    pub fn audit_log_list(&self) -> &SmartList<crate::AuditLog> {
        &self._relations.audit_log_list
    }

    pub fn audit_log_list_mut(&mut self) -> &mut SmartList<crate::AuditLog> {
        &mut self._relations.audit_log_list
    }

    pub fn eval_audit_log_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::AuditLog>> {
        if !self.is_loaded("audit_log_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "audit_log_list".to_string(), attempted_path: "audit_log_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.audit_log_list)
        }
    }

    pub fn job_assignment_list(&self) -> &SmartList<crate::JobAssignment> {
        &self._relations.job_assignment_list
    }

    pub fn job_assignment_list_mut(&mut self) -> &mut SmartList<crate::JobAssignment> {
        &mut self._relations.job_assignment_list
    }

    pub fn eval_job_assignment_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::JobAssignment>> {
        if !self.is_loaded("job_assignment_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "job_assignment_list".to_string(), attempted_path: "job_assignment_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.job_assignment_list)
        }
    }

    pub fn route_plan_list(&self) -> &SmartList<crate::RoutePlan> {
        &self._relations.route_plan_list
    }

    pub fn route_plan_list_mut(&mut self) -> &mut SmartList<crate::RoutePlan> {
        &mut self._relations.route_plan_list
    }

    pub fn eval_route_plan_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::RoutePlan>> {
        if !self.is_loaded("route_plan_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "route_plan_list".to_string(), attempted_path: "route_plan_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.route_plan_list)
        }
    }

    pub fn time_slot_list(&self) -> &SmartList<crate::TimeSlot> {
        &self._relations.time_slot_list
    }

    pub fn time_slot_list_mut(&mut self) -> &mut SmartList<crate::TimeSlot> {
        &mut self._relations.time_slot_list
    }

    pub fn eval_time_slot_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::TimeSlot>> {
        if !self.is_loaded("time_slot_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "time_slot_list".to_string(), attempted_path: "time_slot_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.time_slot_list)
        }
    }

    pub fn fulfillment_event_list(&self) -> &SmartList<crate::FulfillmentEvent> {
        &self._relations.fulfillment_event_list
    }

    pub fn fulfillment_event_list_mut(&mut self) -> &mut SmartList<crate::FulfillmentEvent> {
        &mut self._relations.fulfillment_event_list
    }

    pub fn eval_fulfillment_event_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::FulfillmentEvent>> {
        if !self.is_loaded("fulfillment_event_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "fulfillment_event_list".to_string(), attempted_path: "fulfillment_event_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.fulfillment_event_list)
        }
    }

    pub fn box_rental_list(&self) -> &SmartList<crate::BoxRental> {
        &self._relations.box_rental_list
    }

    pub fn box_rental_list_mut(&mut self) -> &mut SmartList<crate::BoxRental> {
        &mut self._relations.box_rental_list
    }

    pub fn eval_box_rental_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::BoxRental>> {
        if !self.is_loaded("box_rental_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "box_rental_list".to_string(), attempted_path: "box_rental_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.box_rental_list)
        }
    }

    pub fn invoice_document_list(&self) -> &SmartList<crate::InvoiceDocument> {
        &self._relations.invoice_document_list
    }

    pub fn invoice_document_list_mut(&mut self) -> &mut SmartList<crate::InvoiceDocument> {
        &mut self._relations.invoice_document_list
    }

    pub fn eval_invoice_document_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::InvoiceDocument>> {
        if !self.is_loaded("invoice_document_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "invoice_document_list".to_string(), attempted_path: "invoice_document_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.invoice_document_list)
        }
    }

    pub fn payment_record_list(&self) -> &SmartList<crate::PaymentRecord> {
        &self._relations.payment_record_list
    }

    pub fn payment_record_list_mut(&mut self) -> &mut SmartList<crate::PaymentRecord> {
        &mut self._relations.payment_record_list
    }

    pub fn eval_payment_record_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::PaymentRecord>> {
        if !self.is_loaded("payment_record_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "payment_record_list".to_string(), attempted_path: "payment_record_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.payment_record_list)
        }
    }

    pub fn expense_record_list(&self) -> &SmartList<crate::ExpenseRecord> {
        &self._relations.expense_record_list
    }

    pub fn expense_record_list_mut(&mut self) -> &mut SmartList<crate::ExpenseRecord> {
        &mut self._relations.expense_record_list
    }

    pub fn eval_expense_record_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::ExpenseRecord>> {
        if !self.is_loaded("expense_record_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "expense_record_list".to_string(), attempted_path: "expense_record_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.expense_record_list)
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

#[derive(Clone, Debug, PartialEq, teaql_macros::TeaqlReverseRelations)]
pub struct MoveOrderReverseRelations {
#[teaql(relation(target = "AuditLog", local_key = "id", foreign_key = "entity_reference_id", many))]
    audit_log_list: SmartList<crate::AuditLog>,
#[teaql(relation(target = "JobAssignment", local_key = "id", foreign_key = "move_order_id", many))]
    job_assignment_list: SmartList<crate::JobAssignment>,
#[teaql(relation(target = "RoutePlan", local_key = "id", foreign_key = "move_order_id", many))]
    route_plan_list: SmartList<crate::RoutePlan>,
#[teaql(relation(target = "TimeSlot", local_key = "id", foreign_key = "move_order_id", many))]
    time_slot_list: SmartList<crate::TimeSlot>,
#[teaql(relation(target = "FulfillmentEvent", local_key = "id", foreign_key = "move_order_id", many))]
    fulfillment_event_list: SmartList<crate::FulfillmentEvent>,
#[teaql(relation(target = "BoxRental", local_key = "id", foreign_key = "move_order_id", many))]
    box_rental_list: SmartList<crate::BoxRental>,
#[teaql(relation(target = "InvoiceDocument", local_key = "id", foreign_key = "move_order_id", many))]
    invoice_document_list: SmartList<crate::InvoiceDocument>,
#[teaql(relation(target = "PaymentRecord", local_key = "id", foreign_key = "move_order_id", many))]
    payment_record_list: SmartList<crate::PaymentRecord>,
#[teaql(relation(target = "ExpenseRecord", local_key = "id", foreign_key = "move_order_id", many))]
    expense_record_list: SmartList<crate::ExpenseRecord>,
}

impl MoveOrderReverseRelations {
    pub fn new() -> Self {
        Self {
            audit_log_list: Default::default(),
            job_assignment_list: Default::default(),
            route_plan_list: Default::default(),
            time_slot_list: Default::default(),
            fulfillment_event_list: Default::default(),
            box_rental_list: Default::default(),
            invoice_document_list: Default::default(),
            payment_record_list: Default::default(),
            expense_record_list: Default::default(),
        }
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        for entity in &mut self.audit_log_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.job_assignment_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.route_plan_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.time_slot_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.fulfillment_event_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.box_rental_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.invoice_document_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.payment_record_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.expense_record_list {
            entity.attach_root_recursive(root.clone());
        }
    }
}
