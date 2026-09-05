use std::marker::PhantomData;

use serde_json::Value as JsonValue;
use teaql_core::{Aggregate, AggregateFunction, EntityDescriptor, Expr, Record, SelectQuery, SmartList};
use teaql_runtime::{DataServiceError, RuntimeError};

use crate::request_support::*;

impl EntityReference for crate::Campaign {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(&self)
    }
}

impl EntityReference for &crate::Campaign {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(self)
    }
}

// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/campaign
#[derive(Debug)]
pub struct CampaignRequest<R = crate::Campaign> {
    query: SelectQuery,
    relation_selections: Vec<RelationSelection>,
    relation_filters: Vec<RelationFilter>,
    child_enhancements: Vec<QuerySelection>,
    query_options: QueryOptions,
    marker: PhantomData<R>,
}

impl<R> Clone for CampaignRequest<R> {
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

impl<R> CampaignRequest<R> {
    pub(crate) fn new() -> Self {
        Self {
            query: SelectQuery::new("Campaign")
                .project("id")
                .project("version"),
            relation_selections: Vec::new(),
            relation_filters: Vec::new(),
            child_enhancements: Vec::new(),
            query_options: QueryOptions::default(),
            marker: PhantomData,
        }
    }

    pub fn return_type<T>(self) -> CampaignRequest<T> {
        CampaignRequest {
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::CampaignRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
        R: teaql_core::Entity,
    {
        let repository = ctx
            .campaign_repository()
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
    ) -> Result<Vec<teaql_data_service::StreamChunk>, TeaqlDataServiceError<C::CampaignRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .campaign_repository()
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::CampaignRepository<'a>>>
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::CampaignRepository<'a>>>
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::CampaignRepository<'a>>>
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
    ) -> Result<u64, TeaqlDataServiceError<C::CampaignRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .campaign_repository()
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
            .ok_or_else(|| DataServiceError::Runtime(RuntimeError::Graph(format!("count result for Campaign is missing or not numeric"))))
    }

    pub(crate) async fn _execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, TeaqlDataServiceError<C::CampaignRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .campaign_repository()
            .map_err(|err| DataServiceError::Runtime(RuntimeError::Graph(err.to_string())))?;
        let mut query = self.query.limit(1);
        query.relations.clear();
        let rows = repository.fetch_all(&query).await?;
        Ok(!rows.is_empty())
    }

    pub(crate) async fn _execute_for_records<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<SmartList<Record>, TeaqlDataServiceError<C::CampaignRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .campaign_repository()
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
    ) -> Result<Option<Record>, TeaqlDataServiceError<C::CampaignRepository<'a>>>
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
            "start_date" => Some("start_date"),
            "end_date" => Some("end_date"),
            "budget" => Some("budget"),
            "target_audience" => Some("target_audience"),
            "create_time" => Some("create_time"),
            "update_time" => Some("update_time"),
            "version" => Some("version"),
            _ => None,
        }
    }

    fn apply_dynamic_json_chain_filter(self, head: &str, tail: &str, value: &JsonValue) -> Self {
        let _ = (tail, value);
        match head {
            "conversion_metric_list" => {
                self.with_conversion_metric_list_matching(
                    crate::Q::conversion_metrics_minimal()
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
        self.query = self.query.project("name");
        self.query = self.query.project("start_date");
        self.query = self.query.project("end_date");
        self.query = self.query.project("budget");
        self.query = self.query.project("target_audience");
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
        request = request.select_conversion_metric_list();
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


    pub fn select_start_date(mut self) -> Self {
        self.query = self.query.project("start_date");
        self
    }

    pub fn project_start_date(self) -> Self {
        self.select_start_date()
    }

    pub fn select_start_date_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_start_date_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_start_date_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("start_date", raw_sql_segment));
        self
    }

    pub fn group_by_start_date(self) -> Self {
        self.group_by("start_date")
    }

    pub fn group_by_start_date_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("start_date");
        request.query = request
            .query
            .project_expr(alias, Expr::column("start_date"));
        request
    }

    pub fn group_by_start_date_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("start_date")
            .aggregate_with_function("start_date", alias, function)
    }

    pub fn count_start_date(self) -> Self {
        self.count_start_date_as("start_date_count")
    }

    pub fn count_start_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("start_date", alias)
    }

    pub fn sum_start_date(self) -> Self {
        self.sum_start_date_as("sum_start_date")
    }

    pub fn sum_start_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("start_date", alias)
    }

    pub fn avg_start_date(self) -> Self {
        self.avg_start_date_as("avg_start_date")
    }

    pub fn avg_start_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("start_date", alias)
    }

    pub fn min_start_date(self) -> Self {
        self.min_start_date_as("min_start_date")
    }

    pub fn min_start_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("start_date", alias)
    }

    pub fn max_start_date(self) -> Self {
        self.max_start_date_as("max_start_date")
    }

    pub fn max_start_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("start_date", alias)
    }

    pub fn unselect_start_date(mut self) -> Self {
        self.query.projection.retain(|field| field != "start_date");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "start_date");
        self
    }


    pub fn with_start_date(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "start_date",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_start_date_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "start_date",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_start_date_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("start_date", value));
        self
    }



    pub fn with_start_date_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("start_date", value));
        self
    }

    pub fn with_start_date_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("start_date", value));
        self
    }

    pub fn with_start_date_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("start_date", value));
        self
    }

    pub fn with_start_date_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("start_date", value));
        self
    }

    pub fn with_start_date_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("start_date", value));
        self
    }

    pub fn with_start_date_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("start_date", lower, upper));
        self
    }

    pub fn with_start_date_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "start_date",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_start_date_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "start_date",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_start_date_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "start_date",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_start_date_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("start_date", value));
        self
    }

    pub fn with_start_date_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("start_date", value));
        self
    }

    pub fn with_start_date_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("start_date"));
        self
    }



    pub fn with_start_date_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("start_date"));
        self
    }


    pub fn order_by_start_date_asc(mut self) -> Self {
        self.query = self.query.order_asc("start_date");
        self
    }

    pub fn order_by_start_date_desc(mut self) -> Self {
        self.query = self.query.order_desc("start_date");
        self
    }

    pub fn order_by_start_date_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("start_date");
        self
    }

    pub fn order_by_start_date_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("start_date");
        self
    }


    pub fn select_end_date(mut self) -> Self {
        self.query = self.query.project("end_date");
        self
    }

    pub fn project_end_date(self) -> Self {
        self.select_end_date()
    }

    pub fn select_end_date_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_end_date_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_end_date_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("end_date", raw_sql_segment));
        self
    }

    pub fn group_by_end_date(self) -> Self {
        self.group_by("end_date")
    }

    pub fn group_by_end_date_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("end_date");
        request.query = request
            .query
            .project_expr(alias, Expr::column("end_date"));
        request
    }

    pub fn group_by_end_date_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("end_date")
            .aggregate_with_function("end_date", alias, function)
    }

    pub fn count_end_date(self) -> Self {
        self.count_end_date_as("end_date_count")
    }

    pub fn count_end_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("end_date", alias)
    }

    pub fn sum_end_date(self) -> Self {
        self.sum_end_date_as("sum_end_date")
    }

    pub fn sum_end_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("end_date", alias)
    }

    pub fn avg_end_date(self) -> Self {
        self.avg_end_date_as("avg_end_date")
    }

    pub fn avg_end_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("end_date", alias)
    }

    pub fn min_end_date(self) -> Self {
        self.min_end_date_as("min_end_date")
    }

    pub fn min_end_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("end_date", alias)
    }

    pub fn max_end_date(self) -> Self {
        self.max_end_date_as("max_end_date")
    }

    pub fn max_end_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("end_date", alias)
    }

    pub fn unselect_end_date(mut self) -> Self {
        self.query.projection.retain(|field| field != "end_date");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "end_date");
        self
    }


    pub fn with_end_date(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "end_date",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_end_date_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "end_date",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_end_date_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("end_date", value));
        self
    }



    pub fn with_end_date_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("end_date", value));
        self
    }

    pub fn with_end_date_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("end_date", value));
        self
    }

    pub fn with_end_date_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("end_date", value));
        self
    }

    pub fn with_end_date_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("end_date", value));
        self
    }

    pub fn with_end_date_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("end_date", value));
        self
    }

    pub fn with_end_date_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("end_date", lower, upper));
        self
    }

    pub fn with_end_date_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "end_date",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_end_date_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "end_date",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_end_date_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "end_date",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_end_date_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("end_date", value));
        self
    }

    pub fn with_end_date_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("end_date", value));
        self
    }

    pub fn with_end_date_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("end_date"));
        self
    }



    pub fn with_end_date_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("end_date"));
        self
    }


    pub fn order_by_end_date_asc(mut self) -> Self {
        self.query = self.query.order_asc("end_date");
        self
    }

    pub fn order_by_end_date_desc(mut self) -> Self {
        self.query = self.query.order_desc("end_date");
        self
    }

    pub fn order_by_end_date_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("end_date");
        self
    }

    pub fn order_by_end_date_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("end_date");
        self
    }


    pub fn select_budget(mut self) -> Self {
        self.query = self.query.project("budget");
        self
    }

    pub fn project_budget(self) -> Self {
        self.select_budget()
    }

    pub fn select_budget_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_budget_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_budget_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("budget", raw_sql_segment));
        self
    }

    pub fn select_budget_with_function(self, function: AggregateFunction) -> Self {
        self.select_budget_as_with_function("budget", function)
    }

    pub fn select_budget_as_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.aggregate_with_function("budget", alias, function)
    }

    pub fn group_by_budget(self) -> Self {
        self.group_by("budget")
    }

    pub fn group_by_budget_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("budget");
        request.query = request
            .query
            .project_expr(alias, Expr::column("budget"));
        request
    }

    pub fn group_by_budget_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("budget")
            .aggregate_with_function("budget", alias, function)
    }

    pub fn count_budget(self) -> Self {
        self.count_budget_as("budget_count")
    }

    pub fn count_budget_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("budget", alias)
    }

    pub fn sum_budget(self) -> Self {
        self.sum_budget_as("sum_budget")
    }

    pub fn sum_budget_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("budget", alias)
    }

    pub fn avg_budget(self) -> Self {
        self.avg_budget_as("avg_budget")
    }

    pub fn avg_budget_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("budget", alias)
    }

    pub fn min_budget(self) -> Self {
        self.min_budget_as("min_budget")
    }

    pub fn min_budget_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("budget", alias)
    }

    pub fn max_budget(self) -> Self {
        self.max_budget_as("max_budget")
    }

    pub fn max_budget_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("budget", alias)
    }

    pub fn standard_deviation_budget(self) -> Self {
        self.standard_deviation_budget_as("stdDev_budget")
    }

    pub fn standard_deviation_budget_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev("budget", alias)
    }

    pub fn square_root_of_population_standard_deviation_budget(self) -> Self {
        self.square_root_of_population_standard_deviation_budget_as("stdDevPop_budget")
    }

    pub fn square_root_of_population_standard_deviation_budget_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev_pop("budget", alias)
    }

    pub fn sample_variance_budget(self) -> Self {
        self.sample_variance_budget_as("varSamp_budget")
    }

    pub fn sample_variance_budget_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_samp("budget", alias)
    }

    pub fn sample_population_variance_budget(self) -> Self {
        self.sample_population_variance_budget_as("varPop_budget")
    }

    pub fn sample_population_variance_budget_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_pop("budget", alias)
    }

    pub fn unselect_budget(mut self) -> Self {
        self.query.projection.retain(|field| field != "budget");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "budget");
        self
    }


    pub fn with_budget(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "budget",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_budget_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "budget",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_budget_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("budget", value));
        self
    }



    pub fn with_budget_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("budget", value));
        self
    }

    pub fn with_budget_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("budget", value));
        self
    }

    pub fn with_budget_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("budget", value));
        self
    }

    pub fn with_budget_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("budget", value));
        self
    }

    pub fn with_budget_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("budget", value));
        self
    }

    pub fn with_budget_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("budget", lower, upper));
        self
    }

    pub fn with_budget_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "budget",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_budget_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "budget",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_budget_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "budget",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_budget_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("budget", value));
        self
    }

    pub fn with_budget_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("budget", value));
        self
    }

    pub fn with_budget_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("budget"));
        self
    }



    pub fn with_budget_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("budget"));
        self
    }


    pub fn order_by_budget_asc(mut self) -> Self {
        self.query = self.query.order_asc("budget");
        self
    }

    pub fn order_by_budget_desc(mut self) -> Self {
        self.query = self.query.order_desc("budget");
        self
    }

    pub fn order_by_budget_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("budget");
        self
    }

    pub fn order_by_budget_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("budget");
        self
    }


    pub fn select_target_audience(mut self) -> Self {
        self.query = self.query.project("target_audience");
        self
    }

    pub fn project_target_audience(self) -> Self {
        self.select_target_audience()
    }

    pub fn select_target_audience_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_target_audience_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_target_audience_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("target_audience", raw_sql_segment));
        self
    }

    pub fn group_by_target_audience(self) -> Self {
        self.group_by("target_audience")
    }

    pub fn group_by_target_audience_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("target_audience");
        request.query = request
            .query
            .project_expr(alias, Expr::column("target_audience"));
        request
    }

    pub fn group_by_target_audience_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("target_audience")
            .aggregate_with_function("target_audience", alias, function)
    }

    pub fn count_target_audience(self) -> Self {
        self.count_target_audience_as("target_audience_count")
    }

    pub fn count_target_audience_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("target_audience", alias)
    }

    pub fn sum_target_audience(self) -> Self {
        self.sum_target_audience_as("sum_target_audience")
    }

    pub fn sum_target_audience_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("target_audience", alias)
    }

    pub fn avg_target_audience(self) -> Self {
        self.avg_target_audience_as("avg_target_audience")
    }

    pub fn avg_target_audience_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("target_audience", alias)
    }

    pub fn min_target_audience(self) -> Self {
        self.min_target_audience_as("min_target_audience")
    }

    pub fn min_target_audience_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("target_audience", alias)
    }

    pub fn max_target_audience(self) -> Self {
        self.max_target_audience_as("max_target_audience")
    }

    pub fn max_target_audience_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("target_audience", alias)
    }

    pub fn unselect_target_audience(mut self) -> Self {
        self.query.projection.retain(|field| field != "target_audience");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "target_audience");
        self
    }


    pub fn with_target_audience(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "target_audience",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_target_audience_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "target_audience",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_target_audience_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("target_audience", value));
        self
    }



    pub fn with_target_audience_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("target_audience", value));
        self
    }

    pub fn with_target_audience_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("target_audience", value));
        self
    }

    pub fn with_target_audience_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("target_audience", value));
        self
    }

    pub fn with_target_audience_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("target_audience", value));
        self
    }

    pub fn with_target_audience_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("target_audience", value));
        self
    }

    pub fn with_target_audience_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("target_audience", lower, upper));
        self
    }

    pub fn with_target_audience_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "target_audience",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_target_audience_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "target_audience",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_target_audience_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "target_audience",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_target_audience_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("target_audience", value));
        self
    }

    pub fn with_target_audience_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("target_audience", value));
        self
    }

    pub fn with_target_audience_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("target_audience", value));
        self
    }

    pub fn with_target_audience_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("target_audience", value));
        self
    }

    pub fn with_target_audience_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("target_audience", value));
        self
    }

    pub fn with_target_audience_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("target_audience", value));
        self
    }

    pub fn with_target_audience_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("target_audience", value));
        self
    }
    pub fn with_target_audience_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("target_audience", value));
        self
    }

    pub fn with_target_audience_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("target_audience", value));
        self
    }

    pub fn with_target_audience_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("target_audience"));
        self
    }



    pub fn with_target_audience_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("target_audience"));
        self
    }


    pub fn order_by_target_audience_asc(mut self) -> Self {
        self.query = self.query.order_asc("target_audience");
        self
    }

    pub fn order_by_target_audience_desc(mut self) -> Self {
        self.query = self.query.order_desc("target_audience");
        self
    }

    pub fn order_by_target_audience_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("target_audience");
        self
    }

    pub fn order_by_target_audience_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("target_audience");
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
    pub fn name_is_summer_move_promotion(self) -> Self {
        self.with_name_is("Summer Move Promotion")
    }

    pub fn with_name_is_summer_move_promotion(self) -> Self {
        self.with_name_is("Summer Move Promotion")
    }



    pub fn with_name_is_not_summer_move_promotion(self) -> Self {
        self.with_name_is_not("Summer Move Promotion")
    }



    pub fn start_date_is_value_2024_06_01(self) -> Self {
        self.with_start_date_is("2024-06-01")
    }

    pub fn with_start_date_is_value_2024_06_01(self) -> Self {
        self.with_start_date_is("2024-06-01")
    }



    pub fn with_start_date_is_not_value_2024_06_01(self) -> Self {
        self.with_start_date_is_not("2024-06-01")
    }



    pub fn end_date_is_value_2024_08_31(self) -> Self {
        self.with_end_date_is("2024-08-31")
    }

    pub fn with_end_date_is_value_2024_08_31(self) -> Self {
        self.with_end_date_is("2024-08-31")
    }



    pub fn with_end_date_is_not_value_2024_08_31(self) -> Self {
        self.with_end_date_is_not("2024-08-31")
    }



    pub fn budget_is_value_10000_00(self) -> Self {
        self.with_budget_is("10000.00")
    }

    pub fn with_budget_is_value_10000_00(self) -> Self {
        self.with_budget_is("10000.00")
    }



    pub fn with_budget_is_not_value_10000_00(self) -> Self {
        self.with_budget_is_not("10000.00")
    }



    pub fn target_audience_is_residential(self) -> Self {
        self.with_target_audience_is("Residential")
    }

    pub fn with_target_audience_is_residential(self) -> Self {
        self.with_target_audience_is("Residential")
    }



    pub fn with_target_audience_is_not_residential(self) -> Self {
        self.with_target_audience_is_not("Residential")
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




    pub fn have_conversion_metrics(self) -> Self {
        self.with_conversion_metric_list_matching(SelectQuery::new("ConversionMetric"))
    }

    pub fn have_no_conversion_metrics(self) -> Self {
        self.without_conversion_metric_list_matching(SelectQuery::new("ConversionMetric"))
    }

    pub fn with_conversion_metric_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::ConversionMetric as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "campaign_id",
        ));
        self.relation_filters.push(RelationFilter::new("conversion_metric_list", selection));
        self
    }

    pub fn without_conversion_metric_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::ConversionMetric as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "campaign_id",
        ));
        self.relation_filters.push(RelationFilter::new("conversion_metric_list", selection));
        self
    }

    pub fn select_conversion_metric_list(mut self) -> Self {
        self.query = self.query.relation("conversion_metric_list");
        self
    }

    pub fn select_conversion_metric_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("conversion_metric_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("conversion_metric_list", selection));
        self
}
    pub fn count_conversion_metrics(self) -> Self {
        self.count_conversion_metrics_as("count_conversion_metrics")
    }

    pub fn count_conversion_metrics_as(self, alias: impl Into<String>) -> Self {
        self.count_conversion_metrics_with(alias, crate::Q::conversion_metrics().unlimited())
    }

    pub fn count_conversion_metrics_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "conversion_metric_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_conversion_metrics(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as("refinements", request)
    }

    pub fn stats_from_conversion_metrics_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "conversion_metric_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_conversion_metrics_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics(request)
    }


    pub fn sum_leads_generated_of_conversion_metrics(self) -> Self {
        self.sum_leads_generated_of_conversion_metrics_as("sum_leads_generated_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn sum_leads_generated_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().sum("leads_generated", "sum_leads_generated"))
    }
    pub fn min_leads_generated_of_conversion_metrics(self) -> Self {
        self.min_leads_generated_of_conversion_metrics_as("min_leads_generated_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn min_leads_generated_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().min("leads_generated", "min_leads_generated"))
    }
    pub fn max_leads_generated_of_conversion_metrics(self) -> Self {
        self.max_leads_generated_of_conversion_metrics_as("max_leads_generated_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn max_leads_generated_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().max("leads_generated", "max_leads_generated"))
    }
    pub fn avg_leads_generated_of_conversion_metrics(self) -> Self {
        self.avg_leads_generated_of_conversion_metrics_as("avg_leads_generated_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn avg_leads_generated_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().avg("leads_generated", "avg_leads_generated"))
    }
    pub fn standard_deviation_leads_generated_of_conversion_metrics(self) -> Self {
        self.standard_deviation_leads_generated_of_conversion_metrics_as("standard_deviation_leads_generated_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn standard_deviation_leads_generated_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().stddev("leads_generated", "stdDev_leads_generated"))
    }
    pub fn square_root_of_population_standard_deviation_leads_generated_of_conversion_metrics(self) -> Self {
        self.square_root_of_population_standard_deviation_leads_generated_of_conversion_metrics_as("square_root_of_population_standard_deviation_leads_generated_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_leads_generated_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().stddev_pop("leads_generated", "stdDevPop_leads_generated"))
    }
    pub fn sample_variance_leads_generated_of_conversion_metrics(self) -> Self {
        self.sample_variance_leads_generated_of_conversion_metrics_as("sample_variance_leads_generated_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn sample_variance_leads_generated_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().var_samp("leads_generated", "varSamp_leads_generated"))
    }
    pub fn sample_population_variance_leads_generated_of_conversion_metrics(self) -> Self {
        self.sample_population_variance_leads_generated_of_conversion_metrics_as("sample_population_variance_leads_generated_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn sample_population_variance_leads_generated_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().var_pop("leads_generated", "varPop_leads_generated"))
    }
    pub fn sum_conversions_of_conversion_metrics(self) -> Self {
        self.sum_conversions_of_conversion_metrics_as("sum_conversions_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn sum_conversions_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().sum("conversions", "sum_conversions"))
    }
    pub fn min_conversions_of_conversion_metrics(self) -> Self {
        self.min_conversions_of_conversion_metrics_as("min_conversions_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn min_conversions_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().min("conversions", "min_conversions"))
    }
    pub fn max_conversions_of_conversion_metrics(self) -> Self {
        self.max_conversions_of_conversion_metrics_as("max_conversions_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn max_conversions_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().max("conversions", "max_conversions"))
    }
    pub fn avg_conversions_of_conversion_metrics(self) -> Self {
        self.avg_conversions_of_conversion_metrics_as("avg_conversions_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn avg_conversions_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().avg("conversions", "avg_conversions"))
    }
    pub fn standard_deviation_conversions_of_conversion_metrics(self) -> Self {
        self.standard_deviation_conversions_of_conversion_metrics_as("standard_deviation_conversions_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn standard_deviation_conversions_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().stddev("conversions", "stdDev_conversions"))
    }
    pub fn square_root_of_population_standard_deviation_conversions_of_conversion_metrics(self) -> Self {
        self.square_root_of_population_standard_deviation_conversions_of_conversion_metrics_as("square_root_of_population_standard_deviation_conversions_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_conversions_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().stddev_pop("conversions", "stdDevPop_conversions"))
    }
    pub fn sample_variance_conversions_of_conversion_metrics(self) -> Self {
        self.sample_variance_conversions_of_conversion_metrics_as("sample_variance_conversions_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn sample_variance_conversions_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().var_samp("conversions", "varSamp_conversions"))
    }
    pub fn sample_population_variance_conversions_of_conversion_metrics(self) -> Self {
        self.sample_population_variance_conversions_of_conversion_metrics_as("sample_population_variance_conversions_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn sample_population_variance_conversions_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().var_pop("conversions", "varPop_conversions"))
    }
    pub fn sum_conversion_rate_of_conversion_metrics(self) -> Self {
        self.sum_conversion_rate_of_conversion_metrics_as("sum_conversion_rate_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn sum_conversion_rate_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().sum("conversion_rate", "sum_conversion_rate"))
    }
    pub fn min_conversion_rate_of_conversion_metrics(self) -> Self {
        self.min_conversion_rate_of_conversion_metrics_as("min_conversion_rate_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn min_conversion_rate_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().min("conversion_rate", "min_conversion_rate"))
    }
    pub fn max_conversion_rate_of_conversion_metrics(self) -> Self {
        self.max_conversion_rate_of_conversion_metrics_as("max_conversion_rate_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn max_conversion_rate_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().max("conversion_rate", "max_conversion_rate"))
    }
    pub fn avg_conversion_rate_of_conversion_metrics(self) -> Self {
        self.avg_conversion_rate_of_conversion_metrics_as("avg_conversion_rate_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn avg_conversion_rate_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().avg("conversion_rate", "avg_conversion_rate"))
    }
    pub fn standard_deviation_conversion_rate_of_conversion_metrics(self) -> Self {
        self.standard_deviation_conversion_rate_of_conversion_metrics_as("standard_deviation_conversion_rate_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn standard_deviation_conversion_rate_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().stddev("conversion_rate", "stdDev_conversion_rate"))
    }
    pub fn square_root_of_population_standard_deviation_conversion_rate_of_conversion_metrics(self) -> Self {
        self.square_root_of_population_standard_deviation_conversion_rate_of_conversion_metrics_as("square_root_of_population_standard_deviation_conversion_rate_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_conversion_rate_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().stddev_pop("conversion_rate", "stdDevPop_conversion_rate"))
    }
    pub fn sample_variance_conversion_rate_of_conversion_metrics(self) -> Self {
        self.sample_variance_conversion_rate_of_conversion_metrics_as("sample_variance_conversion_rate_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn sample_variance_conversion_rate_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().var_samp("conversion_rate", "varSamp_conversion_rate"))
    }
    pub fn sample_population_variance_conversion_rate_of_conversion_metrics(self) -> Self {
        self.sample_population_variance_conversion_rate_of_conversion_metrics_as("sample_population_variance_conversion_rate_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn sample_population_variance_conversion_rate_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().var_pop("conversion_rate", "varPop_conversion_rate"))
    }
    pub fn sum_revenue_attributed_of_conversion_metrics(self) -> Self {
        self.sum_revenue_attributed_of_conversion_metrics_as("sum_revenue_attributed_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn sum_revenue_attributed_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().sum("revenue_attributed", "sum_revenue_attributed"))
    }
    pub fn min_revenue_attributed_of_conversion_metrics(self) -> Self {
        self.min_revenue_attributed_of_conversion_metrics_as("min_revenue_attributed_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn min_revenue_attributed_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().min("revenue_attributed", "min_revenue_attributed"))
    }
    pub fn max_revenue_attributed_of_conversion_metrics(self) -> Self {
        self.max_revenue_attributed_of_conversion_metrics_as("max_revenue_attributed_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn max_revenue_attributed_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().max("revenue_attributed", "max_revenue_attributed"))
    }
    pub fn avg_revenue_attributed_of_conversion_metrics(self) -> Self {
        self.avg_revenue_attributed_of_conversion_metrics_as("avg_revenue_attributed_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn avg_revenue_attributed_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().avg("revenue_attributed", "avg_revenue_attributed"))
    }
    pub fn standard_deviation_revenue_attributed_of_conversion_metrics(self) -> Self {
        self.standard_deviation_revenue_attributed_of_conversion_metrics_as("standard_deviation_revenue_attributed_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn standard_deviation_revenue_attributed_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().stddev("revenue_attributed", "stdDev_revenue_attributed"))
    }
    pub fn square_root_of_population_standard_deviation_revenue_attributed_of_conversion_metrics(self) -> Self {
        self.square_root_of_population_standard_deviation_revenue_attributed_of_conversion_metrics_as("square_root_of_population_standard_deviation_revenue_attributed_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_revenue_attributed_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().stddev_pop("revenue_attributed", "stdDevPop_revenue_attributed"))
    }
    pub fn sample_variance_revenue_attributed_of_conversion_metrics(self) -> Self {
        self.sample_variance_revenue_attributed_of_conversion_metrics_as("sample_variance_revenue_attributed_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn sample_variance_revenue_attributed_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().var_samp("revenue_attributed", "varSamp_revenue_attributed"))
    }
    pub fn sample_population_variance_revenue_attributed_of_conversion_metrics(self) -> Self {
        self.sample_population_variance_revenue_attributed_of_conversion_metrics_as("sample_population_variance_revenue_attributed_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn sample_population_variance_revenue_attributed_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().var_pop("revenue_attributed", "varPop_revenue_attributed"))
    }
    pub fn min_date_recorded_of_conversion_metrics(self) -> Self {
        self.min_date_recorded_of_conversion_metrics_as("min_date_recorded_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn min_date_recorded_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().min("date_recorded", "min_date_recorded"))
    }
    pub fn max_date_recorded_of_conversion_metrics(self) -> Self {
        self.max_date_recorded_of_conversion_metrics_as("max_date_recorded_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn max_date_recorded_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().max("date_recorded", "max_date_recorded"))
    }
    pub fn min_create_time_of_conversion_metrics(self) -> Self {
        self.min_create_time_of_conversion_metrics_as("min_create_time_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn min_create_time_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_conversion_metrics(self) -> Self {
        self.max_create_time_of_conversion_metrics_as("max_create_time_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn max_create_time_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_conversion_metrics(self) -> Self {
        self.min_update_time_of_conversion_metrics_as("min_update_time_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn min_update_time_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_conversion_metrics(self) -> Self {
        self.max_update_time_of_conversion_metrics_as("max_update_time_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn max_update_time_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }
}

impl<R> Default for CampaignRequest<R> {
    fn default() -> Self {
        Self::new()
    }
}

impl<R> From< CampaignRequest<R> > for SelectQuery {
    fn from(request: CampaignRequest<R>) -> Self {
        QuerySelection::from(request).into_query()
    }
}

impl<R> From< CampaignRequest<R> > for QuerySelection {
    fn from(request: CampaignRequest<R>) -> Self {
        Self {
            query: request.query,
            relation_selections: request.relation_selections,
            relation_filters: request.relation_filters,
            child_enhancements: request.child_enhancements,
            query_options: request.query_options,
        }
    }
}


impl<'a, C> crate::request_support::AuditedSave<'a, C> for teaql_core::Audited<crate::Campaign> 
where C: crate::request_support::TeaqlRepositoryProvider + ?Sized + 'a
{
    type Error = crate::TeaqlDataServiceError<C::CampaignRepository<'a>>;
    fn save(self, ctx: &'a C) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<teaql_runtime::GraphNode, Self::Error>> + '_>> {
        Box::pin(async move { self.into_entity().save(ctx).await })
    }
}

impl<R: teaql_core::Entity> crate::PurposedQuery<CampaignRequest<R>> {
    pub fn new_entity<C>(&self, ctx: &C) -> crate::Campaign
    where
        C: crate::TeaqlRuntime + ?Sized,
    {
        crate::Campaign::runtime_new(ctx.user_context().entity_root())
    }

    fn into_inner_with_trace(mut self) -> CampaignRequest<R> {
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
    ) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::CampaignRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_page(ctx, offset, limit).await
    }

    pub async fn execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, crate::request_support::TeaqlDataServiceError<C::CampaignRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_exists(ctx).await
    }

    pub async fn execute_for_list<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::CampaignRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_list(ctx).await
    }

    /// Execute query in streaming mode (chunked).
    /// Returns a Vec of StreamChunk, each containing up to chunk_size rows.
    /// Set chunk size via .stream(chunk_size) or .stream_default() on the query.
    pub async fn execute_for_stream<'a, C>(self, ctx: &'a C) -> Result<Vec<teaql_data_service::StreamChunk>, crate::request_support::TeaqlDataServiceError<C::CampaignRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_stream(ctx).await
    }

    pub async fn execute_for_first<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::CampaignRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_first(ctx).await
    }

    pub async fn execute_for_one<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::CampaignRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_one(ctx).await
    }


    pub async fn execute_for_records<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::CampaignRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_records(ctx).await
    }

    pub async fn execute_for_record<'a, C>(self, ctx: &'a C) -> Result<Option<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::CampaignRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_record(ctx).await
    }

    pub async fn execute_for_count<'a, C>(self, ctx: &'a C) -> Result<u64, crate::request_support::TeaqlDataServiceError<C::CampaignRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_count(ctx).await
    }
}
