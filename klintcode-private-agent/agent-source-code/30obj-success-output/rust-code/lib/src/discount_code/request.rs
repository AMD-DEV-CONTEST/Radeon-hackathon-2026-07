use std::marker::PhantomData;

use serde_json::Value as JsonValue;
use teaql_core::{Aggregate, AggregateFunction, EntityDescriptor, Expr, Record, SelectQuery, SmartList};
use teaql_runtime::{DataServiceError, RuntimeError};

use crate::request_support::*;

impl EntityReference for crate::DiscountCode {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(&self)
    }
}

impl EntityReference for &crate::DiscountCode {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(self)
    }
}

// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/discount_code
#[derive(Debug)]
pub struct DiscountCodeRequest<R = crate::DiscountCode> {
    query: SelectQuery,
    relation_selections: Vec<RelationSelection>,
    relation_filters: Vec<RelationFilter>,
    child_enhancements: Vec<QuerySelection>,
    query_options: QueryOptions,
    marker: PhantomData<R>,
}

impl<R> Clone for DiscountCodeRequest<R> {
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

impl<R> DiscountCodeRequest<R> {
    pub(crate) fn new() -> Self {
        Self {
            query: SelectQuery::new("DiscountCode")
                .project("id")
                .project("version"),
            relation_selections: Vec::new(),
            relation_filters: Vec::new(),
            child_enhancements: Vec::new(),
            query_options: QueryOptions::default(),
            marker: PhantomData,
        }
    }

    pub fn return_type<T>(self) -> DiscountCodeRequest<T> {
        DiscountCodeRequest {
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::DiscountCodeRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
        R: teaql_core::Entity,
    {
        let repository = ctx
            .discount_code_repository()
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
    ) -> Result<Vec<teaql_data_service::StreamChunk>, TeaqlDataServiceError<C::DiscountCodeRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .discount_code_repository()
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::DiscountCodeRepository<'a>>>
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::DiscountCodeRepository<'a>>>
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::DiscountCodeRepository<'a>>>
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
    ) -> Result<u64, TeaqlDataServiceError<C::DiscountCodeRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .discount_code_repository()
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
            .ok_or_else(|| DataServiceError::Runtime(RuntimeError::Graph(format!("count result for DiscountCode is missing or not numeric"))))
    }

    pub(crate) async fn _execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, TeaqlDataServiceError<C::DiscountCodeRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .discount_code_repository()
            .map_err(|err| DataServiceError::Runtime(RuntimeError::Graph(err.to_string())))?;
        let mut query = self.query.limit(1);
        query.relations.clear();
        let rows = repository.fetch_all(&query).await?;
        Ok(!rows.is_empty())
    }

    pub(crate) async fn _execute_for_records<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<SmartList<Record>, TeaqlDataServiceError<C::DiscountCodeRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .discount_code_repository()
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
    ) -> Result<Option<Record>, TeaqlDataServiceError<C::DiscountCodeRepository<'a>>>
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
            "code" => Some("code"),
            "discount_percent" => Some("discount_percent"),
            "usage_limit" => Some("usage_limit"),
            "used_count" => Some("used_count"),
            "valid_from" => Some("valid_from"),
            "valid_to" => Some("valid_to"),
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
        self.query = self.query.project("code");
        self.query = self.query.project("discount_percent");
        self.query = self.query.project("usage_limit");
        self.query = self.query.project("used_count");
        self.query = self.query.project("valid_from");
        self.query = self.query.project("valid_to");
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


    pub fn select_code(mut self) -> Self {
        self.query = self.query.project("code");
        self
    }

    pub fn project_code(self) -> Self {
        self.select_code()
    }

    pub fn select_code_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_code_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_code_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("code", raw_sql_segment));
        self
    }

    pub fn group_by_code(self) -> Self {
        self.group_by("code")
    }

    pub fn group_by_code_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("code");
        request.query = request
            .query
            .project_expr(alias, Expr::column("code"));
        request
    }

    pub fn group_by_code_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("code")
            .aggregate_with_function("code", alias, function)
    }

    pub fn count_code(self) -> Self {
        self.count_code_as("code_count")
    }

    pub fn count_code_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("code", alias)
    }

    pub fn sum_code(self) -> Self {
        self.sum_code_as("sum_code")
    }

    pub fn sum_code_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("code", alias)
    }

    pub fn avg_code(self) -> Self {
        self.avg_code_as("avg_code")
    }

    pub fn avg_code_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("code", alias)
    }

    pub fn min_code(self) -> Self {
        self.min_code_as("min_code")
    }

    pub fn min_code_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("code", alias)
    }

    pub fn max_code(self) -> Self {
        self.max_code_as("max_code")
    }

    pub fn max_code_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("code", alias)
    }

    pub fn unselect_code(mut self) -> Self {
        self.query.projection.retain(|field| field != "code");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "code");
        self
    }


    pub fn with_code(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "code",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_code_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "code",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_code_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("code", value));
        self
    }



    pub fn with_code_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("code", value));
        self
    }

    pub fn with_code_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("code", value));
        self
    }

    pub fn with_code_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("code", value));
        self
    }

    pub fn with_code_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("code", value));
        self
    }

    pub fn with_code_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("code", value));
        self
    }

    pub fn with_code_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("code", lower, upper));
        self
    }

    pub fn with_code_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "code",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_code_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "code",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_code_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "code",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_code_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("code", value));
        self
    }

    pub fn with_code_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("code", value));
        self
    }

    pub fn with_code_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("code", value));
        self
    }

    pub fn with_code_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("code", value));
        self
    }

    pub fn with_code_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("code", value));
        self
    }

    pub fn with_code_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("code", value));
        self
    }

    pub fn with_code_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("code", value));
        self
    }
    pub fn with_code_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("code", value));
        self
    }

    pub fn with_code_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("code", value));
        self
    }

    pub fn with_code_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("code"));
        self
    }



    pub fn with_code_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("code"));
        self
    }


    pub fn order_by_code_asc(mut self) -> Self {
        self.query = self.query.order_asc("code");
        self
    }

    pub fn order_by_code_desc(mut self) -> Self {
        self.query = self.query.order_desc("code");
        self
    }

    pub fn order_by_code_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("code");
        self
    }

    pub fn order_by_code_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("code");
        self
    }


    pub fn select_discount_percent(mut self) -> Self {
        self.query = self.query.project("discount_percent");
        self
    }

    pub fn project_discount_percent(self) -> Self {
        self.select_discount_percent()
    }

    pub fn select_discount_percent_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_discount_percent_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_discount_percent_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("discount_percent", raw_sql_segment));
        self
    }

    pub fn select_discount_percent_with_function(self, function: AggregateFunction) -> Self {
        self.select_discount_percent_as_with_function("discount_percent", function)
    }

    pub fn select_discount_percent_as_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.aggregate_with_function("discount_percent", alias, function)
    }

    pub fn group_by_discount_percent(self) -> Self {
        self.group_by("discount_percent")
    }

    pub fn group_by_discount_percent_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("discount_percent");
        request.query = request
            .query
            .project_expr(alias, Expr::column("discount_percent"));
        request
    }

    pub fn group_by_discount_percent_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("discount_percent")
            .aggregate_with_function("discount_percent", alias, function)
    }

    pub fn count_discount_percent(self) -> Self {
        self.count_discount_percent_as("discount_percent_count")
    }

    pub fn count_discount_percent_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("discount_percent", alias)
    }

    pub fn sum_discount_percent(self) -> Self {
        self.sum_discount_percent_as("sum_discount_percent")
    }

    pub fn sum_discount_percent_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("discount_percent", alias)
    }

    pub fn avg_discount_percent(self) -> Self {
        self.avg_discount_percent_as("avg_discount_percent")
    }

    pub fn avg_discount_percent_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("discount_percent", alias)
    }

    pub fn min_discount_percent(self) -> Self {
        self.min_discount_percent_as("min_discount_percent")
    }

    pub fn min_discount_percent_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("discount_percent", alias)
    }

    pub fn max_discount_percent(self) -> Self {
        self.max_discount_percent_as("max_discount_percent")
    }

    pub fn max_discount_percent_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("discount_percent", alias)
    }

    pub fn standard_deviation_discount_percent(self) -> Self {
        self.standard_deviation_discount_percent_as("stdDev_discount_percent")
    }

    pub fn standard_deviation_discount_percent_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev("discount_percent", alias)
    }

    pub fn square_root_of_population_standard_deviation_discount_percent(self) -> Self {
        self.square_root_of_population_standard_deviation_discount_percent_as("stdDevPop_discount_percent")
    }

    pub fn square_root_of_population_standard_deviation_discount_percent_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev_pop("discount_percent", alias)
    }

    pub fn sample_variance_discount_percent(self) -> Self {
        self.sample_variance_discount_percent_as("varSamp_discount_percent")
    }

    pub fn sample_variance_discount_percent_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_samp("discount_percent", alias)
    }

    pub fn sample_population_variance_discount_percent(self) -> Self {
        self.sample_population_variance_discount_percent_as("varPop_discount_percent")
    }

    pub fn sample_population_variance_discount_percent_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_pop("discount_percent", alias)
    }

    pub fn unselect_discount_percent(mut self) -> Self {
        self.query.projection.retain(|field| field != "discount_percent");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "discount_percent");
        self
    }


    pub fn with_discount_percent(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "discount_percent",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_discount_percent_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "discount_percent",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_discount_percent_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("discount_percent", value));
        self
    }



    pub fn with_discount_percent_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("discount_percent", value));
        self
    }

    pub fn with_discount_percent_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("discount_percent", value));
        self
    }

    pub fn with_discount_percent_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("discount_percent", value));
        self
    }

    pub fn with_discount_percent_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("discount_percent", value));
        self
    }

    pub fn with_discount_percent_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("discount_percent", value));
        self
    }

    pub fn with_discount_percent_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("discount_percent", lower, upper));
        self
    }

    pub fn with_discount_percent_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "discount_percent",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_discount_percent_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "discount_percent",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_discount_percent_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "discount_percent",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_discount_percent_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("discount_percent", value));
        self
    }

    pub fn with_discount_percent_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("discount_percent", value));
        self
    }

    pub fn with_discount_percent_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("discount_percent"));
        self
    }



    pub fn with_discount_percent_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("discount_percent"));
        self
    }


    pub fn order_by_discount_percent_asc(mut self) -> Self {
        self.query = self.query.order_asc("discount_percent");
        self
    }

    pub fn order_by_discount_percent_desc(mut self) -> Self {
        self.query = self.query.order_desc("discount_percent");
        self
    }

    pub fn order_by_discount_percent_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("discount_percent");
        self
    }

    pub fn order_by_discount_percent_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("discount_percent");
        self
    }


    pub fn select_usage_limit(mut self) -> Self {
        self.query = self.query.project("usage_limit");
        self
    }

    pub fn project_usage_limit(self) -> Self {
        self.select_usage_limit()
    }

    pub fn select_usage_limit_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_usage_limit_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_usage_limit_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("usage_limit", raw_sql_segment));
        self
    }

    pub fn select_usage_limit_with_function(self, function: AggregateFunction) -> Self {
        self.select_usage_limit_as_with_function("usage_limit", function)
    }

    pub fn select_usage_limit_as_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.aggregate_with_function("usage_limit", alias, function)
    }

    pub fn group_by_usage_limit(self) -> Self {
        self.group_by("usage_limit")
    }

    pub fn group_by_usage_limit_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("usage_limit");
        request.query = request
            .query
            .project_expr(alias, Expr::column("usage_limit"));
        request
    }

    pub fn group_by_usage_limit_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("usage_limit")
            .aggregate_with_function("usage_limit", alias, function)
    }

    pub fn count_usage_limit(self) -> Self {
        self.count_usage_limit_as("usage_limit_count")
    }

    pub fn count_usage_limit_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("usage_limit", alias)
    }

    pub fn sum_usage_limit(self) -> Self {
        self.sum_usage_limit_as("sum_usage_limit")
    }

    pub fn sum_usage_limit_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("usage_limit", alias)
    }

    pub fn avg_usage_limit(self) -> Self {
        self.avg_usage_limit_as("avg_usage_limit")
    }

    pub fn avg_usage_limit_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("usage_limit", alias)
    }

    pub fn min_usage_limit(self) -> Self {
        self.min_usage_limit_as("min_usage_limit")
    }

    pub fn min_usage_limit_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("usage_limit", alias)
    }

    pub fn max_usage_limit(self) -> Self {
        self.max_usage_limit_as("max_usage_limit")
    }

    pub fn max_usage_limit_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("usage_limit", alias)
    }

    pub fn standard_deviation_usage_limit(self) -> Self {
        self.standard_deviation_usage_limit_as("stdDev_usage_limit")
    }

    pub fn standard_deviation_usage_limit_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev("usage_limit", alias)
    }

    pub fn square_root_of_population_standard_deviation_usage_limit(self) -> Self {
        self.square_root_of_population_standard_deviation_usage_limit_as("stdDevPop_usage_limit")
    }

    pub fn square_root_of_population_standard_deviation_usage_limit_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev_pop("usage_limit", alias)
    }

    pub fn sample_variance_usage_limit(self) -> Self {
        self.sample_variance_usage_limit_as("varSamp_usage_limit")
    }

    pub fn sample_variance_usage_limit_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_samp("usage_limit", alias)
    }

    pub fn sample_population_variance_usage_limit(self) -> Self {
        self.sample_population_variance_usage_limit_as("varPop_usage_limit")
    }

    pub fn sample_population_variance_usage_limit_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_pop("usage_limit", alias)
    }

    pub fn unselect_usage_limit(mut self) -> Self {
        self.query.projection.retain(|field| field != "usage_limit");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "usage_limit");
        self
    }


    pub fn with_usage_limit(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "usage_limit",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_usage_limit_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "usage_limit",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_usage_limit_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("usage_limit", value));
        self
    }



    pub fn with_usage_limit_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("usage_limit", value));
        self
    }

    pub fn with_usage_limit_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("usage_limit", value));
        self
    }

    pub fn with_usage_limit_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("usage_limit", value));
        self
    }

    pub fn with_usage_limit_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("usage_limit", value));
        self
    }

    pub fn with_usage_limit_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("usage_limit", value));
        self
    }

    pub fn with_usage_limit_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("usage_limit", lower, upper));
        self
    }

    pub fn with_usage_limit_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "usage_limit",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_usage_limit_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "usage_limit",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_usage_limit_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "usage_limit",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_usage_limit_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("usage_limit", value));
        self
    }

    pub fn with_usage_limit_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("usage_limit", value));
        self
    }

    pub fn with_usage_limit_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("usage_limit"));
        self
    }



    pub fn with_usage_limit_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("usage_limit"));
        self
    }


    pub fn order_by_usage_limit_asc(mut self) -> Self {
        self.query = self.query.order_asc("usage_limit");
        self
    }

    pub fn order_by_usage_limit_desc(mut self) -> Self {
        self.query = self.query.order_desc("usage_limit");
        self
    }

    pub fn order_by_usage_limit_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("usage_limit");
        self
    }

    pub fn order_by_usage_limit_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("usage_limit");
        self
    }


    pub fn select_used_count(mut self) -> Self {
        self.query = self.query.project("used_count");
        self
    }

    pub fn project_used_count(self) -> Self {
        self.select_used_count()
    }

    pub fn select_used_count_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_used_count_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_used_count_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("used_count", raw_sql_segment));
        self
    }

    pub fn select_used_count_with_function(self, function: AggregateFunction) -> Self {
        self.select_used_count_as_with_function("used_count", function)
    }

    pub fn select_used_count_as_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.aggregate_with_function("used_count", alias, function)
    }

    pub fn group_by_used_count(self) -> Self {
        self.group_by("used_count")
    }

    pub fn group_by_used_count_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("used_count");
        request.query = request
            .query
            .project_expr(alias, Expr::column("used_count"));
        request
    }

    pub fn group_by_used_count_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("used_count")
            .aggregate_with_function("used_count", alias, function)
    }

    pub fn count_used_count(self) -> Self {
        self.count_used_count_as("used_count_count")
    }

    pub fn count_used_count_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("used_count", alias)
    }

    pub fn sum_used_count(self) -> Self {
        self.sum_used_count_as("sum_used_count")
    }

    pub fn sum_used_count_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("used_count", alias)
    }

    pub fn avg_used_count(self) -> Self {
        self.avg_used_count_as("avg_used_count")
    }

    pub fn avg_used_count_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("used_count", alias)
    }

    pub fn min_used_count(self) -> Self {
        self.min_used_count_as("min_used_count")
    }

    pub fn min_used_count_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("used_count", alias)
    }

    pub fn max_used_count(self) -> Self {
        self.max_used_count_as("max_used_count")
    }

    pub fn max_used_count_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("used_count", alias)
    }

    pub fn standard_deviation_used_count(self) -> Self {
        self.standard_deviation_used_count_as("stdDev_used_count")
    }

    pub fn standard_deviation_used_count_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev("used_count", alias)
    }

    pub fn square_root_of_population_standard_deviation_used_count(self) -> Self {
        self.square_root_of_population_standard_deviation_used_count_as("stdDevPop_used_count")
    }

    pub fn square_root_of_population_standard_deviation_used_count_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev_pop("used_count", alias)
    }

    pub fn sample_variance_used_count(self) -> Self {
        self.sample_variance_used_count_as("varSamp_used_count")
    }

    pub fn sample_variance_used_count_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_samp("used_count", alias)
    }

    pub fn sample_population_variance_used_count(self) -> Self {
        self.sample_population_variance_used_count_as("varPop_used_count")
    }

    pub fn sample_population_variance_used_count_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_pop("used_count", alias)
    }

    pub fn unselect_used_count(mut self) -> Self {
        self.query.projection.retain(|field| field != "used_count");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "used_count");
        self
    }


    pub fn with_used_count(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "used_count",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_used_count_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "used_count",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_used_count_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("used_count", value));
        self
    }



    pub fn with_used_count_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("used_count", value));
        self
    }

    pub fn with_used_count_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("used_count", value));
        self
    }

    pub fn with_used_count_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("used_count", value));
        self
    }

    pub fn with_used_count_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("used_count", value));
        self
    }

    pub fn with_used_count_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("used_count", value));
        self
    }

    pub fn with_used_count_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("used_count", lower, upper));
        self
    }

    pub fn with_used_count_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "used_count",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_used_count_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "used_count",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_used_count_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "used_count",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_used_count_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("used_count", value));
        self
    }

    pub fn with_used_count_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("used_count", value));
        self
    }

    pub fn with_used_count_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("used_count"));
        self
    }



    pub fn with_used_count_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("used_count"));
        self
    }


    pub fn order_by_used_count_asc(mut self) -> Self {
        self.query = self.query.order_asc("used_count");
        self
    }

    pub fn order_by_used_count_desc(mut self) -> Self {
        self.query = self.query.order_desc("used_count");
        self
    }

    pub fn order_by_used_count_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("used_count");
        self
    }

    pub fn order_by_used_count_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("used_count");
        self
    }


    pub fn select_valid_from(mut self) -> Self {
        self.query = self.query.project("valid_from");
        self
    }

    pub fn project_valid_from(self) -> Self {
        self.select_valid_from()
    }

    pub fn select_valid_from_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_valid_from_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_valid_from_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("valid_from", raw_sql_segment));
        self
    }

    pub fn group_by_valid_from(self) -> Self {
        self.group_by("valid_from")
    }

    pub fn group_by_valid_from_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("valid_from");
        request.query = request
            .query
            .project_expr(alias, Expr::column("valid_from"));
        request
    }

    pub fn group_by_valid_from_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("valid_from")
            .aggregate_with_function("valid_from", alias, function)
    }

    pub fn count_valid_from(self) -> Self {
        self.count_valid_from_as("valid_from_count")
    }

    pub fn count_valid_from_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("valid_from", alias)
    }

    pub fn sum_valid_from(self) -> Self {
        self.sum_valid_from_as("sum_valid_from")
    }

    pub fn sum_valid_from_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("valid_from", alias)
    }

    pub fn avg_valid_from(self) -> Self {
        self.avg_valid_from_as("avg_valid_from")
    }

    pub fn avg_valid_from_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("valid_from", alias)
    }

    pub fn min_valid_from(self) -> Self {
        self.min_valid_from_as("min_valid_from")
    }

    pub fn min_valid_from_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("valid_from", alias)
    }

    pub fn max_valid_from(self) -> Self {
        self.max_valid_from_as("max_valid_from")
    }

    pub fn max_valid_from_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("valid_from", alias)
    }

    pub fn unselect_valid_from(mut self) -> Self {
        self.query.projection.retain(|field| field != "valid_from");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "valid_from");
        self
    }


    pub fn with_valid_from(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "valid_from",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_valid_from_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "valid_from",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_valid_from_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("valid_from", value));
        self
    }



    pub fn with_valid_from_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("valid_from", value));
        self
    }

    pub fn with_valid_from_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("valid_from", value));
        self
    }

    pub fn with_valid_from_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("valid_from", value));
        self
    }

    pub fn with_valid_from_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("valid_from", value));
        self
    }

    pub fn with_valid_from_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("valid_from", value));
        self
    }

    pub fn with_valid_from_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("valid_from", lower, upper));
        self
    }

    pub fn with_valid_from_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "valid_from",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_valid_from_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "valid_from",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_valid_from_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "valid_from",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_valid_from_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("valid_from", value));
        self
    }

    pub fn with_valid_from_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("valid_from", value));
        self
    }

    pub fn with_valid_from_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("valid_from"));
        self
    }



    pub fn with_valid_from_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("valid_from"));
        self
    }


    pub fn order_by_valid_from_asc(mut self) -> Self {
        self.query = self.query.order_asc("valid_from");
        self
    }

    pub fn order_by_valid_from_desc(mut self) -> Self {
        self.query = self.query.order_desc("valid_from");
        self
    }

    pub fn order_by_valid_from_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("valid_from");
        self
    }

    pub fn order_by_valid_from_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("valid_from");
        self
    }


    pub fn select_valid_to(mut self) -> Self {
        self.query = self.query.project("valid_to");
        self
    }

    pub fn project_valid_to(self) -> Self {
        self.select_valid_to()
    }

    pub fn select_valid_to_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_valid_to_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_valid_to_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("valid_to", raw_sql_segment));
        self
    }

    pub fn group_by_valid_to(self) -> Self {
        self.group_by("valid_to")
    }

    pub fn group_by_valid_to_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("valid_to");
        request.query = request
            .query
            .project_expr(alias, Expr::column("valid_to"));
        request
    }

    pub fn group_by_valid_to_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("valid_to")
            .aggregate_with_function("valid_to", alias, function)
    }

    pub fn count_valid_to(self) -> Self {
        self.count_valid_to_as("valid_to_count")
    }

    pub fn count_valid_to_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("valid_to", alias)
    }

    pub fn sum_valid_to(self) -> Self {
        self.sum_valid_to_as("sum_valid_to")
    }

    pub fn sum_valid_to_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("valid_to", alias)
    }

    pub fn avg_valid_to(self) -> Self {
        self.avg_valid_to_as("avg_valid_to")
    }

    pub fn avg_valid_to_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("valid_to", alias)
    }

    pub fn min_valid_to(self) -> Self {
        self.min_valid_to_as("min_valid_to")
    }

    pub fn min_valid_to_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("valid_to", alias)
    }

    pub fn max_valid_to(self) -> Self {
        self.max_valid_to_as("max_valid_to")
    }

    pub fn max_valid_to_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("valid_to", alias)
    }

    pub fn unselect_valid_to(mut self) -> Self {
        self.query.projection.retain(|field| field != "valid_to");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "valid_to");
        self
    }


    pub fn with_valid_to(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "valid_to",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_valid_to_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "valid_to",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_valid_to_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("valid_to", value));
        self
    }



    pub fn with_valid_to_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("valid_to", value));
        self
    }

    pub fn with_valid_to_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("valid_to", value));
        self
    }

    pub fn with_valid_to_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("valid_to", value));
        self
    }

    pub fn with_valid_to_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("valid_to", value));
        self
    }

    pub fn with_valid_to_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("valid_to", value));
        self
    }

    pub fn with_valid_to_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("valid_to", lower, upper));
        self
    }

    pub fn with_valid_to_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "valid_to",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_valid_to_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "valid_to",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_valid_to_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "valid_to",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_valid_to_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("valid_to", value));
        self
    }

    pub fn with_valid_to_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("valid_to", value));
        self
    }

    pub fn with_valid_to_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("valid_to"));
        self
    }



    pub fn with_valid_to_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("valid_to"));
        self
    }


    pub fn order_by_valid_to_asc(mut self) -> Self {
        self.query = self.query.order_asc("valid_to");
        self
    }

    pub fn order_by_valid_to_desc(mut self) -> Self {
        self.query = self.query.order_desc("valid_to");
        self
    }

    pub fn order_by_valid_to_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("valid_to");
        self
    }

    pub fn order_by_valid_to_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("valid_to");
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
    pub fn code_is_summer10(self) -> Self {
        self.with_code_is("SUMMER10")
    }

    pub fn with_code_is_summer10(self) -> Self {
        self.with_code_is("SUMMER10")
    }



    pub fn with_code_is_not_summer10(self) -> Self {
        self.with_code_is_not("SUMMER10")
    }



    pub fn discount_percent_is_value_10_00(self) -> Self {
        self.with_discount_percent_is("10.00")
    }

    pub fn with_discount_percent_is_value_10_00(self) -> Self {
        self.with_discount_percent_is("10.00")
    }



    pub fn with_discount_percent_is_not_value_10_00(self) -> Self {
        self.with_discount_percent_is_not("10.00")
    }



    pub fn usage_limit_is_value_500(self) -> Self {
        self.with_usage_limit_is("500")
    }

    pub fn with_usage_limit_is_value_500(self) -> Self {
        self.with_usage_limit_is("500")
    }



    pub fn with_usage_limit_is_not_value_500(self) -> Self {
        self.with_usage_limit_is_not("500")
    }



    pub fn used_count_is_value_0(self) -> Self {
        self.with_used_count_is("0")
    }

    pub fn with_used_count_is_value_0(self) -> Self {
        self.with_used_count_is("0")
    }



    pub fn with_used_count_is_not_value_0(self) -> Self {
        self.with_used_count_is_not("0")
    }



    pub fn valid_from_is_value_2024_06_01(self) -> Self {
        self.with_valid_from_is("2024-06-01")
    }

    pub fn with_valid_from_is_value_2024_06_01(self) -> Self {
        self.with_valid_from_is("2024-06-01")
    }



    pub fn with_valid_from_is_not_value_2024_06_01(self) -> Self {
        self.with_valid_from_is_not("2024-06-01")
    }



    pub fn valid_to_is_value_2024_08_31(self) -> Self {
        self.with_valid_to_is("2024-08-31")
    }

    pub fn with_valid_to_is_value_2024_08_31(self) -> Self {
        self.with_valid_to_is("2024-08-31")
    }



    pub fn with_valid_to_is_not_value_2024_08_31(self) -> Self {
        self.with_valid_to_is_not("2024-08-31")
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

impl<R> Default for DiscountCodeRequest<R> {
    fn default() -> Self {
        Self::new()
    }
}

impl<R> From< DiscountCodeRequest<R> > for SelectQuery {
    fn from(request: DiscountCodeRequest<R>) -> Self {
        QuerySelection::from(request).into_query()
    }
}

impl<R> From< DiscountCodeRequest<R> > for QuerySelection {
    fn from(request: DiscountCodeRequest<R>) -> Self {
        Self {
            query: request.query,
            relation_selections: request.relation_selections,
            relation_filters: request.relation_filters,
            child_enhancements: request.child_enhancements,
            query_options: request.query_options,
        }
    }
}


impl<'a, C> crate::request_support::AuditedSave<'a, C> for teaql_core::Audited<crate::DiscountCode> 
where C: crate::request_support::TeaqlRepositoryProvider + ?Sized + 'a
{
    type Error = crate::TeaqlDataServiceError<C::DiscountCodeRepository<'a>>;
    fn save(self, ctx: &'a C) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<teaql_runtime::GraphNode, Self::Error>> + '_>> {
        Box::pin(async move { self.into_entity().save(ctx).await })
    }
}

impl<R: teaql_core::Entity> crate::PurposedQuery<DiscountCodeRequest<R>> {
    pub fn new_entity<C>(&self, ctx: &C) -> crate::DiscountCode
    where
        C: crate::TeaqlRuntime + ?Sized,
    {
        crate::DiscountCode::runtime_new(ctx.user_context().entity_root())
    }

    fn into_inner_with_trace(mut self) -> DiscountCodeRequest<R> {
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
    ) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::DiscountCodeRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_page(ctx, offset, limit).await
    }

    pub async fn execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, crate::request_support::TeaqlDataServiceError<C::DiscountCodeRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_exists(ctx).await
    }

    pub async fn execute_for_list<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::DiscountCodeRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_list(ctx).await
    }

    /// Execute query in streaming mode (chunked).
    /// Returns a Vec of StreamChunk, each containing up to chunk_size rows.
    /// Set chunk size via .stream(chunk_size) or .stream_default() on the query.
    pub async fn execute_for_stream<'a, C>(self, ctx: &'a C) -> Result<Vec<teaql_data_service::StreamChunk>, crate::request_support::TeaqlDataServiceError<C::DiscountCodeRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_stream(ctx).await
    }

    pub async fn execute_for_first<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::DiscountCodeRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_first(ctx).await
    }

    pub async fn execute_for_one<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::DiscountCodeRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_one(ctx).await
    }


    pub async fn execute_for_records<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::DiscountCodeRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_records(ctx).await
    }

    pub async fn execute_for_record<'a, C>(self, ctx: &'a C) -> Result<Option<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::DiscountCodeRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_record(ctx).await
    }

    pub async fn execute_for_count<'a, C>(self, ctx: &'a C) -> Result<u64, crate::request_support::TeaqlDataServiceError<C::DiscountCodeRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_count(ctx).await
    }
}
