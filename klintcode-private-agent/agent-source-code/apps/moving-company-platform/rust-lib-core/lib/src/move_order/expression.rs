#[derive(Clone)]
pub struct MoveOrderExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::MoveOrder>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> MoveOrderExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::MoveOrder>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::MoveOrder> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::MoveOrder> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::MoveOrder {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_order_status(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("order_status", |entity| entity.eval_order_status());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_create_time(self) -> crate::ValueExpression<'a, chrono::DateTime<chrono::Utc>> {
        let next = self.result.and_then("create_time", |entity| entity.eval_create_time());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_update_time(self) -> crate::ValueExpression<'a, chrono::DateTime<chrono::Utc>> {
        let next = self.result.and_then("update_time", |entity| entity.eval_update_time());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_version(self) -> crate::ValueExpression<'a, i64> {
        let next = self.result.and_then("version", |entity| entity.eval_version());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_private_customer_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("private_customer_id", |entity| entity.eval_private_customer_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_corporate_customer_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("corporate_customer_id", |entity| entity.eval_corporate_customer_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_origin_address_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("origin_address_id", |entity| entity.eval_origin_address_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_dest_address_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("dest_address_id", |entity| entity.eval_dest_address_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_assigned_vehicle_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("assigned_vehicle_id", |entity| entity.eval_assigned_vehicle_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_private_customer(self) -> crate::PrivateCustomerExpression<'a> {
        let next = self.result.and_then("private_customer", |entity| entity.eval_private_customer());
        crate::PrivateCustomerExpression::new(next, self.root_desc.clone())
    }

    pub fn get_corporate_customer(self) -> crate::CorporateCustomerExpression<'a> {
        let next = self.result.and_then("corporate_customer", |entity| entity.eval_corporate_customer());
        crate::CorporateCustomerExpression::new(next, self.root_desc.clone())
    }

    pub fn get_origin_address(self) -> crate::AddressRecordExpression<'a> {
        let next = self.result.and_then("origin_address", |entity| entity.eval_origin_address());
        crate::AddressRecordExpression::new(next, self.root_desc.clone())
    }

    pub fn get_dest_address(self) -> crate::AddressRecordExpression<'a> {
        let next = self.result.and_then("dest_address", |entity| entity.eval_dest_address());
        crate::AddressRecordExpression::new(next, self.root_desc.clone())
    }

    pub fn get_assigned_vehicle(self) -> crate::VehicleAssetExpression<'a> {
        let next = self.result.and_then("assigned_vehicle", |entity| entity.eval_assigned_vehicle());
        crate::VehicleAssetExpression::new(next, self.root_desc.clone())
    }
    pub fn get_route_plan_list(self) -> crate::RoutePlanListExpression<'a> {
        let next = self.result.and_then("route_plan_list", |entity| entity.eval_route_plan_list());
        crate::RoutePlanListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_time_slot_list(self) -> crate::TimeSlotListExpression<'a> {
        let next = self.result.and_then("time_slot_list", |entity| entity.eval_time_slot_list());
        crate::TimeSlotListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_fulfillment_event_list(self) -> crate::FulfillmentEventListExpression<'a> {
        let next = self.result.and_then("fulfillment_event_list", |entity| entity.eval_fulfillment_event_list());
        crate::FulfillmentEventListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_job_assignment_list(self) -> crate::JobAssignmentListExpression<'a> {
        let next = self.result.and_then("job_assignment_list", |entity| entity.eval_job_assignment_list());
        crate::JobAssignmentListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_service_config_list(self) -> crate::ServiceConfigListExpression<'a> {
        let next = self.result.and_then("service_config_list", |entity| entity.eval_service_config_list());
        crate::ServiceConfigListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_box_rental_list(self) -> crate::BoxRentalListExpression<'a> {
        let next = self.result.and_then("box_rental_list", |entity| entity.eval_box_rental_list());
        crate::BoxRentalListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_conversion_metric_list(self) -> crate::ConversionMetricListExpression<'a> {
        let next = self.result.and_then("conversion_metric_list", |entity| entity.eval_conversion_metric_list());
        crate::ConversionMetricListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_invoice_document_list(self) -> crate::InvoiceDocumentListExpression<'a> {
        let next = self.result.and_then("invoice_document_list", |entity| entity.eval_invoice_document_list());
        crate::InvoiceDocumentListExpression::new(next, self.root_desc.clone())
    }

    pub fn get_payment_record_list(self) -> crate::PaymentRecordListExpression<'a> {
        let next = self.result.and_then("payment_record_list", |entity| entity.eval_payment_record_list());
        crate::PaymentRecordListExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct MoveOrderListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::MoveOrder>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> MoveOrderListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::MoveOrder>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::MoveOrder>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::MoveOrder>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::MoveOrder> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::MoveOrderExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::MoveOrderExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::MoveOrderExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::MoveOrderExpression::new(next, self.root_desc.clone())
    }
}