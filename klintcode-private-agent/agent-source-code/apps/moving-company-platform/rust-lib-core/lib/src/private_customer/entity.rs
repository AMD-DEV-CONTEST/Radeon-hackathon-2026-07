
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/private_customer
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
#[teaql(entity = "PrivateCustomer", table = "private_customer_data", data_service = "sqlite", audit_mask_fields = "mobile_phone")]
pub struct PrivateCustomer {
#[teaql(id)]
    id: u64,

// @source moving-company.xml:89
    first_name: String,

// @source moving-company.xml:89
    last_name: String,

// @source moving-company.xml:89
    mobile_phone: String,

// @source moving-company.xml:89
    create_time: chrono::DateTime<chrono::Utc>,

// @source moving-company.xml:89
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source moving-company.xml:89
#[teaql(column = "company")]
    company_id: u64,
// @source moving-company.xml:89
#[teaql(relation(target = "Company", local_key = "company_id", foreign_key = "id"))]
    company: Option<crate::Company>,
    #[teaql(boxed_relations)]
    pub _relations: Box<PrivateCustomerReverseRelations>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl PrivateCustomer {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            first_name: String::new(),
            last_name: String::new(),
            mobile_phone: String::new(),
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            company_id: 0_u64,
            company: None,
            _relations: Box::new(PrivateCustomerReverseRelations::new()),
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("PrivateCustomer", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.company {
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

    pub fn mobile_phone(&self) -> String {
        self.changed_mobile_phone().and_then(|value| value.try_text().map(|value| value.to_owned())).unwrap_or_else(|| self.mobile_phone.clone())
    }

    pub fn update_mobile_phone(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.mobile_phone = value.try_text().map(|value| value.trim().to_owned()).unwrap_or_else(|| self.mobile_phone.clone());
        self.root.set(self.entity_key(), "mobile_phone", value);
        self
    }

    pub fn changed_mobile_phone(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "mobile_phone")
    }

    pub fn eval_mobile_phone(&self) -> teaql_core::eval::EvalResult<String> {
        if !self.is_loaded("mobile_phone") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "mobile_phone".to_string(), attempted_path: "mobile_phone".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.mobile_phone())
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
    pub fn company_id(&self) -> u64 {
        self.changed_company_id().and_then(|value| value.try_u64()).unwrap_or(self.company_id)
    }

    pub fn update_company_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.company_id = value.try_u64().unwrap_or(self.company_id.clone());
        self.root.set(self.entity_key(), "company_id", value);
        self
    }

    pub fn changed_company_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "company_id")
    }

    pub fn eval_company_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("company_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "company_id".to_string(), attempted_path: "company_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.company_id())
                }}
    pub fn company(&self) -> Option<&crate::Company> {
        self.company.as_ref()
    }

    pub fn eval_company(&self) -> teaql_core::eval::EvalResult<&crate::Company> {
        if !self.is_loaded("company") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "company".to_string(), attempted_path: "company".to_string() }
        } else {
            match &self.company {
                Some(v) => teaql_core::eval::EvalResult::Value(v),
                None => teaql_core::eval::EvalResult::Null,
            }
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
pub struct PrivateCustomerReverseRelations {
#[teaql(relation(target = "BillingInfo", local_key = "id", foreign_key = "private_customer_id", many))]
    billing_info_list: SmartList<crate::BillingInfo>,
#[teaql(relation(target = "InteractionHistory", local_key = "id", foreign_key = "private_customer_id", many))]
    interaction_history_list: SmartList<crate::InteractionHistory>,
#[teaql(relation(target = "MoveOrder", local_key = "id", foreign_key = "private_customer_id", many))]
    move_order_list: SmartList<crate::MoveOrder>,
#[teaql(relation(target = "InvoiceDocument", local_key = "id", foreign_key = "private_customer_id", many))]
    invoice_document_list: SmartList<crate::InvoiceDocument>,
#[teaql(relation(target = "PaymentRecord", local_key = "id", foreign_key = "private_customer_id", many))]
    payment_record_list: SmartList<crate::PaymentRecord>,
}

impl PrivateCustomerReverseRelations {
    pub fn new() -> Self {
        Self {
            billing_info_list: Default::default(),
            interaction_history_list: Default::default(),
            move_order_list: Default::default(),
            invoice_document_list: Default::default(),
            payment_record_list: Default::default(),
        }
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        for entity in &mut self.billing_info_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.interaction_history_list {
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
