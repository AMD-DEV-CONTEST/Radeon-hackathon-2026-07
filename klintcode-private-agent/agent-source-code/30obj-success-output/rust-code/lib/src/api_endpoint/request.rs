use std::marker::PhantomData;

use serde_json::Value as JsonValue;
use teaql_core::{Aggregate, AggregateFunction, EntityDescriptor, Expr, Record, SelectQuery, SmartList};
use teaql_runtime::{DataServiceError, RuntimeError};

use crate::request_support::*;

impl EntityReference for crate::ApiEndpoint {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(&self)
    }
}

impl EntityReference for &crate::ApiEndpoint {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(self)
    }
}

// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/api_endpoint
#[derive(Debug)]
pub struct ApiEndpointRequest<R = crate::ApiEndpoint> {
    query: SelectQuery,
    relation_selections: Vec<RelationSelection>,
    relation_filters: Vec<RelationFilter>,
    child_enhancements: Vec<QuerySelection>,
    query_options: QueryOptions,
    marker: PhantomData<R>,
}

impl<R> Clone for ApiEndpointRequest<R> {
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

impl<R> ApiEndpointRequest<R> {
    pub(crate) fn new() -> Self {
        Self {
            query: SelectQuery::new("ApiEndpoint")
                .project("id"),
            relation_selections: Vec::new(),
            relation_filters: Vec::new(),
            child_enhancements: Vec::new(),
            query_options: QueryOptions::default(),
            marker: PhantomData,
        }
    }

    pub fn return_type<T>(self) -> ApiEndpointRequest<T> {
        ApiEndpointRequest {
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::ApiEndpointRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
        R: teaql_core::Entity,
    {
        let repository = ctx
            .api_endpoint_repository()
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
    ) -> Result<Vec<teaql_data_service::StreamChunk>, TeaqlDataServiceError<C::ApiEndpointRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .api_endpoint_repository()
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::ApiEndpointRepository<'a>>>
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::ApiEndpointRepository<'a>>>
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::ApiEndpointRepository<'a>>>
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
    ) -> Result<u64, TeaqlDataServiceError<C::ApiEndpointRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .api_endpoint_repository()
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
            .ok_or_else(|| DataServiceError::Runtime(RuntimeError::Graph(format!("count result for ApiEndpoint is missing or not numeric"))))
    }

    pub(crate) async fn _execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, TeaqlDataServiceError<C::ApiEndpointRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .api_endpoint_repository()
            .map_err(|err| DataServiceError::Runtime(RuntimeError::Graph(err.to_string())))?;
        let mut query = self.query.limit(1);
        query.relations.clear();
        let rows = repository.fetch_all(&query).await?;
        Ok(!rows.is_empty())
    }

    pub(crate) async fn _execute_for_records<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<SmartList<Record>, TeaqlDataServiceError<C::ApiEndpointRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .api_endpoint_repository()
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
    ) -> Result<Option<Record>, TeaqlDataServiceError<C::ApiEndpointRepository<'a>>>
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
            "path" => Some("path"),
            "method" => Some("method"),
            "description" => Some("description"),
            "version" => Some("version"),
            "active" => Some("active"),
            "create_time" => Some("create_time"),
            "update_time" => Some("update_time"),
            _ => None,
        }
    }

    fn apply_dynamic_json_chain_filter(self, head: &str, tail: &str, value: &JsonValue) -> Self {
        let _ = (tail, value);
        match head {
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
        self.query = self.query.project("path");
        self.query = self.query.project("method");
        self.query = self.query.project("description");
        self.query = self.query.project("version");
        self.query = self.query.project("active");
        self.query = self.query.project("create_time");
        self.query = self.query.project("update_time");
        self
    }

    pub fn select_self_fields(self) -> Self {
        self.select_self()
    }

    pub fn select_self_without_parent(self) -> Self {
        self.select_self_fields()
    }

    pub fn select_all(self) -> Self {
        self.select_self()
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


    pub fn select_path(mut self) -> Self {
        self.query = self.query.project("path");
        self
    }

    pub fn project_path(self) -> Self {
        self.select_path()
    }

    pub fn select_path_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_path_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_path_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("path", raw_sql_segment));
        self
    }

    pub fn group_by_path(self) -> Self {
        self.group_by("path")
    }

    pub fn group_by_path_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("path");
        request.query = request
            .query
            .project_expr(alias, Expr::column("path"));
        request
    }

    pub fn group_by_path_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("path")
            .aggregate_with_function("path", alias, function)
    }

    pub fn count_path(self) -> Self {
        self.count_path_as("path_count")
    }

    pub fn count_path_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("path", alias)
    }

    pub fn sum_path(self) -> Self {
        self.sum_path_as("sum_path")
    }

    pub fn sum_path_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("path", alias)
    }

    pub fn avg_path(self) -> Self {
        self.avg_path_as("avg_path")
    }

    pub fn avg_path_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("path", alias)
    }

    pub fn min_path(self) -> Self {
        self.min_path_as("min_path")
    }

    pub fn min_path_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("path", alias)
    }

    pub fn max_path(self) -> Self {
        self.max_path_as("max_path")
    }

    pub fn max_path_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("path", alias)
    }

    pub fn unselect_path(mut self) -> Self {
        self.query.projection.retain(|field| field != "path");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "path");
        self
    }


    pub fn with_path(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "path",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_path_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "path",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_path_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("path", value));
        self
    }



    pub fn with_path_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("path", value));
        self
    }

    pub fn with_path_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("path", value));
        self
    }

    pub fn with_path_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("path", value));
        self
    }

    pub fn with_path_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("path", value));
        self
    }

    pub fn with_path_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("path", value));
        self
    }

    pub fn with_path_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("path", lower, upper));
        self
    }

    pub fn with_path_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "path",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_path_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "path",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_path_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "path",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_path_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("path", value));
        self
    }

    pub fn with_path_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("path", value));
        self
    }

    pub fn with_path_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("path", value));
        self
    }

    pub fn with_path_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("path", value));
        self
    }

    pub fn with_path_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("path", value));
        self
    }

    pub fn with_path_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("path", value));
        self
    }

    pub fn with_path_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("path", value));
        self
    }
    pub fn with_path_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("path", value));
        self
    }

    pub fn with_path_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("path", value));
        self
    }

    pub fn with_path_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("path"));
        self
    }



    pub fn with_path_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("path"));
        self
    }


    pub fn order_by_path_asc(mut self) -> Self {
        self.query = self.query.order_asc("path");
        self
    }

    pub fn order_by_path_desc(mut self) -> Self {
        self.query = self.query.order_desc("path");
        self
    }

    pub fn order_by_path_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("path");
        self
    }

    pub fn order_by_path_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("path");
        self
    }


    pub fn select_method(mut self) -> Self {
        self.query = self.query.project("method");
        self
    }

    pub fn project_method(self) -> Self {
        self.select_method()
    }

    pub fn select_method_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_method_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_method_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("method", raw_sql_segment));
        self
    }

    pub fn group_by_method(self) -> Self {
        self.group_by("method")
    }

    pub fn group_by_method_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("method");
        request.query = request
            .query
            .project_expr(alias, Expr::column("method"));
        request
    }

    pub fn group_by_method_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("method")
            .aggregate_with_function("method", alias, function)
    }

    pub fn count_method(self) -> Self {
        self.count_method_as("method_count")
    }

    pub fn count_method_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("method", alias)
    }

    pub fn sum_method(self) -> Self {
        self.sum_method_as("sum_method")
    }

    pub fn sum_method_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("method", alias)
    }

    pub fn avg_method(self) -> Self {
        self.avg_method_as("avg_method")
    }

    pub fn avg_method_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("method", alias)
    }

    pub fn min_method(self) -> Self {
        self.min_method_as("min_method")
    }

    pub fn min_method_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("method", alias)
    }

    pub fn max_method(self) -> Self {
        self.max_method_as("max_method")
    }

    pub fn max_method_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("method", alias)
    }

    pub fn unselect_method(mut self) -> Self {
        self.query.projection.retain(|field| field != "method");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "method");
        self
    }


    pub fn with_method(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "method",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_method_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "method",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_method_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("method", value));
        self
    }



    pub fn with_method_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("method", value));
        self
    }

    pub fn with_method_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("method", value));
        self
    }

    pub fn with_method_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("method", value));
        self
    }

    pub fn with_method_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("method", value));
        self
    }

    pub fn with_method_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("method", value));
        self
    }

    pub fn with_method_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("method", lower, upper));
        self
    }

    pub fn with_method_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "method",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_method_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "method",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_method_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "method",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_method_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("method", value));
        self
    }

    pub fn with_method_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("method", value));
        self
    }

    pub fn with_method_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("method", value));
        self
    }

    pub fn with_method_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("method", value));
        self
    }

    pub fn with_method_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("method", value));
        self
    }

    pub fn with_method_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("method", value));
        self
    }

    pub fn with_method_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("method", value));
        self
    }
    pub fn with_method_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("method", value));
        self
    }

    pub fn with_method_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("method", value));
        self
    }

    pub fn with_method_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("method"));
        self
    }



    pub fn with_method_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("method"));
        self
    }


    pub fn order_by_method_asc(mut self) -> Self {
        self.query = self.query.order_asc("method");
        self
    }

    pub fn order_by_method_desc(mut self) -> Self {
        self.query = self.query.order_desc("method");
        self
    }

    pub fn order_by_method_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("method");
        self
    }

    pub fn order_by_method_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("method");
        self
    }


    pub fn select_description(mut self) -> Self {
        self.query = self.query.project("description");
        self
    }

    pub fn project_description(self) -> Self {
        self.select_description()
    }

    pub fn select_description_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_description_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_description_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("description", raw_sql_segment));
        self
    }

    pub fn group_by_description(self) -> Self {
        self.group_by("description")
    }

    pub fn group_by_description_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("description");
        request.query = request
            .query
            .project_expr(alias, Expr::column("description"));
        request
    }

    pub fn group_by_description_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("description")
            .aggregate_with_function("description", alias, function)
    }

    pub fn count_description(self) -> Self {
        self.count_description_as("description_count")
    }

    pub fn count_description_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("description", alias)
    }

    pub fn sum_description(self) -> Self {
        self.sum_description_as("sum_description")
    }

    pub fn sum_description_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("description", alias)
    }

    pub fn avg_description(self) -> Self {
        self.avg_description_as("avg_description")
    }

    pub fn avg_description_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("description", alias)
    }

    pub fn min_description(self) -> Self {
        self.min_description_as("min_description")
    }

    pub fn min_description_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("description", alias)
    }

    pub fn max_description(self) -> Self {
        self.max_description_as("max_description")
    }

    pub fn max_description_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("description", alias)
    }

    pub fn unselect_description(mut self) -> Self {
        self.query.projection.retain(|field| field != "description");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "description");
        self
    }


    pub fn with_description(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "description",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_description_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "description",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_description_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("description", value));
        self
    }



    pub fn with_description_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("description", value));
        self
    }

    pub fn with_description_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("description", value));
        self
    }

    pub fn with_description_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("description", value));
        self
    }

    pub fn with_description_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("description", value));
        self
    }

    pub fn with_description_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("description", value));
        self
    }

    pub fn with_description_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("description", lower, upper));
        self
    }

    pub fn with_description_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "description",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_description_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "description",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_description_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "description",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_description_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("description", value));
        self
    }

    pub fn with_description_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("description", value));
        self
    }

    pub fn with_description_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("description", value));
        self
    }

    pub fn with_description_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("description", value));
        self
    }

    pub fn with_description_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("description", value));
        self
    }

    pub fn with_description_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("description", value));
        self
    }

    pub fn with_description_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("description", value));
        self
    }
    pub fn with_description_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("description", value));
        self
    }

    pub fn with_description_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("description", value));
        self
    }

    pub fn with_description_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("description"));
        self
    }



    pub fn with_description_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("description"));
        self
    }


    pub fn order_by_description_asc(mut self) -> Self {
        self.query = self.query.order_asc("description");
        self
    }

    pub fn order_by_description_desc(mut self) -> Self {
        self.query = self.query.order_desc("description");
        self
    }

    pub fn order_by_description_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("description");
        self
    }

    pub fn order_by_description_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("description");
        self
    }


    pub fn select_version(mut self) -> Self {
        self.query = self.query.project("version");
        self
    }

    pub fn project_version(self) -> Self {
        self.select_version()
    }

    pub fn select_version_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_version_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_version_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("version", raw_sql_segment));
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

    pub fn unselect_version(mut self) -> Self {
        self.query.projection.retain(|field| field != "version");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "version");
        self
    }


    pub fn with_version(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "version",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_version_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "version",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_version_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("version", value));
        self
    }



    pub fn with_version_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("version", value));
        self
    }

    pub fn with_version_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("version", value));
        self
    }

    pub fn with_version_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("version", value));
        self
    }

    pub fn with_version_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("version", value));
        self
    }

    pub fn with_version_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("version", value));
        self
    }

    pub fn with_version_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("version", lower, upper));
        self
    }

    pub fn with_version_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "version",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_version_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "version",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_version_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "version",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_version_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("version", value));
        self
    }

    pub fn with_version_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("version", value));
        self
    }

    pub fn with_version_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("version", value));
        self
    }

    pub fn with_version_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("version", value));
        self
    }

    pub fn with_version_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("version", value));
        self
    }

    pub fn with_version_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("version", value));
        self
    }

    pub fn with_version_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("version", value));
        self
    }
    pub fn with_version_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("version", value));
        self
    }

    pub fn with_version_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("version", value));
        self
    }

    pub fn with_version_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("version"));
        self
    }



    pub fn with_version_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("version"));
        self
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


    pub fn select_active(mut self) -> Self {
        self.query = self.query.project("active");
        self
    }

    pub fn project_active(self) -> Self {
        self.select_active()
    }

    pub fn select_active_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_active_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_active_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("active", raw_sql_segment));
        self
    }

    pub fn group_by_active(self) -> Self {
        self.group_by("active")
    }

    pub fn group_by_active_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("active");
        request.query = request
            .query
            .project_expr(alias, Expr::column("active"));
        request
    }

    pub fn group_by_active_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("active")
            .aggregate_with_function("active", alias, function)
    }

    pub fn count_active(self) -> Self {
        self.count_active_as("active_count")
    }

    pub fn count_active_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("active", alias)
    }

    pub fn sum_active(self) -> Self {
        self.sum_active_as("sum_active")
    }

    pub fn sum_active_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("active", alias)
    }

    pub fn avg_active(self) -> Self {
        self.avg_active_as("avg_active")
    }

    pub fn avg_active_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("active", alias)
    }

    pub fn min_active(self) -> Self {
        self.min_active_as("min_active")
    }

    pub fn min_active_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("active", alias)
    }

    pub fn max_active(self) -> Self {
        self.max_active_as("max_active")
    }

    pub fn max_active_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("active", alias)
    }

    pub fn unselect_active(mut self) -> Self {
        self.query.projection.retain(|field| field != "active");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "active");
        self
    }


    pub fn with_active(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "active",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_active_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "active",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_active_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("active", value));
        self
    }



    pub fn with_active_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("active", value));
        self
    }

    pub fn with_active_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("active", value));
        self
    }

    pub fn with_active_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("active", value));
        self
    }

    pub fn with_active_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("active", value));
        self
    }

    pub fn with_active_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("active", value));
        self
    }

    pub fn with_active_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("active", lower, upper));
        self
    }

    pub fn with_active_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "active",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_active_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "active",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_active_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "active",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_active_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("active", value));
        self
    }

    pub fn with_active_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("active", value));
        self
    }

    pub fn with_active_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("active"));
        self
    }



    pub fn with_active_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("active"));
        self
    }


    pub fn order_by_active_asc(mut self) -> Self {
        self.query = self.query.order_asc("active");
        self
    }

    pub fn order_by_active_desc(mut self) -> Self {
        self.query = self.query.order_desc("active");
        self
    }

    pub fn order_by_active_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("active");
        self
    }

    pub fn order_by_active_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("active");
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
    pub fn path_is_api_v1_users(self) -> Self {
        self.with_path_is("/api/v1/users")
    }

    pub fn with_path_is_api_v1_users(self) -> Self {
        self.with_path_is("/api/v1/users")
    }



    pub fn with_path_is_not_api_v1_users(self) -> Self {
        self.with_path_is_not("/api/v1/users")
    }



    pub fn method_is_ge_t(self) -> Self {
        self.with_method_is("GET")
    }

    pub fn with_method_is_ge_t(self) -> Self {
        self.with_method_is("GET")
    }



    pub fn with_method_is_not_ge_t(self) -> Self {
        self.with_method_is_not("GET")
    }



    pub fn description_is_get_user_list(self) -> Self {
        self.with_description_is("Get user list")
    }

    pub fn with_description_is_get_user_list(self) -> Self {
        self.with_description_is("Get user list")
    }



    pub fn with_description_is_not_get_user_list(self) -> Self {
        self.with_description_is_not("Get user list")
    }



    pub fn version_is_v1(self) -> Self {
        self.with_version_is("v1")
    }

    pub fn with_version_is_v1(self) -> Self {
        self.with_version_is("v1")
    }



    pub fn with_version_is_not_v1(self) -> Self {
        self.with_version_is_not("v1")
    }



    pub fn active_is_true(self) -> Self {
        self.with_active_is("true")
    }

    pub fn with_active_is_true(self) -> Self {
        self.with_active_is("true")
    }



    pub fn with_active_is_not_true(self) -> Self {
        self.with_active_is_not("true")
    }



    pub fn create_time_is_create_time(self) -> Self {
        self.with_create_time_is("createTime()")
    }

    pub fn with_create_time_is_create_time(self) -> Self {
        self.with_create_time_is("createTime()")
    }



    pub fn with_create_time_is_not_create_time(self) -> Self {
        self.with_create_time_is_not("createTime()")
    }



    pub fn update_time_is_update_time(self) -> Self {
        self.with_update_time_is("updateTime()")
    }

    pub fn with_update_time_is_update_time(self) -> Self {
        self.with_update_time_is("updateTime()")
    }



    pub fn with_update_time_is_not_update_time(self) -> Self {
        self.with_update_time_is_not("updateTime()")
    }


}

impl<R> Default for ApiEndpointRequest<R> {
    fn default() -> Self {
        Self::new()
    }
}

impl<R> From< ApiEndpointRequest<R> > for SelectQuery {
    fn from(request: ApiEndpointRequest<R>) -> Self {
        QuerySelection::from(request).into_query()
    }
}

impl<R> From< ApiEndpointRequest<R> > for QuerySelection {
    fn from(request: ApiEndpointRequest<R>) -> Self {
        Self {
            query: request.query,
            relation_selections: request.relation_selections,
            relation_filters: request.relation_filters,
            child_enhancements: request.child_enhancements,
            query_options: request.query_options,
        }
    }
}


impl<'a, C> crate::request_support::AuditedSave<'a, C> for teaql_core::Audited<crate::ApiEndpoint> 
where C: crate::request_support::TeaqlRepositoryProvider + ?Sized + 'a
{
    type Error = crate::TeaqlDataServiceError<C::ApiEndpointRepository<'a>>;
    fn save(self, ctx: &'a C) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<teaql_runtime::GraphNode, Self::Error>> + '_>> {
        Box::pin(async move { self.into_entity().save(ctx).await })
    }
}

impl<R: teaql_core::Entity> crate::PurposedQuery<ApiEndpointRequest<R>> {
    pub fn new_entity<C>(&self, ctx: &C) -> crate::ApiEndpoint
    where
        C: crate::TeaqlRuntime + ?Sized,
    {
        crate::ApiEndpoint::runtime_new(ctx.user_context().entity_root())
    }

    fn into_inner_with_trace(mut self) -> ApiEndpointRequest<R> {
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
    ) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::ApiEndpointRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_page(ctx, offset, limit).await
    }

    pub async fn execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, crate::request_support::TeaqlDataServiceError<C::ApiEndpointRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_exists(ctx).await
    }

    pub async fn execute_for_list<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::ApiEndpointRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_list(ctx).await
    }

    /// Execute query in streaming mode (chunked).
    /// Returns a Vec of StreamChunk, each containing up to chunk_size rows.
    /// Set chunk size via .stream(chunk_size) or .stream_default() on the query.
    pub async fn execute_for_stream<'a, C>(self, ctx: &'a C) -> Result<Vec<teaql_data_service::StreamChunk>, crate::request_support::TeaqlDataServiceError<C::ApiEndpointRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_stream(ctx).await
    }

    pub async fn execute_for_first<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::ApiEndpointRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_first(ctx).await
    }

    pub async fn execute_for_one<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::ApiEndpointRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_one(ctx).await
    }


    pub async fn execute_for_records<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::ApiEndpointRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_records(ctx).await
    }

    pub async fn execute_for_record<'a, C>(self, ctx: &'a C) -> Result<Option<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::ApiEndpointRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_record(ctx).await
    }

    pub async fn execute_for_count<'a, C>(self, ctx: &'a C) -> Result<u64, crate::request_support::TeaqlDataServiceError<C::ApiEndpointRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_count(ctx).await
    }
}
