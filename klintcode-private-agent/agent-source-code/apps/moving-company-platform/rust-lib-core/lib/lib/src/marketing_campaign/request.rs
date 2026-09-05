use std::marker::PhantomData;

use serde_json::Value as JsonValue;
use teaql_core::{Aggregate, AggregateFunction, EntityDescriptor, Expr, Record, SelectQuery, SmartList};
use teaql_runtime::{DataServiceError, RuntimeError};

use crate::request_support::*;

impl EntityReference for crate::MarketingCampaign {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(&self)
    }
}

impl EntityReference for &crate::MarketingCampaign {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(self)
    }
}

// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/marketing_campaign
#[derive(Debug)]
pub struct MarketingCampaignRequest<R = crate::MarketingCampaign> {
    query: SelectQuery,
    relation_selections: Vec<RelationSelection>,
    relation_filters: Vec<RelationFilter>,
    child_enhancements: Vec<QuerySelection>,
    query_options: QueryOptions,
    marker: PhantomData<R>,
}

impl<R> Clone for MarketingCampaignRequest<R> {
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

impl<R> MarketingCampaignRequest<R> {
    pub(crate) fn new() -> Self {
        Self {
            query: SelectQuery::new("MarketingCampaign")
                .project("id")
                .project("version"),
            relation_selections: Vec::new(),
            relation_filters: Vec::new(),
            child_enhancements: Vec::new(),
            query_options: QueryOptions::default(),
            marker: PhantomData,
        }
    }

    pub fn return_type<T>(self) -> MarketingCampaignRequest<T> {
        MarketingCampaignRequest {
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::MarketingCampaignRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
        R: teaql_core::Entity,
    {
        let repository = ctx
            .marketing_campaign_repository()
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
    ) -> Result<Vec<teaql_data_service::StreamChunk>, TeaqlDataServiceError<C::MarketingCampaignRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .marketing_campaign_repository()
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::MarketingCampaignRepository<'a>>>
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::MarketingCampaignRepository<'a>>>
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::MarketingCampaignRepository<'a>>>
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
    ) -> Result<u64, TeaqlDataServiceError<C::MarketingCampaignRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .marketing_campaign_repository()
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
            .ok_or_else(|| DataServiceError::Runtime(RuntimeError::Graph(format!("count result for MarketingCampaign is missing or not numeric"))))
    }

    pub(crate) async fn _execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, TeaqlDataServiceError<C::MarketingCampaignRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .marketing_campaign_repository()
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
    ) -> Result<SmartList<Record>, TeaqlDataServiceError<C::MarketingCampaignRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .marketing_campaign_repository()
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
    ) -> Result<Option<Record>, TeaqlDataServiceError<C::MarketingCampaignRepository<'a>>>
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
            "campaign_name" => Some("campaign_name"),
            "target_audience" => Some("target_audience"),
            "budget_amount" => Some("budget_amount"),
            "start_date" => Some("start_date"),
            "end_date" => Some("end_date"),
            "create_time" => Some("create_time"),
            "version" => Some("version"),
            "company_profile" | "company_profile_id" => Some("company_profile_id"),
            "campaign_status" | "campaign_status_id" => Some("campaign_status_id"),
            _ => None,
        }
    }

    fn apply_dynamic_json_chain_filter(self, head: &str, tail: &str, value: &JsonValue) -> Self {
        let _ = (tail, value);
        match head {
            "company_profile" => {
                self.with_company_profile_matching(
                    crate::Q::company_profiles_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "campaign_status" => {
                self.with_campaign_status_matching(
                    crate::Q::campaign_statuses_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "sales_lead_list" => {
                self.with_sales_lead_list_matching(
                    crate::Q::sales_leads_minimal()
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
        self.query = self.query.project("campaign_name");
        self.query = self.query.project("target_audience");
        self.query = self.query.project("budget_amount");
        self.query = self.query.project("start_date");
        self.query = self.query.project("end_date");
        self.query = self.query.project("create_time");
        self.query = self.query.project("version");
        self.query = self.query.project("company_profile_id");
        self.query = self.query.project("campaign_status_id");
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
        request = request.select_company_profile();
        request = request.select_campaign_status();
        request
    }

    pub fn select_children(self) -> Self {
        let mut request = self.select_all();
        request = request.select_sales_lead_list();
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


    pub fn select_campaign_name(mut self) -> Self {
        self.query = self.query.project("campaign_name");
        self
    }

    pub fn project_campaign_name(self) -> Self {
        self.select_campaign_name()
    }

    pub fn select_campaign_name_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_campaign_name_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_campaign_name_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("campaign_name", raw_sql_segment));
        self
    }

    pub fn group_by_campaign_name(self) -> Self {
        self.group_by("campaign_name")
    }

    pub fn group_by_campaign_name_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("campaign_name");
        request.query = request
            .query
            .project_expr(alias, Expr::column("campaign_name"));
        request
    }

    pub fn group_by_campaign_name_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("campaign_name")
            .aggregate_with_function("campaign_name", alias, function)
    }

    pub fn count_campaign_name(self) -> Self {
        self.count_campaign_name_as("campaign_name_count")
    }

    pub fn count_campaign_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("campaign_name", alias)
    }

    pub fn sum_campaign_name(self) -> Self {
        self.sum_campaign_name_as("sum_campaign_name")
    }

    pub fn sum_campaign_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("campaign_name", alias)
    }

    pub fn avg_campaign_name(self) -> Self {
        self.avg_campaign_name_as("avg_campaign_name")
    }

    pub fn avg_campaign_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("campaign_name", alias)
    }

    pub fn min_campaign_name(self) -> Self {
        self.min_campaign_name_as("min_campaign_name")
    }

    pub fn min_campaign_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("campaign_name", alias)
    }

    pub fn max_campaign_name(self) -> Self {
        self.max_campaign_name_as("max_campaign_name")
    }

    pub fn max_campaign_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("campaign_name", alias)
    }

    pub fn unselect_campaign_name(mut self) -> Self {
        self.query.projection.retain(|field| field != "campaign_name");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "campaign_name");
        self
    }


    pub fn with_campaign_name(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "campaign_name",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_campaign_name_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "campaign_name",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_campaign_name_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("campaign_name", value));
        self
    }



    pub fn with_campaign_name_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("campaign_name", value));
        self
    }

    pub fn with_campaign_name_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("campaign_name", value));
        self
    }

    pub fn with_campaign_name_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("campaign_name", value));
        self
    }

    pub fn with_campaign_name_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("campaign_name", value));
        self
    }

    pub fn with_campaign_name_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("campaign_name", value));
        self
    }

    pub fn with_campaign_name_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("campaign_name", lower, upper));
        self
    }

    pub fn with_campaign_name_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "campaign_name",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_campaign_name_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "campaign_name",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_campaign_name_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "campaign_name",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_campaign_name_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("campaign_name", value));
        self
    }

    pub fn with_campaign_name_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("campaign_name", value));
        self
    }

    pub fn with_campaign_name_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("campaign_name", value));
        self
    }

    pub fn with_campaign_name_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("campaign_name", value));
        self
    }

    pub fn with_campaign_name_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("campaign_name", value));
        self
    }

    pub fn with_campaign_name_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("campaign_name", value));
        self
    }

    pub fn with_campaign_name_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("campaign_name", value));
        self
    }
    pub fn with_campaign_name_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("campaign_name", value));
        self
    }

    pub fn with_campaign_name_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("campaign_name", value));
        self
    }

    pub fn with_campaign_name_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("campaign_name"));
        self
    }



    pub fn with_campaign_name_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("campaign_name"));
        self
    }


    pub fn order_by_campaign_name_asc(mut self) -> Self {
        self.query = self.query.order_asc("campaign_name");
        self
    }

    pub fn order_by_campaign_name_desc(mut self) -> Self {
        self.query = self.query.order_desc("campaign_name");
        self
    }

    pub fn order_by_campaign_name_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("campaign_name");
        self
    }

    pub fn order_by_campaign_name_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("campaign_name");
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


    pub fn select_budget_amount(mut self) -> Self {
        self.query = self.query.project("budget_amount");
        self
    }

    pub fn project_budget_amount(self) -> Self {
        self.select_budget_amount()
    }

    pub fn select_budget_amount_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_budget_amount_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_budget_amount_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("budget_amount", raw_sql_segment));
        self
    }

    pub fn select_budget_amount_with_function(self, function: AggregateFunction) -> Self {
        self.select_budget_amount_as_with_function("budget_amount", function)
    }

    pub fn select_budget_amount_as_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.aggregate_with_function("budget_amount", alias, function)
    }

    pub fn group_by_budget_amount(self) -> Self {
        self.group_by("budget_amount")
    }

    pub fn group_by_budget_amount_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("budget_amount");
        request.query = request
            .query
            .project_expr(alias, Expr::column("budget_amount"));
        request
    }

    pub fn group_by_budget_amount_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("budget_amount")
            .aggregate_with_function("budget_amount", alias, function)
    }

    pub fn count_budget_amount(self) -> Self {
        self.count_budget_amount_as("budget_amount_count")
    }

    pub fn count_budget_amount_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("budget_amount", alias)
    }

    pub fn sum_budget_amount(self) -> Self {
        self.sum_budget_amount_as("sum_budget_amount")
    }

    pub fn sum_budget_amount_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("budget_amount", alias)
    }

    pub fn avg_budget_amount(self) -> Self {
        self.avg_budget_amount_as("avg_budget_amount")
    }

    pub fn avg_budget_amount_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("budget_amount", alias)
    }

    pub fn min_budget_amount(self) -> Self {
        self.min_budget_amount_as("min_budget_amount")
    }

    pub fn min_budget_amount_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("budget_amount", alias)
    }

    pub fn max_budget_amount(self) -> Self {
        self.max_budget_amount_as("max_budget_amount")
    }

    pub fn max_budget_amount_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("budget_amount", alias)
    }

    pub fn standard_deviation_budget_amount(self) -> Self {
        self.standard_deviation_budget_amount_as("stdDev_budget_amount")
    }

    pub fn standard_deviation_budget_amount_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev("budget_amount", alias)
    }

    pub fn square_root_of_population_standard_deviation_budget_amount(self) -> Self {
        self.square_root_of_population_standard_deviation_budget_amount_as("stdDevPop_budget_amount")
    }

    pub fn square_root_of_population_standard_deviation_budget_amount_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev_pop("budget_amount", alias)
    }

    pub fn sample_variance_budget_amount(self) -> Self {
        self.sample_variance_budget_amount_as("varSamp_budget_amount")
    }

    pub fn sample_variance_budget_amount_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_samp("budget_amount", alias)
    }

    pub fn sample_population_variance_budget_amount(self) -> Self {
        self.sample_population_variance_budget_amount_as("varPop_budget_amount")
    }

    pub fn sample_population_variance_budget_amount_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_pop("budget_amount", alias)
    }

    pub fn unselect_budget_amount(mut self) -> Self {
        self.query.projection.retain(|field| field != "budget_amount");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "budget_amount");
        self
    }


    pub fn with_budget_amount(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "budget_amount",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_budget_amount_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "budget_amount",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_budget_amount_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("budget_amount", value));
        self
    }



    pub fn with_budget_amount_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("budget_amount", value));
        self
    }

    pub fn with_budget_amount_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("budget_amount", value));
        self
    }

    pub fn with_budget_amount_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("budget_amount", value));
        self
    }

    pub fn with_budget_amount_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("budget_amount", value));
        self
    }

    pub fn with_budget_amount_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("budget_amount", value));
        self
    }

    pub fn with_budget_amount_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("budget_amount", lower, upper));
        self
    }

    pub fn with_budget_amount_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "budget_amount",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_budget_amount_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "budget_amount",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_budget_amount_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "budget_amount",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_budget_amount_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("budget_amount", value));
        self
    }

    pub fn with_budget_amount_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("budget_amount", value));
        self
    }

    pub fn with_budget_amount_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("budget_amount"));
        self
    }



    pub fn with_budget_amount_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("budget_amount"));
        self
    }


    pub fn order_by_budget_amount_asc(mut self) -> Self {
        self.query = self.query.order_asc("budget_amount");
        self
    }

    pub fn order_by_budget_amount_desc(mut self) -> Self {
        self.query = self.query.order_desc("budget_amount");
        self
    }

    pub fn order_by_budget_amount_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("budget_amount");
        self
    }

    pub fn order_by_budget_amount_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("budget_amount");
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
    pub fn filter_by_company_profile(mut self, value: impl EntityReference) -> Self {
        self.query = self.query.and_filter(Expr::eq("company_profile_id", value.entity_id_value()));
        self
    }

    pub fn with_company_profile_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "company_profile_id",
            <crate::CompanyProfile as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("company_profile", selection));
        self
    }


    pub fn without_company_profile_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "company_profile_id",
            <crate::CompanyProfile as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("company_profile", selection));
        self
    }


    pub fn have_company_profile(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("company_profile_id"));
        self
    }

    pub fn have_no_company_profile(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("company_profile_id"));
        self
    }


    pub fn group_by_company_profile(self) -> Self {
        self.group_by("company_profile_id")
    }

    pub fn group_by_company_profile_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("company_profile_id");
        request.query = request
            .query
            .project_expr(alias, Expr::column("company_profile_id"));
        request
    }

    pub fn group_by_company_profile_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("company_profile_id")
            .aggregate_with_function("company_profile_id", alias, function)
    }

    pub fn group_by_company_profile_with(mut self, request: impl Into<QuerySelection>) -> Self {
        self.query = self.query.group_by("company_profile_id");
        self.query_options.object_group_bys.push(ObjectGroupBy::new(
            "company_profile",
            "company_profile_id",
            request,
        ));
        self
    }

    pub fn group_by_company_profile_with_details(self) -> Self {
        self.group_by_company_profile_with_details_from(crate::Q::company_profiles().unlimited())
    }

    pub fn group_by_company_profile_with_details_from(self, request: impl Into<QuerySelection>) -> Self {
        self.group_by_company_profile_with(request)
    }


    pub fn roll_up_to_company_profile(self) -> Self {
        self.roll_up_to_company_profile_with(crate::Q::company_profiles().unlimited())
    }

    pub fn roll_up_to_company_profile_with(self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.with_company_profile_matching(selection.clone())
            .group_by_company_profile_with(selection)
    }

    pub fn count_company_profile(self) -> Self {
        self.count_company_profile_as("company_profile_count")
    }

    pub fn count_company_profile_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("company_profile_id", alias)
    }

    pub fn unselect_company_profile(mut self) -> Self {
        self.query.projection.retain(|field| field != "company_profile_id");
        self.query.relations.retain(|relation| relation.name != "company_profile");
        self
    }


    /// Please use `with_campaign_status_is` instead
    pub(crate) fn filter_by_campaign_status(mut self, value: impl EntityReference) -> Self {
        self.query = self.query.and_filter(Expr::eq("campaign_status_id", value.entity_id_value()));
        self
    }
    /// Complex relation filter for `campaign_status`.
    ///
    /// **Usage Priority:**
    ///
    /// 1. **Preferred**: If you only want to filter by specific known constants, please **prefer** the generated semantic shortcut methods, such as:
    ///    - [`Self::with_campaign_status_is_xxx`]
    ///
    ///    This gives the best code readability.
    ///
    /// 2. **Advanced**: Only use this method when you need to perform advanced searches, dynamic subqueries, or filter based on complex relation conditions.
    ///
    /// # Example
    /// ```rust
    /// // Only use when building dynamic queries
    /// let dynamic_query = crate::Q::campaign_statuses_minimal().filter(...);
    /// let request = crate::Q::marketing_campaigns().with_campaign_status_matching(dynamic_query);
    /// ```
    pub fn with_campaign_status_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "campaign_status_id",
            <crate::CampaignStatus as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("campaign_status", selection));
        self
    }


    /// Complex relation filter for `campaign_status`.
    ///
    /// **Usage Priority:**
    ///
    /// 1. **Preferred**: If you only want to filter by specific known constants, please **prefer** the generated semantic shortcut methods, such as:
    ///    - [`Self::with_campaign_status_is_not_xxx`]
    ///
    ///    This gives the best code readability.
    ///
    /// 2. **Advanced**: Only use this method when you need to perform advanced searches, dynamic subqueries, or filter based on complex relation conditions.
    ///
    /// # Example
    /// ```rust
    /// // Only use when building dynamic queries
    /// let dynamic_query = crate::Q::campaign_statuses_minimal().filter(...);
    /// let request = crate::Q::marketing_campaigns().without_campaign_status_matching(dynamic_query);
    /// ```
    pub fn without_campaign_status_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "campaign_status_id",
            <crate::CampaignStatus as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("campaign_status", selection));
        self
    }


    pub fn have_campaign_status(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("campaign_status_id"));
        self
    }

    pub fn have_no_campaign_status(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("campaign_status_id"));
        self
    }


    pub fn group_by_campaign_status(self) -> Self {
        self.group_by("campaign_status_id")
    }

    pub fn group_by_campaign_status_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("campaign_status_id");
        request.query = request
            .query
            .project_expr(alias, Expr::column("campaign_status_id"));
        request
    }

    pub fn group_by_campaign_status_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("campaign_status_id")
            .aggregate_with_function("campaign_status_id", alias, function)
    }

    pub fn group_by_campaign_status_with(mut self, request: impl Into<QuerySelection>) -> Self {
        self.query = self.query.group_by("campaign_status_id");
        self.query_options.object_group_bys.push(ObjectGroupBy::new(
            "campaign_status",
            "campaign_status_id",
            request,
        ));
        self
    }

    pub fn group_by_campaign_status_with_details(self) -> Self {
        self.group_by_campaign_status_with_details_from(crate::Q::campaign_statuses().unlimited())
    }

    pub fn group_by_campaign_status_with_details_from(self, request: impl Into<QuerySelection>) -> Self {
        self.group_by_campaign_status_with(request)
    }


    pub fn roll_up_to_campaign_status(self) -> Self {
        self.roll_up_to_campaign_status_with(crate::Q::campaign_statuses().unlimited())
    }

    pub fn roll_up_to_campaign_status_with(self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.with_campaign_status_matching(selection.clone())
            .group_by_campaign_status_with(selection)
    }

    pub fn count_campaign_status(self) -> Self {
        self.count_campaign_status_as("campaign_status_count")
    }

    pub fn count_campaign_status_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("campaign_status_id", alias)
    }

    pub fn unselect_campaign_status(mut self) -> Self {
        self.query.projection.retain(|field| field != "campaign_status_id");
        self.query.relations.retain(|relation| relation.name != "campaign_status");
        self
    }
    pub fn campaign_status_is_planned(self) -> Self {
        self.filter_by_campaign_status(9001_u64)
    }

    pub fn with_campaign_status_is_planned(self) -> Self {
        self.filter_by_campaign_status(9001_u64)
    }



    pub fn with_campaign_status_is_not_planned(mut self) -> Self {
        self.query = self.query.and_filter(Expr::ne("campaign_status_id", 9001_u64));
        self
    }


    pub fn campaign_status_is_active(self) -> Self {
        self.filter_by_campaign_status(9002_u64)
    }

    pub fn with_campaign_status_is_active(self) -> Self {
        self.filter_by_campaign_status(9002_u64)
    }



    pub fn with_campaign_status_is_not_active(mut self) -> Self {
        self.query = self.query.and_filter(Expr::ne("campaign_status_id", 9002_u64));
        self
    }


    pub fn campaign_status_is_completed(self) -> Self {
        self.filter_by_campaign_status(9003_u64)
    }

    pub fn with_campaign_status_is_completed(self) -> Self {
        self.filter_by_campaign_status(9003_u64)
    }



    pub fn with_campaign_status_is_not_completed(mut self) -> Self {
        self.query = self.query.and_filter(Expr::ne("campaign_status_id", 9003_u64));
        self
    }


    pub fn select_company_profile(mut self) -> Self {
        self.query = self.query.relation("company_profile");
        self
    }

    pub fn select_company_profile_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("company_profile", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("company_profile", selection));
        self
}

    pub fn facet_by_company_profile_as(self, facet_name: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.facet_by_company_profile_as_with_options(facet_name, request, true)
    }

    pub fn facet_by_company_profile_as_with_options(
        mut self,
        facet_name: impl Into<String>,
        request: impl Into<QuerySelection>,
        include_all_facets: bool,
    ) -> Self {
        self.query_options.facets.push(FacetRequest::new(
            facet_name,
            "company_profile",
            request,
            include_all_facets,
        ));
        self
    }

    pub fn select_campaign_status(mut self) -> Self {
        self.query = self.query.relation("campaign_status");
        self
    }

    pub fn select_campaign_status_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("campaign_status", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("campaign_status", selection));
        self
}

    pub fn facet_by_campaign_status_as(self, facet_name: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.facet_by_campaign_status_as_with_options(facet_name, request, true)
    }

    pub fn facet_by_campaign_status_as_with_options(
        mut self,
        facet_name: impl Into<String>,
        request: impl Into<QuerySelection>,
        include_all_facets: bool,
    ) -> Self {
        self.query_options.facets.push(FacetRequest::new(
            facet_name,
            "campaign_status",
            request,
            include_all_facets,
        ));
        self
    }
    pub fn have_sales_leads(self) -> Self {
        self.with_sales_lead_list_matching(SelectQuery::new("SalesLead"))
    }

    pub fn have_no_sales_leads(self) -> Self {
        self.without_sales_lead_list_matching(SelectQuery::new("SalesLead"))
    }

    pub fn with_sales_lead_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::SalesLead as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "marketing_campaign_id",
        ));
        self.relation_filters.push(RelationFilter::new("sales_lead_list", selection));
        self
    }

    pub fn without_sales_lead_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::SalesLead as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "marketing_campaign_id",
        ));
        self.relation_filters.push(RelationFilter::new("sales_lead_list", selection));
        self
    }

    pub fn select_sales_lead_list(mut self) -> Self {
        self.query = self.query.relation("sales_lead_list");
        self
    }

    pub fn select_sales_lead_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("sales_lead_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("sales_lead_list", selection));
        self
}
    pub fn count_sales_leads(self) -> Self {
        self.count_sales_leads_as("count_sales_leads")
    }

    pub fn count_sales_leads_as(self, alias: impl Into<String>) -> Self {
        self.count_sales_leads_with(alias, crate::Q::sales_leads().unlimited())
    }

    pub fn count_sales_leads_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "sales_lead_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_sales_leads(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_sales_leads_as("refinements", request)
    }

    pub fn stats_from_sales_leads_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "sales_lead_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_sales_leads_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_sales_leads(request)
    }


    pub fn sum_estimated_value_of_sales_leads(self) -> Self {
        self.sum_estimated_value_of_sales_leads_as("sum_estimated_value_of_sales_leads", crate::Q::sales_leads().unlimited())
    }

    pub fn sum_estimated_value_of_sales_leads_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_sales_leads_as(alias, request.into().into_query().sum("estimated_value", "sum_estimated_value"))
    }
    pub fn min_estimated_value_of_sales_leads(self) -> Self {
        self.min_estimated_value_of_sales_leads_as("min_estimated_value_of_sales_leads", crate::Q::sales_leads().unlimited())
    }

    pub fn min_estimated_value_of_sales_leads_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_sales_leads_as(alias, request.into().into_query().min("estimated_value", "min_estimated_value"))
    }
    pub fn max_estimated_value_of_sales_leads(self) -> Self {
        self.max_estimated_value_of_sales_leads_as("max_estimated_value_of_sales_leads", crate::Q::sales_leads().unlimited())
    }

    pub fn max_estimated_value_of_sales_leads_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_sales_leads_as(alias, request.into().into_query().max("estimated_value", "max_estimated_value"))
    }
    pub fn avg_estimated_value_of_sales_leads(self) -> Self {
        self.avg_estimated_value_of_sales_leads_as("avg_estimated_value_of_sales_leads", crate::Q::sales_leads().unlimited())
    }

    pub fn avg_estimated_value_of_sales_leads_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_sales_leads_as(alias, request.into().into_query().avg("estimated_value", "avg_estimated_value"))
    }
    pub fn standard_deviation_estimated_value_of_sales_leads(self) -> Self {
        self.standard_deviation_estimated_value_of_sales_leads_as("standard_deviation_estimated_value_of_sales_leads", crate::Q::sales_leads().unlimited())
    }

    pub fn standard_deviation_estimated_value_of_sales_leads_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_sales_leads_as(alias, request.into().into_query().stddev("estimated_value", "stdDev_estimated_value"))
    }
    pub fn square_root_of_population_standard_deviation_estimated_value_of_sales_leads(self) -> Self {
        self.square_root_of_population_standard_deviation_estimated_value_of_sales_leads_as("square_root_of_population_standard_deviation_estimated_value_of_sales_leads", crate::Q::sales_leads().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_estimated_value_of_sales_leads_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_sales_leads_as(alias, request.into().into_query().stddev_pop("estimated_value", "stdDevPop_estimated_value"))
    }
    pub fn sample_variance_estimated_value_of_sales_leads(self) -> Self {
        self.sample_variance_estimated_value_of_sales_leads_as("sample_variance_estimated_value_of_sales_leads", crate::Q::sales_leads().unlimited())
    }

    pub fn sample_variance_estimated_value_of_sales_leads_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_sales_leads_as(alias, request.into().into_query().var_samp("estimated_value", "varSamp_estimated_value"))
    }
    pub fn sample_population_variance_estimated_value_of_sales_leads(self) -> Self {
        self.sample_population_variance_estimated_value_of_sales_leads_as("sample_population_variance_estimated_value_of_sales_leads", crate::Q::sales_leads().unlimited())
    }

    pub fn sample_population_variance_estimated_value_of_sales_leads_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_sales_leads_as(alias, request.into().into_query().var_pop("estimated_value", "varPop_estimated_value"))
    }
    pub fn min_create_time_of_sales_leads(self) -> Self {
        self.min_create_time_of_sales_leads_as("min_create_time_of_sales_leads", crate::Q::sales_leads().unlimited())
    }

    pub fn min_create_time_of_sales_leads_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_sales_leads_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_sales_leads(self) -> Self {
        self.max_create_time_of_sales_leads_as("max_create_time_of_sales_leads", crate::Q::sales_leads().unlimited())
    }

    pub fn max_create_time_of_sales_leads_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_sales_leads_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
}

impl<R> Default for MarketingCampaignRequest<R> {
    fn default() -> Self {
        Self::new()
    }
}

impl<R> From< MarketingCampaignRequest<R> > for SelectQuery {
    fn from(request: MarketingCampaignRequest<R>) -> Self {
        QuerySelection::from(request).into_query()
    }
}

impl<R> From< MarketingCampaignRequest<R> > for QuerySelection {
    fn from(request: MarketingCampaignRequest<R>) -> Self {
        Self {
            query: request.query,
            relation_selections: request.relation_selections,
            relation_filters: request.relation_filters,
            child_enhancements: request.child_enhancements,
            query_options: request.query_options,
        }
    }
}


impl<'a, C> crate::request_support::AuditedSave<'a, C> for teaql_core::Audited<crate::MarketingCampaign> 
where C: crate::request_support::TeaqlRepositoryProvider + ?Sized + 'a
{
    type Error = crate::TeaqlDataServiceError<C::MarketingCampaignRepository<'a>>;
    fn save(self, ctx: &'a C) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<teaql_runtime::GraphNode, Self::Error>> + '_>> {
        Box::pin(async move {
            teaql_runtime::save_audited_ledger_entity(self, ctx.user_context())
                .await
                .map_err(DataServiceError::Runtime)
        })
    }
}

impl<R: teaql_core::Entity> crate::PurposedQuery<MarketingCampaignRequest<R>> {
    pub fn new_entity<C>(&self, ctx: &C) -> crate::MarketingCampaign
    where
        C: crate::TeaqlRuntime + ?Sized,
    {
        let mut entity = crate::MarketingCampaign::runtime_new(ctx.user_context().entity_root());
        if let Ok(id) = ctx.user_context().next_id(crate::MarketingCampaign::ENTITY_NAME) {
            entity.update_id(id);
        }
        entity
    }

    fn into_inner_with_trace(mut self) -> MarketingCampaignRequest<R> {
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
    ) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::MarketingCampaignRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_page(ctx, offset, limit).await
    }

    pub async fn execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, crate::request_support::TeaqlDataServiceError<C::MarketingCampaignRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_exists(ctx).await
    }

    pub async fn execute_for_list<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::MarketingCampaignRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_list(ctx).await
    }

    /// Execute query in streaming mode (chunked).
    /// Returns a Vec of StreamChunk, each containing up to chunk_size rows.
    /// Set chunk size via .stream(chunk_size) or .stream_default() on the query.
    pub async fn execute_for_stream<'a, C>(self, ctx: &'a C) -> Result<Vec<teaql_data_service::StreamChunk>, crate::request_support::TeaqlDataServiceError<C::MarketingCampaignRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_stream(ctx).await
    }

    pub async fn execute_for_first<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::MarketingCampaignRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_first(ctx).await
    }

    pub async fn execute_for_one<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::MarketingCampaignRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_one(ctx).await
    }


    pub async fn execute_for_records<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::MarketingCampaignRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_records(ctx).await
    }

    pub async fn execute_for_record<'a, C>(self, ctx: &'a C) -> Result<Option<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::MarketingCampaignRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_record(ctx).await
    }

    pub async fn execute_for_count<'a, C>(self, ctx: &'a C) -> Result<u64, crate::request_support::TeaqlDataServiceError<C::MarketingCampaignRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_count(ctx).await
    }
}
