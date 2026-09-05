use std::marker::PhantomData;

use serde_json::Value as JsonValue;
use teaql_core::{Aggregate, AggregateFunction, EntityDescriptor, Expr, Record, SelectQuery, SmartList};
use teaql_runtime::{DataServiceError, RuntimeError};

use crate::request_support::*;

impl EntityReference for crate::ConversionMetric {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(&self)
    }
}

impl EntityReference for &crate::ConversionMetric {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(self)
    }
}

// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/conversion_metric
#[derive(Debug)]
pub struct ConversionMetricRequest<R = crate::ConversionMetric> {
    query: SelectQuery,
    relation_selections: Vec<RelationSelection>,
    relation_filters: Vec<RelationFilter>,
    child_enhancements: Vec<QuerySelection>,
    query_options: QueryOptions,
    marker: PhantomData<R>,
}

impl<R> Clone for ConversionMetricRequest<R> {
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

impl<R> ConversionMetricRequest<R> {
    pub(crate) fn new() -> Self {
        Self {
            query: SelectQuery::new("ConversionMetric")
                .project("id")
                .project("version"),
            relation_selections: Vec::new(),
            relation_filters: Vec::new(),
            child_enhancements: Vec::new(),
            query_options: QueryOptions::default(),
            marker: PhantomData,
        }
    }

    pub fn return_type<T>(self) -> ConversionMetricRequest<T> {
        ConversionMetricRequest {
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::ConversionMetricRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
        R: teaql_core::Entity,
    {
        let repository = ctx
            .conversion_metric_repository()
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
    ) -> Result<Vec<teaql_data_service::StreamChunk>, TeaqlDataServiceError<C::ConversionMetricRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .conversion_metric_repository()
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::ConversionMetricRepository<'a>>>
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::ConversionMetricRepository<'a>>>
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::ConversionMetricRepository<'a>>>
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
    ) -> Result<u64, TeaqlDataServiceError<C::ConversionMetricRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .conversion_metric_repository()
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
            .ok_or_else(|| DataServiceError::Runtime(RuntimeError::Graph(format!("count result for ConversionMetric is missing or not numeric"))))
    }

    pub(crate) async fn _execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, TeaqlDataServiceError<C::ConversionMetricRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .conversion_metric_repository()
            .map_err(|err| DataServiceError::Runtime(RuntimeError::Graph(err.to_string())))?;
        let mut query = self.query.limit(1);
        query.relations.clear();
        let rows = repository.fetch_all(&query).await?;
        Ok(!rows.is_empty())
    }

    pub(crate) async fn _execute_for_records<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<SmartList<Record>, TeaqlDataServiceError<C::ConversionMetricRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .conversion_metric_repository()
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
    ) -> Result<Option<Record>, TeaqlDataServiceError<C::ConversionMetricRepository<'a>>>
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
            "leads_generated" => Some("leads_generated"),
            "conversions" => Some("conversions"),
            "conversion_rate" => Some("conversion_rate"),
            "revenue_attributed" => Some("revenue_attributed"),
            "date_recorded" => Some("date_recorded"),
            "create_time" => Some("create_time"),
            "update_time" => Some("update_time"),
            "version" => Some("version"),
            "campaign" | "campaign_id" => Some("campaign_id"),
            _ => None,
        }
    }

    fn apply_dynamic_json_chain_filter(self, head: &str, tail: &str, value: &JsonValue) -> Self {
        let _ = (tail, value);
        match head {
            "campaign" => {
                self.with_campaign_matching(
                    crate::Q::campaigns_minimal()
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
        self.query = self.query.project("leads_generated");
        self.query = self.query.project("conversions");
        self.query = self.query.project("conversion_rate");
        self.query = self.query.project("revenue_attributed");
        self.query = self.query.project("date_recorded");
        self.query = self.query.project("create_time");
        self.query = self.query.project("update_time");
        self.query = self.query.project("version");
        self.query = self.query.project("campaign_id");
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
        request = request.select_campaign();
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


    pub fn select_leads_generated(mut self) -> Self {
        self.query = self.query.project("leads_generated");
        self
    }

    pub fn project_leads_generated(self) -> Self {
        self.select_leads_generated()
    }

    pub fn select_leads_generated_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_leads_generated_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_leads_generated_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("leads_generated", raw_sql_segment));
        self
    }

    pub fn select_leads_generated_with_function(self, function: AggregateFunction) -> Self {
        self.select_leads_generated_as_with_function("leads_generated", function)
    }

    pub fn select_leads_generated_as_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.aggregate_with_function("leads_generated", alias, function)
    }

    pub fn group_by_leads_generated(self) -> Self {
        self.group_by("leads_generated")
    }

    pub fn group_by_leads_generated_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("leads_generated");
        request.query = request
            .query
            .project_expr(alias, Expr::column("leads_generated"));
        request
    }

    pub fn group_by_leads_generated_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("leads_generated")
            .aggregate_with_function("leads_generated", alias, function)
    }

    pub fn count_leads_generated(self) -> Self {
        self.count_leads_generated_as("leads_generated_count")
    }

    pub fn count_leads_generated_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("leads_generated", alias)
    }

    pub fn sum_leads_generated(self) -> Self {
        self.sum_leads_generated_as("sum_leads_generated")
    }

    pub fn sum_leads_generated_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("leads_generated", alias)
    }

    pub fn avg_leads_generated(self) -> Self {
        self.avg_leads_generated_as("avg_leads_generated")
    }

    pub fn avg_leads_generated_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("leads_generated", alias)
    }

    pub fn min_leads_generated(self) -> Self {
        self.min_leads_generated_as("min_leads_generated")
    }

    pub fn min_leads_generated_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("leads_generated", alias)
    }

    pub fn max_leads_generated(self) -> Self {
        self.max_leads_generated_as("max_leads_generated")
    }

    pub fn max_leads_generated_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("leads_generated", alias)
    }

    pub fn standard_deviation_leads_generated(self) -> Self {
        self.standard_deviation_leads_generated_as("stdDev_leads_generated")
    }

    pub fn standard_deviation_leads_generated_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev("leads_generated", alias)
    }

    pub fn square_root_of_population_standard_deviation_leads_generated(self) -> Self {
        self.square_root_of_population_standard_deviation_leads_generated_as("stdDevPop_leads_generated")
    }

    pub fn square_root_of_population_standard_deviation_leads_generated_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev_pop("leads_generated", alias)
    }

    pub fn sample_variance_leads_generated(self) -> Self {
        self.sample_variance_leads_generated_as("varSamp_leads_generated")
    }

    pub fn sample_variance_leads_generated_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_samp("leads_generated", alias)
    }

    pub fn sample_population_variance_leads_generated(self) -> Self {
        self.sample_population_variance_leads_generated_as("varPop_leads_generated")
    }

    pub fn sample_population_variance_leads_generated_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_pop("leads_generated", alias)
    }

    pub fn unselect_leads_generated(mut self) -> Self {
        self.query.projection.retain(|field| field != "leads_generated");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "leads_generated");
        self
    }


    pub fn with_leads_generated(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "leads_generated",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_leads_generated_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "leads_generated",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_leads_generated_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("leads_generated", value));
        self
    }



    pub fn with_leads_generated_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("leads_generated", value));
        self
    }

    pub fn with_leads_generated_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("leads_generated", value));
        self
    }

    pub fn with_leads_generated_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("leads_generated", value));
        self
    }

    pub fn with_leads_generated_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("leads_generated", value));
        self
    }

    pub fn with_leads_generated_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("leads_generated", value));
        self
    }

    pub fn with_leads_generated_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("leads_generated", lower, upper));
        self
    }

    pub fn with_leads_generated_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "leads_generated",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_leads_generated_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "leads_generated",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_leads_generated_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "leads_generated",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_leads_generated_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("leads_generated", value));
        self
    }

    pub fn with_leads_generated_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("leads_generated", value));
        self
    }

    pub fn with_leads_generated_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("leads_generated"));
        self
    }



    pub fn with_leads_generated_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("leads_generated"));
        self
    }


    pub fn order_by_leads_generated_asc(mut self) -> Self {
        self.query = self.query.order_asc("leads_generated");
        self
    }

    pub fn order_by_leads_generated_desc(mut self) -> Self {
        self.query = self.query.order_desc("leads_generated");
        self
    }

    pub fn order_by_leads_generated_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("leads_generated");
        self
    }

    pub fn order_by_leads_generated_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("leads_generated");
        self
    }


    pub fn select_conversions(mut self) -> Self {
        self.query = self.query.project("conversions");
        self
    }

    pub fn project_conversions(self) -> Self {
        self.select_conversions()
    }

    pub fn select_conversions_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_conversions_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_conversions_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("conversions", raw_sql_segment));
        self
    }

    pub fn select_conversions_with_function(self, function: AggregateFunction) -> Self {
        self.select_conversions_as_with_function("conversions", function)
    }

    pub fn select_conversions_as_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.aggregate_with_function("conversions", alias, function)
    }

    pub fn group_by_conversions(self) -> Self {
        self.group_by("conversions")
    }

    pub fn group_by_conversions_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("conversions");
        request.query = request
            .query
            .project_expr(alias, Expr::column("conversions"));
        request
    }

    pub fn group_by_conversions_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("conversions")
            .aggregate_with_function("conversions", alias, function)
    }

    pub fn count_conversions(self) -> Self {
        self.count_conversions_as("conversions_count")
    }

    pub fn count_conversions_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("conversions", alias)
    }

    pub fn sum_conversions(self) -> Self {
        self.sum_conversions_as("sum_conversions")
    }

    pub fn sum_conversions_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("conversions", alias)
    }

    pub fn avg_conversions(self) -> Self {
        self.avg_conversions_as("avg_conversions")
    }

    pub fn avg_conversions_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("conversions", alias)
    }

    pub fn min_conversions(self) -> Self {
        self.min_conversions_as("min_conversions")
    }

    pub fn min_conversions_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("conversions", alias)
    }

    pub fn max_conversions(self) -> Self {
        self.max_conversions_as("max_conversions")
    }

    pub fn max_conversions_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("conversions", alias)
    }

    pub fn standard_deviation_conversions(self) -> Self {
        self.standard_deviation_conversions_as("stdDev_conversions")
    }

    pub fn standard_deviation_conversions_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev("conversions", alias)
    }

    pub fn square_root_of_population_standard_deviation_conversions(self) -> Self {
        self.square_root_of_population_standard_deviation_conversions_as("stdDevPop_conversions")
    }

    pub fn square_root_of_population_standard_deviation_conversions_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev_pop("conversions", alias)
    }

    pub fn sample_variance_conversions(self) -> Self {
        self.sample_variance_conversions_as("varSamp_conversions")
    }

    pub fn sample_variance_conversions_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_samp("conversions", alias)
    }

    pub fn sample_population_variance_conversions(self) -> Self {
        self.sample_population_variance_conversions_as("varPop_conversions")
    }

    pub fn sample_population_variance_conversions_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_pop("conversions", alias)
    }

    pub fn unselect_conversions(mut self) -> Self {
        self.query.projection.retain(|field| field != "conversions");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "conversions");
        self
    }


    pub fn with_conversions(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "conversions",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_conversions_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "conversions",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_conversions_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("conversions", value));
        self
    }



    pub fn with_conversions_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("conversions", value));
        self
    }

    pub fn with_conversions_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("conversions", value));
        self
    }

    pub fn with_conversions_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("conversions", value));
        self
    }

    pub fn with_conversions_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("conversions", value));
        self
    }

    pub fn with_conversions_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("conversions", value));
        self
    }

    pub fn with_conversions_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("conversions", lower, upper));
        self
    }

    pub fn with_conversions_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "conversions",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_conversions_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "conversions",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_conversions_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "conversions",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_conversions_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("conversions", value));
        self
    }

    pub fn with_conversions_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("conversions", value));
        self
    }

    pub fn with_conversions_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("conversions"));
        self
    }



    pub fn with_conversions_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("conversions"));
        self
    }


    pub fn order_by_conversions_asc(mut self) -> Self {
        self.query = self.query.order_asc("conversions");
        self
    }

    pub fn order_by_conversions_desc(mut self) -> Self {
        self.query = self.query.order_desc("conversions");
        self
    }

    pub fn order_by_conversions_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("conversions");
        self
    }

    pub fn order_by_conversions_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("conversions");
        self
    }


    pub fn select_conversion_rate(mut self) -> Self {
        self.query = self.query.project("conversion_rate");
        self
    }

    pub fn project_conversion_rate(self) -> Self {
        self.select_conversion_rate()
    }

    pub fn select_conversion_rate_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_conversion_rate_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_conversion_rate_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("conversion_rate", raw_sql_segment));
        self
    }

    pub fn select_conversion_rate_with_function(self, function: AggregateFunction) -> Self {
        self.select_conversion_rate_as_with_function("conversion_rate", function)
    }

    pub fn select_conversion_rate_as_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.aggregate_with_function("conversion_rate", alias, function)
    }

    pub fn group_by_conversion_rate(self) -> Self {
        self.group_by("conversion_rate")
    }

    pub fn group_by_conversion_rate_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("conversion_rate");
        request.query = request
            .query
            .project_expr(alias, Expr::column("conversion_rate"));
        request
    }

    pub fn group_by_conversion_rate_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("conversion_rate")
            .aggregate_with_function("conversion_rate", alias, function)
    }

    pub fn count_conversion_rate(self) -> Self {
        self.count_conversion_rate_as("conversion_rate_count")
    }

    pub fn count_conversion_rate_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("conversion_rate", alias)
    }

    pub fn sum_conversion_rate(self) -> Self {
        self.sum_conversion_rate_as("sum_conversion_rate")
    }

    pub fn sum_conversion_rate_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("conversion_rate", alias)
    }

    pub fn avg_conversion_rate(self) -> Self {
        self.avg_conversion_rate_as("avg_conversion_rate")
    }

    pub fn avg_conversion_rate_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("conversion_rate", alias)
    }

    pub fn min_conversion_rate(self) -> Self {
        self.min_conversion_rate_as("min_conversion_rate")
    }

    pub fn min_conversion_rate_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("conversion_rate", alias)
    }

    pub fn max_conversion_rate(self) -> Self {
        self.max_conversion_rate_as("max_conversion_rate")
    }

    pub fn max_conversion_rate_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("conversion_rate", alias)
    }

    pub fn standard_deviation_conversion_rate(self) -> Self {
        self.standard_deviation_conversion_rate_as("stdDev_conversion_rate")
    }

    pub fn standard_deviation_conversion_rate_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev("conversion_rate", alias)
    }

    pub fn square_root_of_population_standard_deviation_conversion_rate(self) -> Self {
        self.square_root_of_population_standard_deviation_conversion_rate_as("stdDevPop_conversion_rate")
    }

    pub fn square_root_of_population_standard_deviation_conversion_rate_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev_pop("conversion_rate", alias)
    }

    pub fn sample_variance_conversion_rate(self) -> Self {
        self.sample_variance_conversion_rate_as("varSamp_conversion_rate")
    }

    pub fn sample_variance_conversion_rate_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_samp("conversion_rate", alias)
    }

    pub fn sample_population_variance_conversion_rate(self) -> Self {
        self.sample_population_variance_conversion_rate_as("varPop_conversion_rate")
    }

    pub fn sample_population_variance_conversion_rate_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_pop("conversion_rate", alias)
    }

    pub fn unselect_conversion_rate(mut self) -> Self {
        self.query.projection.retain(|field| field != "conversion_rate");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "conversion_rate");
        self
    }


    pub fn with_conversion_rate(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "conversion_rate",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_conversion_rate_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "conversion_rate",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_conversion_rate_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("conversion_rate", value));
        self
    }



    pub fn with_conversion_rate_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("conversion_rate", value));
        self
    }

    pub fn with_conversion_rate_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("conversion_rate", value));
        self
    }

    pub fn with_conversion_rate_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("conversion_rate", value));
        self
    }

    pub fn with_conversion_rate_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("conversion_rate", value));
        self
    }

    pub fn with_conversion_rate_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("conversion_rate", value));
        self
    }

    pub fn with_conversion_rate_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("conversion_rate", lower, upper));
        self
    }

    pub fn with_conversion_rate_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "conversion_rate",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_conversion_rate_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "conversion_rate",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_conversion_rate_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "conversion_rate",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_conversion_rate_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("conversion_rate", value));
        self
    }

    pub fn with_conversion_rate_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("conversion_rate", value));
        self
    }

    pub fn with_conversion_rate_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("conversion_rate"));
        self
    }



    pub fn with_conversion_rate_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("conversion_rate"));
        self
    }


    pub fn order_by_conversion_rate_asc(mut self) -> Self {
        self.query = self.query.order_asc("conversion_rate");
        self
    }

    pub fn order_by_conversion_rate_desc(mut self) -> Self {
        self.query = self.query.order_desc("conversion_rate");
        self
    }

    pub fn order_by_conversion_rate_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("conversion_rate");
        self
    }

    pub fn order_by_conversion_rate_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("conversion_rate");
        self
    }


    pub fn select_revenue_attributed(mut self) -> Self {
        self.query = self.query.project("revenue_attributed");
        self
    }

    pub fn project_revenue_attributed(self) -> Self {
        self.select_revenue_attributed()
    }

    pub fn select_revenue_attributed_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_revenue_attributed_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_revenue_attributed_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("revenue_attributed", raw_sql_segment));
        self
    }

    pub fn select_revenue_attributed_with_function(self, function: AggregateFunction) -> Self {
        self.select_revenue_attributed_as_with_function("revenue_attributed", function)
    }

    pub fn select_revenue_attributed_as_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.aggregate_with_function("revenue_attributed", alias, function)
    }

    pub fn group_by_revenue_attributed(self) -> Self {
        self.group_by("revenue_attributed")
    }

    pub fn group_by_revenue_attributed_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("revenue_attributed");
        request.query = request
            .query
            .project_expr(alias, Expr::column("revenue_attributed"));
        request
    }

    pub fn group_by_revenue_attributed_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("revenue_attributed")
            .aggregate_with_function("revenue_attributed", alias, function)
    }

    pub fn count_revenue_attributed(self) -> Self {
        self.count_revenue_attributed_as("revenue_attributed_count")
    }

    pub fn count_revenue_attributed_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("revenue_attributed", alias)
    }

    pub fn sum_revenue_attributed(self) -> Self {
        self.sum_revenue_attributed_as("sum_revenue_attributed")
    }

    pub fn sum_revenue_attributed_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("revenue_attributed", alias)
    }

    pub fn avg_revenue_attributed(self) -> Self {
        self.avg_revenue_attributed_as("avg_revenue_attributed")
    }

    pub fn avg_revenue_attributed_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("revenue_attributed", alias)
    }

    pub fn min_revenue_attributed(self) -> Self {
        self.min_revenue_attributed_as("min_revenue_attributed")
    }

    pub fn min_revenue_attributed_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("revenue_attributed", alias)
    }

    pub fn max_revenue_attributed(self) -> Self {
        self.max_revenue_attributed_as("max_revenue_attributed")
    }

    pub fn max_revenue_attributed_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("revenue_attributed", alias)
    }

    pub fn standard_deviation_revenue_attributed(self) -> Self {
        self.standard_deviation_revenue_attributed_as("stdDev_revenue_attributed")
    }

    pub fn standard_deviation_revenue_attributed_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev("revenue_attributed", alias)
    }

    pub fn square_root_of_population_standard_deviation_revenue_attributed(self) -> Self {
        self.square_root_of_population_standard_deviation_revenue_attributed_as("stdDevPop_revenue_attributed")
    }

    pub fn square_root_of_population_standard_deviation_revenue_attributed_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev_pop("revenue_attributed", alias)
    }

    pub fn sample_variance_revenue_attributed(self) -> Self {
        self.sample_variance_revenue_attributed_as("varSamp_revenue_attributed")
    }

    pub fn sample_variance_revenue_attributed_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_samp("revenue_attributed", alias)
    }

    pub fn sample_population_variance_revenue_attributed(self) -> Self {
        self.sample_population_variance_revenue_attributed_as("varPop_revenue_attributed")
    }

    pub fn sample_population_variance_revenue_attributed_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_pop("revenue_attributed", alias)
    }

    pub fn unselect_revenue_attributed(mut self) -> Self {
        self.query.projection.retain(|field| field != "revenue_attributed");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "revenue_attributed");
        self
    }


    pub fn with_revenue_attributed(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "revenue_attributed",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_revenue_attributed_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "revenue_attributed",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_revenue_attributed_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("revenue_attributed", value));
        self
    }



    pub fn with_revenue_attributed_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("revenue_attributed", value));
        self
    }

    pub fn with_revenue_attributed_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("revenue_attributed", value));
        self
    }

    pub fn with_revenue_attributed_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("revenue_attributed", value));
        self
    }

    pub fn with_revenue_attributed_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("revenue_attributed", value));
        self
    }

    pub fn with_revenue_attributed_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("revenue_attributed", value));
        self
    }

    pub fn with_revenue_attributed_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("revenue_attributed", lower, upper));
        self
    }

    pub fn with_revenue_attributed_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "revenue_attributed",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_revenue_attributed_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "revenue_attributed",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_revenue_attributed_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "revenue_attributed",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_revenue_attributed_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("revenue_attributed", value));
        self
    }

    pub fn with_revenue_attributed_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("revenue_attributed", value));
        self
    }

    pub fn with_revenue_attributed_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("revenue_attributed"));
        self
    }



    pub fn with_revenue_attributed_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("revenue_attributed"));
        self
    }


    pub fn order_by_revenue_attributed_asc(mut self) -> Self {
        self.query = self.query.order_asc("revenue_attributed");
        self
    }

    pub fn order_by_revenue_attributed_desc(mut self) -> Self {
        self.query = self.query.order_desc("revenue_attributed");
        self
    }

    pub fn order_by_revenue_attributed_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("revenue_attributed");
        self
    }

    pub fn order_by_revenue_attributed_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("revenue_attributed");
        self
    }


    pub fn select_date_recorded(mut self) -> Self {
        self.query = self.query.project("date_recorded");
        self
    }

    pub fn project_date_recorded(self) -> Self {
        self.select_date_recorded()
    }

    pub fn select_date_recorded_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_date_recorded_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_date_recorded_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("date_recorded", raw_sql_segment));
        self
    }

    pub fn group_by_date_recorded(self) -> Self {
        self.group_by("date_recorded")
    }

    pub fn group_by_date_recorded_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("date_recorded");
        request.query = request
            .query
            .project_expr(alias, Expr::column("date_recorded"));
        request
    }

    pub fn group_by_date_recorded_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("date_recorded")
            .aggregate_with_function("date_recorded", alias, function)
    }

    pub fn count_date_recorded(self) -> Self {
        self.count_date_recorded_as("date_recorded_count")
    }

    pub fn count_date_recorded_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("date_recorded", alias)
    }

    pub fn sum_date_recorded(self) -> Self {
        self.sum_date_recorded_as("sum_date_recorded")
    }

    pub fn sum_date_recorded_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("date_recorded", alias)
    }

    pub fn avg_date_recorded(self) -> Self {
        self.avg_date_recorded_as("avg_date_recorded")
    }

    pub fn avg_date_recorded_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("date_recorded", alias)
    }

    pub fn min_date_recorded(self) -> Self {
        self.min_date_recorded_as("min_date_recorded")
    }

    pub fn min_date_recorded_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("date_recorded", alias)
    }

    pub fn max_date_recorded(self) -> Self {
        self.max_date_recorded_as("max_date_recorded")
    }

    pub fn max_date_recorded_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("date_recorded", alias)
    }

    pub fn unselect_date_recorded(mut self) -> Self {
        self.query.projection.retain(|field| field != "date_recorded");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "date_recorded");
        self
    }


    pub fn with_date_recorded(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "date_recorded",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_date_recorded_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "date_recorded",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_date_recorded_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("date_recorded", value));
        self
    }



    pub fn with_date_recorded_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("date_recorded", value));
        self
    }

    pub fn with_date_recorded_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("date_recorded", value));
        self
    }

    pub fn with_date_recorded_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("date_recorded", value));
        self
    }

    pub fn with_date_recorded_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("date_recorded", value));
        self
    }

    pub fn with_date_recorded_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("date_recorded", value));
        self
    }

    pub fn with_date_recorded_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("date_recorded", lower, upper));
        self
    }

    pub fn with_date_recorded_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "date_recorded",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_date_recorded_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "date_recorded",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_date_recorded_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "date_recorded",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_date_recorded_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("date_recorded", value));
        self
    }

    pub fn with_date_recorded_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("date_recorded", value));
        self
    }

    pub fn with_date_recorded_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("date_recorded"));
        self
    }



    pub fn with_date_recorded_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("date_recorded"));
        self
    }


    pub fn order_by_date_recorded_asc(mut self) -> Self {
        self.query = self.query.order_asc("date_recorded");
        self
    }

    pub fn order_by_date_recorded_desc(mut self) -> Self {
        self.query = self.query.order_desc("date_recorded");
        self
    }

    pub fn order_by_date_recorded_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("date_recorded");
        self
    }

    pub fn order_by_date_recorded_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("date_recorded");
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
    pub fn filter_by_campaign(mut self, value: impl EntityReference) -> Self {
        self.query = self.query.and_filter(Expr::eq("campaign_id", value.entity_id_value()));
        self
    }

    pub fn with_campaign_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "campaign_id",
            <crate::Campaign as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("campaign", selection));
        self
    }


    pub fn without_campaign_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "campaign_id",
            <crate::Campaign as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("campaign", selection));
        self
    }


    pub fn have_campaign(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("campaign_id"));
        self
    }

    pub fn have_no_campaign(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("campaign_id"));
        self
    }


    pub fn group_by_campaign(self) -> Self {
        self.group_by("campaign_id")
    }

    pub fn group_by_campaign_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("campaign_id");
        request.query = request
            .query
            .project_expr(alias, Expr::column("campaign_id"));
        request
    }

    pub fn group_by_campaign_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("campaign_id")
            .aggregate_with_function("campaign_id", alias, function)
    }

    pub fn group_by_campaign_with(mut self, request: impl Into<QuerySelection>) -> Self {
        self.query = self.query.group_by("campaign_id");
        self.query_options.object_group_bys.push(ObjectGroupBy::new(
            "campaign",
            "campaign_id",
            request,
        ));
        self
    }

    pub fn group_by_campaign_with_details(self) -> Self {
        self.group_by_campaign_with_details_from(crate::Q::campaigns().unlimited())
    }

    pub fn group_by_campaign_with_details_from(self, request: impl Into<QuerySelection>) -> Self {
        self.group_by_campaign_with(request)
    }


    pub fn roll_up_to_campaign(self) -> Self {
        self.roll_up_to_campaign_with(crate::Q::campaigns().unlimited())
    }

    pub fn roll_up_to_campaign_with(self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.with_campaign_matching(selection.clone())
            .group_by_campaign_with(selection)
    }

    pub fn count_campaign(self) -> Self {
        self.count_campaign_as("campaign_count")
    }

    pub fn count_campaign_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("campaign_id", alias)
    }

    pub fn unselect_campaign(mut self) -> Self {
        self.query.projection.retain(|field| field != "campaign_id");
        self.query.relations.retain(|relation| relation.name != "campaign");
        self
    }
    pub fn select_campaign(mut self) -> Self {
        self.query = self.query.relation("campaign");
        self
    }

    pub fn select_campaign_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("campaign", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("campaign", selection));
        self
}

    pub fn facet_by_campaign_as(self, facet_name: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.facet_by_campaign_as_with_options(facet_name, request, true)
    }

    pub fn facet_by_campaign_as_with_options(
        mut self,
        facet_name: impl Into<String>,
        request: impl Into<QuerySelection>,
        include_all_facets: bool,
    ) -> Self {
        self.query_options.facets.push(FacetRequest::new(
            facet_name,
            "campaign",
            request,
            include_all_facets,
        ));
        self
    }
}

impl<R> Default for ConversionMetricRequest<R> {
    fn default() -> Self {
        Self::new()
    }
}

impl<R> From< ConversionMetricRequest<R> > for SelectQuery {
    fn from(request: ConversionMetricRequest<R>) -> Self {
        QuerySelection::from(request).into_query()
    }
}

impl<R> From< ConversionMetricRequest<R> > for QuerySelection {
    fn from(request: ConversionMetricRequest<R>) -> Self {
        Self {
            query: request.query,
            relation_selections: request.relation_selections,
            relation_filters: request.relation_filters,
            child_enhancements: request.child_enhancements,
            query_options: request.query_options,
        }
    }
}


impl<'a, C> crate::request_support::AuditedSave<'a, C> for teaql_core::Audited<crate::ConversionMetric> 
where C: crate::request_support::TeaqlRepositoryProvider + ?Sized + 'a
{
    type Error = crate::TeaqlDataServiceError<C::ConversionMetricRepository<'a>>;
    fn save(self, ctx: &'a C) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<teaql_runtime::GraphNode, Self::Error>> + '_>> {
        Box::pin(async move { self.into_entity().save(ctx).await })
    }
}

impl<R: teaql_core::Entity> crate::PurposedQuery<ConversionMetricRequest<R>> {
    pub fn new_entity<C>(&self, ctx: &C) -> crate::ConversionMetric
    where
        C: crate::TeaqlRuntime + ?Sized,
    {
        crate::ConversionMetric::runtime_new(ctx.user_context().entity_root())
    }

    fn into_inner_with_trace(mut self) -> ConversionMetricRequest<R> {
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
    ) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::ConversionMetricRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_page(ctx, offset, limit).await
    }

    pub async fn execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, crate::request_support::TeaqlDataServiceError<C::ConversionMetricRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_exists(ctx).await
    }

    pub async fn execute_for_list<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::ConversionMetricRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_list(ctx).await
    }

    /// Execute query in streaming mode (chunked).
    /// Returns a Vec of StreamChunk, each containing up to chunk_size rows.
    /// Set chunk size via .stream(chunk_size) or .stream_default() on the query.
    pub async fn execute_for_stream<'a, C>(self, ctx: &'a C) -> Result<Vec<teaql_data_service::StreamChunk>, crate::request_support::TeaqlDataServiceError<C::ConversionMetricRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_stream(ctx).await
    }

    pub async fn execute_for_first<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::ConversionMetricRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_first(ctx).await
    }

    pub async fn execute_for_one<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::ConversionMetricRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_one(ctx).await
    }


    pub async fn execute_for_records<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::ConversionMetricRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_records(ctx).await
    }

    pub async fn execute_for_record<'a, C>(self, ctx: &'a C) -> Result<Option<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::ConversionMetricRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_record(ctx).await
    }

    pub async fn execute_for_count<'a, C>(self, ctx: &'a C) -> Result<u64, crate::request_support::TeaqlDataServiceError<C::ConversionMetricRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_count(ctx).await
    }
}
