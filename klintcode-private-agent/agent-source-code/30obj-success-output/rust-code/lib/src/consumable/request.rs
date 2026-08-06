use std::marker::PhantomData;

use serde_json::Value as JsonValue;
use teaql_core::{Aggregate, AggregateFunction, EntityDescriptor, Expr, Record, SelectQuery, SmartList};
use teaql_runtime::{DataServiceError, RuntimeError};

use crate::request_support::*;

impl EntityReference for crate::Consumable {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(&self)
    }
}

impl EntityReference for &crate::Consumable {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(self)
    }
}

// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/consumable
#[derive(Debug)]
pub struct ConsumableRequest<R = crate::Consumable> {
    query: SelectQuery,
    relation_selections: Vec<RelationSelection>,
    relation_filters: Vec<RelationFilter>,
    child_enhancements: Vec<QuerySelection>,
    query_options: QueryOptions,
    marker: PhantomData<R>,
}

impl<R> Clone for ConsumableRequest<R> {
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

impl<R> ConsumableRequest<R> {
    pub(crate) fn new() -> Self {
        Self {
            query: SelectQuery::new("Consumable")
                .project("id")
                .project("version"),
            relation_selections: Vec::new(),
            relation_filters: Vec::new(),
            child_enhancements: Vec::new(),
            query_options: QueryOptions::default(),
            marker: PhantomData,
        }
    }

    pub fn return_type<T>(self) -> ConsumableRequest<T> {
        ConsumableRequest {
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::ConsumableRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
        R: teaql_core::Entity,
    {
        let repository = ctx
            .consumable_repository()
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
    ) -> Result<Vec<teaql_data_service::StreamChunk>, TeaqlDataServiceError<C::ConsumableRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .consumable_repository()
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::ConsumableRepository<'a>>>
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::ConsumableRepository<'a>>>
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::ConsumableRepository<'a>>>
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
    ) -> Result<u64, TeaqlDataServiceError<C::ConsumableRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .consumable_repository()
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
            .ok_or_else(|| DataServiceError::Runtime(RuntimeError::Graph(format!("count result for Consumable is missing or not numeric"))))
    }

    pub(crate) async fn _execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, TeaqlDataServiceError<C::ConsumableRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .consumable_repository()
            .map_err(|err| DataServiceError::Runtime(RuntimeError::Graph(err.to_string())))?;
        let mut query = self.query.limit(1);
        query.relations.clear();
        let rows = repository.fetch_all(&query).await?;
        Ok(!rows.is_empty())
    }

    pub(crate) async fn _execute_for_records<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<SmartList<Record>, TeaqlDataServiceError<C::ConsumableRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .consumable_repository()
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
    ) -> Result<Option<Record>, TeaqlDataServiceError<C::ConsumableRepository<'a>>>
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
            "name" => Some("name"),
            "item_type" => Some("item_type"),
            "unit_cost" => Some("unit_cost"),
            "quantity_in_stock" => Some("quantity_in_stock"),
            "reorder_level" => Some("reorder_level"),
            "create_time" => Some("create_time"),
            "update_time" => Some("update_time"),
            "version" => Some("version"),
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
        self.query = self.query.project("name");
        self.query = self.query.project("item_type");
        self.query = self.query.project("unit_cost");
        self.query = self.query.project("quantity_in_stock");
        self.query = self.query.project("reorder_level");
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


    pub fn select_name(mut self) -> Self {
        self.query = self.query.project("name");
        self
    }

    pub fn project_name(self) -> Self {
        self.select_name()
    }

    pub fn select_name_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_name_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_name_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("name", raw_sql_segment));
        self
    }

    pub fn group_by_name(self) -> Self {
        self.group_by("name")
    }

    pub fn group_by_name_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("name");
        request.query = request
            .query
            .project_expr(alias, Expr::column("name"));
        request
    }

    pub fn group_by_name_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("name")
            .aggregate_with_function("name", alias, function)
    }

    pub fn count_name(self) -> Self {
        self.count_name_as("name_count")
    }

    pub fn count_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("name", alias)
    }

    pub fn sum_name(self) -> Self {
        self.sum_name_as("sum_name")
    }

    pub fn sum_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("name", alias)
    }

    pub fn avg_name(self) -> Self {
        self.avg_name_as("avg_name")
    }

    pub fn avg_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("name", alias)
    }

    pub fn min_name(self) -> Self {
        self.min_name_as("min_name")
    }

    pub fn min_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("name", alias)
    }

    pub fn max_name(self) -> Self {
        self.max_name_as("max_name")
    }

    pub fn max_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("name", alias)
    }

    pub fn unselect_name(mut self) -> Self {
        self.query.projection.retain(|field| field != "name");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "name");
        self
    }


    pub fn with_name(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "name",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_name_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "name",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_name_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("name", value));
        self
    }



    pub fn with_name_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("name", value));
        self
    }

    pub fn with_name_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("name", value));
        self
    }

    pub fn with_name_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("name", value));
        self
    }

    pub fn with_name_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("name", value));
        self
    }

    pub fn with_name_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("name", value));
        self
    }

    pub fn with_name_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("name", lower, upper));
        self
    }

    pub fn with_name_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "name",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_name_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "name",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_name_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "name",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_name_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("name", value));
        self
    }

    pub fn with_name_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("name", value));
        self
    }

    pub fn with_name_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("name", value));
        self
    }

    pub fn with_name_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("name", value));
        self
    }

    pub fn with_name_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("name", value));
        self
    }

    pub fn with_name_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("name", value));
        self
    }

    pub fn with_name_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("name", value));
        self
    }
    pub fn with_name_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("name", value));
        self
    }

    pub fn with_name_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("name", value));
        self
    }

    pub fn with_name_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("name"));
        self
    }



    pub fn with_name_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("name"));
        self
    }


    pub fn order_by_name_asc(mut self) -> Self {
        self.query = self.query.order_asc("name");
        self
    }

    pub fn order_by_name_desc(mut self) -> Self {
        self.query = self.query.order_desc("name");
        self
    }

    pub fn order_by_name_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("name");
        self
    }

    pub fn order_by_name_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("name");
        self
    }


    pub fn select_item_type(mut self) -> Self {
        self.query = self.query.project("item_type");
        self
    }

    pub fn project_item_type(self) -> Self {
        self.select_item_type()
    }

    pub fn select_item_type_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_item_type_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_item_type_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("item_type", raw_sql_segment));
        self
    }

    pub fn group_by_item_type(self) -> Self {
        self.group_by("item_type")
    }

    pub fn group_by_item_type_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("item_type");
        request.query = request
            .query
            .project_expr(alias, Expr::column("item_type"));
        request
    }

    pub fn group_by_item_type_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("item_type")
            .aggregate_with_function("item_type", alias, function)
    }

    pub fn count_item_type(self) -> Self {
        self.count_item_type_as("item_type_count")
    }

    pub fn count_item_type_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("item_type", alias)
    }

    pub fn sum_item_type(self) -> Self {
        self.sum_item_type_as("sum_item_type")
    }

    pub fn sum_item_type_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("item_type", alias)
    }

    pub fn avg_item_type(self) -> Self {
        self.avg_item_type_as("avg_item_type")
    }

    pub fn avg_item_type_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("item_type", alias)
    }

    pub fn min_item_type(self) -> Self {
        self.min_item_type_as("min_item_type")
    }

    pub fn min_item_type_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("item_type", alias)
    }

    pub fn max_item_type(self) -> Self {
        self.max_item_type_as("max_item_type")
    }

    pub fn max_item_type_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("item_type", alias)
    }

    pub fn unselect_item_type(mut self) -> Self {
        self.query.projection.retain(|field| field != "item_type");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "item_type");
        self
    }


    pub fn with_item_type(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "item_type",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_item_type_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "item_type",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_item_type_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("item_type", value));
        self
    }



    pub fn with_item_type_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("item_type", value));
        self
    }

    pub fn with_item_type_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("item_type", value));
        self
    }

    pub fn with_item_type_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("item_type", value));
        self
    }

    pub fn with_item_type_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("item_type", value));
        self
    }

    pub fn with_item_type_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("item_type", value));
        self
    }

    pub fn with_item_type_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("item_type", lower, upper));
        self
    }

    pub fn with_item_type_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "item_type",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_item_type_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "item_type",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_item_type_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "item_type",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_item_type_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("item_type", value));
        self
    }

    pub fn with_item_type_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("item_type", value));
        self
    }

    pub fn with_item_type_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("item_type", value));
        self
    }

    pub fn with_item_type_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("item_type", value));
        self
    }

    pub fn with_item_type_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("item_type", value));
        self
    }

    pub fn with_item_type_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("item_type", value));
        self
    }

    pub fn with_item_type_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("item_type", value));
        self
    }
    pub fn with_item_type_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("item_type", value));
        self
    }

    pub fn with_item_type_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("item_type", value));
        self
    }

    pub fn with_item_type_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("item_type"));
        self
    }



    pub fn with_item_type_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("item_type"));
        self
    }


    pub fn order_by_item_type_asc(mut self) -> Self {
        self.query = self.query.order_asc("item_type");
        self
    }

    pub fn order_by_item_type_desc(mut self) -> Self {
        self.query = self.query.order_desc("item_type");
        self
    }

    pub fn order_by_item_type_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("item_type");
        self
    }

    pub fn order_by_item_type_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("item_type");
        self
    }


    pub fn select_unit_cost(mut self) -> Self {
        self.query = self.query.project("unit_cost");
        self
    }

    pub fn project_unit_cost(self) -> Self {
        self.select_unit_cost()
    }

    pub fn select_unit_cost_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_unit_cost_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_unit_cost_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("unit_cost", raw_sql_segment));
        self
    }

    pub fn select_unit_cost_with_function(self, function: AggregateFunction) -> Self {
        self.select_unit_cost_as_with_function("unit_cost", function)
    }

    pub fn select_unit_cost_as_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.aggregate_with_function("unit_cost", alias, function)
    }

    pub fn group_by_unit_cost(self) -> Self {
        self.group_by("unit_cost")
    }

    pub fn group_by_unit_cost_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("unit_cost");
        request.query = request
            .query
            .project_expr(alias, Expr::column("unit_cost"));
        request
    }

    pub fn group_by_unit_cost_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("unit_cost")
            .aggregate_with_function("unit_cost", alias, function)
    }

    pub fn count_unit_cost(self) -> Self {
        self.count_unit_cost_as("unit_cost_count")
    }

    pub fn count_unit_cost_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("unit_cost", alias)
    }

    pub fn sum_unit_cost(self) -> Self {
        self.sum_unit_cost_as("sum_unit_cost")
    }

    pub fn sum_unit_cost_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("unit_cost", alias)
    }

    pub fn avg_unit_cost(self) -> Self {
        self.avg_unit_cost_as("avg_unit_cost")
    }

    pub fn avg_unit_cost_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("unit_cost", alias)
    }

    pub fn min_unit_cost(self) -> Self {
        self.min_unit_cost_as("min_unit_cost")
    }

    pub fn min_unit_cost_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("unit_cost", alias)
    }

    pub fn max_unit_cost(self) -> Self {
        self.max_unit_cost_as("max_unit_cost")
    }

    pub fn max_unit_cost_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("unit_cost", alias)
    }

    pub fn standard_deviation_unit_cost(self) -> Self {
        self.standard_deviation_unit_cost_as("stdDev_unit_cost")
    }

    pub fn standard_deviation_unit_cost_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev("unit_cost", alias)
    }

    pub fn square_root_of_population_standard_deviation_unit_cost(self) -> Self {
        self.square_root_of_population_standard_deviation_unit_cost_as("stdDevPop_unit_cost")
    }

    pub fn square_root_of_population_standard_deviation_unit_cost_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev_pop("unit_cost", alias)
    }

    pub fn sample_variance_unit_cost(self) -> Self {
        self.sample_variance_unit_cost_as("varSamp_unit_cost")
    }

    pub fn sample_variance_unit_cost_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_samp("unit_cost", alias)
    }

    pub fn sample_population_variance_unit_cost(self) -> Self {
        self.sample_population_variance_unit_cost_as("varPop_unit_cost")
    }

    pub fn sample_population_variance_unit_cost_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_pop("unit_cost", alias)
    }

    pub fn unselect_unit_cost(mut self) -> Self {
        self.query.projection.retain(|field| field != "unit_cost");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "unit_cost");
        self
    }


    pub fn with_unit_cost(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "unit_cost",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_unit_cost_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "unit_cost",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_unit_cost_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("unit_cost", value));
        self
    }



    pub fn with_unit_cost_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("unit_cost", value));
        self
    }

    pub fn with_unit_cost_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("unit_cost", value));
        self
    }

    pub fn with_unit_cost_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("unit_cost", value));
        self
    }

    pub fn with_unit_cost_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("unit_cost", value));
        self
    }

    pub fn with_unit_cost_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("unit_cost", value));
        self
    }

    pub fn with_unit_cost_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("unit_cost", lower, upper));
        self
    }

    pub fn with_unit_cost_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "unit_cost",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_unit_cost_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "unit_cost",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_unit_cost_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "unit_cost",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_unit_cost_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("unit_cost", value));
        self
    }

    pub fn with_unit_cost_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("unit_cost", value));
        self
    }

    pub fn with_unit_cost_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("unit_cost"));
        self
    }



    pub fn with_unit_cost_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("unit_cost"));
        self
    }


    pub fn order_by_unit_cost_asc(mut self) -> Self {
        self.query = self.query.order_asc("unit_cost");
        self
    }

    pub fn order_by_unit_cost_desc(mut self) -> Self {
        self.query = self.query.order_desc("unit_cost");
        self
    }

    pub fn order_by_unit_cost_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("unit_cost");
        self
    }

    pub fn order_by_unit_cost_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("unit_cost");
        self
    }


    pub fn select_quantity_in_stock(mut self) -> Self {
        self.query = self.query.project("quantity_in_stock");
        self
    }

    pub fn project_quantity_in_stock(self) -> Self {
        self.select_quantity_in_stock()
    }

    pub fn select_quantity_in_stock_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_quantity_in_stock_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_quantity_in_stock_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("quantity_in_stock", raw_sql_segment));
        self
    }

    pub fn select_quantity_in_stock_with_function(self, function: AggregateFunction) -> Self {
        self.select_quantity_in_stock_as_with_function("quantity_in_stock", function)
    }

    pub fn select_quantity_in_stock_as_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.aggregate_with_function("quantity_in_stock", alias, function)
    }

    pub fn group_by_quantity_in_stock(self) -> Self {
        self.group_by("quantity_in_stock")
    }

    pub fn group_by_quantity_in_stock_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("quantity_in_stock");
        request.query = request
            .query
            .project_expr(alias, Expr::column("quantity_in_stock"));
        request
    }

    pub fn group_by_quantity_in_stock_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("quantity_in_stock")
            .aggregate_with_function("quantity_in_stock", alias, function)
    }

    pub fn count_quantity_in_stock(self) -> Self {
        self.count_quantity_in_stock_as("quantity_in_stock_count")
    }

    pub fn count_quantity_in_stock_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("quantity_in_stock", alias)
    }

    pub fn sum_quantity_in_stock(self) -> Self {
        self.sum_quantity_in_stock_as("sum_quantity_in_stock")
    }

    pub fn sum_quantity_in_stock_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("quantity_in_stock", alias)
    }

    pub fn avg_quantity_in_stock(self) -> Self {
        self.avg_quantity_in_stock_as("avg_quantity_in_stock")
    }

    pub fn avg_quantity_in_stock_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("quantity_in_stock", alias)
    }

    pub fn min_quantity_in_stock(self) -> Self {
        self.min_quantity_in_stock_as("min_quantity_in_stock")
    }

    pub fn min_quantity_in_stock_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("quantity_in_stock", alias)
    }

    pub fn max_quantity_in_stock(self) -> Self {
        self.max_quantity_in_stock_as("max_quantity_in_stock")
    }

    pub fn max_quantity_in_stock_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("quantity_in_stock", alias)
    }

    pub fn standard_deviation_quantity_in_stock(self) -> Self {
        self.standard_deviation_quantity_in_stock_as("stdDev_quantity_in_stock")
    }

    pub fn standard_deviation_quantity_in_stock_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev("quantity_in_stock", alias)
    }

    pub fn square_root_of_population_standard_deviation_quantity_in_stock(self) -> Self {
        self.square_root_of_population_standard_deviation_quantity_in_stock_as("stdDevPop_quantity_in_stock")
    }

    pub fn square_root_of_population_standard_deviation_quantity_in_stock_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev_pop("quantity_in_stock", alias)
    }

    pub fn sample_variance_quantity_in_stock(self) -> Self {
        self.sample_variance_quantity_in_stock_as("varSamp_quantity_in_stock")
    }

    pub fn sample_variance_quantity_in_stock_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_samp("quantity_in_stock", alias)
    }

    pub fn sample_population_variance_quantity_in_stock(self) -> Self {
        self.sample_population_variance_quantity_in_stock_as("varPop_quantity_in_stock")
    }

    pub fn sample_population_variance_quantity_in_stock_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_pop("quantity_in_stock", alias)
    }

    pub fn unselect_quantity_in_stock(mut self) -> Self {
        self.query.projection.retain(|field| field != "quantity_in_stock");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "quantity_in_stock");
        self
    }


    pub fn with_quantity_in_stock(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "quantity_in_stock",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_quantity_in_stock_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "quantity_in_stock",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_quantity_in_stock_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("quantity_in_stock", value));
        self
    }



    pub fn with_quantity_in_stock_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("quantity_in_stock", value));
        self
    }

    pub fn with_quantity_in_stock_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("quantity_in_stock", value));
        self
    }

    pub fn with_quantity_in_stock_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("quantity_in_stock", value));
        self
    }

    pub fn with_quantity_in_stock_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("quantity_in_stock", value));
        self
    }

    pub fn with_quantity_in_stock_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("quantity_in_stock", value));
        self
    }

    pub fn with_quantity_in_stock_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("quantity_in_stock", lower, upper));
        self
    }

    pub fn with_quantity_in_stock_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "quantity_in_stock",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_quantity_in_stock_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "quantity_in_stock",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_quantity_in_stock_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "quantity_in_stock",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_quantity_in_stock_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("quantity_in_stock", value));
        self
    }

    pub fn with_quantity_in_stock_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("quantity_in_stock", value));
        self
    }

    pub fn with_quantity_in_stock_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("quantity_in_stock"));
        self
    }



    pub fn with_quantity_in_stock_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("quantity_in_stock"));
        self
    }


    pub fn order_by_quantity_in_stock_asc(mut self) -> Self {
        self.query = self.query.order_asc("quantity_in_stock");
        self
    }

    pub fn order_by_quantity_in_stock_desc(mut self) -> Self {
        self.query = self.query.order_desc("quantity_in_stock");
        self
    }

    pub fn order_by_quantity_in_stock_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("quantity_in_stock");
        self
    }

    pub fn order_by_quantity_in_stock_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("quantity_in_stock");
        self
    }


    pub fn select_reorder_level(mut self) -> Self {
        self.query = self.query.project("reorder_level");
        self
    }

    pub fn project_reorder_level(self) -> Self {
        self.select_reorder_level()
    }

    pub fn select_reorder_level_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_reorder_level_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_reorder_level_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("reorder_level", raw_sql_segment));
        self
    }

    pub fn select_reorder_level_with_function(self, function: AggregateFunction) -> Self {
        self.select_reorder_level_as_with_function("reorder_level", function)
    }

    pub fn select_reorder_level_as_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.aggregate_with_function("reorder_level", alias, function)
    }

    pub fn group_by_reorder_level(self) -> Self {
        self.group_by("reorder_level")
    }

    pub fn group_by_reorder_level_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("reorder_level");
        request.query = request
            .query
            .project_expr(alias, Expr::column("reorder_level"));
        request
    }

    pub fn group_by_reorder_level_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("reorder_level")
            .aggregate_with_function("reorder_level", alias, function)
    }

    pub fn count_reorder_level(self) -> Self {
        self.count_reorder_level_as("reorder_level_count")
    }

    pub fn count_reorder_level_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("reorder_level", alias)
    }

    pub fn sum_reorder_level(self) -> Self {
        self.sum_reorder_level_as("sum_reorder_level")
    }

    pub fn sum_reorder_level_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("reorder_level", alias)
    }

    pub fn avg_reorder_level(self) -> Self {
        self.avg_reorder_level_as("avg_reorder_level")
    }

    pub fn avg_reorder_level_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("reorder_level", alias)
    }

    pub fn min_reorder_level(self) -> Self {
        self.min_reorder_level_as("min_reorder_level")
    }

    pub fn min_reorder_level_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("reorder_level", alias)
    }

    pub fn max_reorder_level(self) -> Self {
        self.max_reorder_level_as("max_reorder_level")
    }

    pub fn max_reorder_level_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("reorder_level", alias)
    }

    pub fn standard_deviation_reorder_level(self) -> Self {
        self.standard_deviation_reorder_level_as("stdDev_reorder_level")
    }

    pub fn standard_deviation_reorder_level_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev("reorder_level", alias)
    }

    pub fn square_root_of_population_standard_deviation_reorder_level(self) -> Self {
        self.square_root_of_population_standard_deviation_reorder_level_as("stdDevPop_reorder_level")
    }

    pub fn square_root_of_population_standard_deviation_reorder_level_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev_pop("reorder_level", alias)
    }

    pub fn sample_variance_reorder_level(self) -> Self {
        self.sample_variance_reorder_level_as("varSamp_reorder_level")
    }

    pub fn sample_variance_reorder_level_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_samp("reorder_level", alias)
    }

    pub fn sample_population_variance_reorder_level(self) -> Self {
        self.sample_population_variance_reorder_level_as("varPop_reorder_level")
    }

    pub fn sample_population_variance_reorder_level_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_pop("reorder_level", alias)
    }

    pub fn unselect_reorder_level(mut self) -> Self {
        self.query.projection.retain(|field| field != "reorder_level");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "reorder_level");
        self
    }


    pub fn with_reorder_level(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "reorder_level",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_reorder_level_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "reorder_level",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_reorder_level_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("reorder_level", value));
        self
    }



    pub fn with_reorder_level_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("reorder_level", value));
        self
    }

    pub fn with_reorder_level_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("reorder_level", value));
        self
    }

    pub fn with_reorder_level_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("reorder_level", value));
        self
    }

    pub fn with_reorder_level_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("reorder_level", value));
        self
    }

    pub fn with_reorder_level_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("reorder_level", value));
        self
    }

    pub fn with_reorder_level_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("reorder_level", lower, upper));
        self
    }

    pub fn with_reorder_level_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "reorder_level",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_reorder_level_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "reorder_level",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_reorder_level_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "reorder_level",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_reorder_level_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("reorder_level", value));
        self
    }

    pub fn with_reorder_level_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("reorder_level", value));
        self
    }

    pub fn with_reorder_level_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("reorder_level"));
        self
    }



    pub fn with_reorder_level_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("reorder_level"));
        self
    }


    pub fn order_by_reorder_level_asc(mut self) -> Self {
        self.query = self.query.order_asc("reorder_level");
        self
    }

    pub fn order_by_reorder_level_desc(mut self) -> Self {
        self.query = self.query.order_desc("reorder_level");
        self
    }

    pub fn order_by_reorder_level_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("reorder_level");
        self
    }

    pub fn order_by_reorder_level_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("reorder_level");
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
    pub fn name_is_moving_blanket(self) -> Self {
        self.with_name_is("Moving Blanket")
    }

    pub fn with_name_is_moving_blanket(self) -> Self {
        self.with_name_is("Moving Blanket")
    }



    pub fn with_name_is_not_moving_blanket(self) -> Self {
        self.with_name_is_not("Moving Blanket")
    }



    pub fn item_type_is_packing_material(self) -> Self {
        self.with_item_type_is("Packing Material")
    }

    pub fn with_item_type_is_packing_material(self) -> Self {
        self.with_item_type_is("Packing Material")
    }



    pub fn with_item_type_is_not_packing_material(self) -> Self {
        self.with_item_type_is_not("Packing Material")
    }



    pub fn unit_cost_is_value_8_50(self) -> Self {
        self.with_unit_cost_is("8.50")
    }

    pub fn with_unit_cost_is_value_8_50(self) -> Self {
        self.with_unit_cost_is("8.50")
    }



    pub fn with_unit_cost_is_not_value_8_50(self) -> Self {
        self.with_unit_cost_is_not("8.50")
    }



    pub fn quantity_in_stock_is_value_200(self) -> Self {
        self.with_quantity_in_stock_is("200")
    }

    pub fn with_quantity_in_stock_is_value_200(self) -> Self {
        self.with_quantity_in_stock_is("200")
    }



    pub fn with_quantity_in_stock_is_not_value_200(self) -> Self {
        self.with_quantity_in_stock_is_not("200")
    }



    pub fn reorder_level_is_value_50(self) -> Self {
        self.with_reorder_level_is("50")
    }

    pub fn with_reorder_level_is_value_50(self) -> Self {
        self.with_reorder_level_is("50")
    }



    pub fn with_reorder_level_is_not_value_50(self) -> Self {
        self.with_reorder_level_is_not("50")
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

impl<R> Default for ConsumableRequest<R> {
    fn default() -> Self {
        Self::new()
    }
}

impl<R> From< ConsumableRequest<R> > for SelectQuery {
    fn from(request: ConsumableRequest<R>) -> Self {
        QuerySelection::from(request).into_query()
    }
}

impl<R> From< ConsumableRequest<R> > for QuerySelection {
    fn from(request: ConsumableRequest<R>) -> Self {
        Self {
            query: request.query,
            relation_selections: request.relation_selections,
            relation_filters: request.relation_filters,
            child_enhancements: request.child_enhancements,
            query_options: request.query_options,
        }
    }
}


impl<'a, C> crate::request_support::AuditedSave<'a, C> for teaql_core::Audited<crate::Consumable> 
where C: crate::request_support::TeaqlRepositoryProvider + ?Sized + 'a
{
    type Error = crate::TeaqlDataServiceError<C::ConsumableRepository<'a>>;
    fn save(self, ctx: &'a C) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<teaql_runtime::GraphNode, Self::Error>> + '_>> {
        Box::pin(async move { self.into_entity().save(ctx).await })
    }
}

impl<R: teaql_core::Entity> crate::PurposedQuery<ConsumableRequest<R>> {
    pub fn new_entity<C>(&self, ctx: &C) -> crate::Consumable
    where
        C: crate::TeaqlRuntime + ?Sized,
    {
        crate::Consumable::runtime_new(ctx.user_context().entity_root())
    }

    fn into_inner_with_trace(mut self) -> ConsumableRequest<R> {
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
    ) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::ConsumableRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_page(ctx, offset, limit).await
    }

    pub async fn execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, crate::request_support::TeaqlDataServiceError<C::ConsumableRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_exists(ctx).await
    }

    pub async fn execute_for_list<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::ConsumableRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_list(ctx).await
    }

    /// Execute query in streaming mode (chunked).
    /// Returns a Vec of StreamChunk, each containing up to chunk_size rows.
    /// Set chunk size via .stream(chunk_size) or .stream_default() on the query.
    pub async fn execute_for_stream<'a, C>(self, ctx: &'a C) -> Result<Vec<teaql_data_service::StreamChunk>, crate::request_support::TeaqlDataServiceError<C::ConsumableRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_stream(ctx).await
    }

    pub async fn execute_for_first<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::ConsumableRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_first(ctx).await
    }

    pub async fn execute_for_one<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::ConsumableRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_one(ctx).await
    }


    pub async fn execute_for_records<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::ConsumableRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_records(ctx).await
    }

    pub async fn execute_for_record<'a, C>(self, ctx: &'a C) -> Result<Option<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::ConsumableRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_record(ctx).await
    }

    pub async fn execute_for_count<'a, C>(self, ctx: &'a C) -> Result<u64, crate::request_support::TeaqlDataServiceError<C::ConsumableRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_count(ctx).await
    }
}
