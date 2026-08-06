
// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/vat_record
use std::collections::BTreeMap;

use teaql_macros::TeaqlEntity;

/// [TEAQL AI WARNING]
/// TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
/// DO NOT GUESS METHOD NAMES!
/// The methods listed below are the ONLY valid ways to interact with this entity.
/// If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
/// Read the method signatures in this file before proceeding.
#[derive(Clone, Debug, PartialEq, TeaqlEntity)]
#[teaql(entity = "VatRecord", table = "vat_record_data", data_service = "sqlite")]
pub struct VatRecord {
#[teaql(id)]
    id: u64,

// @source moving-company.xml:379
    vat_percent: rust_decimal::Decimal,

// @source moving-company.xml:379
    vat_amount: rust_decimal::Decimal,

// @source moving-company.xml:379
    create_time: teaql_core::time::Timestamp,
#[teaql(version)]
    version: i64,
// @source moving-company.xml:379
#[teaql(column = "invoice_document")]
    invoice_document_id: u64,
// @source moving-company.xml:379
#[teaql(relation(target = "InvoiceDocument", local_key = "invoice_document_id", foreign_key = "id"))]
    invoice_document: Option<crate::InvoiceDocument>,
    #[teaql(dynamic)]
    dynamic: BTreeMap<String, teaql_core::Value>,
    #[teaql(skip)]
    root: teaql_runtime::EntityRoot,
    #[teaql(skip)]
    pub __load_state: teaql_core::eval::LoadState,
}

impl VatRecord {
    pub fn with_id(id: u64) -> teaql_core::Value {
        teaql_core::Value::U64(id)
    }

    pub(crate) fn runtime_new(root: teaql_runtime::EntityRoot) -> Self {
        Self {
            id: 0_u64,
            vat_percent: rust_decimal::Decimal::ZERO,
            vat_amount: rust_decimal::Decimal::ZERO,
            create_time: teaql_core::time::Timestamp::now(),
            version: 0_i64,
            invoice_document_id: 0_u64,
            invoice_document: None,
            dynamic: BTreeMap::new(),
            root,
            __load_state: teaql_core::eval::LoadState::FullyLoaded,
        }
    }

    pub fn entity_key(&self) -> teaql_runtime::EntityKey {
        teaql_runtime::EntityKey::new("VatRecord", self.id)
    }

    pub fn attach_root_recursive(&mut self, root: teaql_runtime::EntityRoot) {
        self.root = root.clone();
        if let Some(entity) = &mut self.invoice_document {
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

    pub fn vat_percent(&self) -> rust_decimal::Decimal {
        self.changed_vat_percent().and_then(|value| value.try_decimal()).unwrap_or(self.vat_percent)
    }

    pub fn update_vat_percent(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.vat_percent = value.try_decimal().unwrap_or(self.vat_percent.clone());
        self.root.set(self.entity_key(), "vat_percent", value);
        self
    }

    pub fn changed_vat_percent(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "vat_percent")
    }

    pub fn eval_vat_percent(&self) -> teaql_core::eval::EvalResult<rust_decimal::Decimal> {
        if !self.is_loaded("vat_percent") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "vat_percent".to_string(), attempted_path: "vat_percent".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.vat_percent())
                }}

    pub fn vat_amount(&self) -> rust_decimal::Decimal {
        self.changed_vat_amount().and_then(|value| value.try_decimal()).unwrap_or(self.vat_amount)
    }

    pub fn update_vat_amount(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.vat_amount = value.try_decimal().unwrap_or(self.vat_amount.clone());
        self.root.set(self.entity_key(), "vat_amount", value);
        self
    }

    pub fn changed_vat_amount(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "vat_amount")
    }

    pub fn eval_vat_amount(&self) -> teaql_core::eval::EvalResult<rust_decimal::Decimal> {
        if !self.is_loaded("vat_amount") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "vat_amount".to_string(), attempted_path: "vat_amount".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.vat_amount())
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
    pub fn invoice_document_id(&self) -> u64 {
        self.changed_invoice_document_id().and_then(|value| value.try_u64()).unwrap_or(self.invoice_document_id)
    }

    pub fn update_invoice_document_id(&mut self, value: impl Into<teaql_core::Value>) -> &mut Self {
        let value = value.into();
        self.invoice_document_id = value.try_u64().unwrap_or(self.invoice_document_id.clone());
        self.root.set(self.entity_key(), "invoice_document_id", value);
        self
    }

    pub fn changed_invoice_document_id(&self) -> Option<teaql_core::Value> {
        self.root.get(&self.entity_key(), "invoice_document_id")
    }

    pub fn eval_invoice_document_id(&self) -> teaql_core::eval::EvalResult<u64> {
        if !self.is_loaded("invoice_document_id") {
                    teaql_core::eval::EvalResult::NotLoaded { failed_node: "invoice_document_id".to_string(), attempted_path: "invoice_document_id".to_string() }
                } else {
                    teaql_core::eval::EvalResult::Value(self.invoice_document_id())
                }}
    pub fn invoice_document(&self) -> Option<&crate::InvoiceDocument> {
        self.invoice_document.as_ref()
    }

    pub fn eval_invoice_document(&self) -> teaql_core::eval::EvalResult<&crate::InvoiceDocument> {
        if !self.is_loaded("invoice_document") {
            teaql_core::eval::EvalResult::NotLoaded { failed_node: "invoice_document".to_string(), attempted_path: "invoice_document".to_string() }
        } else {
            match &self.invoice_document {
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

