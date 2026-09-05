#[derive(Clone)]
pub struct MovingEventExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::MovingEvent>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> MovingEventExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::MovingEvent>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::MovingEvent> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::MovingEvent> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::MovingEvent {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_event_name(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("event_name", |entity| entity.eval_event_name());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_scheduled_date(self) -> crate::ValueExpression<'a, chrono::NaiveDate> {
        let next = self.result.and_then("scheduled_date", |entity| entity.eval_scheduled_date());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_status(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("status", |entity| entity.eval_status());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_customer(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("customer", |entity| entity.eval_customer());
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
    pub fn get_origin_address_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("origin_address_id", |entity| entity.eval_origin_address_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_destination_address_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("destination_address_id", |entity| entity.eval_destination_address_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_origin_address(self) -> crate::AddressExpression<'a> {
        let next = self.result.and_then("origin_address", |entity| entity.eval_origin_address());
        crate::AddressExpression::new(next, self.root_desc.clone())
    }

    pub fn get_destination_address(self) -> crate::AddressExpression<'a> {
        let next = self.result.and_then("destination_address", |entity| entity.eval_destination_address());
        crate::AddressExpression::new(next, self.root_desc.clone())
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
}

#[derive(Clone)]
pub struct MovingEventListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::MovingEvent>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> MovingEventListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::MovingEvent>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::MovingEvent>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::MovingEvent>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::MovingEvent> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::MovingEventExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::MovingEventExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::MovingEventExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::MovingEventExpression::new(next, self.root_desc.clone())
    }
}