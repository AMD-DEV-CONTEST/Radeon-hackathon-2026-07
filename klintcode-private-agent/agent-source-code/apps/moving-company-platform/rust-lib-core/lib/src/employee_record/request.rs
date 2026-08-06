use std::marker::PhantomData;

use serde_json::Value as JsonValue;
use teaql_core::{Aggregate, AggregateFunction, EntityDescriptor, Expr, Record, SelectQuery, SmartList};
use teaql_runtime::{DataServiceError, RuntimeError};

use crate::request_support::*;

impl EntityReference for crate::EmployeeRecord {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(&self)
    }
}

impl EntityReference for &crate::EmployeeRecord {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(self)
    }
}

// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/employee_record
#[derive(Debug)]
pub struct EmployeeRecordRequest<R = crate::EmployeeRecord> {
    query: SelectQuery,
    relation_selections: Vec<RelationSelection>,
    relation_filters: Vec<RelationFilter>,
    child_enhancements: Vec<QuerySelection>,
    query_options: QueryOptions,
    marker: PhantomData<R>,
}

impl<R> Clone for EmployeeRecordRequest<R> {
    fn clone(&self) -> Self {
        Self {
            query: self.query.clone(),
            relation_selections: self.relation_selections.clone(),
            relation_filters: self.relation_filters.clone(),
            child_enhancements: self.child_enhancements.clone(),
            query_options: self.query_options.clone(),
            marker: PhantomData,
        }
    }
}

impl<R> EmployeeRecordRequest<R> {
    pub(crate) fn new() -> Self {
        Self {
            query: SelectQuery::new("EmployeeRecord")
                .project("id")
                .project("version"),
            relation_selections: Vec::new(),
            relation_filters: Vec::new(),
            child_enhancements: Vec::new(),
            query_options: QueryOptions::default(),
            marker: PhantomData,
        }
    }

    pub fn return_type<T>(self) -> EmployeeRecordRequest<T> {
        EmployeeRecordRequest {
            query: self.query,
            relation_selections: self.relation_selections,
            relation_filters: self.relation_filters,
            child_enhancements: self.child_enhancements,
            query_options: self.query_options,
            marker: PhantomData,
        }
    }

    pub fn query(&self) -> &SelectQuery {
        &self.query
    }

    pub fn relation_selections(&self) -> &[RelationSelection] {
        &self.relation_selections
    }

    pub fn relation_filters(&self) -> &[RelationFilter] {
        &self.relation_filters
    }

    pub fn child_enhancements(&self) -> &[QuerySelection] {
        &self.child_enhancements
    }

    pub fn query_options(&self) -> &QueryOptions {
        &self.query_options
    }

    pub fn into_query(self) -> SelectQuery {
        self.query
    }


    pub fn purpose(self, purpose: impl Into<String>) -> crate::PurposedQuery<Self> {
        crate::PurposedQuery::new(self, purpose)
    }

    pub(crate) async fn _execute_for_list<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::EmployeeRecordRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
        R: teaql_core::Entity,
    {
        let repository = ctx
            .employee_record_repository()
            .map_err(|err| DataServiceError::Runtime(RuntimeError::Graph(err.to_string())))?;
        let query_options = self.query_options.clone();
        let relation_aggregates = runtime_relation_aggregates(&query_options);
        let query = authorize_query(apply_runtime_metadata(
            self.query,
            &query_options,
            &self.child_enhancements,
        )).map_err(DataServiceError::Runtime)?;
        let mut rows = repository.fetch_enhanced_entities_with_relation_aggregates::<R>(
            &query,
            &relation_aggregates,
        ).await?;
        let facets = execute_facets(ctx, query.as_query(), &query_options)
            .await
            .map_err(DataServiceError::Runtime)?;
        attach_facets(&mut rows, facets);
        Ok(rows)
    }

    pub(crate) async fn _execute_for_stream<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<Vec<teaql_data_service::StreamChunk>, TeaqlDataServiceError<C::EmployeeRecordRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .employee_record_repository()
            .map_err(|err| DataServiceError::Runtime(RuntimeError::Graph(err.to_string())))?;
        let query_options = self.query_options.clone();
        let query = authorize_query(apply_runtime_metadata(
            self.query,
            &query_options,
            &self.child_enhancements,
        )).map_err(DataServiceError::Runtime)?;
        let chunks = repository.fetch_stream(&query)
            .await?;
        Ok(chunks)
    }

    pub(crate) async fn _execute_for_first<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<Option<R>, TeaqlDataServiceError<C::EmployeeRecordRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
        R: teaql_core::Entity,
    {
        let rows = self.limit(1)._execute_for_list(ctx).await?;
        Ok(rows.into_iter().next())
    }

    pub(crate) async fn _execute_for_one<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<Option<R>, TeaqlDataServiceError<C::EmployeeRecordRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
        R: teaql_core::Entity,
    {
        self._execute_for_first(ctx).await
    }


    pub(crate) async fn _execute_for_page<'a, C>(
        self,
        ctx: &'a C,
        offset: u64,
        limit: u64,
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::EmployeeRecordRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
        R: teaql_core::Entity,
    {
        let total_count = self.clone()._execute_for_count(ctx).await?;
        let mut rows = self.page_offset(offset, limit)._execute_for_list(ctx).await?;
        rows.total_count = Some(total_count);
        Ok(rows)
    }

    pub(crate) async fn _execute_for_count<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<u64, TeaqlDataServiceError<C::EmployeeRecordRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .employee_record_repository()
            .map_err(|err| DataServiceError::Runtime(RuntimeError::Graph(err.to_string())))?;
        let mut query = self.query;
        query.projection.clear();
        query.expr_projection.clear();
        query.order_by.clear();
        query.slice = None;
        query.relations.clear();
        query = query.count(COUNT_ALIAS);
        let query = authorize_query(query).map_err(DataServiceError::Runtime)?;
        let rows = repository.fetch_all(&query).await?;
        rows.first()
            .and_then(|row| row.get(COUNT_ALIAS))
            .and_then(teaql_core::Value::try_u64)
            .ok_or_else(|| DataServiceError::Runtime(RuntimeError::Graph(format!("count result for EmployeeRecord is missing or not numeric"))))
    }

    pub(crate) async fn _execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, TeaqlDataServiceError<C::EmployeeRecordRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .employee_record_repository()
            .map_err(|err| DataServiceError::Runtime(RuntimeError::Graph(err.to_string())))?;
        let mut query = self.query.limit(1);
        query.relations.clear();
        let query = authorize_query(query).map_err(DataServiceError::Runtime)?;
        let rows = repository.fetch_all(&query).await?;
        Ok(!rows.is_empty())
    }

    pub(crate) async fn _execute_for_records<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<SmartList<Record>, TeaqlDataServiceError<C::EmployeeRecordRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .employee_record_repository()
            .map_err(|err| DataServiceError::Runtime(RuntimeError::Graph(err.to_string())))?;
        let query_options = self.query_options.clone();
        let outer_query = self.query.clone();
        let relation_aggregates = runtime_relation_aggregates(&query_options);
        let query = authorize_query(apply_runtime_metadata(
            self.query,
            &query_options,
            &self.child_enhancements,
        )).map_err(DataServiceError::Runtime)?;
        let mut rows = repository.fetch_smart_list_with_relation_aggregates(&query, &relation_aggregates).await?;
        let facets = execute_facets(ctx, &outer_query, &query_options)
            .await
            .map_err(DataServiceError::Runtime)?;
        attach_facets(&mut rows, facets);
        Ok(rows)
    }

    pub(crate) async fn _execute_for_record<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<Option<Record>, TeaqlDataServiceError<C::EmployeeRecordRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let records = self.limit(1)._execute_for_records(ctx).await?;
        Ok(records.into_iter().next())
    }

    pub fn search_with_text(mut self, text: impl Into<String>) -> Self {
        self.query = self.query.search_with_text(text);
        self
    }

    pub fn filter(mut self, filter: Expr) -> Self {
        self.query = self.query.filter(filter);
        self
    }

    pub fn and_filter(mut self, filter: Expr) -> Self {
        self.query = self.query.and_filter(filter);
        self
    }

    pub fn or_filter(mut self, filter: Expr) -> Self {
        self.query = self.query.or_filter(filter);
        self
    }

    pub fn append_search_criteria(self, criteria: Expr) -> Self {
        self.and_filter(criteria)
    }

    pub fn filter_property(
        mut self,
        property1: impl AsRef<str>,
        operator: FieldOperator,
        property2: impl AsRef<str>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_column_expr(
            property1.as_ref(),
            operator,
            property2.as_ref(),
        ));
        self
    }

    pub fn with_deleted_rows(mut self) -> Self {
        self.query.filter = remove_default_live_filter(self.query.filter);
        self
    }

    pub fn deleted_rows_only(mut self) -> Self {
        self.query.filter = remove_default_live_filter(self.query.filter);
        self.query = self.query.and_filter(Expr::lte("version", 0_i64));
        self
    }

    pub fn match_types(
        mut self,
        types: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(TYPE_FIELD, types.into_iter().map(Into::into)));
        self
    }


    pub fn with_type_group(mut self) -> Self {
        self.query = self.query.project(TYPE_GROUP_FIELD);
        self
    }

    pub fn matching_any_of(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        let entity = EntityDescriptor::new(selection.query.entity.clone());
        self.query = self.query.and_filter(Expr::in_subquery("id", entity, selection.query.clone(), "id"));
        self
    }

    pub fn match_any_of(self, request: impl Into<QuerySelection>) -> Self {
        self.matching_any_of(request)
    }

    pub fn enhance_child(mut self, request: impl Into<QuerySelection>) -> Self {
        self.child_enhancements.push(request.into());
        self
    }

    pub fn enhance_children_if_needed(self) -> Self {
        let request = self;
        request
    }


    pub fn comment(mut self, comment: impl Into<String>) -> Self {
        self.query_options.comment = Some(comment.into());
        self
    }

    pub fn raw_sql(self, raw_sql: impl Into<String>) -> Self {
        self.unsafe_raw_sql(UnsafeRawSqlSegment::trusted(raw_sql))
    }

    pub fn unsafe_raw_sql(mut self, raw_sql: UnsafeRawSqlSegment) -> Self {
        self.query_options.raw_sql = Some(raw_sql.into_sql());
        self
    }

    pub fn raw_sql_filter(self, raw_sql: impl Into<String>) -> Self {
        self.unsafe_raw_sql_filter(UnsafeRawSqlSegment::trusted(raw_sql))
    }

    pub fn unsafe_raw_sql_filter(mut self, raw_sql: UnsafeRawSqlSegment) -> Self {
        self.query_options.raw_sql_search_criteria.push(raw_sql.into_sql());
        self
    }
    pub fn filter_with_json(self, json_expr: impl Into<String>) -> Self {
        self.merge_dynamic_json_expr(json_expr.into())
    }

    fn merge_dynamic_json_expr(self, json_expr: String) -> Self {
        let json = serde_json::from_str::<JsonValue>(&json_expr)
            .unwrap_or_else(|_| panic!("Input JSON format error: {json_expr}"));
        self.merge_dynamic_json(&json)
    }

    fn merge_dynamic_json(mut self, json: &JsonValue) -> Self {
        let Some(object) = json.as_object() else {
            return self;
        };

        for (field, value) in object {
            if field.starts_with('_') {
                continue;
            }
            self = self.apply_dynamic_json_filter(field, value);
        }

        self = self.apply_dynamic_json_order_by(object.get("_orderBy"));

        if let Some(offset) = dynamic_json_u64_field(object, "_start") {
            self = self.skip(offset);
        }
        if let Some(size) = dynamic_json_u64_field(object, "_size") {
            self = self.limit(size);
        }

        if let Some(page_size) = dynamic_json_u64_field(object, "_pageSize") {
            self = self.limit(page_size);
        }
        if let Some(page_number) = dynamic_json_u64_field(object, "_page") {
            if page_number > 0 {
                let size = dynamic_json_u64_field(object, "_pageSize")
                    .or_else(|| self.query.slice.as_ref().and_then(|slice| slice.limit))
                    .unwrap_or(10);
                let offset = page_number.saturating_sub(1).saturating_mul(size);
                self = self.page_offset(offset, size);
            }
        }

        self
    }

    pub(crate) fn apply_dynamic_json_filter(self, field: &str, value: &JsonValue) -> Self {
        if let Some((head, tail)) = field.split_once('.') {
            self.apply_dynamic_json_chain_filter(head, tail, value)
        } else if let Some(storage_field) = Self::dynamic_json_self_field(field) {
            self.and_filter(dynamic_json_filter_expr(storage_field, value))
        } else {
            self
        }
    }

    fn apply_dynamic_json_order_by(mut self, order_by: Option<&JsonValue>) -> Self {
        match order_by {
            Some(JsonValue::String(field)) => {
                if let Some(storage_field) = Self::dynamic_json_self_field(field) {
                    self.query = self.query.order_desc(storage_field);
                }
            }
            Some(JsonValue::Object(order_by)) => {
                self = self.apply_dynamic_json_single_order_by(order_by);
            }
            Some(JsonValue::Array(order_bys)) => {
                for order_by in order_bys {
                    if let Some(order_by) = order_by.as_object() {
                        self = self.apply_dynamic_json_single_order_by(order_by);
                    }
                }
            }
            _ => {}
        }
        self
    }

    fn apply_dynamic_json_single_order_by(
        mut self,
        order_by: &serde_json::Map<String, JsonValue>,
    ) -> Self {
        let Some(field) = order_by.get("field").and_then(JsonValue::as_str) else {
            return self;
        };
        let Some(storage_field) = Self::dynamic_json_self_field(field) else {
            return self;
        };
        if order_by
            .get("useAsc")
            .and_then(JsonValue::as_bool)
            .unwrap_or(false)
        {
            self.query = self.query.order_asc(storage_field);
        } else {
            self.query = self.query.order_desc(storage_field);
        }
        self
    }

    fn dynamic_json_self_field(field: &str) -> Option<&'static str> {
        match field {
            "id" => Some("id"),
            "employee_number" => Some("employee_number"),
            "hire_date" => Some("hire_date"),
            "create_time" => Some("create_time"),
            "update_time" => Some("update_time"),
            "version" => Some("version"),
            "user_account" | "user_account_id" => Some("user_account_id"),
            _ => None,
        }
    }

    fn apply_dynamic_json_chain_filter(self, head: &str, tail: &str, value: &JsonValue) -> Self {
        let _ = (tail, value);
        match head {
            "user_account" => {
                self.with_user_account_matching(
                    crate::Q::user_accounts_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "payroll_calculation_list" => {
                self.with_payroll_calculation_list_matching(
                    crate::Q::payroll_calculations_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "worked_hours_list" => {
                self.with_worked_hours_list_matching(
                    crate::Q::worked_hourses_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "leave_request_list" => {
                self.with_leave_request_list_matching(
                    crate::Q::leave_requests_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "corporate_customer_list" => {
                self.with_corporate_customer_list_matching(
                    crate::Q::corporate_customers_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "inventory_tracking_list" => {
                self.with_inventory_tracking_list_matching(
                    crate::Q::inventory_trackings_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "job_assignment_list" => {
                self.with_job_assignment_list_matching(
                    crate::Q::job_assignments_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "expense_record_list" => {
                self.with_expense_record_list_matching(
                    crate::Q::expense_records_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "financial_summary_list" => {
                self.with_financial_summary_list_matching(
                    crate::Q::financial_summaries_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            _ => self,
        }
    }

    pub fn create_property_as(
        self,
        property_name: impl Into<String>,
        raw_sql_segment: impl Into<String>,
    ) -> Self {
        self.unsafe_create_property_as(property_name, UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn unsafe_create_property_as(
        mut self,
        property_name: impl Into<String>,
        raw_sql_segment: UnsafeRawSqlSegment,
    ) -> Self {
        self.query_options
            .dynamic_properties
            .push(RawDynamicProperty::new(property_name, raw_sql_segment));
        self
    }

    pub fn limit(mut self, limit: u64) -> Self {
        self.query = self.query.limit(limit);
        self
    }

    pub fn skip(mut self, offset: u64) -> Self {
        self.query = self.query.offset(offset);
        self
    }

    pub fn offset_only(self, offset: u64) -> Self {
        self.skip(offset)
    }

    pub fn offset(self, offset: u64, size: u64) -> Self {
        self.page_offset(offset, size)
    }

    pub fn page_offset(mut self, offset: u64, limit: u64) -> Self {
        self.query = self.query.page(offset, limit);
        self
    }

    pub fn top(self, top_n: u64) -> Self {
        self.limit(top_n)
    }

    pub fn offset_size(self, offset: u64, size: u64) -> Self {
        self.offset(offset, size)
    }

    pub fn unlimited(mut self) -> Self {
        self.query.slice = None;
        self
    }

    pub fn page_number(self, page_number: u64, page_size: u64) -> Self {
        let offset = page_number.saturating_sub(1).saturating_mul(page_size);
        self.page_offset(offset, page_size)
    }

    pub fn page_number_default(self, page_number: u64) -> Self {
        self.page_number(page_number, 10)
    }

    pub fn page(self, page_number: u64, page_size: u64) -> Self {
        self.page_number(page_number, page_size)
    }

    pub fn page_default(self, page_number: u64) -> Self {
        self.page_number_default(page_number)
    }

    pub fn select_self(mut self) -> Self {
        self.query = self.query.project("id");
        self.query = self.query.project("employee_number");
        self.query = self.query.project("hire_date");
        self.query = self.query.project("create_time");
        self.query = self.query.project("update_time");
        self.query = self.query.project("version");
        self.query = self.query.project("user_account_id");
        self
    }

    pub fn select_self_fields(self) -> Self {
        self.select_self()
    }

    pub fn select_self_without_parent(self) -> Self {
        self.select_self_fields()
    }

    pub fn select_all(self) -> Self {
        let mut request = self.select_self();
        request = request.select_user_account();
        request
    }

    pub fn select_children(self) -> Self {
        let mut request = self.select_all();
        request = request.select_payroll_calculation_list();
        request = request.select_worked_hours_list();
        request = request.select_leave_request_list();
        request = request.select_corporate_customer_list();
        request = request.select_inventory_tracking_list();
        request = request.select_job_assignment_list();
        request = request.select_expense_record_list();
        request = request.select_financial_summary_list();
        request
    }

    pub fn select_any(self) -> Self {
        self.select_children()
    }

    pub fn group_by(mut self, field: impl Into<String>) -> Self {
        self.query = self.query.group_by(field);
        self
    }

    pub fn aggregate_count(mut self, alias: impl Into<String>) -> Self {
        self.query = self.query.count(alias);
        self
    }

    pub fn aggregate_count_field(mut self, field: impl Into<String>, alias: impl Into<String>) -> Self {
        self.query = self.query.count_field(field, alias);
        self
    }

    pub fn aggregate_with_function(
        mut self,
        field: impl Into<String>,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.query = self.query.aggregate(Aggregate::new(function, field, alias));
        self
    }

    pub fn aggregate_sum(mut self, field: impl Into<String>, alias: impl Into<String>) -> Self {
        self.query = self.query.sum(field, alias);
        self
    }

    pub fn aggregate_avg(mut self, field: impl Into<String>, alias: impl Into<String>) -> Self {
        self.query = self.query.avg(field, alias);
        self
    }

    pub fn aggregate_min(mut self, field: impl Into<String>, alias: impl Into<String>) -> Self {
        self.query = self.query.min(field, alias);
        self
    }

    pub fn aggregate_max(mut self, field: impl Into<String>, alias: impl Into<String>) -> Self {
        self.query = self.query.max(field, alias);
        self
    }

    pub fn aggregate_stddev(mut self, field: impl Into<String>, alias: impl Into<String>) -> Self {
        self.query = self.query.stddev(field, alias);
        self
    }

    pub fn aggregate_stddev_pop(mut self, field: impl Into<String>, alias: impl Into<String>) -> Self {
        self.query = self.query.stddev_pop(field, alias);
        self
    }

    pub fn aggregate_var_samp(mut self, field: impl Into<String>, alias: impl Into<String>) -> Self {
        self.query = self.query.var_samp(field, alias);
        self
    }

    pub fn aggregate_var_pop(mut self, field: impl Into<String>, alias: impl Into<String>) -> Self {
        self.query = self.query.var_pop(field, alias);
        self
    }

    pub fn aggregate_bit_and(mut self, field: impl Into<String>, alias: impl Into<String>) -> Self {
        self.query = self.query.bit_and(field, alias);
        self
    }

    pub fn aggregate_bit_or(mut self, field: impl Into<String>, alias: impl Into<String>) -> Self {
        self.query = self.query.bit_or(field, alias);
        self
    }

    pub fn aggregate_bit_xor(mut self, field: impl Into<String>, alias: impl Into<String>) -> Self {
        self.query = self.query.bit_xor(field, alias);
        self
    }

    pub fn enable_aggregation_cache(mut self) -> Self {
        self.query = self.query.enable_aggregation_cache();
        self
    }

    pub fn enable_aggregation_cache_for(mut self, cache_expired_millis: u64) -> Self {
        self.query = self.query.enable_aggregation_cache_for(cache_expired_millis);
        self
    }

    pub fn propagate_aggregation_cache(mut self, cache_expired_millis: u64) -> Self {
        self.query = self.query.propagate_aggregation_cache(cache_expired_millis);
        self
    }

    pub fn group_by_id(self) -> Self {
        self.group_by("id")
    }

    pub fn group_by_id_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("id");
        request.query = request
            .query
            .project_expr(alias, Expr::column("id"));
        request
    }

    pub fn group_by_id_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("id")
            .aggregate_with_function("id", alias, function)
    }

    pub fn count_id(self) -> Self {
        self.count_id_as("id_count")
    }

    pub fn count_id_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("id", alias)
    }

    pub fn sum_id(self) -> Self {
        self.sum_id_as("sum_id")
    }

    pub fn sum_id_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("id", alias)
    }

    pub fn avg_id(self) -> Self {
        self.avg_id_as("avg_id")
    }

    pub fn avg_id_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("id", alias)
    }

    pub fn min_id(self) -> Self {
        self.min_id_as("min_id")
    }

    pub fn min_id_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("id", alias)
    }

    pub fn max_id(self) -> Self {
        self.max_id_as("max_id")
    }

    pub fn max_id_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("id", alias)
    }


    pub fn with_id(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "id",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_id_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "id",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_id_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("id", value));
        self
    }



    pub fn with_id_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("id", value));
        self
    }

    pub fn with_id_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "id",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_id_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "id",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn order_by_id_asc(mut self) -> Self {
        self.query = self.query.order_asc("id");
        self
    }

    pub fn order_by_id_desc(mut self) -> Self {
        self.query = self.query.order_desc("id");
        self
    }

    pub fn order_by_id_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("id");
        self
    }

    pub fn order_by_id_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("id");
        self
    }


    pub fn select_employee_number(mut self) -> Self {
        self.query = self.query.project("employee_number");
        self
    }

    pub fn project_employee_number(self) -> Self {
        self.select_employee_number()
    }

    pub fn select_employee_number_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_employee_number_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_employee_number_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("employee_number", raw_sql_segment));
        self
    }

    pub fn group_by_employee_number(self) -> Self {
        self.group_by("employee_number")
    }

    pub fn group_by_employee_number_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("employee_number");
        request.query = request
            .query
            .project_expr(alias, Expr::column("employee_number"));
        request
    }

    pub fn group_by_employee_number_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("employee_number")
            .aggregate_with_function("employee_number", alias, function)
    }

    pub fn count_employee_number(self) -> Self {
        self.count_employee_number_as("employee_number_count")
    }

    pub fn count_employee_number_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("employee_number", alias)
    }

    pub fn sum_employee_number(self) -> Self {
        self.sum_employee_number_as("sum_employee_number")
    }

    pub fn sum_employee_number_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("employee_number", alias)
    }

    pub fn avg_employee_number(self) -> Self {
        self.avg_employee_number_as("avg_employee_number")
    }

    pub fn avg_employee_number_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("employee_number", alias)
    }

    pub fn min_employee_number(self) -> Self {
        self.min_employee_number_as("min_employee_number")
    }

    pub fn min_employee_number_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("employee_number", alias)
    }

    pub fn max_employee_number(self) -> Self {
        self.max_employee_number_as("max_employee_number")
    }

    pub fn max_employee_number_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("employee_number", alias)
    }

    pub fn unselect_employee_number(mut self) -> Self {
        self.query.projection.retain(|field| field != "employee_number");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "employee_number");
        self
    }


    pub fn with_employee_number(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "employee_number",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_employee_number_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "employee_number",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_employee_number_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("employee_number", value));
        self
    }



    pub fn with_employee_number_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("employee_number", value));
        self
    }

    pub fn with_employee_number_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("employee_number", value));
        self
    }

    pub fn with_employee_number_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("employee_number", value));
        self
    }

    pub fn with_employee_number_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("employee_number", value));
        self
    }

    pub fn with_employee_number_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("employee_number", value));
        self
    }

    pub fn with_employee_number_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("employee_number", lower, upper));
        self
    }

    pub fn with_employee_number_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "employee_number",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_employee_number_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "employee_number",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_employee_number_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "employee_number",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_employee_number_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("employee_number", value));
        self
    }

    pub fn with_employee_number_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("employee_number", value));
        self
    }

    pub fn with_employee_number_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("employee_number", value));
        self
    }

    pub fn with_employee_number_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("employee_number", value));
        self
    }

    pub fn with_employee_number_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("employee_number", value));
        self
    }

    pub fn with_employee_number_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("employee_number", value));
        self
    }

    pub fn with_employee_number_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("employee_number", value));
        self
    }
    pub fn with_employee_number_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("employee_number", value));
        self
    }

    pub fn with_employee_number_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("employee_number", value));
        self
    }

    pub fn with_employee_number_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("employee_number"));
        self
    }



    pub fn with_employee_number_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("employee_number"));
        self
    }


    pub fn order_by_employee_number_asc(mut self) -> Self {
        self.query = self.query.order_asc("employee_number");
        self
    }

    pub fn order_by_employee_number_desc(mut self) -> Self {
        self.query = self.query.order_desc("employee_number");
        self
    }

    pub fn order_by_employee_number_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("employee_number");
        self
    }

    pub fn order_by_employee_number_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("employee_number");
        self
    }


    pub fn select_hire_date(mut self) -> Self {
        self.query = self.query.project("hire_date");
        self
    }

    pub fn project_hire_date(self) -> Self {
        self.select_hire_date()
    }

    pub fn select_hire_date_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_hire_date_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_hire_date_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("hire_date", raw_sql_segment));
        self
    }

    pub fn group_by_hire_date(self) -> Self {
        self.group_by("hire_date")
    }

    pub fn group_by_hire_date_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("hire_date");
        request.query = request
            .query
            .project_expr(alias, Expr::column("hire_date"));
        request
    }

    pub fn group_by_hire_date_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("hire_date")
            .aggregate_with_function("hire_date", alias, function)
    }

    pub fn count_hire_date(self) -> Self {
        self.count_hire_date_as("hire_date_count")
    }

    pub fn count_hire_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("hire_date", alias)
    }

    pub fn sum_hire_date(self) -> Self {
        self.sum_hire_date_as("sum_hire_date")
    }

    pub fn sum_hire_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("hire_date", alias)
    }

    pub fn avg_hire_date(self) -> Self {
        self.avg_hire_date_as("avg_hire_date")
    }

    pub fn avg_hire_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("hire_date", alias)
    }

    pub fn min_hire_date(self) -> Self {
        self.min_hire_date_as("min_hire_date")
    }

    pub fn min_hire_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("hire_date", alias)
    }

    pub fn max_hire_date(self) -> Self {
        self.max_hire_date_as("max_hire_date")
    }

    pub fn max_hire_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("hire_date", alias)
    }

    pub fn unselect_hire_date(mut self) -> Self {
        self.query.projection.retain(|field| field != "hire_date");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "hire_date");
        self
    }


    pub fn with_hire_date(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "hire_date",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_hire_date_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "hire_date",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_hire_date_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("hire_date", value));
        self
    }



    pub fn with_hire_date_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("hire_date", value));
        self
    }

    pub fn with_hire_date_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("hire_date", value));
        self
    }

    pub fn with_hire_date_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("hire_date", value));
        self
    }

    pub fn with_hire_date_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("hire_date", value));
        self
    }

    pub fn with_hire_date_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("hire_date", value));
        self
    }

    pub fn with_hire_date_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("hire_date", lower, upper));
        self
    }

    pub fn with_hire_date_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "hire_date",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_hire_date_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "hire_date",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_hire_date_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "hire_date",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_hire_date_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("hire_date", value));
        self
    }

    pub fn with_hire_date_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("hire_date", value));
        self
    }

    pub fn with_hire_date_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("hire_date"));
        self
    }



    pub fn with_hire_date_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("hire_date"));
        self
    }


    pub fn order_by_hire_date_asc(mut self) -> Self {
        self.query = self.query.order_asc("hire_date");
        self
    }

    pub fn order_by_hire_date_desc(mut self) -> Self {
        self.query = self.query.order_desc("hire_date");
        self
    }

    pub fn order_by_hire_date_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("hire_date");
        self
    }

    pub fn order_by_hire_date_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("hire_date");
        self
    }


    pub fn select_create_time(mut self) -> Self {
        self.query = self.query.project("create_time");
        self
    }

    pub fn project_create_time(self) -> Self {
        self.select_create_time()
    }

    pub fn select_create_time_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_create_time_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_create_time_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("create_time", raw_sql_segment));
        self
    }

    pub fn group_by_create_time(self) -> Self {
        self.group_by("create_time")
    }

    pub fn group_by_create_time_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("create_time");
        request.query = request
            .query
            .project_expr(alias, Expr::column("create_time"));
        request
    }

    pub fn group_by_create_time_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("create_time")
            .aggregate_with_function("create_time", alias, function)
    }

    pub fn count_create_time(self) -> Self {
        self.count_create_time_as("create_time_count")
    }

    pub fn count_create_time_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("create_time", alias)
    }

    pub fn sum_create_time(self) -> Self {
        self.sum_create_time_as("sum_create_time")
    }

    pub fn sum_create_time_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("create_time", alias)
    }

    pub fn avg_create_time(self) -> Self {
        self.avg_create_time_as("avg_create_time")
    }

    pub fn avg_create_time_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("create_time", alias)
    }

    pub fn min_create_time(self) -> Self {
        self.min_create_time_as("min_create_time")
    }

    pub fn min_create_time_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("create_time", alias)
    }

    pub fn max_create_time(self) -> Self {
        self.max_create_time_as("max_create_time")
    }

    pub fn max_create_time_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("create_time", alias)
    }

    pub fn unselect_create_time(mut self) -> Self {
        self.query.projection.retain(|field| field != "create_time");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "create_time");
        self
    }


    pub fn with_create_time(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "create_time",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_create_time_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "create_time",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_create_time_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("create_time", value));
        self
    }



    pub fn with_create_time_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("create_time", value));
        self
    }

    pub fn with_create_time_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("create_time", value));
        self
    }

    pub fn with_create_time_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("create_time", value));
        self
    }

    pub fn with_create_time_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("create_time", value));
        self
    }

    pub fn with_create_time_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("create_time", value));
        self
    }

    pub fn with_create_time_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("create_time", lower, upper));
        self
    }

    pub fn with_create_time_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "create_time",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_create_time_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "create_time",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_create_time_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "create_time",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_create_time_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("create_time", value));
        self
    }

    pub fn with_create_time_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("create_time", value));
        self
    }

    pub fn with_create_time_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("create_time"));
        self
    }



    pub fn with_create_time_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("create_time"));
        self
    }


    pub fn order_by_create_time_asc(mut self) -> Self {
        self.query = self.query.order_asc("create_time");
        self
    }

    pub fn order_by_create_time_desc(mut self) -> Self {
        self.query = self.query.order_desc("create_time");
        self
    }

    pub fn order_by_create_time_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("create_time");
        self
    }

    pub fn order_by_create_time_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("create_time");
        self
    }


    pub fn select_update_time(mut self) -> Self {
        self.query = self.query.project("update_time");
        self
    }

    pub fn project_update_time(self) -> Self {
        self.select_update_time()
    }

    pub fn select_update_time_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_update_time_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_update_time_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("update_time", raw_sql_segment));
        self
    }

    pub fn group_by_update_time(self) -> Self {
        self.group_by("update_time")
    }

    pub fn group_by_update_time_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("update_time");
        request.query = request
            .query
            .project_expr(alias, Expr::column("update_time"));
        request
    }

    pub fn group_by_update_time_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("update_time")
            .aggregate_with_function("update_time", alias, function)
    }

    pub fn count_update_time(self) -> Self {
        self.count_update_time_as("update_time_count")
    }

    pub fn count_update_time_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("update_time", alias)
    }

    pub fn sum_update_time(self) -> Self {
        self.sum_update_time_as("sum_update_time")
    }

    pub fn sum_update_time_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("update_time", alias)
    }

    pub fn avg_update_time(self) -> Self {
        self.avg_update_time_as("avg_update_time")
    }

    pub fn avg_update_time_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("update_time", alias)
    }

    pub fn min_update_time(self) -> Self {
        self.min_update_time_as("min_update_time")
    }

    pub fn min_update_time_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("update_time", alias)
    }

    pub fn max_update_time(self) -> Self {
        self.max_update_time_as("max_update_time")
    }

    pub fn max_update_time_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("update_time", alias)
    }

    pub fn unselect_update_time(mut self) -> Self {
        self.query.projection.retain(|field| field != "update_time");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "update_time");
        self
    }


    pub fn with_update_time(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "update_time",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_update_time_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "update_time",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_update_time_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("update_time", value));
        self
    }



    pub fn with_update_time_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("update_time", value));
        self
    }

    pub fn with_update_time_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("update_time", value));
        self
    }

    pub fn with_update_time_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("update_time", value));
        self
    }

    pub fn with_update_time_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("update_time", value));
        self
    }

    pub fn with_update_time_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("update_time", value));
        self
    }

    pub fn with_update_time_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("update_time", lower, upper));
        self
    }

    pub fn with_update_time_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "update_time",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_update_time_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "update_time",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_update_time_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "update_time",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_update_time_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("update_time", value));
        self
    }

    pub fn with_update_time_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("update_time", value));
        self
    }

    pub fn with_update_time_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("update_time"));
        self
    }



    pub fn with_update_time_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("update_time"));
        self
    }


    pub fn order_by_update_time_asc(mut self) -> Self {
        self.query = self.query.order_asc("update_time");
        self
    }

    pub fn order_by_update_time_desc(mut self) -> Self {
        self.query = self.query.order_desc("update_time");
        self
    }

    pub fn order_by_update_time_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("update_time");
        self
    }

    pub fn order_by_update_time_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("update_time");
        self
    }

    pub fn group_by_version(self) -> Self {
        self.group_by("version")
    }

    pub fn group_by_version_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("version");
        request.query = request
            .query
            .project_expr(alias, Expr::column("version"));
        request
    }

    pub fn group_by_version_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("version")
            .aggregate_with_function("version", alias, function)
    }

    pub fn count_version(self) -> Self {
        self.count_version_as("version_count")
    }

    pub fn count_version_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("version", alias)
    }

    pub fn sum_version(self) -> Self {
        self.sum_version_as("sum_version")
    }

    pub fn sum_version_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("version", alias)
    }

    pub fn avg_version(self) -> Self {
        self.avg_version_as("avg_version")
    }

    pub fn avg_version_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("version", alias)
    }

    pub fn min_version(self) -> Self {
        self.min_version_as("min_version")
    }

    pub fn min_version_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("version", alias)
    }

    pub fn max_version(self) -> Self {
        self.max_version_as("max_version")
    }

    pub fn max_version_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("version", alias)
    }

    pub fn order_by_version_asc(mut self) -> Self {
        self.query = self.query.order_asc("version");
        self
    }

    pub fn order_by_version_desc(mut self) -> Self {
        self.query = self.query.order_desc("version");
        self
    }

    pub fn order_by_version_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("version");
        self
    }

    pub fn order_by_version_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("version");
        self
    }
    pub fn filter_by_user_account(mut self, value: impl EntityReference) -> Self {
        self.query = self.query.and_filter(Expr::eq("user_account_id", value.entity_id_value()));
        self
    }

    pub fn with_user_account_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "user_account_id",
            <crate::UserAccount as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("user_account", selection));
        self
    }


    pub fn without_user_account_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "user_account_id",
            <crate::UserAccount as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("user_account", selection));
        self
    }


    pub fn have_user_account(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("user_account_id"));
        self
    }

    pub fn have_no_user_account(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("user_account_id"));
        self
    }


    pub fn group_by_user_account(self) -> Self {
        self.group_by("user_account_id")
    }

    pub fn group_by_user_account_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("user_account_id");
        request.query = request
            .query
            .project_expr(alias, Expr::column("user_account_id"));
        request
    }

    pub fn group_by_user_account_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("user_account_id")
            .aggregate_with_function("user_account_id", alias, function)
    }

    pub fn group_by_user_account_with(mut self, request: impl Into<QuerySelection>) -> Self {
        self.query = self.query.group_by("user_account_id");
        self.query_options.object_group_bys.push(ObjectGroupBy::new(
            "user_account",
            "user_account_id",
            request,
        ));
        self
    }

    pub fn group_by_user_account_with_details(self) -> Self {
        self.group_by_user_account_with_details_from(crate::Q::user_accounts().unlimited())
    }

    pub fn group_by_user_account_with_details_from(self, request: impl Into<QuerySelection>) -> Self {
        self.group_by_user_account_with(request)
    }


    pub fn roll_up_to_user_account(self) -> Self {
        self.roll_up_to_user_account_with(crate::Q::user_accounts().unlimited())
    }

    pub fn roll_up_to_user_account_with(self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.with_user_account_matching(selection.clone())
            .group_by_user_account_with(selection)
    }

    pub fn count_user_account(self) -> Self {
        self.count_user_account_as("user_account_count")
    }

    pub fn count_user_account_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("user_account_id", alias)
    }

    pub fn unselect_user_account(mut self) -> Self {
        self.query.projection.retain(|field| field != "user_account_id");
        self.query.relations.retain(|relation| relation.name != "user_account");
        self
    }
    pub fn select_user_account(mut self) -> Self {
        self.query = self.query.relation("user_account");
        self
    }

    pub fn select_user_account_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("user_account", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("user_account", selection));
        self
}

    pub fn facet_by_user_account_as(self, facet_name: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.facet_by_user_account_as_with_options(facet_name, request, true)
    }

    pub fn facet_by_user_account_as_with_options(
        mut self,
        facet_name: impl Into<String>,
        request: impl Into<QuerySelection>,
        include_all_facets: bool,
    ) -> Self {
        self.query_options.facets.push(FacetRequest::new(
            facet_name,
            "user_account",
            request,
            include_all_facets,
        ));
        self
    }
    pub fn have_payroll_calculations(self) -> Self {
        self.with_payroll_calculation_list_matching(SelectQuery::new("PayrollCalculation"))
    }

    pub fn have_no_payroll_calculations(self) -> Self {
        self.without_payroll_calculation_list_matching(SelectQuery::new("PayrollCalculation"))
    }

    pub fn with_payroll_calculation_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::PayrollCalculation as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "employee_record_id",
        ));
        self.relation_filters.push(RelationFilter::new("payroll_calculation_list", selection));
        self
    }

    pub fn without_payroll_calculation_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::PayrollCalculation as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "employee_record_id",
        ));
        self.relation_filters.push(RelationFilter::new("payroll_calculation_list", selection));
        self
    }

    pub fn select_payroll_calculation_list(mut self) -> Self {
        self.query = self.query.relation("payroll_calculation_list");
        self
    }

    pub fn select_payroll_calculation_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("payroll_calculation_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("payroll_calculation_list", selection));
        self
}

    pub fn have_worked_hourses(self) -> Self {
        self.with_worked_hours_list_matching(SelectQuery::new("WorkedHours"))
    }

    pub fn have_no_worked_hourses(self) -> Self {
        self.without_worked_hours_list_matching(SelectQuery::new("WorkedHours"))
    }

    pub fn with_worked_hours_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::WorkedHours as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "employee_record_id",
        ));
        self.relation_filters.push(RelationFilter::new("worked_hours_list", selection));
        self
    }

    pub fn without_worked_hours_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::WorkedHours as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "employee_record_id",
        ));
        self.relation_filters.push(RelationFilter::new("worked_hours_list", selection));
        self
    }

    pub fn select_worked_hours_list(mut self) -> Self {
        self.query = self.query.relation("worked_hours_list");
        self
    }

    pub fn select_worked_hours_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("worked_hours_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("worked_hours_list", selection));
        self
}

    pub fn have_leave_requests(self) -> Self {
        self.with_leave_request_list_matching(SelectQuery::new("LeaveRequest"))
    }

    pub fn have_no_leave_requests(self) -> Self {
        self.without_leave_request_list_matching(SelectQuery::new("LeaveRequest"))
    }

    pub fn with_leave_request_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::LeaveRequest as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "employee_record_id",
        ));
        self.relation_filters.push(RelationFilter::new("leave_request_list", selection));
        self
    }

    pub fn without_leave_request_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::LeaveRequest as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "employee_record_id",
        ));
        self.relation_filters.push(RelationFilter::new("leave_request_list", selection));
        self
    }

    pub fn select_leave_request_list(mut self) -> Self {
        self.query = self.query.relation("leave_request_list");
        self
    }

    pub fn select_leave_request_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("leave_request_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("leave_request_list", selection));
        self
}

    pub fn have_corporate_customers(self) -> Self {
        self.with_corporate_customer_list_matching(SelectQuery::new("CorporateCustomer"))
    }

    pub fn have_no_corporate_customers(self) -> Self {
        self.without_corporate_customer_list_matching(SelectQuery::new("CorporateCustomer"))
    }

    pub fn with_corporate_customer_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::CorporateCustomer as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "account_manager_id",
        ));
        self.relation_filters.push(RelationFilter::new("corporate_customer_list", selection));
        self
    }

    pub fn without_corporate_customer_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::CorporateCustomer as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "account_manager_id",
        ));
        self.relation_filters.push(RelationFilter::new("corporate_customer_list", selection));
        self
    }

    pub fn select_corporate_customer_list(mut self) -> Self {
        self.query = self.query.relation("corporate_customer_list");
        self
    }

    pub fn select_corporate_customer_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("corporate_customer_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("corporate_customer_list", selection));
        self
}

    pub fn have_inventory_trackings(self) -> Self {
        self.with_inventory_tracking_list_matching(SelectQuery::new("InventoryTracking"))
    }

    pub fn have_no_inventory_trackings(self) -> Self {
        self.without_inventory_tracking_list_matching(SelectQuery::new("InventoryTracking"))
    }

    pub fn with_inventory_tracking_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::InventoryTracking as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "employee_record_id",
        ));
        self.relation_filters.push(RelationFilter::new("inventory_tracking_list", selection));
        self
    }

    pub fn without_inventory_tracking_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::InventoryTracking as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "employee_record_id",
        ));
        self.relation_filters.push(RelationFilter::new("inventory_tracking_list", selection));
        self
    }

    pub fn select_inventory_tracking_list(mut self) -> Self {
        self.query = self.query.relation("inventory_tracking_list");
        self
    }

    pub fn select_inventory_tracking_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("inventory_tracking_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("inventory_tracking_list", selection));
        self
}

    pub fn have_job_assignments(self) -> Self {
        self.with_job_assignment_list_matching(SelectQuery::new("JobAssignment"))
    }

    pub fn have_no_job_assignments(self) -> Self {
        self.without_job_assignment_list_matching(SelectQuery::new("JobAssignment"))
    }

    pub fn with_job_assignment_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::JobAssignment as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "employee_record_id",
        ));
        self.relation_filters.push(RelationFilter::new("job_assignment_list", selection));
        self
    }

    pub fn without_job_assignment_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::JobAssignment as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "employee_record_id",
        ));
        self.relation_filters.push(RelationFilter::new("job_assignment_list", selection));
        self
    }

    pub fn select_job_assignment_list(mut self) -> Self {
        self.query = self.query.relation("job_assignment_list");
        self
    }

    pub fn select_job_assignment_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("job_assignment_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("job_assignment_list", selection));
        self
}

    pub fn have_expense_records(self) -> Self {
        self.with_expense_record_list_matching(SelectQuery::new("ExpenseRecord"))
    }

    pub fn have_no_expense_records(self) -> Self {
        self.without_expense_record_list_matching(SelectQuery::new("ExpenseRecord"))
    }

    pub fn with_expense_record_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::ExpenseRecord as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "employee_record_id",
        ));
        self.relation_filters.push(RelationFilter::new("expense_record_list", selection));
        self
    }

    pub fn without_expense_record_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::ExpenseRecord as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "employee_record_id",
        ));
        self.relation_filters.push(RelationFilter::new("expense_record_list", selection));
        self
    }

    pub fn select_expense_record_list(mut self) -> Self {
        self.query = self.query.relation("expense_record_list");
        self
    }

    pub fn select_expense_record_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("expense_record_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("expense_record_list", selection));
        self
}

    pub fn have_financial_summaries(self) -> Self {
        self.with_financial_summary_list_matching(SelectQuery::new("FinancialSummary"))
    }

    pub fn have_no_financial_summaries(self) -> Self {
        self.without_financial_summary_list_matching(SelectQuery::new("FinancialSummary"))
    }

    pub fn with_financial_summary_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::FinancialSummary as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "employee_record_id",
        ));
        self.relation_filters.push(RelationFilter::new("financial_summary_list", selection));
        self
    }

    pub fn without_financial_summary_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::FinancialSummary as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "employee_record_id",
        ));
        self.relation_filters.push(RelationFilter::new("financial_summary_list", selection));
        self
    }

    pub fn select_financial_summary_list(mut self) -> Self {
        self.query = self.query.relation("financial_summary_list");
        self
    }

    pub fn select_financial_summary_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("financial_summary_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("financial_summary_list", selection));
        self
}
    pub fn count_payroll_calculations(self) -> Self {
        self.count_payroll_calculations_as("count_payroll_calculations")
    }

    pub fn count_payroll_calculations_as(self, alias: impl Into<String>) -> Self {
        self.count_payroll_calculations_with(alias, crate::Q::payroll_calculations().unlimited())
    }

    pub fn count_payroll_calculations_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "payroll_calculation_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_payroll_calculations(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payroll_calculations_as("refinements", request)
    }

    pub fn stats_from_payroll_calculations_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "payroll_calculation_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_payroll_calculations_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payroll_calculations(request)
    }


    pub fn min_period_start_of_payroll_calculations(self) -> Self {
        self.min_period_start_of_payroll_calculations_as("min_period_start_of_payroll_calculations", crate::Q::payroll_calculations().unlimited())
    }

    pub fn min_period_start_of_payroll_calculations_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payroll_calculations_as(alias, request.into().into_query().min("period_start", "min_period_start"))
    }
    pub fn max_period_start_of_payroll_calculations(self) -> Self {
        self.max_period_start_of_payroll_calculations_as("max_period_start_of_payroll_calculations", crate::Q::payroll_calculations().unlimited())
    }

    pub fn max_period_start_of_payroll_calculations_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payroll_calculations_as(alias, request.into().into_query().max("period_start", "max_period_start"))
    }
    pub fn min_period_end_of_payroll_calculations(self) -> Self {
        self.min_period_end_of_payroll_calculations_as("min_period_end_of_payroll_calculations", crate::Q::payroll_calculations().unlimited())
    }

    pub fn min_period_end_of_payroll_calculations_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payroll_calculations_as(alias, request.into().into_query().min("period_end", "min_period_end"))
    }
    pub fn max_period_end_of_payroll_calculations(self) -> Self {
        self.max_period_end_of_payroll_calculations_as("max_period_end_of_payroll_calculations", crate::Q::payroll_calculations().unlimited())
    }

    pub fn max_period_end_of_payroll_calculations_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payroll_calculations_as(alias, request.into().into_query().max("period_end", "max_period_end"))
    }
    pub fn sum_total_amount_of_payroll_calculations(self) -> Self {
        self.sum_total_amount_of_payroll_calculations_as("sum_total_amount_of_payroll_calculations", crate::Q::payroll_calculations().unlimited())
    }

    pub fn sum_total_amount_of_payroll_calculations_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payroll_calculations_as(alias, request.into().into_query().sum("total_amount", "sum_total_amount"))
    }
    pub fn min_total_amount_of_payroll_calculations(self) -> Self {
        self.min_total_amount_of_payroll_calculations_as("min_total_amount_of_payroll_calculations", crate::Q::payroll_calculations().unlimited())
    }

    pub fn min_total_amount_of_payroll_calculations_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payroll_calculations_as(alias, request.into().into_query().min("total_amount", "min_total_amount"))
    }
    pub fn max_total_amount_of_payroll_calculations(self) -> Self {
        self.max_total_amount_of_payroll_calculations_as("max_total_amount_of_payroll_calculations", crate::Q::payroll_calculations().unlimited())
    }

    pub fn max_total_amount_of_payroll_calculations_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payroll_calculations_as(alias, request.into().into_query().max("total_amount", "max_total_amount"))
    }
    pub fn avg_total_amount_of_payroll_calculations(self) -> Self {
        self.avg_total_amount_of_payroll_calculations_as("avg_total_amount_of_payroll_calculations", crate::Q::payroll_calculations().unlimited())
    }

    pub fn avg_total_amount_of_payroll_calculations_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payroll_calculations_as(alias, request.into().into_query().avg("total_amount", "avg_total_amount"))
    }
    pub fn standard_deviation_total_amount_of_payroll_calculations(self) -> Self {
        self.standard_deviation_total_amount_of_payroll_calculations_as("standard_deviation_total_amount_of_payroll_calculations", crate::Q::payroll_calculations().unlimited())
    }

    pub fn standard_deviation_total_amount_of_payroll_calculations_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payroll_calculations_as(alias, request.into().into_query().stddev("total_amount", "stdDev_total_amount"))
    }
    pub fn square_root_of_population_standard_deviation_total_amount_of_payroll_calculations(self) -> Self {
        self.square_root_of_population_standard_deviation_total_amount_of_payroll_calculations_as("square_root_of_population_standard_deviation_total_amount_of_payroll_calculations", crate::Q::payroll_calculations().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_total_amount_of_payroll_calculations_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payroll_calculations_as(alias, request.into().into_query().stddev_pop("total_amount", "stdDevPop_total_amount"))
    }
    pub fn sample_variance_total_amount_of_payroll_calculations(self) -> Self {
        self.sample_variance_total_amount_of_payroll_calculations_as("sample_variance_total_amount_of_payroll_calculations", crate::Q::payroll_calculations().unlimited())
    }

    pub fn sample_variance_total_amount_of_payroll_calculations_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payroll_calculations_as(alias, request.into().into_query().var_samp("total_amount", "varSamp_total_amount"))
    }
    pub fn sample_population_variance_total_amount_of_payroll_calculations(self) -> Self {
        self.sample_population_variance_total_amount_of_payroll_calculations_as("sample_population_variance_total_amount_of_payroll_calculations", crate::Q::payroll_calculations().unlimited())
    }

    pub fn sample_population_variance_total_amount_of_payroll_calculations_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payroll_calculations_as(alias, request.into().into_query().var_pop("total_amount", "varPop_total_amount"))
    }
    pub fn min_create_time_of_payroll_calculations(self) -> Self {
        self.min_create_time_of_payroll_calculations_as("min_create_time_of_payroll_calculations", crate::Q::payroll_calculations().unlimited())
    }

    pub fn min_create_time_of_payroll_calculations_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payroll_calculations_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_payroll_calculations(self) -> Self {
        self.max_create_time_of_payroll_calculations_as("max_create_time_of_payroll_calculations", crate::Q::payroll_calculations().unlimited())
    }

    pub fn max_create_time_of_payroll_calculations_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payroll_calculations_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_payroll_calculations(self) -> Self {
        self.min_update_time_of_payroll_calculations_as("min_update_time_of_payroll_calculations", crate::Q::payroll_calculations().unlimited())
    }

    pub fn min_update_time_of_payroll_calculations_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payroll_calculations_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_payroll_calculations(self) -> Self {
        self.max_update_time_of_payroll_calculations_as("max_update_time_of_payroll_calculations", crate::Q::payroll_calculations().unlimited())
    }

    pub fn max_update_time_of_payroll_calculations_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payroll_calculations_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }

    pub fn count_worked_hourses(self) -> Self {
        self.count_worked_hourses_as("count_worked_hourses")
    }

    pub fn count_worked_hourses_as(self, alias: impl Into<String>) -> Self {
        self.count_worked_hourses_with(alias, crate::Q::worked_hourses().unlimited())
    }

    pub fn count_worked_hourses_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "worked_hours_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_worked_hourses(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_worked_hourses_as("refinements", request)
    }

    pub fn stats_from_worked_hourses_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "worked_hours_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_worked_hourses_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_worked_hourses(request)
    }


    pub fn sum_hours_count_of_worked_hourses(self) -> Self {
        self.sum_hours_count_of_worked_hourses_as("sum_hours_count_of_worked_hourses", crate::Q::worked_hourses().unlimited())
    }

    pub fn sum_hours_count_of_worked_hourses_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_worked_hourses_as(alias, request.into().into_query().sum("hours_count", "sum_hours_count"))
    }
    pub fn min_hours_count_of_worked_hourses(self) -> Self {
        self.min_hours_count_of_worked_hourses_as("min_hours_count_of_worked_hourses", crate::Q::worked_hourses().unlimited())
    }

    pub fn min_hours_count_of_worked_hourses_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_worked_hourses_as(alias, request.into().into_query().min("hours_count", "min_hours_count"))
    }
    pub fn max_hours_count_of_worked_hourses(self) -> Self {
        self.max_hours_count_of_worked_hourses_as("max_hours_count_of_worked_hourses", crate::Q::worked_hourses().unlimited())
    }

    pub fn max_hours_count_of_worked_hourses_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_worked_hourses_as(alias, request.into().into_query().max("hours_count", "max_hours_count"))
    }
    pub fn avg_hours_count_of_worked_hourses(self) -> Self {
        self.avg_hours_count_of_worked_hourses_as("avg_hours_count_of_worked_hourses", crate::Q::worked_hourses().unlimited())
    }

    pub fn avg_hours_count_of_worked_hourses_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_worked_hourses_as(alias, request.into().into_query().avg("hours_count", "avg_hours_count"))
    }
    pub fn standard_deviation_hours_count_of_worked_hourses(self) -> Self {
        self.standard_deviation_hours_count_of_worked_hourses_as("standard_deviation_hours_count_of_worked_hourses", crate::Q::worked_hourses().unlimited())
    }

    pub fn standard_deviation_hours_count_of_worked_hourses_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_worked_hourses_as(alias, request.into().into_query().stddev("hours_count", "stdDev_hours_count"))
    }
    pub fn square_root_of_population_standard_deviation_hours_count_of_worked_hourses(self) -> Self {
        self.square_root_of_population_standard_deviation_hours_count_of_worked_hourses_as("square_root_of_population_standard_deviation_hours_count_of_worked_hourses", crate::Q::worked_hourses().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_hours_count_of_worked_hourses_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_worked_hourses_as(alias, request.into().into_query().stddev_pop("hours_count", "stdDevPop_hours_count"))
    }
    pub fn sample_variance_hours_count_of_worked_hourses(self) -> Self {
        self.sample_variance_hours_count_of_worked_hourses_as("sample_variance_hours_count_of_worked_hourses", crate::Q::worked_hourses().unlimited())
    }

    pub fn sample_variance_hours_count_of_worked_hourses_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_worked_hourses_as(alias, request.into().into_query().var_samp("hours_count", "varSamp_hours_count"))
    }
    pub fn sample_population_variance_hours_count_of_worked_hourses(self) -> Self {
        self.sample_population_variance_hours_count_of_worked_hourses_as("sample_population_variance_hours_count_of_worked_hourses", crate::Q::worked_hourses().unlimited())
    }

    pub fn sample_population_variance_hours_count_of_worked_hourses_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_worked_hourses_as(alias, request.into().into_query().var_pop("hours_count", "varPop_hours_count"))
    }
    pub fn min_work_date_of_worked_hourses(self) -> Self {
        self.min_work_date_of_worked_hourses_as("min_work_date_of_worked_hourses", crate::Q::worked_hourses().unlimited())
    }

    pub fn min_work_date_of_worked_hourses_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_worked_hourses_as(alias, request.into().into_query().min("work_date", "min_work_date"))
    }
    pub fn max_work_date_of_worked_hourses(self) -> Self {
        self.max_work_date_of_worked_hourses_as("max_work_date_of_worked_hourses", crate::Q::worked_hourses().unlimited())
    }

    pub fn max_work_date_of_worked_hourses_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_worked_hourses_as(alias, request.into().into_query().max("work_date", "max_work_date"))
    }
    pub fn min_create_time_of_worked_hourses(self) -> Self {
        self.min_create_time_of_worked_hourses_as("min_create_time_of_worked_hourses", crate::Q::worked_hourses().unlimited())
    }

    pub fn min_create_time_of_worked_hourses_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_worked_hourses_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_worked_hourses(self) -> Self {
        self.max_create_time_of_worked_hourses_as("max_create_time_of_worked_hourses", crate::Q::worked_hourses().unlimited())
    }

    pub fn max_create_time_of_worked_hourses_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_worked_hourses_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_worked_hourses(self) -> Self {
        self.min_update_time_of_worked_hourses_as("min_update_time_of_worked_hourses", crate::Q::worked_hourses().unlimited())
    }

    pub fn min_update_time_of_worked_hourses_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_worked_hourses_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_worked_hourses(self) -> Self {
        self.max_update_time_of_worked_hourses_as("max_update_time_of_worked_hourses", crate::Q::worked_hourses().unlimited())
    }

    pub fn max_update_time_of_worked_hourses_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_worked_hourses_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }

    pub fn count_leave_requests(self) -> Self {
        self.count_leave_requests_as("count_leave_requests")
    }

    pub fn count_leave_requests_as(self, alias: impl Into<String>) -> Self {
        self.count_leave_requests_with(alias, crate::Q::leave_requests().unlimited())
    }

    pub fn count_leave_requests_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "leave_request_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_leave_requests(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_leave_requests_as("refinements", request)
    }

    pub fn stats_from_leave_requests_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "leave_request_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_leave_requests_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_leave_requests(request)
    }


    pub fn min_start_date_of_leave_requests(self) -> Self {
        self.min_start_date_of_leave_requests_as("min_start_date_of_leave_requests", crate::Q::leave_requests().unlimited())
    }

    pub fn min_start_date_of_leave_requests_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_leave_requests_as(alias, request.into().into_query().min("start_date", "min_start_date"))
    }
    pub fn max_start_date_of_leave_requests(self) -> Self {
        self.max_start_date_of_leave_requests_as("max_start_date_of_leave_requests", crate::Q::leave_requests().unlimited())
    }

    pub fn max_start_date_of_leave_requests_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_leave_requests_as(alias, request.into().into_query().max("start_date", "max_start_date"))
    }
    pub fn min_end_date_of_leave_requests(self) -> Self {
        self.min_end_date_of_leave_requests_as("min_end_date_of_leave_requests", crate::Q::leave_requests().unlimited())
    }

    pub fn min_end_date_of_leave_requests_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_leave_requests_as(alias, request.into().into_query().min("end_date", "min_end_date"))
    }
    pub fn max_end_date_of_leave_requests(self) -> Self {
        self.max_end_date_of_leave_requests_as("max_end_date_of_leave_requests", crate::Q::leave_requests().unlimited())
    }

    pub fn max_end_date_of_leave_requests_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_leave_requests_as(alias, request.into().into_query().max("end_date", "max_end_date"))
    }
    pub fn min_create_time_of_leave_requests(self) -> Self {
        self.min_create_time_of_leave_requests_as("min_create_time_of_leave_requests", crate::Q::leave_requests().unlimited())
    }

    pub fn min_create_time_of_leave_requests_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_leave_requests_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_leave_requests(self) -> Self {
        self.max_create_time_of_leave_requests_as("max_create_time_of_leave_requests", crate::Q::leave_requests().unlimited())
    }

    pub fn max_create_time_of_leave_requests_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_leave_requests_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_leave_requests(self) -> Self {
        self.min_update_time_of_leave_requests_as("min_update_time_of_leave_requests", crate::Q::leave_requests().unlimited())
    }

    pub fn min_update_time_of_leave_requests_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_leave_requests_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_leave_requests(self) -> Self {
        self.max_update_time_of_leave_requests_as("max_update_time_of_leave_requests", crate::Q::leave_requests().unlimited())
    }

    pub fn max_update_time_of_leave_requests_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_leave_requests_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }

    pub fn count_corporate_customers(self) -> Self {
        self.count_corporate_customers_as("count_corporate_customers")
    }

    pub fn count_corporate_customers_as(self, alias: impl Into<String>) -> Self {
        self.count_corporate_customers_with(alias, crate::Q::corporate_customers().unlimited())
    }

    pub fn count_corporate_customers_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "corporate_customer_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_corporate_customers(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_corporate_customers_as("refinements", request)
    }

    pub fn stats_from_corporate_customers_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "corporate_customer_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_corporate_customers_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_corporate_customers(request)
    }


    pub fn sum_tax_id_of_corporate_customers(self) -> Self {
        self.sum_tax_id_of_corporate_customers_as("sum_tax_id_of_corporate_customers", crate::Q::corporate_customers().unlimited())
    }

    pub fn sum_tax_id_of_corporate_customers_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_corporate_customers_as(alias, request.into().into_query().sum("tax_id", "sum_tax_id"))
    }
    pub fn min_tax_id_of_corporate_customers(self) -> Self {
        self.min_tax_id_of_corporate_customers_as("min_tax_id_of_corporate_customers", crate::Q::corporate_customers().unlimited())
    }

    pub fn min_tax_id_of_corporate_customers_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_corporate_customers_as(alias, request.into().into_query().min("tax_id", "min_tax_id"))
    }
    pub fn max_tax_id_of_corporate_customers(self) -> Self {
        self.max_tax_id_of_corporate_customers_as("max_tax_id_of_corporate_customers", crate::Q::corporate_customers().unlimited())
    }

    pub fn max_tax_id_of_corporate_customers_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_corporate_customers_as(alias, request.into().into_query().max("tax_id", "max_tax_id"))
    }
    pub fn avg_tax_id_of_corporate_customers(self) -> Self {
        self.avg_tax_id_of_corporate_customers_as("avg_tax_id_of_corporate_customers", crate::Q::corporate_customers().unlimited())
    }

    pub fn avg_tax_id_of_corporate_customers_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_corporate_customers_as(alias, request.into().into_query().avg("tax_id", "avg_tax_id"))
    }
    pub fn standard_deviation_tax_id_of_corporate_customers(self) -> Self {
        self.standard_deviation_tax_id_of_corporate_customers_as("standard_deviation_tax_id_of_corporate_customers", crate::Q::corporate_customers().unlimited())
    }

    pub fn standard_deviation_tax_id_of_corporate_customers_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_corporate_customers_as(alias, request.into().into_query().stddev("tax_id", "stdDev_tax_id"))
    }
    pub fn square_root_of_population_standard_deviation_tax_id_of_corporate_customers(self) -> Self {
        self.square_root_of_population_standard_deviation_tax_id_of_corporate_customers_as("square_root_of_population_standard_deviation_tax_id_of_corporate_customers", crate::Q::corporate_customers().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_tax_id_of_corporate_customers_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_corporate_customers_as(alias, request.into().into_query().stddev_pop("tax_id", "stdDevPop_tax_id"))
    }
    pub fn sample_variance_tax_id_of_corporate_customers(self) -> Self {
        self.sample_variance_tax_id_of_corporate_customers_as("sample_variance_tax_id_of_corporate_customers", crate::Q::corporate_customers().unlimited())
    }

    pub fn sample_variance_tax_id_of_corporate_customers_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_corporate_customers_as(alias, request.into().into_query().var_samp("tax_id", "varSamp_tax_id"))
    }
    pub fn sample_population_variance_tax_id_of_corporate_customers(self) -> Self {
        self.sample_population_variance_tax_id_of_corporate_customers_as("sample_population_variance_tax_id_of_corporate_customers", crate::Q::corporate_customers().unlimited())
    }

    pub fn sample_population_variance_tax_id_of_corporate_customers_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_corporate_customers_as(alias, request.into().into_query().var_pop("tax_id", "varPop_tax_id"))
    }
    pub fn min_create_time_of_corporate_customers(self) -> Self {
        self.min_create_time_of_corporate_customers_as("min_create_time_of_corporate_customers", crate::Q::corporate_customers().unlimited())
    }

    pub fn min_create_time_of_corporate_customers_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_corporate_customers_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_corporate_customers(self) -> Self {
        self.max_create_time_of_corporate_customers_as("max_create_time_of_corporate_customers", crate::Q::corporate_customers().unlimited())
    }

    pub fn max_create_time_of_corporate_customers_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_corporate_customers_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_corporate_customers(self) -> Self {
        self.min_update_time_of_corporate_customers_as("min_update_time_of_corporate_customers", crate::Q::corporate_customers().unlimited())
    }

    pub fn min_update_time_of_corporate_customers_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_corporate_customers_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_corporate_customers(self) -> Self {
        self.max_update_time_of_corporate_customers_as("max_update_time_of_corporate_customers", crate::Q::corporate_customers().unlimited())
    }

    pub fn max_update_time_of_corporate_customers_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_corporate_customers_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }

    pub fn count_inventory_trackings(self) -> Self {
        self.count_inventory_trackings_as("count_inventory_trackings")
    }

    pub fn count_inventory_trackings_as(self, alias: impl Into<String>) -> Self {
        self.count_inventory_trackings_with(alias, crate::Q::inventory_trackings().unlimited())
    }

    pub fn count_inventory_trackings_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "inventory_tracking_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_inventory_trackings(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_inventory_trackings_as("refinements", request)
    }

    pub fn stats_from_inventory_trackings_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "inventory_tracking_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_inventory_trackings_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_inventory_trackings(request)
    }


    pub fn min_last_counted_date_of_inventory_trackings(self) -> Self {
        self.min_last_counted_date_of_inventory_trackings_as("min_last_counted_date_of_inventory_trackings", crate::Q::inventory_trackings().unlimited())
    }

    pub fn min_last_counted_date_of_inventory_trackings_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_inventory_trackings_as(alias, request.into().into_query().min("last_counted_date", "min_last_counted_date"))
    }
    pub fn max_last_counted_date_of_inventory_trackings(self) -> Self {
        self.max_last_counted_date_of_inventory_trackings_as("max_last_counted_date_of_inventory_trackings", crate::Q::inventory_trackings().unlimited())
    }

    pub fn max_last_counted_date_of_inventory_trackings_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_inventory_trackings_as(alias, request.into().into_query().max("last_counted_date", "max_last_counted_date"))
    }
    pub fn sum_count_difference_of_inventory_trackings(self) -> Self {
        self.sum_count_difference_of_inventory_trackings_as("sum_count_difference_of_inventory_trackings", crate::Q::inventory_trackings().unlimited())
    }

    pub fn sum_count_difference_of_inventory_trackings_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_inventory_trackings_as(alias, request.into().into_query().sum("count_difference", "sum_count_difference"))
    }
    pub fn min_count_difference_of_inventory_trackings(self) -> Self {
        self.min_count_difference_of_inventory_trackings_as("min_count_difference_of_inventory_trackings", crate::Q::inventory_trackings().unlimited())
    }

    pub fn min_count_difference_of_inventory_trackings_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_inventory_trackings_as(alias, request.into().into_query().min("count_difference", "min_count_difference"))
    }
    pub fn max_count_difference_of_inventory_trackings(self) -> Self {
        self.max_count_difference_of_inventory_trackings_as("max_count_difference_of_inventory_trackings", crate::Q::inventory_trackings().unlimited())
    }

    pub fn max_count_difference_of_inventory_trackings_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_inventory_trackings_as(alias, request.into().into_query().max("count_difference", "max_count_difference"))
    }
    pub fn avg_count_difference_of_inventory_trackings(self) -> Self {
        self.avg_count_difference_of_inventory_trackings_as("avg_count_difference_of_inventory_trackings", crate::Q::inventory_trackings().unlimited())
    }

    pub fn avg_count_difference_of_inventory_trackings_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_inventory_trackings_as(alias, request.into().into_query().avg("count_difference", "avg_count_difference"))
    }
    pub fn standard_deviation_count_difference_of_inventory_trackings(self) -> Self {
        self.standard_deviation_count_difference_of_inventory_trackings_as("standard_deviation_count_difference_of_inventory_trackings", crate::Q::inventory_trackings().unlimited())
    }

    pub fn standard_deviation_count_difference_of_inventory_trackings_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_inventory_trackings_as(alias, request.into().into_query().stddev("count_difference", "stdDev_count_difference"))
    }
    pub fn square_root_of_population_standard_deviation_count_difference_of_inventory_trackings(self) -> Self {
        self.square_root_of_population_standard_deviation_count_difference_of_inventory_trackings_as("square_root_of_population_standard_deviation_count_difference_of_inventory_trackings", crate::Q::inventory_trackings().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_count_difference_of_inventory_trackings_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_inventory_trackings_as(alias, request.into().into_query().stddev_pop("count_difference", "stdDevPop_count_difference"))
    }
    pub fn sample_variance_count_difference_of_inventory_trackings(self) -> Self {
        self.sample_variance_count_difference_of_inventory_trackings_as("sample_variance_count_difference_of_inventory_trackings", crate::Q::inventory_trackings().unlimited())
    }

    pub fn sample_variance_count_difference_of_inventory_trackings_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_inventory_trackings_as(alias, request.into().into_query().var_samp("count_difference", "varSamp_count_difference"))
    }
    pub fn sample_population_variance_count_difference_of_inventory_trackings(self) -> Self {
        self.sample_population_variance_count_difference_of_inventory_trackings_as("sample_population_variance_count_difference_of_inventory_trackings", crate::Q::inventory_trackings().unlimited())
    }

    pub fn sample_population_variance_count_difference_of_inventory_trackings_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_inventory_trackings_as(alias, request.into().into_query().var_pop("count_difference", "varPop_count_difference"))
    }
    pub fn min_create_time_of_inventory_trackings(self) -> Self {
        self.min_create_time_of_inventory_trackings_as("min_create_time_of_inventory_trackings", crate::Q::inventory_trackings().unlimited())
    }

    pub fn min_create_time_of_inventory_trackings_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_inventory_trackings_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_inventory_trackings(self) -> Self {
        self.max_create_time_of_inventory_trackings_as("max_create_time_of_inventory_trackings", crate::Q::inventory_trackings().unlimited())
    }

    pub fn max_create_time_of_inventory_trackings_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_inventory_trackings_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_inventory_trackings(self) -> Self {
        self.min_update_time_of_inventory_trackings_as("min_update_time_of_inventory_trackings", crate::Q::inventory_trackings().unlimited())
    }

    pub fn min_update_time_of_inventory_trackings_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_inventory_trackings_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_inventory_trackings(self) -> Self {
        self.max_update_time_of_inventory_trackings_as("max_update_time_of_inventory_trackings", crate::Q::inventory_trackings().unlimited())
    }

    pub fn max_update_time_of_inventory_trackings_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_inventory_trackings_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }

    pub fn count_job_assignments(self) -> Self {
        self.count_job_assignments_as("count_job_assignments")
    }

    pub fn count_job_assignments_as(self, alias: impl Into<String>) -> Self {
        self.count_job_assignments_with(alias, crate::Q::job_assignments().unlimited())
    }

    pub fn count_job_assignments_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "job_assignment_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_job_assignments(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_job_assignments_as("refinements", request)
    }

    pub fn stats_from_job_assignments_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "job_assignment_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_job_assignments_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_job_assignments(request)
    }


    pub fn min_create_time_of_job_assignments(self) -> Self {
        self.min_create_time_of_job_assignments_as("min_create_time_of_job_assignments", crate::Q::job_assignments().unlimited())
    }

    pub fn min_create_time_of_job_assignments_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_job_assignments_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_job_assignments(self) -> Self {
        self.max_create_time_of_job_assignments_as("max_create_time_of_job_assignments", crate::Q::job_assignments().unlimited())
    }

    pub fn max_create_time_of_job_assignments_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_job_assignments_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_job_assignments(self) -> Self {
        self.min_update_time_of_job_assignments_as("min_update_time_of_job_assignments", crate::Q::job_assignments().unlimited())
    }

    pub fn min_update_time_of_job_assignments_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_job_assignments_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_job_assignments(self) -> Self {
        self.max_update_time_of_job_assignments_as("max_update_time_of_job_assignments", crate::Q::job_assignments().unlimited())
    }

    pub fn max_update_time_of_job_assignments_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_job_assignments_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }

    pub fn count_expense_records(self) -> Self {
        self.count_expense_records_as("count_expense_records")
    }

    pub fn count_expense_records_as(self, alias: impl Into<String>) -> Self {
        self.count_expense_records_with(alias, crate::Q::expense_records().unlimited())
    }

    pub fn count_expense_records_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "expense_record_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_expense_records(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records_as("refinements", request)
    }

    pub fn stats_from_expense_records_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "expense_record_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_expense_records_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records(request)
    }


    pub fn sum_expense_amount_of_expense_records(self) -> Self {
        self.sum_expense_amount_of_expense_records_as("sum_expense_amount_of_expense_records", crate::Q::expense_records().unlimited())
    }

    pub fn sum_expense_amount_of_expense_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records_as(alias, request.into().into_query().sum("expense_amount", "sum_expense_amount"))
    }
    pub fn min_expense_amount_of_expense_records(self) -> Self {
        self.min_expense_amount_of_expense_records_as("min_expense_amount_of_expense_records", crate::Q::expense_records().unlimited())
    }

    pub fn min_expense_amount_of_expense_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records_as(alias, request.into().into_query().min("expense_amount", "min_expense_amount"))
    }
    pub fn max_expense_amount_of_expense_records(self) -> Self {
        self.max_expense_amount_of_expense_records_as("max_expense_amount_of_expense_records", crate::Q::expense_records().unlimited())
    }

    pub fn max_expense_amount_of_expense_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records_as(alias, request.into().into_query().max("expense_amount", "max_expense_amount"))
    }
    pub fn avg_expense_amount_of_expense_records(self) -> Self {
        self.avg_expense_amount_of_expense_records_as("avg_expense_amount_of_expense_records", crate::Q::expense_records().unlimited())
    }

    pub fn avg_expense_amount_of_expense_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records_as(alias, request.into().into_query().avg("expense_amount", "avg_expense_amount"))
    }
    pub fn standard_deviation_expense_amount_of_expense_records(self) -> Self {
        self.standard_deviation_expense_amount_of_expense_records_as("standard_deviation_expense_amount_of_expense_records", crate::Q::expense_records().unlimited())
    }

    pub fn standard_deviation_expense_amount_of_expense_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records_as(alias, request.into().into_query().stddev("expense_amount", "stdDev_expense_amount"))
    }
    pub fn square_root_of_population_standard_deviation_expense_amount_of_expense_records(self) -> Self {
        self.square_root_of_population_standard_deviation_expense_amount_of_expense_records_as("square_root_of_population_standard_deviation_expense_amount_of_expense_records", crate::Q::expense_records().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_expense_amount_of_expense_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records_as(alias, request.into().into_query().stddev_pop("expense_amount", "stdDevPop_expense_amount"))
    }
    pub fn sample_variance_expense_amount_of_expense_records(self) -> Self {
        self.sample_variance_expense_amount_of_expense_records_as("sample_variance_expense_amount_of_expense_records", crate::Q::expense_records().unlimited())
    }

    pub fn sample_variance_expense_amount_of_expense_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records_as(alias, request.into().into_query().var_samp("expense_amount", "varSamp_expense_amount"))
    }
    pub fn sample_population_variance_expense_amount_of_expense_records(self) -> Self {
        self.sample_population_variance_expense_amount_of_expense_records_as("sample_population_variance_expense_amount_of_expense_records", crate::Q::expense_records().unlimited())
    }

    pub fn sample_population_variance_expense_amount_of_expense_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records_as(alias, request.into().into_query().var_pop("expense_amount", "varPop_expense_amount"))
    }
    pub fn min_create_time_of_expense_records(self) -> Self {
        self.min_create_time_of_expense_records_as("min_create_time_of_expense_records", crate::Q::expense_records().unlimited())
    }

    pub fn min_create_time_of_expense_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_expense_records(self) -> Self {
        self.max_create_time_of_expense_records_as("max_create_time_of_expense_records", crate::Q::expense_records().unlimited())
    }

    pub fn max_create_time_of_expense_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_expense_records(self) -> Self {
        self.min_update_time_of_expense_records_as("min_update_time_of_expense_records", crate::Q::expense_records().unlimited())
    }

    pub fn min_update_time_of_expense_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_expense_records(self) -> Self {
        self.max_update_time_of_expense_records_as("max_update_time_of_expense_records", crate::Q::expense_records().unlimited())
    }

    pub fn max_update_time_of_expense_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }

    pub fn count_financial_summaries(self) -> Self {
        self.count_financial_summaries_as("count_financial_summaries")
    }

    pub fn count_financial_summaries_as(self, alias: impl Into<String>) -> Self {
        self.count_financial_summaries_with(alias, crate::Q::financial_summaries().unlimited())
    }

    pub fn count_financial_summaries_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "financial_summary_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_financial_summaries(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_financial_summaries_as("refinements", request)
    }

    pub fn stats_from_financial_summaries_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "financial_summary_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_financial_summaries_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_financial_summaries(request)
    }


    pub fn sum_total_revenue_of_financial_summaries(self) -> Self {
        self.sum_total_revenue_of_financial_summaries_as("sum_total_revenue_of_financial_summaries", crate::Q::financial_summaries().unlimited())
    }

    pub fn sum_total_revenue_of_financial_summaries_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_financial_summaries_as(alias, request.into().into_query().sum("total_revenue", "sum_total_revenue"))
    }
    pub fn min_total_revenue_of_financial_summaries(self) -> Self {
        self.min_total_revenue_of_financial_summaries_as("min_total_revenue_of_financial_summaries", crate::Q::financial_summaries().unlimited())
    }

    pub fn min_total_revenue_of_financial_summaries_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_financial_summaries_as(alias, request.into().into_query().min("total_revenue", "min_total_revenue"))
    }
    pub fn max_total_revenue_of_financial_summaries(self) -> Self {
        self.max_total_revenue_of_financial_summaries_as("max_total_revenue_of_financial_summaries", crate::Q::financial_summaries().unlimited())
    }

    pub fn max_total_revenue_of_financial_summaries_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_financial_summaries_as(alias, request.into().into_query().max("total_revenue", "max_total_revenue"))
    }
    pub fn avg_total_revenue_of_financial_summaries(self) -> Self {
        self.avg_total_revenue_of_financial_summaries_as("avg_total_revenue_of_financial_summaries", crate::Q::financial_summaries().unlimited())
    }

    pub fn avg_total_revenue_of_financial_summaries_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_financial_summaries_as(alias, request.into().into_query().avg("total_revenue", "avg_total_revenue"))
    }
    pub fn standard_deviation_total_revenue_of_financial_summaries(self) -> Self {
        self.standard_deviation_total_revenue_of_financial_summaries_as("standard_deviation_total_revenue_of_financial_summaries", crate::Q::financial_summaries().unlimited())
    }

    pub fn standard_deviation_total_revenue_of_financial_summaries_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_financial_summaries_as(alias, request.into().into_query().stddev("total_revenue", "stdDev_total_revenue"))
    }
    pub fn square_root_of_population_standard_deviation_total_revenue_of_financial_summaries(self) -> Self {
        self.square_root_of_population_standard_deviation_total_revenue_of_financial_summaries_as("square_root_of_population_standard_deviation_total_revenue_of_financial_summaries", crate::Q::financial_summaries().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_total_revenue_of_financial_summaries_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_financial_summaries_as(alias, request.into().into_query().stddev_pop("total_revenue", "stdDevPop_total_revenue"))
    }
    pub fn sample_variance_total_revenue_of_financial_summaries(self) -> Self {
        self.sample_variance_total_revenue_of_financial_summaries_as("sample_variance_total_revenue_of_financial_summaries", crate::Q::financial_summaries().unlimited())
    }

    pub fn sample_variance_total_revenue_of_financial_summaries_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_financial_summaries_as(alias, request.into().into_query().var_samp("total_revenue", "varSamp_total_revenue"))
    }
    pub fn sample_population_variance_total_revenue_of_financial_summaries(self) -> Self {
        self.sample_population_variance_total_revenue_of_financial_summaries_as("sample_population_variance_total_revenue_of_financial_summaries", crate::Q::financial_summaries().unlimited())
    }

    pub fn sample_population_variance_total_revenue_of_financial_summaries_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_financial_summaries_as(alias, request.into().into_query().var_pop("total_revenue", "varPop_total_revenue"))
    }
    pub fn sum_total_expenses_of_financial_summaries(self) -> Self {
        self.sum_total_expenses_of_financial_summaries_as("sum_total_expenses_of_financial_summaries", crate::Q::financial_summaries().unlimited())
    }

    pub fn sum_total_expenses_of_financial_summaries_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_financial_summaries_as(alias, request.into().into_query().sum("total_expenses", "sum_total_expenses"))
    }
    pub fn min_total_expenses_of_financial_summaries(self) -> Self {
        self.min_total_expenses_of_financial_summaries_as("min_total_expenses_of_financial_summaries", crate::Q::financial_summaries().unlimited())
    }

    pub fn min_total_expenses_of_financial_summaries_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_financial_summaries_as(alias, request.into().into_query().min("total_expenses", "min_total_expenses"))
    }
    pub fn max_total_expenses_of_financial_summaries(self) -> Self {
        self.max_total_expenses_of_financial_summaries_as("max_total_expenses_of_financial_summaries", crate::Q::financial_summaries().unlimited())
    }

    pub fn max_total_expenses_of_financial_summaries_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_financial_summaries_as(alias, request.into().into_query().max("total_expenses", "max_total_expenses"))
    }
    pub fn avg_total_expenses_of_financial_summaries(self) -> Self {
        self.avg_total_expenses_of_financial_summaries_as("avg_total_expenses_of_financial_summaries", crate::Q::financial_summaries().unlimited())
    }

    pub fn avg_total_expenses_of_financial_summaries_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_financial_summaries_as(alias, request.into().into_query().avg("total_expenses", "avg_total_expenses"))
    }
    pub fn standard_deviation_total_expenses_of_financial_summaries(self) -> Self {
        self.standard_deviation_total_expenses_of_financial_summaries_as("standard_deviation_total_expenses_of_financial_summaries", crate::Q::financial_summaries().unlimited())
    }

    pub fn standard_deviation_total_expenses_of_financial_summaries_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_financial_summaries_as(alias, request.into().into_query().stddev("total_expenses", "stdDev_total_expenses"))
    }
    pub fn square_root_of_population_standard_deviation_total_expenses_of_financial_summaries(self) -> Self {
        self.square_root_of_population_standard_deviation_total_expenses_of_financial_summaries_as("square_root_of_population_standard_deviation_total_expenses_of_financial_summaries", crate::Q::financial_summaries().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_total_expenses_of_financial_summaries_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_financial_summaries_as(alias, request.into().into_query().stddev_pop("total_expenses", "stdDevPop_total_expenses"))
    }
    pub fn sample_variance_total_expenses_of_financial_summaries(self) -> Self {
        self.sample_variance_total_expenses_of_financial_summaries_as("sample_variance_total_expenses_of_financial_summaries", crate::Q::financial_summaries().unlimited())
    }

    pub fn sample_variance_total_expenses_of_financial_summaries_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_financial_summaries_as(alias, request.into().into_query().var_samp("total_expenses", "varSamp_total_expenses"))
    }
    pub fn sample_population_variance_total_expenses_of_financial_summaries(self) -> Self {
        self.sample_population_variance_total_expenses_of_financial_summaries_as("sample_population_variance_total_expenses_of_financial_summaries", crate::Q::financial_summaries().unlimited())
    }

    pub fn sample_population_variance_total_expenses_of_financial_summaries_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_financial_summaries_as(alias, request.into().into_query().var_pop("total_expenses", "varPop_total_expenses"))
    }
    pub fn min_create_time_of_financial_summaries(self) -> Self {
        self.min_create_time_of_financial_summaries_as("min_create_time_of_financial_summaries", crate::Q::financial_summaries().unlimited())
    }

    pub fn min_create_time_of_financial_summaries_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_financial_summaries_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_financial_summaries(self) -> Self {
        self.max_create_time_of_financial_summaries_as("max_create_time_of_financial_summaries", crate::Q::financial_summaries().unlimited())
    }

    pub fn max_create_time_of_financial_summaries_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_financial_summaries_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_financial_summaries(self) -> Self {
        self.min_update_time_of_financial_summaries_as("min_update_time_of_financial_summaries", crate::Q::financial_summaries().unlimited())
    }

    pub fn min_update_time_of_financial_summaries_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_financial_summaries_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_financial_summaries(self) -> Self {
        self.max_update_time_of_financial_summaries_as("max_update_time_of_financial_summaries", crate::Q::financial_summaries().unlimited())
    }

    pub fn max_update_time_of_financial_summaries_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_financial_summaries_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }
}

impl<R> Default for EmployeeRecordRequest<R> {
    fn default() -> Self {
        Self::new()
    }
}

impl<R> From< EmployeeRecordRequest<R> > for SelectQuery {
    fn from(request: EmployeeRecordRequest<R>) -> Self {
        QuerySelection::from(request).into_query()
    }
}

impl<R> From< EmployeeRecordRequest<R> > for QuerySelection {
    fn from(request: EmployeeRecordRequest<R>) -> Self {
        Self {
            query: request.query,
            relation_selections: request.relation_selections,
            relation_filters: request.relation_filters,
            child_enhancements: request.child_enhancements,
            query_options: request.query_options,
        }
    }
}


impl<'a, C> crate::request_support::AuditedSave<'a, C> for teaql_core::Audited<crate::EmployeeRecord> 
where C: crate::request_support::TeaqlRepositoryProvider + ?Sized + 'a
{
    type Error = crate::TeaqlDataServiceError<C::EmployeeRecordRepository<'a>>;
    fn save(self, ctx: &'a C) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<teaql_runtime::GraphNode, Self::Error>> + '_>> {
        Box::pin(async move {
            teaql_runtime::save_audited_ledger_entity(self, ctx.user_context())
                .await
                .map_err(DataServiceError::Runtime)
        })
    }
}

impl<R: teaql_core::Entity> crate::PurposedQuery<EmployeeRecordRequest<R>> {
    pub fn new_entity<C>(&self, ctx: &C) -> crate::EmployeeRecord
    where
        C: crate::TeaqlRuntime + ?Sized,
    {
        crate::EmployeeRecord::runtime_new(ctx.user_context().entity_root())
    }

    fn into_inner_with_trace(mut self) -> EmployeeRecordRequest<R> {
        self.inner.query.trace_chain.push(teaql_core::TraceNode::new(
            self.inner.query.entity.clone(),
            None,
            self.purpose,
        ));
        self.inner
    }

    pub async fn execute_for_page<'a, C>(
        self,
        ctx: &'a C,
        offset: u64,
        limit: u64,
    ) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::EmployeeRecordRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_page(ctx, offset, limit).await
    }

    pub async fn execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, crate::request_support::TeaqlDataServiceError<C::EmployeeRecordRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_exists(ctx).await
    }

    pub async fn execute_for_list<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::EmployeeRecordRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_list(ctx).await
    }

    /// Execute query in streaming mode (chunked).
    /// Returns a Vec of StreamChunk, each containing up to chunk_size rows.
    /// Set chunk size via .stream(chunk_size) or .stream_default() on the query.
    pub async fn execute_for_stream<'a, C>(self, ctx: &'a C) -> Result<Vec<teaql_data_service::StreamChunk>, crate::request_support::TeaqlDataServiceError<C::EmployeeRecordRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_stream(ctx).await
    }

    pub async fn execute_for_first<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::EmployeeRecordRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_first(ctx).await
    }

    pub async fn execute_for_one<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::EmployeeRecordRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_one(ctx).await
    }


    pub async fn execute_for_records<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::EmployeeRecordRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_records(ctx).await
    }

    pub async fn execute_for_record<'a, C>(self, ctx: &'a C) -> Result<Option<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::EmployeeRecordRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_record(ctx).await
    }

    pub async fn execute_for_count<'a, C>(self, ctx: &'a C) -> Result<u64, crate::request_support::TeaqlDataServiceError<C::EmployeeRecordRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_count(ctx).await
    }
}
