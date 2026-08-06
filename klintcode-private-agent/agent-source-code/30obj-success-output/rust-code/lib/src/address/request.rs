use std::marker::PhantomData;

use serde_json::Value as JsonValue;
use teaql_core::{Aggregate, AggregateFunction, EntityDescriptor, Expr, Record, SelectQuery, SmartList};
use teaql_runtime::{DataServiceError, RuntimeError};

use crate::request_support::*;

impl EntityReference for crate::Address {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(&self)
    }
}

impl EntityReference for &crate::Address {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(self)
    }
}

// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/address
#[derive(Debug)]
pub struct AddressRequest<R = crate::Address> {
    query: SelectQuery,
    relation_selections: Vec<RelationSelection>,
    relation_filters: Vec<RelationFilter>,
    child_enhancements: Vec<QuerySelection>,
    query_options: QueryOptions,
    marker: PhantomData<R>,
}

impl<R> Clone for AddressRequest<R> {
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

impl<R> AddressRequest<R> {
    pub(crate) fn new() -> Self {
        Self {
            query: SelectQuery::new("Address")
                .project("id")
                .project("version"),
            relation_selections: Vec::new(),
            relation_filters: Vec::new(),
            child_enhancements: Vec::new(),
            query_options: QueryOptions::default(),
            marker: PhantomData,
        }
    }

    pub fn return_type<T>(self) -> AddressRequest<T> {
        AddressRequest {
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::AddressRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
        R: teaql_core::Entity,
    {
        let repository = ctx
            .address_repository()
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
    ) -> Result<Vec<teaql_data_service::StreamChunk>, TeaqlDataServiceError<C::AddressRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .address_repository()
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::AddressRepository<'a>>>
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::AddressRepository<'a>>>
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::AddressRepository<'a>>>
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
    ) -> Result<u64, TeaqlDataServiceError<C::AddressRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .address_repository()
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
            .ok_or_else(|| DataServiceError::Runtime(RuntimeError::Graph(format!("count result for Address is missing or not numeric"))))
    }

    pub(crate) async fn _execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, TeaqlDataServiceError<C::AddressRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .address_repository()
            .map_err(|err| DataServiceError::Runtime(RuntimeError::Graph(err.to_string())))?;
        let mut query = self.query.limit(1);
        query.relations.clear();
        let rows = repository.fetch_all(&query).await?;
        Ok(!rows.is_empty())
    }

    pub(crate) async fn _execute_for_records<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<SmartList<Record>, TeaqlDataServiceError<C::AddressRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .address_repository()
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
    ) -> Result<Option<Record>, TeaqlDataServiceError<C::AddressRepository<'a>>>
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
            "street" => Some("street"),
            "city" => Some("city"),
            "state" => Some("state"),
            "postal_code" => Some("postal_code"),
            "country" => Some("country"),
            "create_time" => Some("create_time"),
            "update_time" => Some("update_time"),
            "version" => Some("version"),
            _ => None,
        }
    }

    fn apply_dynamic_json_chain_filter(self, head: &str, tail: &str, value: &JsonValue) -> Self {
        let _ = (tail, value);
        match head {
            "moving_event_list_as_origin_address" => {
                self.with_moving_event_list_as_origin_address_matching(
                    crate::Q::moving_events_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "moving_event_list_as_destination_address" => {
                self.with_moving_event_list_as_destination_address_matching(
                    crate::Q::moving_events_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "route_list_as_origin" => {
                self.with_route_list_as_origin_matching(
                    crate::Q::routes_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "route_list_as_destination" => {
                self.with_route_list_as_destination_matching(
                    crate::Q::routes_minimal()
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
        self.query = self.query.project("street");
        self.query = self.query.project("city");
        self.query = self.query.project("state");
        self.query = self.query.project("postal_code");
        self.query = self.query.project("country");
        self.query = self.query.project("create_time");
        self.query = self.query.project("update_time");
        self.query = self.query.project("version");
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
        let mut request = self.select_all();
        request = request.select_moving_event_list_as_origin_address();
        request = request.select_moving_event_list_as_destination_address();
        request = request.select_route_list_as_origin();
        request = request.select_route_list_as_destination();
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


    pub fn select_street(mut self) -> Self {
        self.query = self.query.project("street");
        self
    }

    pub fn project_street(self) -> Self {
        self.select_street()
    }

    pub fn select_street_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_street_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_street_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("street", raw_sql_segment));
        self
    }

    pub fn group_by_street(self) -> Self {
        self.group_by("street")
    }

    pub fn group_by_street_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("street");
        request.query = request
            .query
            .project_expr(alias, Expr::column("street"));
        request
    }

    pub fn group_by_street_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("street")
            .aggregate_with_function("street", alias, function)
    }

    pub fn count_street(self) -> Self {
        self.count_street_as("street_count")
    }

    pub fn count_street_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("street", alias)
    }

    pub fn sum_street(self) -> Self {
        self.sum_street_as("sum_street")
    }

    pub fn sum_street_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("street", alias)
    }

    pub fn avg_street(self) -> Self {
        self.avg_street_as("avg_street")
    }

    pub fn avg_street_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("street", alias)
    }

    pub fn min_street(self) -> Self {
        self.min_street_as("min_street")
    }

    pub fn min_street_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("street", alias)
    }

    pub fn max_street(self) -> Self {
        self.max_street_as("max_street")
    }

    pub fn max_street_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("street", alias)
    }

    pub fn unselect_street(mut self) -> Self {
        self.query.projection.retain(|field| field != "street");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "street");
        self
    }


    pub fn with_street(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "street",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_street_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "street",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_street_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("street", value));
        self
    }



    pub fn with_street_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("street", value));
        self
    }

    pub fn with_street_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("street", value));
        self
    }

    pub fn with_street_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("street", value));
        self
    }

    pub fn with_street_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("street", value));
        self
    }

    pub fn with_street_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("street", value));
        self
    }

    pub fn with_street_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("street", lower, upper));
        self
    }

    pub fn with_street_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "street",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_street_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "street",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_street_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "street",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_street_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("street", value));
        self
    }

    pub fn with_street_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("street", value));
        self
    }

    pub fn with_street_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("street", value));
        self
    }

    pub fn with_street_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("street", value));
        self
    }

    pub fn with_street_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("street", value));
        self
    }

    pub fn with_street_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("street", value));
        self
    }

    pub fn with_street_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("street", value));
        self
    }
    pub fn with_street_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("street", value));
        self
    }

    pub fn with_street_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("street", value));
        self
    }

    pub fn with_street_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("street"));
        self
    }



    pub fn with_street_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("street"));
        self
    }


    pub fn order_by_street_asc(mut self) -> Self {
        self.query = self.query.order_asc("street");
        self
    }

    pub fn order_by_street_desc(mut self) -> Self {
        self.query = self.query.order_desc("street");
        self
    }

    pub fn order_by_street_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("street");
        self
    }

    pub fn order_by_street_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("street");
        self
    }


    pub fn select_city(mut self) -> Self {
        self.query = self.query.project("city");
        self
    }

    pub fn project_city(self) -> Self {
        self.select_city()
    }

    pub fn select_city_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_city_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_city_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("city", raw_sql_segment));
        self
    }

    pub fn group_by_city(self) -> Self {
        self.group_by("city")
    }

    pub fn group_by_city_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("city");
        request.query = request
            .query
            .project_expr(alias, Expr::column("city"));
        request
    }

    pub fn group_by_city_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("city")
            .aggregate_with_function("city", alias, function)
    }

    pub fn count_city(self) -> Self {
        self.count_city_as("city_count")
    }

    pub fn count_city_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("city", alias)
    }

    pub fn sum_city(self) -> Self {
        self.sum_city_as("sum_city")
    }

    pub fn sum_city_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("city", alias)
    }

    pub fn avg_city(self) -> Self {
        self.avg_city_as("avg_city")
    }

    pub fn avg_city_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("city", alias)
    }

    pub fn min_city(self) -> Self {
        self.min_city_as("min_city")
    }

    pub fn min_city_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("city", alias)
    }

    pub fn max_city(self) -> Self {
        self.max_city_as("max_city")
    }

    pub fn max_city_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("city", alias)
    }

    pub fn unselect_city(mut self) -> Self {
        self.query.projection.retain(|field| field != "city");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "city");
        self
    }


    pub fn with_city(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "city",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_city_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "city",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_city_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("city", value));
        self
    }



    pub fn with_city_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("city", value));
        self
    }

    pub fn with_city_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("city", value));
        self
    }

    pub fn with_city_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("city", value));
        self
    }

    pub fn with_city_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("city", value));
        self
    }

    pub fn with_city_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("city", value));
        self
    }

    pub fn with_city_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("city", lower, upper));
        self
    }

    pub fn with_city_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "city",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_city_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "city",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_city_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "city",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_city_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("city", value));
        self
    }

    pub fn with_city_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("city", value));
        self
    }

    pub fn with_city_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("city", value));
        self
    }

    pub fn with_city_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("city", value));
        self
    }

    pub fn with_city_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("city", value));
        self
    }

    pub fn with_city_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("city", value));
        self
    }

    pub fn with_city_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("city", value));
        self
    }
    pub fn with_city_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("city", value));
        self
    }

    pub fn with_city_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("city", value));
        self
    }

    pub fn with_city_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("city"));
        self
    }



    pub fn with_city_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("city"));
        self
    }


    pub fn order_by_city_asc(mut self) -> Self {
        self.query = self.query.order_asc("city");
        self
    }

    pub fn order_by_city_desc(mut self) -> Self {
        self.query = self.query.order_desc("city");
        self
    }

    pub fn order_by_city_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("city");
        self
    }

    pub fn order_by_city_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("city");
        self
    }


    pub fn select_state(mut self) -> Self {
        self.query = self.query.project("state");
        self
    }

    pub fn project_state(self) -> Self {
        self.select_state()
    }

    pub fn select_state_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_state_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_state_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("state", raw_sql_segment));
        self
    }

    pub fn group_by_state(self) -> Self {
        self.group_by("state")
    }

    pub fn group_by_state_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("state");
        request.query = request
            .query
            .project_expr(alias, Expr::column("state"));
        request
    }

    pub fn group_by_state_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("state")
            .aggregate_with_function("state", alias, function)
    }

    pub fn count_state(self) -> Self {
        self.count_state_as("state_count")
    }

    pub fn count_state_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("state", alias)
    }

    pub fn sum_state(self) -> Self {
        self.sum_state_as("sum_state")
    }

    pub fn sum_state_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("state", alias)
    }

    pub fn avg_state(self) -> Self {
        self.avg_state_as("avg_state")
    }

    pub fn avg_state_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("state", alias)
    }

    pub fn min_state(self) -> Self {
        self.min_state_as("min_state")
    }

    pub fn min_state_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("state", alias)
    }

    pub fn max_state(self) -> Self {
        self.max_state_as("max_state")
    }

    pub fn max_state_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("state", alias)
    }

    pub fn unselect_state(mut self) -> Self {
        self.query.projection.retain(|field| field != "state");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "state");
        self
    }


    pub fn with_state(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "state",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_state_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "state",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_state_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("state", value));
        self
    }



    pub fn with_state_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("state", value));
        self
    }

    pub fn with_state_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("state", value));
        self
    }

    pub fn with_state_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("state", value));
        self
    }

    pub fn with_state_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("state", value));
        self
    }

    pub fn with_state_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("state", value));
        self
    }

    pub fn with_state_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("state", lower, upper));
        self
    }

    pub fn with_state_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "state",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_state_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "state",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_state_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "state",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_state_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("state", value));
        self
    }

    pub fn with_state_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("state", value));
        self
    }

    pub fn with_state_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("state", value));
        self
    }

    pub fn with_state_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("state", value));
        self
    }

    pub fn with_state_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("state", value));
        self
    }

    pub fn with_state_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("state", value));
        self
    }

    pub fn with_state_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("state", value));
        self
    }
    pub fn with_state_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("state", value));
        self
    }

    pub fn with_state_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("state", value));
        self
    }

    pub fn with_state_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("state"));
        self
    }



    pub fn with_state_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("state"));
        self
    }


    pub fn order_by_state_asc(mut self) -> Self {
        self.query = self.query.order_asc("state");
        self
    }

    pub fn order_by_state_desc(mut self) -> Self {
        self.query = self.query.order_desc("state");
        self
    }

    pub fn order_by_state_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("state");
        self
    }

    pub fn order_by_state_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("state");
        self
    }


    pub fn select_postal_code(mut self) -> Self {
        self.query = self.query.project("postal_code");
        self
    }

    pub fn project_postal_code(self) -> Self {
        self.select_postal_code()
    }

    pub fn select_postal_code_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_postal_code_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_postal_code_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("postal_code", raw_sql_segment));
        self
    }

    pub fn select_postal_code_with_function(self, function: AggregateFunction) -> Self {
        self.select_postal_code_as_with_function("postal_code", function)
    }

    pub fn select_postal_code_as_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.aggregate_with_function("postal_code", alias, function)
    }

    pub fn group_by_postal_code(self) -> Self {
        self.group_by("postal_code")
    }

    pub fn group_by_postal_code_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("postal_code");
        request.query = request
            .query
            .project_expr(alias, Expr::column("postal_code"));
        request
    }

    pub fn group_by_postal_code_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("postal_code")
            .aggregate_with_function("postal_code", alias, function)
    }

    pub fn count_postal_code(self) -> Self {
        self.count_postal_code_as("postal_code_count")
    }

    pub fn count_postal_code_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("postal_code", alias)
    }

    pub fn sum_postal_code(self) -> Self {
        self.sum_postal_code_as("sum_postal_code")
    }

    pub fn sum_postal_code_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("postal_code", alias)
    }

    pub fn avg_postal_code(self) -> Self {
        self.avg_postal_code_as("avg_postal_code")
    }

    pub fn avg_postal_code_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("postal_code", alias)
    }

    pub fn min_postal_code(self) -> Self {
        self.min_postal_code_as("min_postal_code")
    }

    pub fn min_postal_code_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("postal_code", alias)
    }

    pub fn max_postal_code(self) -> Self {
        self.max_postal_code_as("max_postal_code")
    }

    pub fn max_postal_code_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("postal_code", alias)
    }

    pub fn standard_deviation_postal_code(self) -> Self {
        self.standard_deviation_postal_code_as("stdDev_postal_code")
    }

    pub fn standard_deviation_postal_code_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev("postal_code", alias)
    }

    pub fn square_root_of_population_standard_deviation_postal_code(self) -> Self {
        self.square_root_of_population_standard_deviation_postal_code_as("stdDevPop_postal_code")
    }

    pub fn square_root_of_population_standard_deviation_postal_code_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev_pop("postal_code", alias)
    }

    pub fn sample_variance_postal_code(self) -> Self {
        self.sample_variance_postal_code_as("varSamp_postal_code")
    }

    pub fn sample_variance_postal_code_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_samp("postal_code", alias)
    }

    pub fn sample_population_variance_postal_code(self) -> Self {
        self.sample_population_variance_postal_code_as("varPop_postal_code")
    }

    pub fn sample_population_variance_postal_code_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_pop("postal_code", alias)
    }

    pub fn unselect_postal_code(mut self) -> Self {
        self.query.projection.retain(|field| field != "postal_code");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "postal_code");
        self
    }


    pub fn with_postal_code(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "postal_code",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_postal_code_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "postal_code",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_postal_code_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("postal_code", value));
        self
    }



    pub fn with_postal_code_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("postal_code", value));
        self
    }

    pub fn with_postal_code_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("postal_code", value));
        self
    }

    pub fn with_postal_code_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("postal_code", value));
        self
    }

    pub fn with_postal_code_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("postal_code", value));
        self
    }

    pub fn with_postal_code_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("postal_code", value));
        self
    }

    pub fn with_postal_code_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("postal_code", lower, upper));
        self
    }

    pub fn with_postal_code_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "postal_code",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_postal_code_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "postal_code",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_postal_code_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "postal_code",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_postal_code_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("postal_code", value));
        self
    }

    pub fn with_postal_code_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("postal_code", value));
        self
    }

    pub fn with_postal_code_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("postal_code"));
        self
    }



    pub fn with_postal_code_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("postal_code"));
        self
    }


    pub fn order_by_postal_code_asc(mut self) -> Self {
        self.query = self.query.order_asc("postal_code");
        self
    }

    pub fn order_by_postal_code_desc(mut self) -> Self {
        self.query = self.query.order_desc("postal_code");
        self
    }

    pub fn order_by_postal_code_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("postal_code");
        self
    }

    pub fn order_by_postal_code_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("postal_code");
        self
    }


    pub fn select_country(mut self) -> Self {
        self.query = self.query.project("country");
        self
    }

    pub fn project_country(self) -> Self {
        self.select_country()
    }

    pub fn select_country_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_country_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_country_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("country", raw_sql_segment));
        self
    }

    pub fn group_by_country(self) -> Self {
        self.group_by("country")
    }

    pub fn group_by_country_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("country");
        request.query = request
            .query
            .project_expr(alias, Expr::column("country"));
        request
    }

    pub fn group_by_country_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("country")
            .aggregate_with_function("country", alias, function)
    }

    pub fn count_country(self) -> Self {
        self.count_country_as("country_count")
    }

    pub fn count_country_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("country", alias)
    }

    pub fn sum_country(self) -> Self {
        self.sum_country_as("sum_country")
    }

    pub fn sum_country_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("country", alias)
    }

    pub fn avg_country(self) -> Self {
        self.avg_country_as("avg_country")
    }

    pub fn avg_country_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("country", alias)
    }

    pub fn min_country(self) -> Self {
        self.min_country_as("min_country")
    }

    pub fn min_country_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("country", alias)
    }

    pub fn max_country(self) -> Self {
        self.max_country_as("max_country")
    }

    pub fn max_country_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("country", alias)
    }

    pub fn unselect_country(mut self) -> Self {
        self.query.projection.retain(|field| field != "country");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "country");
        self
    }


    pub fn with_country(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "country",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_country_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "country",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_country_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("country", value));
        self
    }



    pub fn with_country_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("country", value));
        self
    }

    pub fn with_country_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("country", value));
        self
    }

    pub fn with_country_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("country", value));
        self
    }

    pub fn with_country_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("country", value));
        self
    }

    pub fn with_country_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("country", value));
        self
    }

    pub fn with_country_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("country", lower, upper));
        self
    }

    pub fn with_country_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "country",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_country_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "country",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_country_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "country",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_country_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("country", value));
        self
    }

    pub fn with_country_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("country", value));
        self
    }

    pub fn with_country_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("country", value));
        self
    }

    pub fn with_country_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("country", value));
        self
    }

    pub fn with_country_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("country", value));
        self
    }

    pub fn with_country_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("country", value));
        self
    }

    pub fn with_country_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("country", value));
        self
    }
    pub fn with_country_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("country", value));
        self
    }

    pub fn with_country_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("country", value));
        self
    }

    pub fn with_country_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("country"));
        self
    }



    pub fn with_country_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("country"));
        self
    }


    pub fn order_by_country_asc(mut self) -> Self {
        self.query = self.query.order_asc("country");
        self
    }

    pub fn order_by_country_desc(mut self) -> Self {
        self.query = self.query.order_desc("country");
        self
    }

    pub fn order_by_country_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("country");
        self
    }

    pub fn order_by_country_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("country");
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
    pub fn street_is_value_123_main_st(self) -> Self {
        self.with_street_is("123 Main St")
    }

    pub fn with_street_is_value_123_main_st(self) -> Self {
        self.with_street_is("123 Main St")
    }



    pub fn with_street_is_not_value_123_main_st(self) -> Self {
        self.with_street_is_not("123 Main St")
    }



    pub fn city_is_new_york(self) -> Self {
        self.with_city_is("New York")
    }

    pub fn with_city_is_new_york(self) -> Self {
        self.with_city_is("New York")
    }



    pub fn with_city_is_not_new_york(self) -> Self {
        self.with_city_is_not("New York")
    }



    pub fn state_is_n_y(self) -> Self {
        self.with_state_is("NY")
    }

    pub fn with_state_is_n_y(self) -> Self {
        self.with_state_is("NY")
    }



    pub fn with_state_is_not_n_y(self) -> Self {
        self.with_state_is_not("NY")
    }



    pub fn postal_code_is_value_10001(self) -> Self {
        self.with_postal_code_is("10001")
    }

    pub fn with_postal_code_is_value_10001(self) -> Self {
        self.with_postal_code_is("10001")
    }



    pub fn with_postal_code_is_not_value_10001(self) -> Self {
        self.with_postal_code_is_not("10001")
    }



    pub fn country_is_us_a(self) -> Self {
        self.with_country_is("USA")
    }

    pub fn with_country_is_us_a(self) -> Self {
        self.with_country_is("USA")
    }



    pub fn with_country_is_not_us_a(self) -> Self {
        self.with_country_is_not("USA")
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




    pub fn have_moving_events_as_origin_address(self) -> Self {
        self.with_moving_event_list_as_origin_address_matching(SelectQuery::new("MovingEvent"))
    }

    pub fn have_no_moving_events_as_origin_address(self) -> Self {
        self.without_moving_event_list_as_origin_address_matching(SelectQuery::new("MovingEvent"))
    }

    pub fn with_moving_event_list_as_origin_address_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::MovingEvent as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "origin_address_id",
        ));
        self.relation_filters.push(RelationFilter::new("moving_event_list_as_origin_address", selection));
        self
    }

    pub fn without_moving_event_list_as_origin_address_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::MovingEvent as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "origin_address_id",
        ));
        self.relation_filters.push(RelationFilter::new("moving_event_list_as_origin_address", selection));
        self
    }

    pub fn select_moving_event_list_as_origin_address(mut self) -> Self {
        self.query = self.query.relation("moving_event_list_as_origin_address");
        self
    }

    pub fn select_moving_event_list_as_origin_address_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("moving_event_list_as_origin_address", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("moving_event_list_as_origin_address", selection));
        self
}

    pub fn have_moving_events_as_destination_address(self) -> Self {
        self.with_moving_event_list_as_destination_address_matching(SelectQuery::new("MovingEvent"))
    }

    pub fn have_no_moving_events_as_destination_address(self) -> Self {
        self.without_moving_event_list_as_destination_address_matching(SelectQuery::new("MovingEvent"))
    }

    pub fn with_moving_event_list_as_destination_address_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::MovingEvent as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "destination_address_id",
        ));
        self.relation_filters.push(RelationFilter::new("moving_event_list_as_destination_address", selection));
        self
    }

    pub fn without_moving_event_list_as_destination_address_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::MovingEvent as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "destination_address_id",
        ));
        self.relation_filters.push(RelationFilter::new("moving_event_list_as_destination_address", selection));
        self
    }

    pub fn select_moving_event_list_as_destination_address(mut self) -> Self {
        self.query = self.query.relation("moving_event_list_as_destination_address");
        self
    }

    pub fn select_moving_event_list_as_destination_address_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("moving_event_list_as_destination_address", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("moving_event_list_as_destination_address", selection));
        self
}

    pub fn have_routes_as_origin(self) -> Self {
        self.with_route_list_as_origin_matching(SelectQuery::new("Route"))
    }

    pub fn have_no_routes_as_origin(self) -> Self {
        self.without_route_list_as_origin_matching(SelectQuery::new("Route"))
    }

    pub fn with_route_list_as_origin_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::Route as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "origin_id",
        ));
        self.relation_filters.push(RelationFilter::new("route_list_as_origin", selection));
        self
    }

    pub fn without_route_list_as_origin_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::Route as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "origin_id",
        ));
        self.relation_filters.push(RelationFilter::new("route_list_as_origin", selection));
        self
    }

    pub fn select_route_list_as_origin(mut self) -> Self {
        self.query = self.query.relation("route_list_as_origin");
        self
    }

    pub fn select_route_list_as_origin_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("route_list_as_origin", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("route_list_as_origin", selection));
        self
}

    pub fn have_routes_as_destination(self) -> Self {
        self.with_route_list_as_destination_matching(SelectQuery::new("Route"))
    }

    pub fn have_no_routes_as_destination(self) -> Self {
        self.without_route_list_as_destination_matching(SelectQuery::new("Route"))
    }

    pub fn with_route_list_as_destination_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::Route as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "destination_id",
        ));
        self.relation_filters.push(RelationFilter::new("route_list_as_destination", selection));
        self
    }

    pub fn without_route_list_as_destination_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::Route as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "destination_id",
        ));
        self.relation_filters.push(RelationFilter::new("route_list_as_destination", selection));
        self
    }

    pub fn select_route_list_as_destination(mut self) -> Self {
        self.query = self.query.relation("route_list_as_destination");
        self
    }

    pub fn select_route_list_as_destination_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("route_list_as_destination", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("route_list_as_destination", selection));
        self
}
    pub fn count_moving_events_as_origin_address(self) -> Self {
        self.count_moving_events_as_origin_address_as("count_moving_events_as_origin_address")
    }

    pub fn count_moving_events_as_origin_address_as(self, alias: impl Into<String>) -> Self {
        self.count_moving_events_as_origin_address_with(alias, crate::Q::moving_events().unlimited())
    }

    pub fn count_moving_events_as_origin_address_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "moving_event_list_as_origin_address",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_moving_events_as_origin_address(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_moving_events_as_origin_address_as("refinements", request)
    }

    pub fn stats_from_moving_events_as_origin_address_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "moving_event_list_as_origin_address",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_moving_events_as_origin_address_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_moving_events_as_origin_address(request)
    }


    pub fn min_scheduled_date_of_moving_events_as_origin_address(self) -> Self {
        self.min_scheduled_date_of_moving_events_as_origin_address_as("min_scheduled_date_of_moving_events_as_origin_address", crate::Q::moving_events().unlimited())
    }

    pub fn min_scheduled_date_of_moving_events_as_origin_address_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_moving_events_as_origin_address_as(alias, request.into().into_query().min("scheduled_date", "min_scheduled_date"))
    }
    pub fn max_scheduled_date_of_moving_events_as_origin_address(self) -> Self {
        self.max_scheduled_date_of_moving_events_as_origin_address_as("max_scheduled_date_of_moving_events_as_origin_address", crate::Q::moving_events().unlimited())
    }

    pub fn max_scheduled_date_of_moving_events_as_origin_address_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_moving_events_as_origin_address_as(alias, request.into().into_query().max("scheduled_date", "max_scheduled_date"))
    }
    pub fn min_create_time_of_moving_events_as_origin_address(self) -> Self {
        self.min_create_time_of_moving_events_as_origin_address_as("min_create_time_of_moving_events_as_origin_address", crate::Q::moving_events().unlimited())
    }

    pub fn min_create_time_of_moving_events_as_origin_address_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_moving_events_as_origin_address_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_moving_events_as_origin_address(self) -> Self {
        self.max_create_time_of_moving_events_as_origin_address_as("max_create_time_of_moving_events_as_origin_address", crate::Q::moving_events().unlimited())
    }

    pub fn max_create_time_of_moving_events_as_origin_address_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_moving_events_as_origin_address_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_moving_events_as_origin_address(self) -> Self {
        self.min_update_time_of_moving_events_as_origin_address_as("min_update_time_of_moving_events_as_origin_address", crate::Q::moving_events().unlimited())
    }

    pub fn min_update_time_of_moving_events_as_origin_address_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_moving_events_as_origin_address_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_moving_events_as_origin_address(self) -> Self {
        self.max_update_time_of_moving_events_as_origin_address_as("max_update_time_of_moving_events_as_origin_address", crate::Q::moving_events().unlimited())
    }

    pub fn max_update_time_of_moving_events_as_origin_address_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_moving_events_as_origin_address_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }

    pub fn count_moving_events_as_destination_address(self) -> Self {
        self.count_moving_events_as_destination_address_as("count_moving_events_as_destination_address")
    }

    pub fn count_moving_events_as_destination_address_as(self, alias: impl Into<String>) -> Self {
        self.count_moving_events_as_destination_address_with(alias, crate::Q::moving_events().unlimited())
    }

    pub fn count_moving_events_as_destination_address_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "moving_event_list_as_destination_address",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_moving_events_as_destination_address(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_moving_events_as_destination_address_as("refinements", request)
    }

    pub fn stats_from_moving_events_as_destination_address_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "moving_event_list_as_destination_address",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_moving_events_as_destination_address_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_moving_events_as_destination_address(request)
    }


    pub fn min_scheduled_date_of_moving_events_as_destination_address(self) -> Self {
        self.min_scheduled_date_of_moving_events_as_destination_address_as("min_scheduled_date_of_moving_events_as_destination_address", crate::Q::moving_events().unlimited())
    }

    pub fn min_scheduled_date_of_moving_events_as_destination_address_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_moving_events_as_destination_address_as(alias, request.into().into_query().min("scheduled_date", "min_scheduled_date"))
    }
    pub fn max_scheduled_date_of_moving_events_as_destination_address(self) -> Self {
        self.max_scheduled_date_of_moving_events_as_destination_address_as("max_scheduled_date_of_moving_events_as_destination_address", crate::Q::moving_events().unlimited())
    }

    pub fn max_scheduled_date_of_moving_events_as_destination_address_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_moving_events_as_destination_address_as(alias, request.into().into_query().max("scheduled_date", "max_scheduled_date"))
    }
    pub fn min_create_time_of_moving_events_as_destination_address(self) -> Self {
        self.min_create_time_of_moving_events_as_destination_address_as("min_create_time_of_moving_events_as_destination_address", crate::Q::moving_events().unlimited())
    }

    pub fn min_create_time_of_moving_events_as_destination_address_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_moving_events_as_destination_address_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_moving_events_as_destination_address(self) -> Self {
        self.max_create_time_of_moving_events_as_destination_address_as("max_create_time_of_moving_events_as_destination_address", crate::Q::moving_events().unlimited())
    }

    pub fn max_create_time_of_moving_events_as_destination_address_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_moving_events_as_destination_address_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_moving_events_as_destination_address(self) -> Self {
        self.min_update_time_of_moving_events_as_destination_address_as("min_update_time_of_moving_events_as_destination_address", crate::Q::moving_events().unlimited())
    }

    pub fn min_update_time_of_moving_events_as_destination_address_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_moving_events_as_destination_address_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_moving_events_as_destination_address(self) -> Self {
        self.max_update_time_of_moving_events_as_destination_address_as("max_update_time_of_moving_events_as_destination_address", crate::Q::moving_events().unlimited())
    }

    pub fn max_update_time_of_moving_events_as_destination_address_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_moving_events_as_destination_address_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }

    pub fn count_routes_as_origin(self) -> Self {
        self.count_routes_as_origin_as("count_routes_as_origin")
    }

    pub fn count_routes_as_origin_as(self, alias: impl Into<String>) -> Self {
        self.count_routes_as_origin_with(alias, crate::Q::routes().unlimited())
    }

    pub fn count_routes_as_origin_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "route_list_as_origin",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_routes_as_origin(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_origin_as("refinements", request)
    }

    pub fn stats_from_routes_as_origin_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "route_list_as_origin",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_routes_as_origin_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_origin(request)
    }


    pub fn sum_distance_km_of_routes_as_origin(self) -> Self {
        self.sum_distance_km_of_routes_as_origin_as("sum_distance_km_of_routes_as_origin", crate::Q::routes().unlimited())
    }

    pub fn sum_distance_km_of_routes_as_origin_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_origin_as(alias, request.into().into_query().sum("distance_km", "sum_distance_km"))
    }
    pub fn min_distance_km_of_routes_as_origin(self) -> Self {
        self.min_distance_km_of_routes_as_origin_as("min_distance_km_of_routes_as_origin", crate::Q::routes().unlimited())
    }

    pub fn min_distance_km_of_routes_as_origin_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_origin_as(alias, request.into().into_query().min("distance_km", "min_distance_km"))
    }
    pub fn max_distance_km_of_routes_as_origin(self) -> Self {
        self.max_distance_km_of_routes_as_origin_as("max_distance_km_of_routes_as_origin", crate::Q::routes().unlimited())
    }

    pub fn max_distance_km_of_routes_as_origin_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_origin_as(alias, request.into().into_query().max("distance_km", "max_distance_km"))
    }
    pub fn avg_distance_km_of_routes_as_origin(self) -> Self {
        self.avg_distance_km_of_routes_as_origin_as("avg_distance_km_of_routes_as_origin", crate::Q::routes().unlimited())
    }

    pub fn avg_distance_km_of_routes_as_origin_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_origin_as(alias, request.into().into_query().avg("distance_km", "avg_distance_km"))
    }
    pub fn standard_deviation_distance_km_of_routes_as_origin(self) -> Self {
        self.standard_deviation_distance_km_of_routes_as_origin_as("standard_deviation_distance_km_of_routes_as_origin", crate::Q::routes().unlimited())
    }

    pub fn standard_deviation_distance_km_of_routes_as_origin_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_origin_as(alias, request.into().into_query().stddev("distance_km", "stdDev_distance_km"))
    }
    pub fn square_root_of_population_standard_deviation_distance_km_of_routes_as_origin(self) -> Self {
        self.square_root_of_population_standard_deviation_distance_km_of_routes_as_origin_as("square_root_of_population_standard_deviation_distance_km_of_routes_as_origin", crate::Q::routes().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_distance_km_of_routes_as_origin_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_origin_as(alias, request.into().into_query().stddev_pop("distance_km", "stdDevPop_distance_km"))
    }
    pub fn sample_variance_distance_km_of_routes_as_origin(self) -> Self {
        self.sample_variance_distance_km_of_routes_as_origin_as("sample_variance_distance_km_of_routes_as_origin", crate::Q::routes().unlimited())
    }

    pub fn sample_variance_distance_km_of_routes_as_origin_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_origin_as(alias, request.into().into_query().var_samp("distance_km", "varSamp_distance_km"))
    }
    pub fn sample_population_variance_distance_km_of_routes_as_origin(self) -> Self {
        self.sample_population_variance_distance_km_of_routes_as_origin_as("sample_population_variance_distance_km_of_routes_as_origin", crate::Q::routes().unlimited())
    }

    pub fn sample_population_variance_distance_km_of_routes_as_origin_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_origin_as(alias, request.into().into_query().var_pop("distance_km", "varPop_distance_km"))
    }
    pub fn sum_estimated_time_minutes_of_routes_as_origin(self) -> Self {
        self.sum_estimated_time_minutes_of_routes_as_origin_as("sum_estimated_time_minutes_of_routes_as_origin", crate::Q::routes().unlimited())
    }

    pub fn sum_estimated_time_minutes_of_routes_as_origin_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_origin_as(alias, request.into().into_query().sum("estimated_time_minutes", "sum_estimated_time_minutes"))
    }
    pub fn min_estimated_time_minutes_of_routes_as_origin(self) -> Self {
        self.min_estimated_time_minutes_of_routes_as_origin_as("min_estimated_time_minutes_of_routes_as_origin", crate::Q::routes().unlimited())
    }

    pub fn min_estimated_time_minutes_of_routes_as_origin_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_origin_as(alias, request.into().into_query().min("estimated_time_minutes", "min_estimated_time_minutes"))
    }
    pub fn max_estimated_time_minutes_of_routes_as_origin(self) -> Self {
        self.max_estimated_time_minutes_of_routes_as_origin_as("max_estimated_time_minutes_of_routes_as_origin", crate::Q::routes().unlimited())
    }

    pub fn max_estimated_time_minutes_of_routes_as_origin_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_origin_as(alias, request.into().into_query().max("estimated_time_minutes", "max_estimated_time_minutes"))
    }
    pub fn avg_estimated_time_minutes_of_routes_as_origin(self) -> Self {
        self.avg_estimated_time_minutes_of_routes_as_origin_as("avg_estimated_time_minutes_of_routes_as_origin", crate::Q::routes().unlimited())
    }

    pub fn avg_estimated_time_minutes_of_routes_as_origin_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_origin_as(alias, request.into().into_query().avg("estimated_time_minutes", "avg_estimated_time_minutes"))
    }
    pub fn standard_deviation_estimated_time_minutes_of_routes_as_origin(self) -> Self {
        self.standard_deviation_estimated_time_minutes_of_routes_as_origin_as("standard_deviation_estimated_time_minutes_of_routes_as_origin", crate::Q::routes().unlimited())
    }

    pub fn standard_deviation_estimated_time_minutes_of_routes_as_origin_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_origin_as(alias, request.into().into_query().stddev("estimated_time_minutes", "stdDev_estimated_time_minutes"))
    }
    pub fn square_root_of_population_standard_deviation_estimated_time_minutes_of_routes_as_origin(self) -> Self {
        self.square_root_of_population_standard_deviation_estimated_time_minutes_of_routes_as_origin_as("square_root_of_population_standard_deviation_estimated_time_minutes_of_routes_as_origin", crate::Q::routes().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_estimated_time_minutes_of_routes_as_origin_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_origin_as(alias, request.into().into_query().stddev_pop("estimated_time_minutes", "stdDevPop_estimated_time_minutes"))
    }
    pub fn sample_variance_estimated_time_minutes_of_routes_as_origin(self) -> Self {
        self.sample_variance_estimated_time_minutes_of_routes_as_origin_as("sample_variance_estimated_time_minutes_of_routes_as_origin", crate::Q::routes().unlimited())
    }

    pub fn sample_variance_estimated_time_minutes_of_routes_as_origin_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_origin_as(alias, request.into().into_query().var_samp("estimated_time_minutes", "varSamp_estimated_time_minutes"))
    }
    pub fn sample_population_variance_estimated_time_minutes_of_routes_as_origin(self) -> Self {
        self.sample_population_variance_estimated_time_minutes_of_routes_as_origin_as("sample_population_variance_estimated_time_minutes_of_routes_as_origin", crate::Q::routes().unlimited())
    }

    pub fn sample_population_variance_estimated_time_minutes_of_routes_as_origin_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_origin_as(alias, request.into().into_query().var_pop("estimated_time_minutes", "varPop_estimated_time_minutes"))
    }
    pub fn min_create_time_of_routes_as_origin(self) -> Self {
        self.min_create_time_of_routes_as_origin_as("min_create_time_of_routes_as_origin", crate::Q::routes().unlimited())
    }

    pub fn min_create_time_of_routes_as_origin_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_origin_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_routes_as_origin(self) -> Self {
        self.max_create_time_of_routes_as_origin_as("max_create_time_of_routes_as_origin", crate::Q::routes().unlimited())
    }

    pub fn max_create_time_of_routes_as_origin_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_origin_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_routes_as_origin(self) -> Self {
        self.min_update_time_of_routes_as_origin_as("min_update_time_of_routes_as_origin", crate::Q::routes().unlimited())
    }

    pub fn min_update_time_of_routes_as_origin_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_origin_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_routes_as_origin(self) -> Self {
        self.max_update_time_of_routes_as_origin_as("max_update_time_of_routes_as_origin", crate::Q::routes().unlimited())
    }

    pub fn max_update_time_of_routes_as_origin_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_origin_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }

    pub fn count_routes_as_destination(self) -> Self {
        self.count_routes_as_destination_as("count_routes_as_destination")
    }

    pub fn count_routes_as_destination_as(self, alias: impl Into<String>) -> Self {
        self.count_routes_as_destination_with(alias, crate::Q::routes().unlimited())
    }

    pub fn count_routes_as_destination_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "route_list_as_destination",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_routes_as_destination(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_destination_as("refinements", request)
    }

    pub fn stats_from_routes_as_destination_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "route_list_as_destination",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_routes_as_destination_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_destination(request)
    }


    pub fn sum_distance_km_of_routes_as_destination(self) -> Self {
        self.sum_distance_km_of_routes_as_destination_as("sum_distance_km_of_routes_as_destination", crate::Q::routes().unlimited())
    }

    pub fn sum_distance_km_of_routes_as_destination_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_destination_as(alias, request.into().into_query().sum("distance_km", "sum_distance_km"))
    }
    pub fn min_distance_km_of_routes_as_destination(self) -> Self {
        self.min_distance_km_of_routes_as_destination_as("min_distance_km_of_routes_as_destination", crate::Q::routes().unlimited())
    }

    pub fn min_distance_km_of_routes_as_destination_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_destination_as(alias, request.into().into_query().min("distance_km", "min_distance_km"))
    }
    pub fn max_distance_km_of_routes_as_destination(self) -> Self {
        self.max_distance_km_of_routes_as_destination_as("max_distance_km_of_routes_as_destination", crate::Q::routes().unlimited())
    }

    pub fn max_distance_km_of_routes_as_destination_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_destination_as(alias, request.into().into_query().max("distance_km", "max_distance_km"))
    }
    pub fn avg_distance_km_of_routes_as_destination(self) -> Self {
        self.avg_distance_km_of_routes_as_destination_as("avg_distance_km_of_routes_as_destination", crate::Q::routes().unlimited())
    }

    pub fn avg_distance_km_of_routes_as_destination_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_destination_as(alias, request.into().into_query().avg("distance_km", "avg_distance_km"))
    }
    pub fn standard_deviation_distance_km_of_routes_as_destination(self) -> Self {
        self.standard_deviation_distance_km_of_routes_as_destination_as("standard_deviation_distance_km_of_routes_as_destination", crate::Q::routes().unlimited())
    }

    pub fn standard_deviation_distance_km_of_routes_as_destination_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_destination_as(alias, request.into().into_query().stddev("distance_km", "stdDev_distance_km"))
    }
    pub fn square_root_of_population_standard_deviation_distance_km_of_routes_as_destination(self) -> Self {
        self.square_root_of_population_standard_deviation_distance_km_of_routes_as_destination_as("square_root_of_population_standard_deviation_distance_km_of_routes_as_destination", crate::Q::routes().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_distance_km_of_routes_as_destination_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_destination_as(alias, request.into().into_query().stddev_pop("distance_km", "stdDevPop_distance_km"))
    }
    pub fn sample_variance_distance_km_of_routes_as_destination(self) -> Self {
        self.sample_variance_distance_km_of_routes_as_destination_as("sample_variance_distance_km_of_routes_as_destination", crate::Q::routes().unlimited())
    }

    pub fn sample_variance_distance_km_of_routes_as_destination_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_destination_as(alias, request.into().into_query().var_samp("distance_km", "varSamp_distance_km"))
    }
    pub fn sample_population_variance_distance_km_of_routes_as_destination(self) -> Self {
        self.sample_population_variance_distance_km_of_routes_as_destination_as("sample_population_variance_distance_km_of_routes_as_destination", crate::Q::routes().unlimited())
    }

    pub fn sample_population_variance_distance_km_of_routes_as_destination_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_destination_as(alias, request.into().into_query().var_pop("distance_km", "varPop_distance_km"))
    }
    pub fn sum_estimated_time_minutes_of_routes_as_destination(self) -> Self {
        self.sum_estimated_time_minutes_of_routes_as_destination_as("sum_estimated_time_minutes_of_routes_as_destination", crate::Q::routes().unlimited())
    }

    pub fn sum_estimated_time_minutes_of_routes_as_destination_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_destination_as(alias, request.into().into_query().sum("estimated_time_minutes", "sum_estimated_time_minutes"))
    }
    pub fn min_estimated_time_minutes_of_routes_as_destination(self) -> Self {
        self.min_estimated_time_minutes_of_routes_as_destination_as("min_estimated_time_minutes_of_routes_as_destination", crate::Q::routes().unlimited())
    }

    pub fn min_estimated_time_minutes_of_routes_as_destination_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_destination_as(alias, request.into().into_query().min("estimated_time_minutes", "min_estimated_time_minutes"))
    }
    pub fn max_estimated_time_minutes_of_routes_as_destination(self) -> Self {
        self.max_estimated_time_minutes_of_routes_as_destination_as("max_estimated_time_minutes_of_routes_as_destination", crate::Q::routes().unlimited())
    }

    pub fn max_estimated_time_minutes_of_routes_as_destination_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_destination_as(alias, request.into().into_query().max("estimated_time_minutes", "max_estimated_time_minutes"))
    }
    pub fn avg_estimated_time_minutes_of_routes_as_destination(self) -> Self {
        self.avg_estimated_time_minutes_of_routes_as_destination_as("avg_estimated_time_minutes_of_routes_as_destination", crate::Q::routes().unlimited())
    }

    pub fn avg_estimated_time_minutes_of_routes_as_destination_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_destination_as(alias, request.into().into_query().avg("estimated_time_minutes", "avg_estimated_time_minutes"))
    }
    pub fn standard_deviation_estimated_time_minutes_of_routes_as_destination(self) -> Self {
        self.standard_deviation_estimated_time_minutes_of_routes_as_destination_as("standard_deviation_estimated_time_minutes_of_routes_as_destination", crate::Q::routes().unlimited())
    }

    pub fn standard_deviation_estimated_time_minutes_of_routes_as_destination_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_destination_as(alias, request.into().into_query().stddev("estimated_time_minutes", "stdDev_estimated_time_minutes"))
    }
    pub fn square_root_of_population_standard_deviation_estimated_time_minutes_of_routes_as_destination(self) -> Self {
        self.square_root_of_population_standard_deviation_estimated_time_minutes_of_routes_as_destination_as("square_root_of_population_standard_deviation_estimated_time_minutes_of_routes_as_destination", crate::Q::routes().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_estimated_time_minutes_of_routes_as_destination_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_destination_as(alias, request.into().into_query().stddev_pop("estimated_time_minutes", "stdDevPop_estimated_time_minutes"))
    }
    pub fn sample_variance_estimated_time_minutes_of_routes_as_destination(self) -> Self {
        self.sample_variance_estimated_time_minutes_of_routes_as_destination_as("sample_variance_estimated_time_minutes_of_routes_as_destination", crate::Q::routes().unlimited())
    }

    pub fn sample_variance_estimated_time_minutes_of_routes_as_destination_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_destination_as(alias, request.into().into_query().var_samp("estimated_time_minutes", "varSamp_estimated_time_minutes"))
    }
    pub fn sample_population_variance_estimated_time_minutes_of_routes_as_destination(self) -> Self {
        self.sample_population_variance_estimated_time_minutes_of_routes_as_destination_as("sample_population_variance_estimated_time_minutes_of_routes_as_destination", crate::Q::routes().unlimited())
    }

    pub fn sample_population_variance_estimated_time_minutes_of_routes_as_destination_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_destination_as(alias, request.into().into_query().var_pop("estimated_time_minutes", "varPop_estimated_time_minutes"))
    }
    pub fn min_create_time_of_routes_as_destination(self) -> Self {
        self.min_create_time_of_routes_as_destination_as("min_create_time_of_routes_as_destination", crate::Q::routes().unlimited())
    }

    pub fn min_create_time_of_routes_as_destination_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_destination_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_routes_as_destination(self) -> Self {
        self.max_create_time_of_routes_as_destination_as("max_create_time_of_routes_as_destination", crate::Q::routes().unlimited())
    }

    pub fn max_create_time_of_routes_as_destination_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_destination_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_routes_as_destination(self) -> Self {
        self.min_update_time_of_routes_as_destination_as("min_update_time_of_routes_as_destination", crate::Q::routes().unlimited())
    }

    pub fn min_update_time_of_routes_as_destination_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_destination_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_routes_as_destination(self) -> Self {
        self.max_update_time_of_routes_as_destination_as("max_update_time_of_routes_as_destination", crate::Q::routes().unlimited())
    }

    pub fn max_update_time_of_routes_as_destination_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_routes_as_destination_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }
}

impl<R> Default for AddressRequest<R> {
    fn default() -> Self {
        Self::new()
    }
}

impl<R> From< AddressRequest<R> > for SelectQuery {
    fn from(request: AddressRequest<R>) -> Self {
        QuerySelection::from(request).into_query()
    }
}

impl<R> From< AddressRequest<R> > for QuerySelection {
    fn from(request: AddressRequest<R>) -> Self {
        Self {
            query: request.query,
            relation_selections: request.relation_selections,
            relation_filters: request.relation_filters,
            child_enhancements: request.child_enhancements,
            query_options: request.query_options,
        }
    }
}


impl<'a, C> crate::request_support::AuditedSave<'a, C> for teaql_core::Audited<crate::Address> 
where C: crate::request_support::TeaqlRepositoryProvider + ?Sized + 'a
{
    type Error = crate::TeaqlDataServiceError<C::AddressRepository<'a>>;
    fn save(self, ctx: &'a C) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<teaql_runtime::GraphNode, Self::Error>> + '_>> {
        Box::pin(async move { self.into_entity().save(ctx).await })
    }
}

impl<R: teaql_core::Entity> crate::PurposedQuery<AddressRequest<R>> {
    pub fn new_entity<C>(&self, ctx: &C) -> crate::Address
    where
        C: crate::TeaqlRuntime + ?Sized,
    {
        crate::Address::runtime_new(ctx.user_context().entity_root())
    }

    fn into_inner_with_trace(mut self) -> AddressRequest<R> {
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
    ) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::AddressRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_page(ctx, offset, limit).await
    }

    pub async fn execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, crate::request_support::TeaqlDataServiceError<C::AddressRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_exists(ctx).await
    }

    pub async fn execute_for_list<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::AddressRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_list(ctx).await
    }

    /// Execute query in streaming mode (chunked).
    /// Returns a Vec of StreamChunk, each containing up to chunk_size rows.
    /// Set chunk size via .stream(chunk_size) or .stream_default() on the query.
    pub async fn execute_for_stream<'a, C>(self, ctx: &'a C) -> Result<Vec<teaql_data_service::StreamChunk>, crate::request_support::TeaqlDataServiceError<C::AddressRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_stream(ctx).await
    }

    pub async fn execute_for_first<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::AddressRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_first(ctx).await
    }

    pub async fn execute_for_one<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::AddressRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_one(ctx).await
    }


    pub async fn execute_for_records<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::AddressRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_records(ctx).await
    }

    pub async fn execute_for_record<'a, C>(self, ctx: &'a C) -> Result<Option<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::AddressRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_record(ctx).await
    }

    pub async fn execute_for_count<'a, C>(self, ctx: &'a C) -> Result<u64, crate::request_support::TeaqlDataServiceError<C::AddressRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_count(ctx).await
    }
}
