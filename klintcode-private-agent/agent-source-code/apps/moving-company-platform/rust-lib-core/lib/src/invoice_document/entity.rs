
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/invoice_document
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
#[teaql(entity = "InvoiceDocument", table = "invoice_document_data", data_service = "sqlite")]
pub struct InvoiceDocument {
#[teaql(id)]
    id: u64,

// @source moving-company.xml:244
    total_due: rust_decimal::Decimal,

// @source moving-company.xml:244
    issue_date: chrono::NaiveDate,

// @source moving-company.xml:244
    create_time: chrono::DateTime<chrono::Utc>,

// @source moving-company.xml:244
    update_time: chrono::DateTime<chrono::Utc>,
#[teaql(version)]
    version: i64,
// @source moving-company.xml:244
#[teaql(column = "move_order")]
    move_order_id: u64,

// @source moving-company.xml:244
#[teaql(column = "private_customer")]
    private_customer_id: u64,

// @source moving-company.xml:244
#[teaql(column = "corporate_customer")]
    corporate_customer_id: u64,
// @source moving-company.xml:244
#[teaql(relation(target = "MoveOrder", local_key = "move_order_id", foreign_key = "id"))]
    move_order: Option<crate::MoveOrder>,

// @source moving-company.xml:244
#[teaql(relation(target = "PrivateCustomer", local_key = "private_customer_id", foreign_key = "id"))]
    private_customer: Option<crate::PrivateCustomer>,

// @source moving-company.xml:244
#[teaql(relation(target = "CorporateCustomer", local_key = "corporate_customer_id", foreign_key = "id"))]
    corporate_customer: Option<crate::CorporateCustomer>,
#[teaql(relation(target = "PaymentRecord", local_key = "id", foreign_key = "invoice_document_id", many))]
    payment_record_list: SmartList<crate::PaymentRecord>,
#[teaql(relation(target = "VatRecord", local_key = "id", foreign_key = "invoice_document_id", many))]
    vat_record_list: SmartList<crate::VatRecord>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl InvoiceDocument {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            total_due: rust_decimal::Decimal::ZERO,
            issue_date: chrono::NaiveDate::from_ymd_opt(1970, 1, 1).unwrap(),
            create_time: chrono::Utc::now(),
            update_time: chrono::Utc::now(),
            version: 0_i64,
            move_order_id: 0_u64,
            private_customer_id: 0_u64,
            corporate_customer_id: 0_u64,
            move_order: None,
            private_customer: None,
            corporate_customer: None,
            payment_record_list: Default::default(),
            vat_record_list: Default::default(),
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("InvoiceDocument", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.move_order {
            entity.attach_root_recursive(root.clone());
        }
        if let Some(entity) = &mut self.private_customer {
            entity.attach_root_recursive(root.clone());
        }
        if let Some(entity) = &mut self.corporate_customer {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.payment_record_list {
            entity.attach_root_recursive(root.clone());
        }
        for entity in &mut self.vat_record_list {
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

    pub fn total_due(&self) -> rust_decimal::Decimal {
        self.changed_total_due().and_then(|value| value.try_decimal()).unwrap_or(self.total_due)
    }

    pub fn update_total_due(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.total_due = value.try_decimal().unwrap_or(self.total_due.clone());
        self.root.set(self.entity_key(), "total_due", value);
        self
    }

    pub fn changed_total_due(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "total_due")
    }

    pub fn eval_total_due(&self) -> teaql_core::eval::EvalResult<rust_decimal::Decimal> {
        if !self.is_loaded("total_due") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "total_due".to_string(), attempted_path: "total_due".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.total_due())
                }}

    pub fn issue_date(&self) -> chrono::NaiveDate {
        self.changed_issue_date().and_then(|value| value.try_date()).unwrap_or(self.issue_date)
    }

    pub fn update_issue_date(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.issue_date = value.try_date().unwrap_or(self.issue_date.clone());
        self.root.set(self.entity_key(), "issue_date", value);
        self
    }

    pub fn changed_issue_date(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "issue_date")
    }

    pub fn eval_issue_date(&self) -> teaql_core::eval::EvalResult<chrono::NaiveDate> {
        if !self.is_loaded("issue_date") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "issue_date".to_string(), attempted_path: "issue_date".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.issue_date())
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
    pub fn payment_record_list(&self) -> &SmartList<crate::PaymentRecord> {
        &self.payment_record_list
    }

    pub fn payment_record_list_mut(&mut self) -> &mut SmartList<crate::PaymentRecord> {
        &mut self.payment_record_list
    }

    pub fn eval_payment_record_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::PaymentRecord>> {
        if !self.is_loaded("payment_record_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "payment_record_list".to_string(), attempted_path: "payment_record_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.payment_record_list)
        }
    }

    pub fn vat_record_list(&self) -> &SmartList<crate::VatRecord> {
        &self.vat_record_list
    }

    pub fn vat_record_list_mut(&mut self) -> &mut SmartList<crate::VatRecord> {
        &mut self.vat_record_list
    }

    pub fn eval_vat_record_list(&self) -> teaql_core::eval::EvalResult<&SmartList<crate::VatRecord>> {
        if !self.is_loaded("vat_record_list") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "vat_record_list".to_string(), attempted_path: "vat_record_list".to_string() }
        } else {
            teaql_core::eval::EvalResult::Value(&self.vat_record_list)
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

