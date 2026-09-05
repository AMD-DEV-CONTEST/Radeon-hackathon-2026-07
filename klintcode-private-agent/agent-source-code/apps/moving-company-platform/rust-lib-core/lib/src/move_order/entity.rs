
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

// @source moving-company.xml:170
    order_status: String,

// @source moving-company.xml:170
    create_time: chrono::DateTime<chrono::Utc>,

// @source moving-company.xml:170
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source moving-company.xml:170
#[teaql(column = "private_customer")]
    private_customer_id: u64,

// @source moving-company.xml:170
#[teaql(column = "corporate_customer")]
    corporate_customer_id: u64,

// @source moving-company.xml:170
#[teaql(column = "origin_address")]
    origin_address_id: u64,

// @source moving-company.xml:170
#[teaql(column = "dest_address")]
    dest_address_id: u64,

// @source moving-company.xml:170
#[teaql(column = "assigned_vehicle")]
    assigned_vehicle_id: u64,
// @source moving-company.xml:170
#[teaql(relation(target = "PrivateCustomer", local_key = "private_customer_id", foreign_key = "id"))]
    private_customer: Option<crate::PrivateCustomer>,

// @source moving-company.xml:170
#[teaql(relation(target = "CorporateCustomer", local_key = "corporate_customer_id", foreign_key = "id"))]
    corporate_customer: Option<crate::CorporateCustomer>,

// @source moving-company.xml:170
#[teaql(relation(target = "AddressRecord", local_key = "origin_address_id", foreign_key = "id"))]
    origin_address: Option<crate::AddressRecord>,

// @source moving-company.xml:170
#[teaql(relation(target = "AddressRecord", local_key = "dest_address_id", foreign_key = "id"))]
    dest_address: Option<crate::AddressRecord>,

// @source moving-company.xml:170
#[teaql(relation(target = "VehicleAsset", local_key = "assigned_vehicle_id", foreign_key = "id"))]
    assigned_vehicle: Option<crate::VehicleAsset>,
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
            order_status: String::new(),
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            private_customer_id: 0_u64,
            corporate_customer_id: 0_u64,
            origin_address_id: 0_u64,
            dest_address_id: 0_u64,
            assigned_vehicle_id: 0_u64,
            private_customer: None,
            corporate_customer: None,
            origin_address: None,
            dest_address: None,
            assigned_vehicle: None,
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
        if let Some(entity) = &mut self.private_customer {
            entity.attach_root_recursive(root.clone());
        }
        if let Some(entity) = &mut self.corporate_customer {
            entity.attach_root_recursive(root.clone());
        }
        if let Some(entity) = &mut self.origin_address {
            entity.attach_root_recursive(root.clone());
        }
        if let Some(entity) = &mut self.dest_address {
            entity.attach_root_recursive(root.clone());
        }
        if let Some(entity) = &mut self.assigned_vehicle {
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

    pub fn order_status(&self) -> String {
        self.changed_order_status().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.order_status.clone())
    }

    pub fn update_order_status(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.order_status = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.order_status.clone());
        self.root.set(self.entity_key(), "order_status", value);
        self
    }

    pub fn changed_order_status(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "order_status")
    }

    pub fn eval_order_status(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("order_status") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "order_status".to_string(), attempted_path: "order_status".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.order_status())
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

    pub fn dest_address_id(&self) -> u64 {
        self.changed_dest_address_id().and_then(|value| value.try_u64()).unwrap_or(self.dest_address_id)
    }

    pub fn update_dest_address_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.dest_address_id = value.try_u64().unwrap_or(self.dest_address_id.clone());
        self.root.set(self.entity_key(), "dest_address_id", value);
        self
    }

    pub fn changed_dest_address_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "dest_address_id")
    }

    pub fn eval_dest_address_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("dest_address_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "dest_address_id".to_string(), attempted_path: "dest_address_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.dest_address_id())
                }}

    pub fn assigned_vehicle_id(&self) -> u64 {
        self.changed_assigned_vehicle_id().and_then(|value| value.try_u64()).unwrap_or(self.assigned_vehicle_id)
    }

    pub fn update_assigned_vehicle_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.assigned_vehicle_id = value.try_u64().unwrap_or(self.assigned_vehicle_id.clone());
        self.root.set(self.entity_key(), "assigned_vehicle_id", value);
        self
    }

    pub fn changed_assigned_vehicle_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "assigned_vehicle_id")
    }

    pub fn eval_assigned_vehicle_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("assigned_vehicle_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "assigned_vehicle_id".to_string(), attempted_path: "assigned_vehicle_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.assigned_vehicle_id())
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

    pub fn origin_address(&self) -> Option<&crate::AddressRecord> {
        self.origin_address.as_ref()
    }

    pub fn eval_origin_address(&self) -> teaql_core::eval::EvalResult<&crate::AddressRecord> {
        if !self.is_loaded("origin_address") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "origin_address".to_string(), attempted_path: "origin_address".to_string() }
        } else {
            match &self.origin_address {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
        }
    }

    pub fn dest_address(&self) -> Option<&crate::AddressRecord> {
        self.dest_address.as_ref()
    }

    pub fn eval_dest_address(&self) -> teaql_core::eval::EvalResult<&crate::AddressRecord> {
        if !self.is_loaded("dest_address") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "dest_address".to_string(), attempted_path: "dest_address".to_string() }
        } else {
            match &self.dest_address {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
        }
    }

    pub fn assigned_vehicle(&self) -> Option<&crate::VehicleAsset> {
        self.assigned_vehicle.as_ref()
    }

    pub fn eval_assigned_vehicle(&self) -> teaql_core::eval::EvalResult<&crate::VehicleAsset> {
        if !self.is_loaded("assigned_vehicle") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "assigned_vehicle".to_string(), attempted_path: "assigned_vehicle".to_string() }
        } else {
            match &self.assigned_vehicle {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
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

    pub fn service_config_list(&self) -> &SmartList<crate::ServiceConfig> {
        &self._relations.service_config_list
    }

    pub fn service_config_list_mut(&mut self) -> &mut SmartList<crate::ServiceConfig> {
        &mut self._relations.service_config_list
    }

    pub fn eval_service_config_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::ServiceConfig>> {
        if !self.is_loaded("service_config_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "service_config_list".to_string(), attempted_path: "service_config_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.service_config_list)
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

    pub fn conversion_metric_list(&self) -> &SmartList<crate::ConversionMetric> {
        &self._relations.conversion_metric_list
    }

    pub fn conversion_metric_list_mut(&mut self) -> &mut SmartList<crate::ConversionMetric> {
        &mut self._relations.conversion_metric_list
    }

    pub fn eval_conversion_metric_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::ConversionMetric>> {
        if !self.is_loaded("conversion_metric_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "conversion_metric_list".to_string(), attempted_path: "conversion_metric_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.conversion_metric_list)
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
#[teaql(relation(target = "RoutePlan", local_key = "id", foreign_key = "move_order_id", many))]
    route_plan_list: SmartList<crate::RoutePlan>,
#[teaql(relation(target = "TimeSlot", local_key = "id", foreign_key = "move_order_id", many))]
    time_slot_list: SmartList<crate::TimeSlot>,
#[teaql(relation(target = "FulfillmentEvent", local_key = "id", foreign_key = "move_order_id", many))]
    fulfillment_event_list: SmartList<crate::FulfillmentEvent>,
#[teaql(relation(target = "JobAssignment", local_key = "id", foreign_key = "move_order_id", many))]
    job_assignment_list: SmartList<crate::JobAssignment>,
#[teaql(relation(target = "ServiceConfig", local_key = "id", foreign_key = "move_order_id", many))]
    service_config_list: SmartList<crate::ServiceConfig>,
#[teaql(relation(target = "BoxRental", local_key = "id", foreign_key = "move_order_id", many))]
    box_rental_list: SmartList<crate::BoxRental>,
#[teaql(relation(target = "ConversionMetric", local_key = "id", foreign_key = "move_order_id", many))]
    conversion_metric_list: SmartList<crate::ConversionMetric>,
#[teaql(relation(target = "InvoiceDocument", local_key = "id", foreign_key = "move_order_id", many))]
    invoice_document_list: SmartList<crate::InvoiceDocument>,
#[teaql(relation(target = "PaymentRecord", local_key = "id", foreign_key = "move_order_id", many))]
    payment_record_list: SmartList<crate::PaymentRecord>,
}

impl MoveOrderReverseRelations {
    pub fn new() -> Self {
        Self {
            route_plan_list: Default::default(),
            time_slot_list: Default::default(),
            fulfillment_event_list: Default::default(),
            job_assignment_list: Default::default(),
            service_config_list: Default::default(),
            box_rental_list: Default::default(),
            conversion_metric_list: Default::default(),
            invoice_document_list: Default::default(),
            payment_record_list: Default::default(),
        }
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        for entity in &mut self.route_plan_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.time_slot_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.fulfillment_event_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.job_assignment_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.service_config_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.box_rental_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.conversion_metric_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.invoice_document_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.payment_record_list {
            entity.attach_root_recursive(root.clone());
        }
    }
}
