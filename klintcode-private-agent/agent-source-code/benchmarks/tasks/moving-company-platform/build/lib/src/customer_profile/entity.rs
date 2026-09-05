
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/customer_profile
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
#[teaql(entity = "CustomerProfile", table = "customer_profile_data", data_service = "sqlite")]
pub struct CustomerProfile {
#[teaql(id)]
    id: u64,

// @source moving-company.xml:165
    profile_type: String,

// @source moving-company.xml:165
    customer_name: String,

// @source moving-company.xml:165
    create_time: teaql_core::time::Timestamp,

// @source moving-company.xml:165
    update_time: teaql_core::time::Timestamp,
#[teaql(version)]
    version: i64,
// @source moving-company.xml:165
#[teaql(column = "account_manager")]
    account_manager_id: u64,
// @source moving-company.xml:165
#[teaql(relation(target = "EmployeeRegistry", local_key = "account_manager_id", foreign_key = "id"))]
    account_manager: Option<crate::EmployeeRegistry>,
    #[teaql(boxed_relations)]
    pub _relations: Box<CustomerProfileReverseRelations>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl CustomerProfile {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            profile_type: String::new(),
            customer_name: String::new(),
            create_time: teaql_core::time::Timestamp::now(),
            update_time: teaql_core::time::Timestamp::now(),
            version: 0_i64,
            account_manager_id: 0_u64,
            account_manager: None,
            _relations: Box::new(CustomerProfileReverseRelations::new()),
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("CustomerProfile", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.account_manager {
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

    pub fn profile_type(&self) -> String {
        self.changed_profile_type().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.profile_type.clone())
    }

    pub fn update_profile_type(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.profile_type = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.profile_type.clone());
        self.root.set(self.entity_key(), "profile_type", value);
        self
    }

    pub fn changed_profile_type(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "profile_type")
    }

    pub fn eval_profile_type(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("profile_type") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "profile_type".to_string(), attempted_path: "profile_type".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.profile_type())
                }}

    pub fn customer_name(&self) -> String {
        self.changed_customer_name().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.customer_name.clone())
    }

    pub fn update_customer_name(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.customer_name = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.customer_name.clone());
        self.root.set(self.entity_key(), "customer_name", value);
        self
    }

    pub fn changed_customer_name(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "customer_name")
    }

    pub fn eval_customer_name(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("customer_name") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "customer_name".to_string(), attempted_path: "customer_name".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.customer_name())
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

    pub fn update_time(&self) -> teaql_core::time::Timestamp {
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

    pub fn eval_update_time(&self) -> teaql_core::eval::EvalResult<teaql_core::time::Timestamp> {
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
    pub fn account_manager_id(&self) -> u64 {
        self.changed_account_manager_id().and_then(|value| value.try_u64()).unwrap_or(self.account_manager_id)
    }

    pub fn update_account_manager_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.account_manager_id = value.try_u64().unwrap_or(self.account_manager_id.clone());
        self.root.set(self.entity_key(), "account_manager_id", value);
        self
    }

    pub fn changed_account_manager_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "account_manager_id")
    }

    pub fn eval_account_manager_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("account_manager_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "account_manager_id".to_string(), attempted_path: "account_manager_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.account_manager_id())
                }}
    pub fn account_manager(&self) -> Option<&crate::EmployeeRegistry> {
        self.account_manager.as_ref()
    }

    pub fn eval_account_manager(&self) -> teaql_core::eval::EvalResult<&crate::EmployeeRegistry> {
        if !self.is_loaded("account_manager") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "account_manager".to_string(), attempted_path: "account_manager".to_string() }
        } else {
            match &self.account_manager {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
        }
    }
    pub fn service_contract_list(&self) -> &SmartList<crate::ServiceContract> {
        &self._relations.service_contract_list
    }

    pub fn service_contract_list_mut(&mut self) -> &mut SmartList<crate::ServiceContract> {
        &mut self._relations.service_contract_list
    }

    pub fn eval_service_contract_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::ServiceContract>> {
        if !self.is_loaded("service_contract_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "service_contract_list".to_string(), attempted_path: "service_contract_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.service_contract_list)
        }
    }

    pub fn document_storage_list(&self) -> &SmartList<crate::DocumentStorage> {
        &self._relations.document_storage_list
    }

    pub fn document_storage_list_mut(&mut self) -> &mut SmartList<crate::DocumentStorage> {
        &mut self._relations.document_storage_list
    }

    pub fn eval_document_storage_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::DocumentStorage>> {
        if !self.is_loaded("document_storage_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "document_storage_list".to_string(), attempted_path: "document_storage_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.document_storage_list)
        }
    }

    pub fn contact_person_list(&self) -> &SmartList<crate::ContactPerson> {
        &self._relations.contact_person_list
    }

    pub fn contact_person_list_mut(&mut self) -> &mut SmartList<crate::ContactPerson> {
        &mut self._relations.contact_person_list
    }

    pub fn eval_contact_person_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::ContactPerson>> {
        if !self.is_loaded("contact_person_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "contact_person_list".to_string(), attempted_path: "contact_person_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.contact_person_list)
        }
    }

    pub fn billing_info_list(&self) -> &SmartList<crate::BillingInfo> {
        &self._relations.billing_info_list
    }

    pub fn billing_info_list_mut(&mut self) -> &mut SmartList<crate::BillingInfo> {
        &mut self._relations.billing_info_list
    }

    pub fn eval_billing_info_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::BillingInfo>> {
        if !self.is_loaded("billing_info_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "billing_info_list".to_string(), attempted_path: "billing_info_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.billing_info_list)
        }
    }

    pub fn interaction_history_list(&self) -> &SmartList<crate::InteractionHistory> {
        &self._relations.interaction_history_list
    }

    pub fn interaction_history_list_mut(&mut self) -> &mut SmartList<crate::InteractionHistory> {
        &mut self._relations.interaction_history_list
    }

    pub fn eval_interaction_history_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::InteractionHistory>> {
        if !self.is_loaded("interaction_history_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "interaction_history_list".to_string(), attempted_path: "interaction_history_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.interaction_history_list)
        }
    }

    pub fn sales_lead_list(&self) -> &SmartList<crate::SalesLead> {
        &self._relations.sales_lead_list
    }

    pub fn sales_lead_list_mut(&mut self) -> &mut SmartList<crate::SalesLead> {
        &mut self._relations.sales_lead_list
    }

    pub fn eval_sales_lead_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::SalesLead>> {
        if !self.is_loaded("sales_lead_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "sales_lead_list".to_string(), attempted_path: "sales_lead_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.sales_lead_list)
        }
    }

    pub fn move_order_list(&self) -> &SmartList<crate::MoveOrder> {
        &self._relations.move_order_list
    }

    pub fn move_order_list_mut(&mut self) -> &mut SmartList<crate::MoveOrder> {
        &mut self._relations.move_order_list
    }

    pub fn eval_move_order_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::MoveOrder>> {
        if !self.is_loaded("move_order_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "move_order_list".to_string(), attempted_path: "move_order_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self._relations.move_order_list)
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
pub struct CustomerProfileReverseRelations {
#[teaql(relation(target = "ServiceContract", local_key = "id", foreign_key = "customer_profile_id", many))]
    service_contract_list: SmartList<crate::ServiceContract>,
#[teaql(relation(target = "DocumentStorage", local_key = "id", foreign_key = "customer_profile_id", many))]
    document_storage_list: SmartList<crate::DocumentStorage>,
#[teaql(relation(target = "ContactPerson", local_key = "id", foreign_key = "customer_profile_id", many))]
    contact_person_list: SmartList<crate::ContactPerson>,
#[teaql(relation(target = "BillingInfo", local_key = "id", foreign_key = "customer_profile_id", many))]
    billing_info_list: SmartList<crate::BillingInfo>,
#[teaql(relation(target = "InteractionHistory", local_key = "id", foreign_key = "customer_profile_id", many))]
    interaction_history_list: SmartList<crate::InteractionHistory>,
#[teaql(relation(target = "SalesLead", local_key = "id", foreign_key = "customer_profile_id", many))]
    sales_lead_list: SmartList<crate::SalesLead>,
#[teaql(relation(target = "MoveOrder", local_key = "id", foreign_key = "customer_profile_id", many))]
    move_order_list: SmartList<crate::MoveOrder>,
#[teaql(relation(target = "InvoiceDocument", local_key = "id", foreign_key = "customer_profile_id", many))]
    invoice_document_list: SmartList<crate::InvoiceDocument>,
#[teaql(relation(target = "PaymentRecord", local_key = "id", foreign_key = "customer_profile_id", many))]
    payment_record_list: SmartList<crate::PaymentRecord>,
}

impl CustomerProfileReverseRelations {
    pub fn new() -> Self {
        Self {
            service_contract_list: Default::default(),
            document_storage_list: Default::default(),
            contact_person_list: Default::default(),
            billing_info_list: Default::default(),
            interaction_history_list: Default::default(),
            sales_lead_list: Default::default(),
            move_order_list: Default::default(),
            invoice_document_list: Default::default(),
            payment_record_list: Default::default(),
        }
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        for entity in &mut self.service_contract_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.document_storage_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.contact_person_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.billing_info_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.interaction_history_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.sales_lead_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.move_order_list {
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
