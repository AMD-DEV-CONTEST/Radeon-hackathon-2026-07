#[derive(Clone)]
pub struct JobTitleExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a crate::JobTitle>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> JobTitleExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a crate::JobTitle>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a crate::JobTitle> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a crate::JobTitle> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a crate::JobTitle {
        self.resolve().expect("Relation was legitimately null in database!")
    }

    pub fn get_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("id", |entity| entity.eval_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_name(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("name", |entity| entity.eval_name());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_code(self) -> crate::ValueExpression<'a, String> {
        let next = self.result.and_then("code", |entity| entity.eval_code());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn get_version(self) -> crate::ValueExpression<'a, i64> {
        let next = self.result.and_then("version", |entity| entity.eval_version());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_company_profile_id(self) -> crate::ValueExpression<'a, u64> {
        let next = self.result.and_then("company_profile_id", |entity| entity.eval_company_profile_id());
        crate::ValueExpression::new(next, self.root_desc.clone())
    }
    pub fn get_company_profile(self) -> crate::CompanyProfileExpression<'a> {
        let next = self.result.and_then("company_profile", |entity| entity.eval_company_profile());
        crate::CompanyProfileExpression::new(next, self.root_desc.clone())
    }
    pub fn get_employee_registry_list(self) -> crate::EmployeeRegistryListExpression<'a> {
        let next = self.result.and_then("employee_registry_list", |entity| entity.eval_employee_registry_list());
        crate::EmployeeRegistryListExpression::new(next, self.root_desc.clone())
    }
}

#[derive(Clone)]
pub struct JobTitleListExpression<'a> {
    result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::JobTitle>>,
    root_desc: std::sync::Arc<String>,
}

impl<'a> JobTitleListExpression<'a> {
    pub fn new(result: teaql_core::eval::EvalResult<&'a teaql_core::SmartList<crate::JobTitle>>, root_desc: std::sync::Arc<String>) -> Self {
        Self { result, root_desc }
    }

    fn resolve(&self) -> Option<&'a teaql_core::SmartList<crate::JobTitle>> {
        match &self.result {
            teaql_core::eval::EvalResult::Value(v) => Some(*v),
            teaql_core::eval::EvalResult::Null => None,
            teaql_core::eval::EvalResult::NotLoaded { failed_node, attempted_path } => {
                crate::trigger_logic_bug_panic(&self.root_desc, &failed_node, &attempted_path)
            }
        }
    }

    pub fn eval(&self) -> Option<&'a teaql_core::SmartList<crate::JobTitle>> {
        self.resolve()
    }

    pub fn unwrap(&self) -> &'a teaql_core::SmartList<crate::JobTitle> {
        self.resolve().expect("List relation was legitimately null in database!")
    }

    pub fn size(&self) -> crate::ValueExpression<'a, usize> {
        let next = self.result.clone().and_then("size", |list| teaql_core::eval::EvalResult::Value(list.len()));
        crate::ValueExpression::new(next, self.root_desc.clone())
    }

    pub fn first(&self) -> crate::JobTitleExpression<'a> {
        let next = self.result.clone().and_then("first", |list| {
            if let Some(item) = list.first() {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::JobTitleExpression::new(next, self.root_desc.clone())
    }

    pub fn get(&self, index: usize) -> crate::JobTitleExpression<'a> {
        let next = self.result.clone().and_then("get", |list| {
            if let Some(item) = list.get(index) {
                teaql_core::eval::EvalResult::Value(item)
            } else {
                teaql_core::eval::EvalResult::Null
            }
        });
        crate::JobTitleExpression::new(next, self.root_desc.clone())
    }
}