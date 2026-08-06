#[derive(Clone)]
pub struct TimeSlotExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::TimeSlot>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> TimeSlotExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::TimeSlot>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::TimeSlot> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::TimeSlot> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::TimeSlot {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_slot_start(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("slot_start", |entity| entity.eval_slot_start());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_slot_end(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("slot_end", |entity| entity.eval_slot_end());
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
    pub fn get_move_order_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("move_order_id", |entity| entity.eval_move_order_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_move_order(self) -> crate::MoveOrderExpression<'a> {
        let next = self.result.and_then("move_order", |entity| entity.eval_move_order());
        crate::MoveOrderExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct TimeSlotListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::TimeSlot>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> TimeSlotListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::TimeSlot>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::TimeSlot>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::TimeSlot>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::TimeSlot> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::TimeSlotExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::TimeSlotExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::TimeSlotExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::TimeSlotExpression::new(next, self.root_desc.clone())
    }
}