use std::marker::PhantomData;

use serde_json::Value as JsonValue;
use teaql_core::{Aggregate, AggregateFunction, EntityDescriptor, Expr, Record, SelectQuery, SmartList};
use teaql_runtime::{DataServiceError, RuntimeError};

use crate::request_support::*;

impl EntityReference for crate::ActivityLog {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(&self)
    }
}

impl EntityReference for &crate::ActivityLog {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(self)
    }
}

// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/activity_log
#[derive(Debug)]
pub struct ActivityLogRequest<R = crate::ActivityLog> {
    query: SelectQuery,
    relation_selections: Vec<RelationSelection>,
    relation_filters: Vec<RelationFilter>,
    child_enhancements: Vec<QuerySelection>,
    query_options: QueryOptions,
    marker: PhantomData<R>,
}

impl<R> Clone for ActivityLogRequest<R> {
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

impl<R> ActivityLogRequest<R> {
    pub(crate) fn new() -> Self {
        Self {
            query: SelectQuery::new("ActivityLog")
                .project("id")
                .project("version"),
            relation_selections: Vec::new(),
            relation_filters: Vec::new(),
            child_enhancements: Vec::new(),
            query_options: QueryOptions::default(),
            marker: PhantomData,
        }
    }

    pub fn return_type<T>(self) -> ActivityLogRequest<T> {
        ActivityLogRequest {
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::ActivityLogRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
        R: teaql_core::Entity,
    {
        let repository = ctx
            .activity_log_repository()
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
    ) -> Result<Vec<teaql_data_service::StreamChunk>, TeaqlDataServiceError<C::ActivityLogRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .activity_log_repository()
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::ActivityLogRepository<'a>>>
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::ActivityLogRepository<'a>>>
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::ActivityLogRepository<'a>>>
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
    ) -> Result<u64, TeaqlDataServiceError<C::ActivityLogRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .activity_log_repository()
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
            .ok_or_else(|| DataServiceError::Runtime(RuntimeError::Graph(format!("count result for ActivityLog is missing or not numeric"))))
    }

    pub(crate) async fn _execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, TeaqlDataServiceError<C::ActivityLogRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .activity_log_repository()
            .map_err(|err| DataServiceError::Runtime(RuntimeError::Graph(err.to_string())))?;
        let mut query = self.query.limit(1);
        query.relations.clear();
        let rows = repository.fetch_all(&query).await?;
        Ok(!rows.is_empty())
    }

    pub(crate) async fn _execute_for_records<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<SmartList<Record>, TeaqlDataServiceError<C::ActivityLogRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .activity_log_repository()
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
    ) -> Result<Option<Record>, TeaqlDataServiceError<C::ActivityLogRepository<'a>>>
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
            "action" => Some("action"),
            "entity_type" => Some("entity_type"),
            "entity_id" => Some("entity_id"),
            "changes_json" => Some("changes_json"),
            "timestamp" => Some("timestamp"),
            "create_time" => Some("create_time"),
            "update_time" => Some("update_time"),
            "version" => Some("version"),
            "user" | "user_id" => Some("user_id"),
            _ => None,
        }
    }

    fn apply_dynamic_json_chain_filter(self, head: &str, tail: &str, value: &JsonValue) -> Self {
        let _ = (tail, value);
        match head {
            "user" => {
                self.with_user_matching(
                    crate::Q::users_minimal()
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
        self.query = self.query.project("action");
        self.query = self.query.project("entity_type");
        self.query = self.query.project("entity_id");
        self.query = self.query.project("changes_json");
        self.query = self.query.project("timestamp");
        self.query = self.query.project("create_time");
        self.query = self.query.project("update_time");
        self.query = self.query.project("version");
        self.query = self.query.project("user_id");
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
        request = request.select_user();
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


    pub fn select_action(mut self) -> Self {
        self.query = self.query.project("action");
        self
    }

    pub fn project_action(self) -> Self {
        self.select_action()
    }

    pub fn select_action_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_action_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_action_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("action", raw_sql_segment));
        self
    }

    pub fn group_by_action(self) -> Self {
        self.group_by("action")
    }

    pub fn group_by_action_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("action");
        request.query = request
            .query
            .project_expr(alias, Expr::column("action"));
        request
    }

    pub fn group_by_action_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("action")
            .aggregate_with_function("action", alias, function)
    }

    pub fn count_action(self) -> Self {
        self.count_action_as("action_count")
    }

    pub fn count_action_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("action", alias)
    }

    pub fn sum_action(self) -> Self {
        self.sum_action_as("sum_action")
    }

    pub fn sum_action_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("action", alias)
    }

    pub fn avg_action(self) -> Self {
        self.avg_action_as("avg_action")
    }

    pub fn avg_action_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("action", alias)
    }

    pub fn min_action(self) -> Self {
        self.min_action_as("min_action")
    }

    pub fn min_action_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("action", alias)
    }

    pub fn max_action(self) -> Self {
        self.max_action_as("max_action")
    }

    pub fn max_action_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("action", alias)
    }

    pub fn unselect_action(mut self) -> Self {
        self.query.projection.retain(|field| field != "action");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "action");
        self
    }


    pub fn with_action(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "action",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_action_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "action",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_action_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("action", value));
        self
    }



    pub fn with_action_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("action", value));
        self
    }

    pub fn with_action_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("action", value));
        self
    }

    pub fn with_action_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("action", value));
        self
    }

    pub fn with_action_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("action", value));
        self
    }

    pub fn with_action_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("action", value));
        self
    }

    pub fn with_action_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("action", lower, upper));
        self
    }

    pub fn with_action_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "action",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_action_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "action",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_action_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "action",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_action_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("action", value));
        self
    }

    pub fn with_action_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("action", value));
        self
    }

    pub fn with_action_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("action", value));
        self
    }

    pub fn with_action_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("action", value));
        self
    }

    pub fn with_action_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("action", value));
        self
    }

    pub fn with_action_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("action", value));
        self
    }

    pub fn with_action_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("action", value));
        self
    }
    pub fn with_action_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("action", value));
        self
    }

    pub fn with_action_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("action", value));
        self
    }

    pub fn with_action_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("action"));
        self
    }



    pub fn with_action_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("action"));
        self
    }


    pub fn order_by_action_asc(mut self) -> Self {
        self.query = self.query.order_asc("action");
        self
    }

    pub fn order_by_action_desc(mut self) -> Self {
        self.query = self.query.order_desc("action");
        self
    }

    pub fn order_by_action_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("action");
        self
    }

    pub fn order_by_action_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("action");
        self
    }


    pub fn select_entity_type(mut self) -> Self {
        self.query = self.query.project("entity_type");
        self
    }

    pub fn project_entity_type(self) -> Self {
        self.select_entity_type()
    }

    pub fn select_entity_type_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_entity_type_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_entity_type_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("entity_type", raw_sql_segment));
        self
    }

    pub fn group_by_entity_type(self) -> Self {
        self.group_by("entity_type")
    }

    pub fn group_by_entity_type_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("entity_type");
        request.query = request
            .query
            .project_expr(alias, Expr::column("entity_type"));
        request
    }

    pub fn group_by_entity_type_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("entity_type")
            .aggregate_with_function("entity_type", alias, function)
    }

    pub fn count_entity_type(self) -> Self {
        self.count_entity_type_as("entity_type_count")
    }

    pub fn count_entity_type_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("entity_type", alias)
    }

    pub fn sum_entity_type(self) -> Self {
        self.sum_entity_type_as("sum_entity_type")
    }

    pub fn sum_entity_type_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("entity_type", alias)
    }

    pub fn avg_entity_type(self) -> Self {
        self.avg_entity_type_as("avg_entity_type")
    }

    pub fn avg_entity_type_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("entity_type", alias)
    }

    pub fn min_entity_type(self) -> Self {
        self.min_entity_type_as("min_entity_type")
    }

    pub fn min_entity_type_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("entity_type", alias)
    }

    pub fn max_entity_type(self) -> Self {
        self.max_entity_type_as("max_entity_type")
    }

    pub fn max_entity_type_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("entity_type", alias)
    }

    pub fn unselect_entity_type(mut self) -> Self {
        self.query.projection.retain(|field| field != "entity_type");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "entity_type");
        self
    }


    pub fn with_entity_type(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "entity_type",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_entity_type_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "entity_type",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_entity_type_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("entity_type", value));
        self
    }



    pub fn with_entity_type_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("entity_type", value));
        self
    }

    pub fn with_entity_type_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("entity_type", value));
        self
    }

    pub fn with_entity_type_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("entity_type", value));
        self
    }

    pub fn with_entity_type_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("entity_type", value));
        self
    }

    pub fn with_entity_type_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("entity_type", value));
        self
    }

    pub fn with_entity_type_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("entity_type", lower, upper));
        self
    }

    pub fn with_entity_type_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "entity_type",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_entity_type_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "entity_type",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_entity_type_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "entity_type",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_entity_type_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("entity_type", value));
        self
    }

    pub fn with_entity_type_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("entity_type", value));
        self
    }

    pub fn with_entity_type_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("entity_type", value));
        self
    }

    pub fn with_entity_type_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("entity_type", value));
        self
    }

    pub fn with_entity_type_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("entity_type", value));
        self
    }

    pub fn with_entity_type_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("entity_type", value));
        self
    }

    pub fn with_entity_type_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("entity_type", value));
        self
    }
    pub fn with_entity_type_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("entity_type", value));
        self
    }

    pub fn with_entity_type_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("entity_type", value));
        self
    }

    pub fn with_entity_type_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("entity_type"));
        self
    }



    pub fn with_entity_type_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("entity_type"));
        self
    }


    pub fn order_by_entity_type_asc(mut self) -> Self {
        self.query = self.query.order_asc("entity_type");
        self
    }

    pub fn order_by_entity_type_desc(mut self) -> Self {
        self.query = self.query.order_desc("entity_type");
        self
    }

    pub fn order_by_entity_type_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("entity_type");
        self
    }

    pub fn order_by_entity_type_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("entity_type");
        self
    }


    pub fn select_entity_id(mut self) -> Self {
        self.query = self.query.project("entity_id");
        self
    }

    pub fn project_entity_id(self) -> Self {
        self.select_entity_id()
    }

    pub fn select_entity_id_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_entity_id_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_entity_id_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("entity_id", raw_sql_segment));
        self
    }

    pub fn select_entity_id_with_function(self, function: AggregateFunction) -> Self {
        self.select_entity_id_as_with_function("entity_id", function)
    }

    pub fn select_entity_id_as_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.aggregate_with_function("entity_id", alias, function)
    }

    pub fn group_by_entity_id(self) -> Self {
        self.group_by("entity_id")
    }

    pub fn group_by_entity_id_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("entity_id");
        request.query = request
            .query
            .project_expr(alias, Expr::column("entity_id"));
        request
    }

    pub fn group_by_entity_id_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("entity_id")
            .aggregate_with_function("entity_id", alias, function)
    }

    pub fn count_entity_id(self) -> Self {
        self.count_entity_id_as("entity_id_count")
    }

    pub fn count_entity_id_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("entity_id", alias)
    }

    pub fn sum_entity_id(self) -> Self {
        self.sum_entity_id_as("sum_entity_id")
    }

    pub fn sum_entity_id_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("entity_id", alias)
    }

    pub fn avg_entity_id(self) -> Self {
        self.avg_entity_id_as("avg_entity_id")
    }

    pub fn avg_entity_id_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("entity_id", alias)
    }

    pub fn min_entity_id(self) -> Self {
        self.min_entity_id_as("min_entity_id")
    }

    pub fn min_entity_id_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("entity_id", alias)
    }

    pub fn max_entity_id(self) -> Self {
        self.max_entity_id_as("max_entity_id")
    }

    pub fn max_entity_id_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("entity_id", alias)
    }

    pub fn standard_deviation_entity_id(self) -> Self {
        self.standard_deviation_entity_id_as("stdDev_entity_id")
    }

    pub fn standard_deviation_entity_id_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev("entity_id", alias)
    }

    pub fn square_root_of_population_standard_deviation_entity_id(self) -> Self {
        self.square_root_of_population_standard_deviation_entity_id_as("stdDevPop_entity_id")
    }

    pub fn square_root_of_population_standard_deviation_entity_id_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev_pop("entity_id", alias)
    }

    pub fn sample_variance_entity_id(self) -> Self {
        self.sample_variance_entity_id_as("varSamp_entity_id")
    }

    pub fn sample_variance_entity_id_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_samp("entity_id", alias)
    }

    pub fn sample_population_variance_entity_id(self) -> Self {
        self.sample_population_variance_entity_id_as("varPop_entity_id")
    }

    pub fn sample_population_variance_entity_id_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_pop("entity_id", alias)
    }

    pub fn unselect_entity_id(mut self) -> Self {
        self.query.projection.retain(|field| field != "entity_id");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "entity_id");
        self
    }


    pub fn with_entity_id(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "entity_id",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_entity_id_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "entity_id",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_entity_id_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("entity_id", value));
        self
    }



    pub fn with_entity_id_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("entity_id", value));
        self
    }

    pub fn with_entity_id_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("entity_id", value));
        self
    }

    pub fn with_entity_id_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("entity_id", value));
        self
    }

    pub fn with_entity_id_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("entity_id", value));
        self
    }

    pub fn with_entity_id_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("entity_id", value));
        self
    }

    pub fn with_entity_id_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("entity_id", lower, upper));
        self
    }

    pub fn with_entity_id_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "entity_id",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_entity_id_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "entity_id",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_entity_id_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "entity_id",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_entity_id_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("entity_id", value));
        self
    }

    pub fn with_entity_id_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("entity_id", value));
        self
    }

    pub fn with_entity_id_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("entity_id"));
        self
    }



    pub fn with_entity_id_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("entity_id"));
        self
    }


    pub fn order_by_entity_id_asc(mut self) -> Self {
        self.query = self.query.order_asc("entity_id");
        self
    }

    pub fn order_by_entity_id_desc(mut self) -> Self {
        self.query = self.query.order_desc("entity_id");
        self
    }

    pub fn order_by_entity_id_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("entity_id");
        self
    }

    pub fn order_by_entity_id_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("entity_id");
        self
    }


    pub fn select_changes_json(mut self) -> Self {
        self.query = self.query.project("changes_json");
        self
    }

    pub fn project_changes_json(self) -> Self {
        self.select_changes_json()
    }

    pub fn select_changes_json_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_changes_json_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_changes_json_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("changes_json", raw_sql_segment));
        self
    }

    pub fn group_by_changes_json(self) -> Self {
        self.group_by("changes_json")
    }

    pub fn group_by_changes_json_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("changes_json");
        request.query = request
            .query
            .project_expr(alias, Expr::column("changes_json"));
        request
    }

    pub fn group_by_changes_json_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("changes_json")
            .aggregate_with_function("changes_json", alias, function)
    }

    pub fn count_changes_json(self) -> Self {
        self.count_changes_json_as("changes_json_count")
    }

    pub fn count_changes_json_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("changes_json", alias)
    }

    pub fn sum_changes_json(self) -> Self {
        self.sum_changes_json_as("sum_changes_json")
    }

    pub fn sum_changes_json_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("changes_json", alias)
    }

    pub fn avg_changes_json(self) -> Self {
        self.avg_changes_json_as("avg_changes_json")
    }

    pub fn avg_changes_json_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("changes_json", alias)
    }

    pub fn min_changes_json(self) -> Self {
        self.min_changes_json_as("min_changes_json")
    }

    pub fn min_changes_json_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("changes_json", alias)
    }

    pub fn max_changes_json(self) -> Self {
        self.max_changes_json_as("max_changes_json")
    }

    pub fn max_changes_json_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("changes_json", alias)
    }

    pub fn unselect_changes_json(mut self) -> Self {
        self.query.projection.retain(|field| field != "changes_json");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "changes_json");
        self
    }


    pub fn with_changes_json(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "changes_json",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_changes_json_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "changes_json",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_changes_json_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("changes_json", value));
        self
    }



    pub fn with_changes_json_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("changes_json", value));
        self
    }

    pub fn with_changes_json_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("changes_json", value));
        self
    }

    pub fn with_changes_json_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("changes_json", value));
        self
    }

    pub fn with_changes_json_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("changes_json", value));
        self
    }

    pub fn with_changes_json_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("changes_json", value));
        self
    }

    pub fn with_changes_json_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("changes_json", lower, upper));
        self
    }

    pub fn with_changes_json_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "changes_json",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_changes_json_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "changes_json",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_changes_json_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "changes_json",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_changes_json_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("changes_json", value));
        self
    }

    pub fn with_changes_json_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("changes_json", value));
        self
    }

    pub fn with_changes_json_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("changes_json", value));
        self
    }

    pub fn with_changes_json_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("changes_json", value));
        self
    }

    pub fn with_changes_json_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("changes_json", value));
        self
    }

    pub fn with_changes_json_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("changes_json", value));
        self
    }

    pub fn with_changes_json_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("changes_json", value));
        self
    }
    pub fn with_changes_json_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("changes_json", value));
        self
    }

    pub fn with_changes_json_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("changes_json", value));
        self
    }

    pub fn with_changes_json_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("changes_json"));
        self
    }



    pub fn with_changes_json_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("changes_json"));
        self
    }


    pub fn order_by_changes_json_asc(mut self) -> Self {
        self.query = self.query.order_asc("changes_json");
        self
    }

    pub fn order_by_changes_json_desc(mut self) -> Self {
        self.query = self.query.order_desc("changes_json");
        self
    }

    pub fn order_by_changes_json_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("changes_json");
        self
    }

    pub fn order_by_changes_json_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("changes_json");
        self
    }


    pub fn select_timestamp(mut self) -> Self {
        self.query = self.query.project("timestamp");
        self
    }

    pub fn project_timestamp(self) -> Self {
        self.select_timestamp()
    }

    pub fn select_timestamp_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_timestamp_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_timestamp_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("timestamp", raw_sql_segment));
        self
    }

    pub fn group_by_timestamp(self) -> Self {
        self.group_by("timestamp")
    }

    pub fn group_by_timestamp_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("timestamp");
        request.query = request
            .query
            .project_expr(alias, Expr::column("timestamp"));
        request
    }

    pub fn group_by_timestamp_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("timestamp")
            .aggregate_with_function("timestamp", alias, function)
    }

    pub fn count_timestamp(self) -> Self {
        self.count_timestamp_as("timestamp_count")
    }

    pub fn count_timestamp_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("timestamp", alias)
    }

    pub fn sum_timestamp(self) -> Self {
        self.sum_timestamp_as("sum_timestamp")
    }

    pub fn sum_timestamp_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("timestamp", alias)
    }

    pub fn avg_timestamp(self) -> Self {
        self.avg_timestamp_as("avg_timestamp")
    }

    pub fn avg_timestamp_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("timestamp", alias)
    }

    pub fn min_timestamp(self) -> Self {
        self.min_timestamp_as("min_timestamp")
    }

    pub fn min_timestamp_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("timestamp", alias)
    }

    pub fn max_timestamp(self) -> Self {
        self.max_timestamp_as("max_timestamp")
    }

    pub fn max_timestamp_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("timestamp", alias)
    }

    pub fn unselect_timestamp(mut self) -> Self {
        self.query.projection.retain(|field| field != "timestamp");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "timestamp");
        self
    }


    pub fn with_timestamp(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "timestamp",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_timestamp_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "timestamp",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_timestamp_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("timestamp", value));
        self
    }



    pub fn with_timestamp_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("timestamp", value));
        self
    }

    pub fn with_timestamp_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("timestamp", value));
        self
    }

    pub fn with_timestamp_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("timestamp", value));
        self
    }

    pub fn with_timestamp_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("timestamp", value));
        self
    }

    pub fn with_timestamp_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("timestamp", value));
        self
    }

    pub fn with_timestamp_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("timestamp", lower, upper));
        self
    }

    pub fn with_timestamp_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "timestamp",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_timestamp_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "timestamp",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_timestamp_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "timestamp",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_timestamp_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("timestamp", value));
        self
    }

    pub fn with_timestamp_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("timestamp", value));
        self
    }

    pub fn with_timestamp_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("timestamp"));
        self
    }



    pub fn with_timestamp_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("timestamp"));
        self
    }


    pub fn order_by_timestamp_asc(mut self) -> Self {
        self.query = self.query.order_asc("timestamp");
        self
    }

    pub fn order_by_timestamp_desc(mut self) -> Self {
        self.query = self.query.order_desc("timestamp");
        self
    }

    pub fn order_by_timestamp_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("timestamp");
        self
    }

    pub fn order_by_timestamp_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("timestamp");
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
    pub fn filter_by_user(mut self, value: impl EntityReference) -> Self {
        self.query = self.query.and_filter(Expr::eq("user_id", value.entity_id_value()));
        self
    }

    pub fn with_user_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "user_id",
            <crate::User as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("user", selection));
        self
    }


    pub fn without_user_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "user_id",
            <crate::User as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("user", selection));
        self
    }


    pub fn have_user(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("user_id"));
        self
    }

    pub fn have_no_user(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("user_id"));
        self
    }


    pub fn group_by_user(self) -> Self {
        self.group_by("user_id")
    }

    pub fn group_by_user_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("user_id");
        request.query = request
            .query
            .project_expr(alias, Expr::column("user_id"));
        request
    }

    pub fn group_by_user_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("user_id")
            .aggregate_with_function("user_id", alias, function)
    }

    pub fn group_by_user_with(mut self, request: impl Into<QuerySelection>) -> Self {
        self.query = self.query.group_by("user_id");
        self.query_options.object_group_bys.push(ObjectGroupBy::new(
            "user",
            "user_id",
            request,
        ));
        self
    }

    pub fn group_by_user_with_details(self) -> Self {
        self.group_by_user_with_details_from(crate::Q::users().unlimited())
    }

    pub fn group_by_user_with_details_from(self, request: impl Into<QuerySelection>) -> Self {
        self.group_by_user_with(request)
    }


    pub fn roll_up_to_user(self) -> Self {
        self.roll_up_to_user_with(crate::Q::users().unlimited())
    }

    pub fn roll_up_to_user_with(self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.with_user_matching(selection.clone())
            .group_by_user_with(selection)
    }

    pub fn count_user(self) -> Self {
        self.count_user_as("user_count")
    }

    pub fn count_user_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("user_id", alias)
    }

    pub fn unselect_user(mut self) -> Self {
        self.query.projection.retain(|field| field != "user_id");
        self.query.relations.retain(|relation| relation.name != "user");
        self
    }
    pub fn select_user(mut self) -> Self {
        self.query = self.query.relation("user");
        self
    }

    pub fn select_user_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("user", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("user", selection));
        self
}

    pub fn facet_by_user_as(self, facet_name: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.facet_by_user_as_with_options(facet_name, request, true)
    }

    pub fn facet_by_user_as_with_options(
        mut self,
        facet_name: impl Into<String>,
        request: impl Into<QuerySelection>,
        include_all_facets: bool,
    ) -> Self {
        self.query_options.facets.push(FacetRequest::new(
            facet_name,
            "user",
            request,
            include_all_facets,
        ));
        self
    }
}

impl<R> Default for ActivityLogRequest<R> {
    fn default() -> Self {
        Self::new()
    }
}

impl<R> From< ActivityLogRequest<R> > for SelectQuery {
    fn from(request: ActivityLogRequest<R>) -> Self {
        QuerySelection::from(request).into_query()
    }
}

impl<R> From< ActivityLogRequest<R> > for QuerySelection {
    fn from(request: ActivityLogRequest<R>) -> Self {
        Self {
            query: request.query,
            relation_selections: request.relation_selections,
            relation_filters: request.relation_filters,
            child_enhancements: request.child_enhancements,
            query_options: request.query_options,
        }
    }
}


impl<'a, C> crate::request_support::AuditedSave<'a, C> for teaql_core::Audited<crate::ActivityLog> 
where C: crate::request_support::TeaqlRepositoryProvider + ?Sized + 'a
{
    type Error = crate::TeaqlDataServiceError<C::ActivityLogRepository<'a>>;
    fn save(self, ctx: &'a C) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<teaql_runtime::GraphNode, Self::Error>> + '_>> {
        Box::pin(async move { self.into_entity().save(ctx).await })
    }
}

impl<R: teaql_core::Entity> crate::PurposedQuery<ActivityLogRequest<R>> {
    pub fn new_entity<C>(&self, ctx: &C) -> crate::ActivityLog
    where
        C: crate::TeaqlRuntime + ?Sized,
    {
        crate::ActivityLog::runtime_new(ctx.user_context().entity_root())
    }

    fn into_inner_with_trace(mut self) -> ActivityLogRequest<R> {
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
    ) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::ActivityLogRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_page(ctx, offset, limit).await
    }

    pub async fn execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, crate::request_support::TeaqlDataServiceError<C::ActivityLogRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_exists(ctx).await
    }

    pub async fn execute_for_list<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::ActivityLogRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_list(ctx).await
    }

    /// Execute query in streaming mode (chunked).
    /// Returns a Vec of StreamChunk, each containing up to chunk_size rows.
    /// Set chunk size via .stream(chunk_size) or .stream_default() on the query.
    pub async fn execute_for_stream<'a, C>(self, ctx: &'a C) -> Result<Vec<teaql_data_service::StreamChunk>, crate::request_support::TeaqlDataServiceError<C::ActivityLogRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_stream(ctx).await
    }

    pub async fn execute_for_first<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::ActivityLogRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_first(ctx).await
    }

    pub async fn execute_for_one<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::ActivityLogRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_one(ctx).await
    }


    pub async fn execute_for_records<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::ActivityLogRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_records(ctx).await
    }

    pub async fn execute_for_record<'a, C>(self, ctx: &'a C) -> Result<Option<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::ActivityLogRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_record(ctx).await
    }

    pub async fn execute_for_count<'a, C>(self, ctx: &'a C) -> Result<u64, crate::request_support::TeaqlDataServiceError<C::ActivityLogRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_count(ctx).await
    }
}
