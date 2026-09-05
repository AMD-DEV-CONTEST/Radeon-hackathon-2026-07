use std::marker::PhantomData;

use serde_json::Value as JsonValue;
use teaql_core::{Aggregate, AggregateFunction, EntityDescriptor, Expr, Record, SelectQuery, SmartList};
use teaql_runtime::{DataServiceError, RuntimeError};

use crate::request_support::*;

impl EntityReference for crate::Payroll {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(&self)
    }
}

impl EntityReference for &crate::Payroll {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(self)
    }
}

// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/payroll
#[derive(Debug)]
pub struct PayrollRequest<R = crate::Payroll> {
    query: SelectQuery,
    relation_selections: Vec<RelationSelection>,
    relation_filters: Vec<RelationFilter>,
    child_enhancements: Vec<QuerySelection>,
    query_options: QueryOptions,
    marker: PhantomData<R>,
}

impl<R> Clone for PayrollRequest<R> {
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

impl<R> PayrollRequest<R> {
    pub(crate) fn new() -> Self {
        Self {
            query: SelectQuery::new("Payroll")
                .project("id")
                .project("version"),
            relation_selections: Vec::new(),
            relation_filters: Vec::new(),
            child_enhancements: Vec::new(),
            query_options: QueryOptions::default(),
            marker: PhantomData,
        }
    }

    pub fn return_type<T>(self) -> PayrollRequest<T> {
        PayrollRequest {
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::PayrollRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
        R: teaql_core::Entity,
    {
        let repository = ctx
            .payroll_repository()
            .map_err(|err| DataServiceError::Runtime(RuntimeError::Graph(err.to_string())))?;
        let query_options = self.query_options.clone();
        let relation_aggregates = runtime_relation_aggregates(&query_options);
        let query = apply_runtime_metadata(self.query, &query_options, &self.child_enhancements);
        let mut rows = repository.fetch_enhanced_entities_with_relation_aggregates::<R>(
            &query,
            &relation_aggregates,
        ).await?;
        let facets = execute_facets(ctx, &query, &query_options)
            .await
            .map_err(DataServiceError::Runtime)?;
        attach_facets(&mut rows, facets);
        Ok(rows)
    }

    pub(crate) async fn _execute_for_stream<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<Vec<teaql_data_service::StreamChunk>, TeaqlDataServiceError<C::PayrollRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .payroll_repository()
            .map_err(|err| DataServiceError::Runtime(RuntimeError::Graph(err.to_string())))?;
        let query_options = self.query_options.clone();
        let query = apply_runtime_metadata(self.query, &query_options, &self.child_enhancements);
        let chunks = repository.fetch_stream(&query)
            .await?;
        Ok(chunks)
    }

    pub(crate) async fn _execute_for_first<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<Option<R>, TeaqlDataServiceError<C::PayrollRepository<'a>>>
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::PayrollRepository<'a>>>
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::PayrollRepository<'a>>>
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
    ) -> Result<u64, TeaqlDataServiceError<C::PayrollRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .payroll_repository()
            .map_err(|err| DataServiceError::Runtime(RuntimeError::Graph(err.to_string())))?;
        let mut query = self.query;
        query.projection.clear();
        query.expr_projection.clear();
        query.order_by.clear();
        query.slice = None;
        query.relations.clear();
        query = query.count(COUNT_ALIAS);
        let rows = repository.fetch_all(&query).await?;
        rows.first()
            .and_then(|row| row.get(COUNT_ALIAS))
            .and_then(teaql_core::Value::try_u64)
            .ok_or_else(|| DataServiceError::Runtime(RuntimeError::Graph(format!("count result for Payroll is missing or not numeric"))))
    }

    pub(crate) async fn _execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, TeaqlDataServiceError<C::PayrollRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .payroll_repository()
            .map_err(|err| DataServiceError::Runtime(RuntimeError::Graph(err.to_string())))?;
        let mut query = self.query.limit(1);
        query.relations.clear();
        let rows = repository.fetch_all(&query).await?;
        Ok(!rows.is_empty())
    }

    pub(crate) async fn _execute_for_records<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<SmartList<Record>, TeaqlDataServiceError<C::PayrollRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .payroll_repository()
            .map_err(|err| DataServiceError::Runtime(RuntimeError::Graph(err.to_string())))?;
        let query_options = self.query_options.clone();
        let outer_query = self.query.clone();
        let relation_aggregates = runtime_relation_aggregates(&query_options);
        let query = apply_runtime_metadata(self.query, &query_options, &self.child_enhancements);
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
    ) -> Result<Option<Record>, TeaqlDataServiceError<C::PayrollRepository<'a>>>
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
            "pay_period_start" => Some("pay_period_start"),
            "pay_period_end" => Some("pay_period_end"),
            "base_salary" => Some("base_salary"),
            "overtime_pay" => Some("overtime_pay"),
            "bonus" => Some("bonus"),
            "deductions" => Some("deductions"),
            "net_pay" => Some("net_pay"),
            "payment_date" => Some("payment_date"),
            "create_time" => Some("create_time"),
            "update_time" => Some("update_time"),
            "version" => Some("version"),
            "staff" | "staff_id" => Some("staff_id"),
            _ => None,
        }
    }

    fn apply_dynamic_json_chain_filter(self, head: &str, tail: &str, value: &JsonValue) -> Self {
        let _ = (tail, value);
        match head {
            "staff" => {
                self.with_staff_matching(
                    crate::Q::staffs_minimal()
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
        self.query = self.query.project("pay_period_start");
        self.query = self.query.project("pay_period_end");
        self.query = self.query.project("base_salary");
        self.query = self.query.project("overtime_pay");
        self.query = self.query.project("bonus");
        self.query = self.query.project("deductions");
        self.query = self.query.project("net_pay");
        self.query = self.query.project("payment_date");
        self.query = self.query.project("create_time");
        self.query = self.query.project("update_time");
        self.query = self.query.project("version");
        self.query = self.query.project("staff_id");
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
        request = request.select_staff();
        request
    }

    pub fn select_children(self) -> Self {
        self.select_all()
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


    pub fn select_pay_period_start(mut self) -> Self {
        self.query = self.query.project("pay_period_start");
        self
    }

    pub fn project_pay_period_start(self) -> Self {
        self.select_pay_period_start()
    }

    pub fn select_pay_period_start_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_pay_period_start_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_pay_period_start_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("pay_period_start", raw_sql_segment));
        self
    }

    pub fn group_by_pay_period_start(self) -> Self {
        self.group_by("pay_period_start")
    }

    pub fn group_by_pay_period_start_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("pay_period_start");
        request.query = request
            .query
            .project_expr(alias, Expr::column("pay_period_start"));
        request
    }

    pub fn group_by_pay_period_start_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("pay_period_start")
            .aggregate_with_function("pay_period_start", alias, function)
    }

    pub fn count_pay_period_start(self) -> Self {
        self.count_pay_period_start_as("pay_period_start_count")
    }

    pub fn count_pay_period_start_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("pay_period_start", alias)
    }

    pub fn sum_pay_period_start(self) -> Self {
        self.sum_pay_period_start_as("sum_pay_period_start")
    }

    pub fn sum_pay_period_start_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("pay_period_start", alias)
    }

    pub fn avg_pay_period_start(self) -> Self {
        self.avg_pay_period_start_as("avg_pay_period_start")
    }

    pub fn avg_pay_period_start_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("pay_period_start", alias)
    }

    pub fn min_pay_period_start(self) -> Self {
        self.min_pay_period_start_as("min_pay_period_start")
    }

    pub fn min_pay_period_start_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("pay_period_start", alias)
    }

    pub fn max_pay_period_start(self) -> Self {
        self.max_pay_period_start_as("max_pay_period_start")
    }

    pub fn max_pay_period_start_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("pay_period_start", alias)
    }

    pub fn unselect_pay_period_start(mut self) -> Self {
        self.query.projection.retain(|field| field != "pay_period_start");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "pay_period_start");
        self
    }


    pub fn with_pay_period_start(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "pay_period_start",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_pay_period_start_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "pay_period_start",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_pay_period_start_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("pay_period_start", value));
        self
    }



    pub fn with_pay_period_start_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("pay_period_start", value));
        self
    }

    pub fn with_pay_period_start_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("pay_period_start", value));
        self
    }

    pub fn with_pay_period_start_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("pay_period_start", value));
        self
    }

    pub fn with_pay_period_start_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("pay_period_start", value));
        self
    }

    pub fn with_pay_period_start_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("pay_period_start", value));
        self
    }

    pub fn with_pay_period_start_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("pay_period_start", lower, upper));
        self
    }

    pub fn with_pay_period_start_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "pay_period_start",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_pay_period_start_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "pay_period_start",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_pay_period_start_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "pay_period_start",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_pay_period_start_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("pay_period_start", value));
        self
    }

    pub fn with_pay_period_start_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("pay_period_start", value));
        self
    }

    pub fn with_pay_period_start_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("pay_period_start"));
        self
    }



    pub fn with_pay_period_start_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("pay_period_start"));
        self
    }


    pub fn order_by_pay_period_start_asc(mut self) -> Self {
        self.query = self.query.order_asc("pay_period_start");
        self
    }

    pub fn order_by_pay_period_start_desc(mut self) -> Self {
        self.query = self.query.order_desc("pay_period_start");
        self
    }

    pub fn order_by_pay_period_start_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("pay_period_start");
        self
    }

    pub fn order_by_pay_period_start_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("pay_period_start");
        self
    }


    pub fn select_pay_period_end(mut self) -> Self {
        self.query = self.query.project("pay_period_end");
        self
    }

    pub fn project_pay_period_end(self) -> Self {
        self.select_pay_period_end()
    }

    pub fn select_pay_period_end_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_pay_period_end_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_pay_period_end_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("pay_period_end", raw_sql_segment));
        self
    }

    pub fn group_by_pay_period_end(self) -> Self {
        self.group_by("pay_period_end")
    }

    pub fn group_by_pay_period_end_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("pay_period_end");
        request.query = request
            .query
            .project_expr(alias, Expr::column("pay_period_end"));
        request
    }

    pub fn group_by_pay_period_end_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("pay_period_end")
            .aggregate_with_function("pay_period_end", alias, function)
    }

    pub fn count_pay_period_end(self) -> Self {
        self.count_pay_period_end_as("pay_period_end_count")
    }

    pub fn count_pay_period_end_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("pay_period_end", alias)
    }

    pub fn sum_pay_period_end(self) -> Self {
        self.sum_pay_period_end_as("sum_pay_period_end")
    }

    pub fn sum_pay_period_end_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("pay_period_end", alias)
    }

    pub fn avg_pay_period_end(self) -> Self {
        self.avg_pay_period_end_as("avg_pay_period_end")
    }

    pub fn avg_pay_period_end_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("pay_period_end", alias)
    }

    pub fn min_pay_period_end(self) -> Self {
        self.min_pay_period_end_as("min_pay_period_end")
    }

    pub fn min_pay_period_end_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("pay_period_end", alias)
    }

    pub fn max_pay_period_end(self) -> Self {
        self.max_pay_period_end_as("max_pay_period_end")
    }

    pub fn max_pay_period_end_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("pay_period_end", alias)
    }

    pub fn unselect_pay_period_end(mut self) -> Self {
        self.query.projection.retain(|field| field != "pay_period_end");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "pay_period_end");
        self
    }


    pub fn with_pay_period_end(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "pay_period_end",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_pay_period_end_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "pay_period_end",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_pay_period_end_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("pay_period_end", value));
        self
    }



    pub fn with_pay_period_end_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("pay_period_end", value));
        self
    }

    pub fn with_pay_period_end_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("pay_period_end", value));
        self
    }

    pub fn with_pay_period_end_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("pay_period_end", value));
        self
    }

    pub fn with_pay_period_end_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("pay_period_end", value));
        self
    }

    pub fn with_pay_period_end_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("pay_period_end", value));
        self
    }

    pub fn with_pay_period_end_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("pay_period_end", lower, upper));
        self
    }

    pub fn with_pay_period_end_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "pay_period_end",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_pay_period_end_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "pay_period_end",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_pay_period_end_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "pay_period_end",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_pay_period_end_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("pay_period_end", value));
        self
    }

    pub fn with_pay_period_end_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("pay_period_end", value));
        self
    }

    pub fn with_pay_period_end_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("pay_period_end"));
        self
    }



    pub fn with_pay_period_end_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("pay_period_end"));
        self
    }


    pub fn order_by_pay_period_end_asc(mut self) -> Self {
        self.query = self.query.order_asc("pay_period_end");
        self
    }

    pub fn order_by_pay_period_end_desc(mut self) -> Self {
        self.query = self.query.order_desc("pay_period_end");
        self
    }

    pub fn order_by_pay_period_end_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("pay_period_end");
        self
    }

    pub fn order_by_pay_period_end_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("pay_period_end");
        self
    }


    pub fn select_base_salary(mut self) -> Self {
        self.query = self.query.project("base_salary");
        self
    }

    pub fn project_base_salary(self) -> Self {
        self.select_base_salary()
    }

    pub fn select_base_salary_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_base_salary_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_base_salary_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("base_salary", raw_sql_segment));
        self
    }

    pub fn select_base_salary_with_function(self, function: AggregateFunction) -> Self {
        self.select_base_salary_as_with_function("base_salary", function)
    }

    pub fn select_base_salary_as_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.aggregate_with_function("base_salary", alias, function)
    }

    pub fn group_by_base_salary(self) -> Self {
        self.group_by("base_salary")
    }

    pub fn group_by_base_salary_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("base_salary");
        request.query = request
            .query
            .project_expr(alias, Expr::column("base_salary"));
        request
    }

    pub fn group_by_base_salary_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("base_salary")
            .aggregate_with_function("base_salary", alias, function)
    }

    pub fn count_base_salary(self) -> Self {
        self.count_base_salary_as("base_salary_count")
    }

    pub fn count_base_salary_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("base_salary", alias)
    }

    pub fn sum_base_salary(self) -> Self {
        self.sum_base_salary_as("sum_base_salary")
    }

    pub fn sum_base_salary_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("base_salary", alias)
    }

    pub fn avg_base_salary(self) -> Self {
        self.avg_base_salary_as("avg_base_salary")
    }

    pub fn avg_base_salary_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("base_salary", alias)
    }

    pub fn min_base_salary(self) -> Self {
        self.min_base_salary_as("min_base_salary")
    }

    pub fn min_base_salary_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("base_salary", alias)
    }

    pub fn max_base_salary(self) -> Self {
        self.max_base_salary_as("max_base_salary")
    }

    pub fn max_base_salary_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("base_salary", alias)
    }

    pub fn standard_deviation_base_salary(self) -> Self {
        self.standard_deviation_base_salary_as("stdDev_base_salary")
    }

    pub fn standard_deviation_base_salary_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev("base_salary", alias)
    }

    pub fn square_root_of_population_standard_deviation_base_salary(self) -> Self {
        self.square_root_of_population_standard_deviation_base_salary_as("stdDevPop_base_salary")
    }

    pub fn square_root_of_population_standard_deviation_base_salary_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev_pop("base_salary", alias)
    }

    pub fn sample_variance_base_salary(self) -> Self {
        self.sample_variance_base_salary_as("varSamp_base_salary")
    }

    pub fn sample_variance_base_salary_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_samp("base_salary", alias)
    }

    pub fn sample_population_variance_base_salary(self) -> Self {
        self.sample_population_variance_base_salary_as("varPop_base_salary")
    }

    pub fn sample_population_variance_base_salary_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_pop("base_salary", alias)
    }

    pub fn unselect_base_salary(mut self) -> Self {
        self.query.projection.retain(|field| field != "base_salary");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "base_salary");
        self
    }


    pub fn with_base_salary(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "base_salary",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_base_salary_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "base_salary",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_base_salary_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("base_salary", value));
        self
    }



    pub fn with_base_salary_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("base_salary", value));
        self
    }

    pub fn with_base_salary_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("base_salary", value));
        self
    }

    pub fn with_base_salary_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("base_salary", value));
        self
    }

    pub fn with_base_salary_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("base_salary", value));
        self
    }

    pub fn with_base_salary_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("base_salary", value));
        self
    }

    pub fn with_base_salary_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("base_salary", lower, upper));
        self
    }

    pub fn with_base_salary_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "base_salary",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_base_salary_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "base_salary",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_base_salary_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "base_salary",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_base_salary_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("base_salary", value));
        self
    }

    pub fn with_base_salary_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("base_salary", value));
        self
    }

    pub fn with_base_salary_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("base_salary"));
        self
    }



    pub fn with_base_salary_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("base_salary"));
        self
    }


    pub fn order_by_base_salary_asc(mut self) -> Self {
        self.query = self.query.order_asc("base_salary");
        self
    }

    pub fn order_by_base_salary_desc(mut self) -> Self {
        self.query = self.query.order_desc("base_salary");
        self
    }

    pub fn order_by_base_salary_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("base_salary");
        self
    }

    pub fn order_by_base_salary_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("base_salary");
        self
    }


    pub fn select_overtime_pay(mut self) -> Self {
        self.query = self.query.project("overtime_pay");
        self
    }

    pub fn project_overtime_pay(self) -> Self {
        self.select_overtime_pay()
    }

    pub fn select_overtime_pay_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_overtime_pay_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_overtime_pay_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("overtime_pay", raw_sql_segment));
        self
    }

    pub fn select_overtime_pay_with_function(self, function: AggregateFunction) -> Self {
        self.select_overtime_pay_as_with_function("overtime_pay", function)
    }

    pub fn select_overtime_pay_as_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.aggregate_with_function("overtime_pay", alias, function)
    }

    pub fn group_by_overtime_pay(self) -> Self {
        self.group_by("overtime_pay")
    }

    pub fn group_by_overtime_pay_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("overtime_pay");
        request.query = request
            .query
            .project_expr(alias, Expr::column("overtime_pay"));
        request
    }

    pub fn group_by_overtime_pay_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("overtime_pay")
            .aggregate_with_function("overtime_pay", alias, function)
    }

    pub fn count_overtime_pay(self) -> Self {
        self.count_overtime_pay_as("overtime_pay_count")
    }

    pub fn count_overtime_pay_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("overtime_pay", alias)
    }

    pub fn sum_overtime_pay(self) -> Self {
        self.sum_overtime_pay_as("sum_overtime_pay")
    }

    pub fn sum_overtime_pay_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("overtime_pay", alias)
    }

    pub fn avg_overtime_pay(self) -> Self {
        self.avg_overtime_pay_as("avg_overtime_pay")
    }

    pub fn avg_overtime_pay_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("overtime_pay", alias)
    }

    pub fn min_overtime_pay(self) -> Self {
        self.min_overtime_pay_as("min_overtime_pay")
    }

    pub fn min_overtime_pay_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("overtime_pay", alias)
    }

    pub fn max_overtime_pay(self) -> Self {
        self.max_overtime_pay_as("max_overtime_pay")
    }

    pub fn max_overtime_pay_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("overtime_pay", alias)
    }

    pub fn standard_deviation_overtime_pay(self) -> Self {
        self.standard_deviation_overtime_pay_as("stdDev_overtime_pay")
    }

    pub fn standard_deviation_overtime_pay_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev("overtime_pay", alias)
    }

    pub fn square_root_of_population_standard_deviation_overtime_pay(self) -> Self {
        self.square_root_of_population_standard_deviation_overtime_pay_as("stdDevPop_overtime_pay")
    }

    pub fn square_root_of_population_standard_deviation_overtime_pay_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev_pop("overtime_pay", alias)
    }

    pub fn sample_variance_overtime_pay(self) -> Self {
        self.sample_variance_overtime_pay_as("varSamp_overtime_pay")
    }

    pub fn sample_variance_overtime_pay_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_samp("overtime_pay", alias)
    }

    pub fn sample_population_variance_overtime_pay(self) -> Self {
        self.sample_population_variance_overtime_pay_as("varPop_overtime_pay")
    }

    pub fn sample_population_variance_overtime_pay_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_pop("overtime_pay", alias)
    }

    pub fn unselect_overtime_pay(mut self) -> Self {
        self.query.projection.retain(|field| field != "overtime_pay");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "overtime_pay");
        self
    }


    pub fn with_overtime_pay(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "overtime_pay",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_overtime_pay_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "overtime_pay",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_overtime_pay_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("overtime_pay", value));
        self
    }



    pub fn with_overtime_pay_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("overtime_pay", value));
        self
    }

    pub fn with_overtime_pay_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("overtime_pay", value));
        self
    }

    pub fn with_overtime_pay_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("overtime_pay", value));
        self
    }

    pub fn with_overtime_pay_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("overtime_pay", value));
        self
    }

    pub fn with_overtime_pay_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("overtime_pay", value));
        self
    }

    pub fn with_overtime_pay_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("overtime_pay", lower, upper));
        self
    }

    pub fn with_overtime_pay_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "overtime_pay",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_overtime_pay_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "overtime_pay",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_overtime_pay_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "overtime_pay",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_overtime_pay_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("overtime_pay", value));
        self
    }

    pub fn with_overtime_pay_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("overtime_pay", value));
        self
    }

    pub fn with_overtime_pay_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("overtime_pay"));
        self
    }



    pub fn with_overtime_pay_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("overtime_pay"));
        self
    }


    pub fn order_by_overtime_pay_asc(mut self) -> Self {
        self.query = self.query.order_asc("overtime_pay");
        self
    }

    pub fn order_by_overtime_pay_desc(mut self) -> Self {
        self.query = self.query.order_desc("overtime_pay");
        self
    }

    pub fn order_by_overtime_pay_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("overtime_pay");
        self
    }

    pub fn order_by_overtime_pay_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("overtime_pay");
        self
    }


    pub fn select_bonus(mut self) -> Self {
        self.query = self.query.project("bonus");
        self
    }

    pub fn project_bonus(self) -> Self {
        self.select_bonus()
    }

    pub fn select_bonus_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_bonus_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_bonus_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("bonus", raw_sql_segment));
        self
    }

    pub fn select_bonus_with_function(self, function: AggregateFunction) -> Self {
        self.select_bonus_as_with_function("bonus", function)
    }

    pub fn select_bonus_as_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.aggregate_with_function("bonus", alias, function)
    }

    pub fn group_by_bonus(self) -> Self {
        self.group_by("bonus")
    }

    pub fn group_by_bonus_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("bonus");
        request.query = request
            .query
            .project_expr(alias, Expr::column("bonus"));
        request
    }

    pub fn group_by_bonus_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("bonus")
            .aggregate_with_function("bonus", alias, function)
    }

    pub fn count_bonus(self) -> Self {
        self.count_bonus_as("bonus_count")
    }

    pub fn count_bonus_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("bonus", alias)
    }

    pub fn sum_bonus(self) -> Self {
        self.sum_bonus_as("sum_bonus")
    }

    pub fn sum_bonus_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("bonus", alias)
    }

    pub fn avg_bonus(self) -> Self {
        self.avg_bonus_as("avg_bonus")
    }

    pub fn avg_bonus_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("bonus", alias)
    }

    pub fn min_bonus(self) -> Self {
        self.min_bonus_as("min_bonus")
    }

    pub fn min_bonus_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("bonus", alias)
    }

    pub fn max_bonus(self) -> Self {
        self.max_bonus_as("max_bonus")
    }

    pub fn max_bonus_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("bonus", alias)
    }

    pub fn standard_deviation_bonus(self) -> Self {
        self.standard_deviation_bonus_as("stdDev_bonus")
    }

    pub fn standard_deviation_bonus_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev("bonus", alias)
    }

    pub fn square_root_of_population_standard_deviation_bonus(self) -> Self {
        self.square_root_of_population_standard_deviation_bonus_as("stdDevPop_bonus")
    }

    pub fn square_root_of_population_standard_deviation_bonus_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev_pop("bonus", alias)
    }

    pub fn sample_variance_bonus(self) -> Self {
        self.sample_variance_bonus_as("varSamp_bonus")
    }

    pub fn sample_variance_bonus_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_samp("bonus", alias)
    }

    pub fn sample_population_variance_bonus(self) -> Self {
        self.sample_population_variance_bonus_as("varPop_bonus")
    }

    pub fn sample_population_variance_bonus_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_pop("bonus", alias)
    }

    pub fn unselect_bonus(mut self) -> Self {
        self.query.projection.retain(|field| field != "bonus");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "bonus");
        self
    }


    pub fn with_bonus(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "bonus",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_bonus_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "bonus",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_bonus_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("bonus", value));
        self
    }



    pub fn with_bonus_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("bonus", value));
        self
    }

    pub fn with_bonus_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("bonus", value));
        self
    }

    pub fn with_bonus_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("bonus", value));
        self
    }

    pub fn with_bonus_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("bonus", value));
        self
    }

    pub fn with_bonus_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("bonus", value));
        self
    }

    pub fn with_bonus_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("bonus", lower, upper));
        self
    }

    pub fn with_bonus_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "bonus",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_bonus_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "bonus",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_bonus_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "bonus",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_bonus_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("bonus", value));
        self
    }

    pub fn with_bonus_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("bonus", value));
        self
    }

    pub fn with_bonus_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("bonus"));
        self
    }



    pub fn with_bonus_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("bonus"));
        self
    }


    pub fn order_by_bonus_asc(mut self) -> Self {
        self.query = self.query.order_asc("bonus");
        self
    }

    pub fn order_by_bonus_desc(mut self) -> Self {
        self.query = self.query.order_desc("bonus");
        self
    }

    pub fn order_by_bonus_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("bonus");
        self
    }

    pub fn order_by_bonus_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("bonus");
        self
    }


    pub fn select_deductions(mut self) -> Self {
        self.query = self.query.project("deductions");
        self
    }

    pub fn project_deductions(self) -> Self {
        self.select_deductions()
    }

    pub fn select_deductions_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_deductions_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_deductions_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("deductions", raw_sql_segment));
        self
    }

    pub fn select_deductions_with_function(self, function: AggregateFunction) -> Self {
        self.select_deductions_as_with_function("deductions", function)
    }

    pub fn select_deductions_as_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.aggregate_with_function("deductions", alias, function)
    }

    pub fn group_by_deductions(self) -> Self {
        self.group_by("deductions")
    }

    pub fn group_by_deductions_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("deductions");
        request.query = request
            .query
            .project_expr(alias, Expr::column("deductions"));
        request
    }

    pub fn group_by_deductions_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("deductions")
            .aggregate_with_function("deductions", alias, function)
    }

    pub fn count_deductions(self) -> Self {
        self.count_deductions_as("deductions_count")
    }

    pub fn count_deductions_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("deductions", alias)
    }

    pub fn sum_deductions(self) -> Self {
        self.sum_deductions_as("sum_deductions")
    }

    pub fn sum_deductions_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("deductions", alias)
    }

    pub fn avg_deductions(self) -> Self {
        self.avg_deductions_as("avg_deductions")
    }

    pub fn avg_deductions_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("deductions", alias)
    }

    pub fn min_deductions(self) -> Self {
        self.min_deductions_as("min_deductions")
    }

    pub fn min_deductions_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("deductions", alias)
    }

    pub fn max_deductions(self) -> Self {
        self.max_deductions_as("max_deductions")
    }

    pub fn max_deductions_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("deductions", alias)
    }

    pub fn standard_deviation_deductions(self) -> Self {
        self.standard_deviation_deductions_as("stdDev_deductions")
    }

    pub fn standard_deviation_deductions_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev("deductions", alias)
    }

    pub fn square_root_of_population_standard_deviation_deductions(self) -> Self {
        self.square_root_of_population_standard_deviation_deductions_as("stdDevPop_deductions")
    }

    pub fn square_root_of_population_standard_deviation_deductions_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev_pop("deductions", alias)
    }

    pub fn sample_variance_deductions(self) -> Self {
        self.sample_variance_deductions_as("varSamp_deductions")
    }

    pub fn sample_variance_deductions_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_samp("deductions", alias)
    }

    pub fn sample_population_variance_deductions(self) -> Self {
        self.sample_population_variance_deductions_as("varPop_deductions")
    }

    pub fn sample_population_variance_deductions_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_pop("deductions", alias)
    }

    pub fn unselect_deductions(mut self) -> Self {
        self.query.projection.retain(|field| field != "deductions");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "deductions");
        self
    }


    pub fn with_deductions(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "deductions",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_deductions_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "deductions",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_deductions_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("deductions", value));
        self
    }



    pub fn with_deductions_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("deductions", value));
        self
    }

    pub fn with_deductions_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("deductions", value));
        self
    }

    pub fn with_deductions_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("deductions", value));
        self
    }

    pub fn with_deductions_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("deductions", value));
        self
    }

    pub fn with_deductions_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("deductions", value));
        self
    }

    pub fn with_deductions_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("deductions", lower, upper));
        self
    }

    pub fn with_deductions_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "deductions",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_deductions_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "deductions",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_deductions_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "deductions",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_deductions_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("deductions", value));
        self
    }

    pub fn with_deductions_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("deductions", value));
        self
    }

    pub fn with_deductions_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("deductions"));
        self
    }



    pub fn with_deductions_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("deductions"));
        self
    }


    pub fn order_by_deductions_asc(mut self) -> Self {
        self.query = self.query.order_asc("deductions");
        self
    }

    pub fn order_by_deductions_desc(mut self) -> Self {
        self.query = self.query.order_desc("deductions");
        self
    }

    pub fn order_by_deductions_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("deductions");
        self
    }

    pub fn order_by_deductions_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("deductions");
        self
    }


    pub fn select_net_pay(mut self) -> Self {
        self.query = self.query.project("net_pay");
        self
    }

    pub fn project_net_pay(self) -> Self {
        self.select_net_pay()
    }

    pub fn select_net_pay_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_net_pay_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_net_pay_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("net_pay", raw_sql_segment));
        self
    }

    pub fn select_net_pay_with_function(self, function: AggregateFunction) -> Self {
        self.select_net_pay_as_with_function("net_pay", function)
    }

    pub fn select_net_pay_as_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.aggregate_with_function("net_pay", alias, function)
    }

    pub fn group_by_net_pay(self) -> Self {
        self.group_by("net_pay")
    }

    pub fn group_by_net_pay_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("net_pay");
        request.query = request
            .query
            .project_expr(alias, Expr::column("net_pay"));
        request
    }

    pub fn group_by_net_pay_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("net_pay")
            .aggregate_with_function("net_pay", alias, function)
    }

    pub fn count_net_pay(self) -> Self {
        self.count_net_pay_as("net_pay_count")
    }

    pub fn count_net_pay_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("net_pay", alias)
    }

    pub fn sum_net_pay(self) -> Self {
        self.sum_net_pay_as("sum_net_pay")
    }

    pub fn sum_net_pay_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("net_pay", alias)
    }

    pub fn avg_net_pay(self) -> Self {
        self.avg_net_pay_as("avg_net_pay")
    }

    pub fn avg_net_pay_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("net_pay", alias)
    }

    pub fn min_net_pay(self) -> Self {
        self.min_net_pay_as("min_net_pay")
    }

    pub fn min_net_pay_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("net_pay", alias)
    }

    pub fn max_net_pay(self) -> Self {
        self.max_net_pay_as("max_net_pay")
    }

    pub fn max_net_pay_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("net_pay", alias)
    }

    pub fn standard_deviation_net_pay(self) -> Self {
        self.standard_deviation_net_pay_as("stdDev_net_pay")
    }

    pub fn standard_deviation_net_pay_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev("net_pay", alias)
    }

    pub fn square_root_of_population_standard_deviation_net_pay(self) -> Self {
        self.square_root_of_population_standard_deviation_net_pay_as("stdDevPop_net_pay")
    }

    pub fn square_root_of_population_standard_deviation_net_pay_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev_pop("net_pay", alias)
    }

    pub fn sample_variance_net_pay(self) -> Self {
        self.sample_variance_net_pay_as("varSamp_net_pay")
    }

    pub fn sample_variance_net_pay_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_samp("net_pay", alias)
    }

    pub fn sample_population_variance_net_pay(self) -> Self {
        self.sample_population_variance_net_pay_as("varPop_net_pay")
    }

    pub fn sample_population_variance_net_pay_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_pop("net_pay", alias)
    }

    pub fn unselect_net_pay(mut self) -> Self {
        self.query.projection.retain(|field| field != "net_pay");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "net_pay");
        self
    }


    pub fn with_net_pay(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "net_pay",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_net_pay_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "net_pay",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_net_pay_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("net_pay", value));
        self
    }



    pub fn with_net_pay_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("net_pay", value));
        self
    }

    pub fn with_net_pay_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("net_pay", value));
        self
    }

    pub fn with_net_pay_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("net_pay", value));
        self
    }

    pub fn with_net_pay_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("net_pay", value));
        self
    }

    pub fn with_net_pay_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("net_pay", value));
        self
    }

    pub fn with_net_pay_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("net_pay", lower, upper));
        self
    }

    pub fn with_net_pay_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "net_pay",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_net_pay_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "net_pay",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_net_pay_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "net_pay",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_net_pay_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("net_pay", value));
        self
    }

    pub fn with_net_pay_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("net_pay", value));
        self
    }

    pub fn with_net_pay_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("net_pay"));
        self
    }



    pub fn with_net_pay_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("net_pay"));
        self
    }


    pub fn order_by_net_pay_asc(mut self) -> Self {
        self.query = self.query.order_asc("net_pay");
        self
    }

    pub fn order_by_net_pay_desc(mut self) -> Self {
        self.query = self.query.order_desc("net_pay");
        self
    }

    pub fn order_by_net_pay_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("net_pay");
        self
    }

    pub fn order_by_net_pay_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("net_pay");
        self
    }


    pub fn select_payment_date(mut self) -> Self {
        self.query = self.query.project("payment_date");
        self
    }

    pub fn project_payment_date(self) -> Self {
        self.select_payment_date()
    }

    pub fn select_payment_date_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_payment_date_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_payment_date_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("payment_date", raw_sql_segment));
        self
    }

    pub fn group_by_payment_date(self) -> Self {
        self.group_by("payment_date")
    }

    pub fn group_by_payment_date_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("payment_date");
        request.query = request
            .query
            .project_expr(alias, Expr::column("payment_date"));
        request
    }

    pub fn group_by_payment_date_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("payment_date")
            .aggregate_with_function("payment_date", alias, function)
    }

    pub fn count_payment_date(self) -> Self {
        self.count_payment_date_as("payment_date_count")
    }

    pub fn count_payment_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("payment_date", alias)
    }

    pub fn sum_payment_date(self) -> Self {
        self.sum_payment_date_as("sum_payment_date")
    }

    pub fn sum_payment_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("payment_date", alias)
    }

    pub fn avg_payment_date(self) -> Self {
        self.avg_payment_date_as("avg_payment_date")
    }

    pub fn avg_payment_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("payment_date", alias)
    }

    pub fn min_payment_date(self) -> Self {
        self.min_payment_date_as("min_payment_date")
    }

    pub fn min_payment_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("payment_date", alias)
    }

    pub fn max_payment_date(self) -> Self {
        self.max_payment_date_as("max_payment_date")
    }

    pub fn max_payment_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("payment_date", alias)
    }

    pub fn unselect_payment_date(mut self) -> Self {
        self.query.projection.retain(|field| field != "payment_date");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "payment_date");
        self
    }


    pub fn with_payment_date(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "payment_date",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_payment_date_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "payment_date",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_payment_date_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("payment_date", value));
        self
    }



    pub fn with_payment_date_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("payment_date", value));
        self
    }

    pub fn with_payment_date_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("payment_date", value));
        self
    }

    pub fn with_payment_date_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("payment_date", value));
        self
    }

    pub fn with_payment_date_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("payment_date", value));
        self
    }

    pub fn with_payment_date_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("payment_date", value));
        self
    }

    pub fn with_payment_date_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("payment_date", lower, upper));
        self
    }

    pub fn with_payment_date_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "payment_date",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_payment_date_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "payment_date",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_payment_date_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "payment_date",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_payment_date_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("payment_date", value));
        self
    }

    pub fn with_payment_date_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("payment_date", value));
        self
    }

    pub fn with_payment_date_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("payment_date"));
        self
    }



    pub fn with_payment_date_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("payment_date"));
        self
    }


    pub fn order_by_payment_date_asc(mut self) -> Self {
        self.query = self.query.order_asc("payment_date");
        self
    }

    pub fn order_by_payment_date_desc(mut self) -> Self {
        self.query = self.query.order_desc("payment_date");
        self
    }

    pub fn order_by_payment_date_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("payment_date");
        self
    }

    pub fn order_by_payment_date_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("payment_date");
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
    pub fn filter_by_staff(mut self, value: impl EntityReference) -> Self {
        self.query = self.query.and_filter(Expr::eq("staff_id", value.entity_id_value()));
        self
    }

    pub fn with_staff_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "staff_id",
            <crate::Staff as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("staff", selection));
        self
    }


    pub fn without_staff_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "staff_id",
            <crate::Staff as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("staff", selection));
        self
    }


    pub fn have_staff(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("staff_id"));
        self
    }

    pub fn have_no_staff(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("staff_id"));
        self
    }


    pub fn group_by_staff(self) -> Self {
        self.group_by("staff_id")
    }

    pub fn group_by_staff_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("staff_id");
        request.query = request
            .query
            .project_expr(alias, Expr::column("staff_id"));
        request
    }

    pub fn group_by_staff_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("staff_id")
            .aggregate_with_function("staff_id", alias, function)
    }

    pub fn group_by_staff_with(mut self, request: impl Into<QuerySelection>) -> Self {
        self.query = self.query.group_by("staff_id");
        self.query_options.object_group_bys.push(ObjectGroupBy::new(
            "staff",
            "staff_id",
            request,
        ));
        self
    }

    pub fn group_by_staff_with_details(self) -> Self {
        self.group_by_staff_with_details_from(crate::Q::staffs().unlimited())
    }

    pub fn group_by_staff_with_details_from(self, request: impl Into<QuerySelection>) -> Self {
        self.group_by_staff_with(request)
    }


    pub fn roll_up_to_staff(self) -> Self {
        self.roll_up_to_staff_with(crate::Q::staffs().unlimited())
    }

    pub fn roll_up_to_staff_with(self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.with_staff_matching(selection.clone())
            .group_by_staff_with(selection)
    }

    pub fn count_staff(self) -> Self {
        self.count_staff_as("staff_count")
    }

    pub fn count_staff_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("staff_id", alias)
    }

    pub fn unselect_staff(mut self) -> Self {
        self.query.projection.retain(|field| field != "staff_id");
        self.query.relations.retain(|relation| relation.name != "staff");
        self
    }
    pub fn select_staff(mut self) -> Self {
        self.query = self.query.relation("staff");
        self
    }

    pub fn select_staff_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("staff", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("staff", selection));
        self
}

    pub fn facet_by_staff_as(self, facet_name: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.facet_by_staff_as_with_options(facet_name, request, true)
    }

    pub fn facet_by_staff_as_with_options(
        mut self,
        facet_name: impl Into<String>,
        request: impl Into<QuerySelection>,
        include_all_facets: bool,
    ) -> Self {
        self.query_options.facets.push(FacetRequest::new(
            facet_name,
            "staff",
            request,
            include_all_facets,
        ));
        self
    }
}

impl<R> Default for PayrollRequest<R> {
    fn default() -> Self {
        Self::new()
    }
}

impl<R> From< PayrollRequest<R> > for SelectQuery {
    fn from(request: PayrollRequest<R>) -> Self {
        QuerySelection::from(request).into_query()
    }
}

impl<R> From< PayrollRequest<R> > for QuerySelection {
    fn from(request: PayrollRequest<R>) -> Self {
        Self {
            query: request.query,
            relation_selections: request.relation_selections,
            relation_filters: request.relation_filters,
            child_enhancements: request.child_enhancements,
            query_options: request.query_options,
        }
    }
}


impl<'a, C> crate::request_support::AuditedSave<'a, C> for teaql_core::Audited<crate::Payroll> 
where C: crate::request_support::TeaqlRepositoryProvider + ?Sized + 'a
{
    type Error = crate::TeaqlDataServiceError<C::PayrollRepository<'a>>;
    fn save(self, ctx: &'a C) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<teaql_runtime::GraphNode, Self::Error>> + '_>> {
        Box::pin(async move { self.into_entity().save(ctx).await })
    }
}

impl<R: teaql_core::Entity> crate::PurposedQuery<PayrollRequest<R>> {
    pub fn new_entity<C>(&self, ctx: &C) -> crate::Payroll
    where
        C: crate::TeaqlRuntime + ?Sized,
    {
        crate::Payroll::runtime_new(ctx.user_context().entity_root())
    }

    fn into_inner_with_trace(mut self) -> PayrollRequest<R> {
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
    ) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::PayrollRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_page(ctx, offset, limit).await
    }

    pub async fn execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, crate::request_support::TeaqlDataServiceError<C::PayrollRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_exists(ctx).await
    }

    pub async fn execute_for_list<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::PayrollRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_list(ctx).await
    }

    /// Execute query in streaming mode (chunked).
    /// Returns a Vec of StreamChunk, each containing up to chunk_size rows.
    /// Set chunk size via .stream(chunk_size) or .stream_default() on the query.
    pub async fn execute_for_stream<'a, C>(self, ctx: &'a C) -> Result<Vec<teaql_data_service::StreamChunk>, crate::request_support::TeaqlDataServiceError<C::PayrollRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_stream(ctx).await
    }

    pub async fn execute_for_first<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::PayrollRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_first(ctx).await
    }

    pub async fn execute_for_one<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::PayrollRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_one(ctx).await
    }


    pub async fn execute_for_records<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::PayrollRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_records(ctx).await
    }

    pub async fn execute_for_record<'a, C>(self, ctx: &'a C) -> Result<Option<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::PayrollRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_record(ctx).await
    }

    pub async fn execute_for_count<'a, C>(self, ctx: &'a C) -> Result<u64, crate::request_support::TeaqlDataServiceError<C::PayrollRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_count(ctx).await
    }
}
