use std::marker::PhantomData;

use serde_json::Value as JsonValue;
use teaql_core::{Aggregate, AggregateFunction, EntityDescriptor, Expr, Record, SelectQuery, SmartList};
use teaql_runtime::{DataServiceError, RuntimeError};

use crate::request_support::*;

impl EntityReference for crate::Company {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(&self)
    }
}

impl EntityReference for &crate::Company {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(self)
    }
}

// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/company
#[derive(Debug)]
pub struct CompanyRequest<R = crate::Company> {
    query: SelectQuery,
    relation_selections: Vec<RelationSelection>,
    relation_filters: Vec<RelationFilter>,
    child_enhancements: Vec<QuerySelection>,
    query_options: QueryOptions,
    marker: PhantomData<R>,
}

impl<R> Clone for CompanyRequest<R> {
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

impl<R> CompanyRequest<R> {
    pub(crate) fn new() -> Self {
        Self {
            query: SelectQuery::new("Company")
                .project("id")
                .project("version"),
            relation_selections: Vec::new(),
            relation_filters: Vec::new(),
            child_enhancements: Vec::new(),
            query_options: QueryOptions::default(),
            marker: PhantomData,
        }
    }

    pub fn return_type<T>(self) -> CompanyRequest<T> {
        CompanyRequest {
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::CompanyRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
        R: teaql_core::Entity,
    {
        let repository = ctx
            .company_repository()
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
    ) -> Result<Vec<teaql_data_service::StreamChunk>, TeaqlDataServiceError<C::CompanyRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .company_repository()
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::CompanyRepository<'a>>>
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::CompanyRepository<'a>>>
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::CompanyRepository<'a>>>
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
    ) -> Result<u64, TeaqlDataServiceError<C::CompanyRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .company_repository()
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
            .ok_or_else(|| DataServiceError::Runtime(RuntimeError::Graph(format!("count result for Company is missing or not numeric"))))
    }

    pub(crate) async fn _execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, TeaqlDataServiceError<C::CompanyRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .company_repository()
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
    ) -> Result<SmartList<Record>, TeaqlDataServiceError<C::CompanyRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .company_repository()
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
    ) -> Result<Option<Record>, TeaqlDataServiceError<C::CompanyRepository<'a>>>
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
            "company_name" => Some("company_name"),
            "founded_year" => Some("founded_year"),
            "create_time" => Some("create_time"),
            "update_time" => Some("update_time"),
            "version" => Some("version"),
            _ => None,
        }
    }

    fn apply_dynamic_json_chain_filter(self, head: &str, tail: &str, value: &JsonValue) -> Self {
        let _ = (tail, value);
        match head {
            "user_account_list" => {
                self.with_user_account_list_matching(
                    crate::Q::user_accounts_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "role_definition_list" => {
                self.with_role_definition_list_matching(
                    crate::Q::role_definitions_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "private_customer_list" => {
                self.with_private_customer_list_matching(
                    crate::Q::private_customers_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "corporate_customer_list" => {
                self.with_corporate_customer_list_matching(
                    crate::Q::corporate_customers_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "vehicle_asset_list" => {
                self.with_vehicle_asset_list_matching(
                    crate::Q::vehicle_assets_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "consumable_item_list" => {
                self.with_consumable_item_list_matching(
                    crate::Q::consumable_items_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "address_record_list" => {
                self.with_address_record_list_matching(
                    crate::Q::address_records_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "service_catalog_list" => {
                self.with_service_catalog_list_matching(
                    crate::Q::service_catalogs_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "marketing_campaign_list" => {
                self.with_marketing_campaign_list_matching(
                    crate::Q::marketing_campaigns_minimal()
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
        self.query = self.query.project("company_name");
        self.query = self.query.project("founded_year");
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
        request = request.select_user_account_list();
        request = request.select_role_definition_list();
        request = request.select_private_customer_list();
        request = request.select_corporate_customer_list();
        request = request.select_vehicle_asset_list();
        request = request.select_consumable_item_list();
        request = request.select_address_record_list();
        request = request.select_service_catalog_list();
        request = request.select_marketing_campaign_list();
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


    pub fn select_company_name(mut self) -> Self {
        self.query = self.query.project("company_name");
        self
    }

    pub fn project_company_name(self) -> Self {
        self.select_company_name()
    }

    pub fn select_company_name_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_company_name_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_company_name_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("company_name", raw_sql_segment));
        self
    }

    pub fn group_by_company_name(self) -> Self {
        self.group_by("company_name")
    }

    pub fn group_by_company_name_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("company_name");
        request.query = request
            .query
            .project_expr(alias, Expr::column("company_name"));
        request
    }

    pub fn group_by_company_name_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("company_name")
            .aggregate_with_function("company_name", alias, function)
    }

    pub fn count_company_name(self) -> Self {
        self.count_company_name_as("company_name_count")
    }

    pub fn count_company_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("company_name", alias)
    }

    pub fn sum_company_name(self) -> Self {
        self.sum_company_name_as("sum_company_name")
    }

    pub fn sum_company_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("company_name", alias)
    }

    pub fn avg_company_name(self) -> Self {
        self.avg_company_name_as("avg_company_name")
    }

    pub fn avg_company_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("company_name", alias)
    }

    pub fn min_company_name(self) -> Self {
        self.min_company_name_as("min_company_name")
    }

    pub fn min_company_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("company_name", alias)
    }

    pub fn max_company_name(self) -> Self {
        self.max_company_name_as("max_company_name")
    }

    pub fn max_company_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("company_name", alias)
    }

    pub fn unselect_company_name(mut self) -> Self {
        self.query.projection.retain(|field| field != "company_name");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "company_name");
        self
    }


    pub fn with_company_name(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "company_name",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_company_name_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "company_name",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_company_name_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("company_name", value));
        self
    }



    pub fn with_company_name_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("company_name", value));
        self
    }

    pub fn with_company_name_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("company_name", value));
        self
    }

    pub fn with_company_name_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("company_name", value));
        self
    }

    pub fn with_company_name_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("company_name", value));
        self
    }

    pub fn with_company_name_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("company_name", value));
        self
    }

    pub fn with_company_name_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("company_name", lower, upper));
        self
    }

    pub fn with_company_name_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "company_name",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_company_name_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "company_name",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_company_name_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "company_name",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_company_name_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("company_name", value));
        self
    }

    pub fn with_company_name_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("company_name", value));
        self
    }

    pub fn with_company_name_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("company_name", value));
        self
    }

    pub fn with_company_name_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("company_name", value));
        self
    }

    pub fn with_company_name_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("company_name", value));
        self
    }

    pub fn with_company_name_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("company_name", value));
        self
    }

    pub fn with_company_name_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("company_name", value));
        self
    }
    pub fn with_company_name_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("company_name", value));
        self
    }

    pub fn with_company_name_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("company_name", value));
        self
    }

    pub fn with_company_name_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("company_name"));
        self
    }



    pub fn with_company_name_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("company_name"));
        self
    }


    pub fn order_by_company_name_asc(mut self) -> Self {
        self.query = self.query.order_asc("company_name");
        self
    }

    pub fn order_by_company_name_desc(mut self) -> Self {
        self.query = self.query.order_desc("company_name");
        self
    }

    pub fn order_by_company_name_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("company_name");
        self
    }

    pub fn order_by_company_name_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("company_name");
        self
    }


    pub fn select_founded_year(mut self) -> Self {
        self.query = self.query.project("founded_year");
        self
    }

    pub fn project_founded_year(self) -> Self {
        self.select_founded_year()
    }

    pub fn select_founded_year_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_founded_year_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_founded_year_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("founded_year", raw_sql_segment));
        self
    }

    pub fn select_founded_year_with_function(self, function: AggregateFunction) -> Self {
        self.select_founded_year_as_with_function("founded_year", function)
    }

    pub fn select_founded_year_as_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.aggregate_with_function("founded_year", alias, function)
    }

    pub fn group_by_founded_year(self) -> Self {
        self.group_by("founded_year")
    }

    pub fn group_by_founded_year_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("founded_year");
        request.query = request
            .query
            .project_expr(alias, Expr::column("founded_year"));
        request
    }

    pub fn group_by_founded_year_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("founded_year")
            .aggregate_with_function("founded_year", alias, function)
    }

    pub fn count_founded_year(self) -> Self {
        self.count_founded_year_as("founded_year_count")
    }

    pub fn count_founded_year_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("founded_year", alias)
    }

    pub fn sum_founded_year(self) -> Self {
        self.sum_founded_year_as("sum_founded_year")
    }

    pub fn sum_founded_year_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("founded_year", alias)
    }

    pub fn avg_founded_year(self) -> Self {
        self.avg_founded_year_as("avg_founded_year")
    }

    pub fn avg_founded_year_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("founded_year", alias)
    }

    pub fn min_founded_year(self) -> Self {
        self.min_founded_year_as("min_founded_year")
    }

    pub fn min_founded_year_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("founded_year", alias)
    }

    pub fn max_founded_year(self) -> Self {
        self.max_founded_year_as("max_founded_year")
    }

    pub fn max_founded_year_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("founded_year", alias)
    }

    pub fn standard_deviation_founded_year(self) -> Self {
        self.standard_deviation_founded_year_as("stdDev_founded_year")
    }

    pub fn standard_deviation_founded_year_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev("founded_year", alias)
    }

    pub fn square_root_of_population_standard_deviation_founded_year(self) -> Self {
        self.square_root_of_population_standard_deviation_founded_year_as("stdDevPop_founded_year")
    }

    pub fn square_root_of_population_standard_deviation_founded_year_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev_pop("founded_year", alias)
    }

    pub fn sample_variance_founded_year(self) -> Self {
        self.sample_variance_founded_year_as("varSamp_founded_year")
    }

    pub fn sample_variance_founded_year_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_samp("founded_year", alias)
    }

    pub fn sample_population_variance_founded_year(self) -> Self {
        self.sample_population_variance_founded_year_as("varPop_founded_year")
    }

    pub fn sample_population_variance_founded_year_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_pop("founded_year", alias)
    }

    pub fn unselect_founded_year(mut self) -> Self {
        self.query.projection.retain(|field| field != "founded_year");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "founded_year");
        self
    }


    pub fn with_founded_year(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "founded_year",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_founded_year_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "founded_year",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_founded_year_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("founded_year", value));
        self
    }



    pub fn with_founded_year_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("founded_year", value));
        self
    }

    pub fn with_founded_year_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("founded_year", value));
        self
    }

    pub fn with_founded_year_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("founded_year", value));
        self
    }

    pub fn with_founded_year_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("founded_year", value));
        self
    }

    pub fn with_founded_year_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("founded_year", value));
        self
    }

    pub fn with_founded_year_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("founded_year", lower, upper));
        self
    }

    pub fn with_founded_year_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "founded_year",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_founded_year_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "founded_year",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_founded_year_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "founded_year",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_founded_year_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("founded_year", value));
        self
    }

    pub fn with_founded_year_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("founded_year", value));
        self
    }

    pub fn with_founded_year_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("founded_year"));
        self
    }



    pub fn with_founded_year_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("founded_year"));
        self
    }


    pub fn order_by_founded_year_asc(mut self) -> Self {
        self.query = self.query.order_asc("founded_year");
        self
    }

    pub fn order_by_founded_year_desc(mut self) -> Self {
        self.query = self.query.order_desc("founded_year");
        self
    }

    pub fn order_by_founded_year_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("founded_year");
        self
    }

    pub fn order_by_founded_year_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("founded_year");
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
    pub fn company_name_is_fast_movers_inc(self) -> Self {
        self.with_company_name_is("Fast Movers Inc")
    }

    pub fn with_company_name_is_fast_movers_inc(self) -> Self {
        self.with_company_name_is("Fast Movers Inc")
    }



    pub fn with_company_name_is_not_fast_movers_inc(self) -> Self {
        self.with_company_name_is_not("Fast Movers Inc")
    }



    pub fn founded_year_is_value_1998(self) -> Self {
        self.with_founded_year_is("1998")
    }

    pub fn with_founded_year_is_value_1998(self) -> Self {
        self.with_founded_year_is("1998")
    }



    pub fn with_founded_year_is_not_value_1998(self) -> Self {
        self.with_founded_year_is_not("1998")
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




    pub fn have_user_accounts(self) -> Self {
        self.with_user_account_list_matching(SelectQuery::new("UserAccount"))
    }

    pub fn have_no_user_accounts(self) -> Self {
        self.without_user_account_list_matching(SelectQuery::new("UserAccount"))
    }

    pub fn with_user_account_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::UserAccount as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "company_id",
        ));
        self.relation_filters.push(RelationFilter::new("user_account_list", selection));
        self
    }

    pub fn without_user_account_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::UserAccount as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "company_id",
        ));
        self.relation_filters.push(RelationFilter::new("user_account_list", selection));
        self
    }

    pub fn select_user_account_list(mut self) -> Self {
        self.query = self.query.relation("user_account_list");
        self
    }

    pub fn select_user_account_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("user_account_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("user_account_list", selection));
        self
}

    pub fn have_role_definitions(self) -> Self {
        self.with_role_definition_list_matching(SelectQuery::new("RoleDefinition"))
    }

    pub fn have_no_role_definitions(self) -> Self {
        self.without_role_definition_list_matching(SelectQuery::new("RoleDefinition"))
    }

    pub fn with_role_definition_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::RoleDefinition as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "company_id",
        ));
        self.relation_filters.push(RelationFilter::new("role_definition_list", selection));
        self
    }

    pub fn without_role_definition_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::RoleDefinition as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "company_id",
        ));
        self.relation_filters.push(RelationFilter::new("role_definition_list", selection));
        self
    }

    pub fn select_role_definition_list(mut self) -> Self {
        self.query = self.query.relation("role_definition_list");
        self
    }

    pub fn select_role_definition_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("role_definition_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("role_definition_list", selection));
        self
}

    pub fn have_private_customers(self) -> Self {
        self.with_private_customer_list_matching(SelectQuery::new("PrivateCustomer"))
    }

    pub fn have_no_private_customers(self) -> Self {
        self.without_private_customer_list_matching(SelectQuery::new("PrivateCustomer"))
    }

    pub fn with_private_customer_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::PrivateCustomer as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "company_id",
        ));
        self.relation_filters.push(RelationFilter::new("private_customer_list", selection));
        self
    }

    pub fn without_private_customer_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::PrivateCustomer as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "company_id",
        ));
        self.relation_filters.push(RelationFilter::new("private_customer_list", selection));
        self
    }

    pub fn select_private_customer_list(mut self) -> Self {
        self.query = self.query.relation("private_customer_list");
        self
    }

    pub fn select_private_customer_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("private_customer_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("private_customer_list", selection));
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
            "company_id",
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
            "company_id",
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

    pub fn have_vehicle_assets(self) -> Self {
        self.with_vehicle_asset_list_matching(SelectQuery::new("VehicleAsset"))
    }

    pub fn have_no_vehicle_assets(self) -> Self {
        self.without_vehicle_asset_list_matching(SelectQuery::new("VehicleAsset"))
    }

    pub fn with_vehicle_asset_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::VehicleAsset as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "company_id",
        ));
        self.relation_filters.push(RelationFilter::new("vehicle_asset_list", selection));
        self
    }

    pub fn without_vehicle_asset_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::VehicleAsset as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "company_id",
        ));
        self.relation_filters.push(RelationFilter::new("vehicle_asset_list", selection));
        self
    }

    pub fn select_vehicle_asset_list(mut self) -> Self {
        self.query = self.query.relation("vehicle_asset_list");
        self
    }

    pub fn select_vehicle_asset_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("vehicle_asset_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("vehicle_asset_list", selection));
        self
}

    pub fn have_consumable_items(self) -> Self {
        self.with_consumable_item_list_matching(SelectQuery::new("ConsumableItem"))
    }

    pub fn have_no_consumable_items(self) -> Self {
        self.without_consumable_item_list_matching(SelectQuery::new("ConsumableItem"))
    }

    pub fn with_consumable_item_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::ConsumableItem as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "company_id",
        ));
        self.relation_filters.push(RelationFilter::new("consumable_item_list", selection));
        self
    }

    pub fn without_consumable_item_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::ConsumableItem as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "company_id",
        ));
        self.relation_filters.push(RelationFilter::new("consumable_item_list", selection));
        self
    }

    pub fn select_consumable_item_list(mut self) -> Self {
        self.query = self.query.relation("consumable_item_list");
        self
    }

    pub fn select_consumable_item_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("consumable_item_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("consumable_item_list", selection));
        self
}

    pub fn have_address_records(self) -> Self {
        self.with_address_record_list_matching(SelectQuery::new("AddressRecord"))
    }

    pub fn have_no_address_records(self) -> Self {
        self.without_address_record_list_matching(SelectQuery::new("AddressRecord"))
    }

    pub fn with_address_record_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::AddressRecord as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "company_id",
        ));
        self.relation_filters.push(RelationFilter::new("address_record_list", selection));
        self
    }

    pub fn without_address_record_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::AddressRecord as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "company_id",
        ));
        self.relation_filters.push(RelationFilter::new("address_record_list", selection));
        self
    }

    pub fn select_address_record_list(mut self) -> Self {
        self.query = self.query.relation("address_record_list");
        self
    }

    pub fn select_address_record_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("address_record_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("address_record_list", selection));
        self
}

    pub fn have_service_catalogs(self) -> Self {
        self.with_service_catalog_list_matching(SelectQuery::new("ServiceCatalog"))
    }

    pub fn have_no_service_catalogs(self) -> Self {
        self.without_service_catalog_list_matching(SelectQuery::new("ServiceCatalog"))
    }

    pub fn with_service_catalog_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::ServiceCatalog as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "company_id",
        ));
        self.relation_filters.push(RelationFilter::new("service_catalog_list", selection));
        self
    }

    pub fn without_service_catalog_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::ServiceCatalog as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "company_id",
        ));
        self.relation_filters.push(RelationFilter::new("service_catalog_list", selection));
        self
    }

    pub fn select_service_catalog_list(mut self) -> Self {
        self.query = self.query.relation("service_catalog_list");
        self
    }

    pub fn select_service_catalog_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("service_catalog_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("service_catalog_list", selection));
        self
}

    pub fn have_marketing_campaigns(self) -> Self {
        self.with_marketing_campaign_list_matching(SelectQuery::new("MarketingCampaign"))
    }

    pub fn have_no_marketing_campaigns(self) -> Self {
        self.without_marketing_campaign_list_matching(SelectQuery::new("MarketingCampaign"))
    }

    pub fn with_marketing_campaign_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::MarketingCampaign as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "company_id",
        ));
        self.relation_filters.push(RelationFilter::new("marketing_campaign_list", selection));
        self
    }

    pub fn without_marketing_campaign_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::MarketingCampaign as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "company_id",
        ));
        self.relation_filters.push(RelationFilter::new("marketing_campaign_list", selection));
        self
    }

    pub fn select_marketing_campaign_list(mut self) -> Self {
        self.query = self.query.relation("marketing_campaign_list");
        self
    }

    pub fn select_marketing_campaign_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("marketing_campaign_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("marketing_campaign_list", selection));
        self
}
    pub fn count_user_accounts(self) -> Self {
        self.count_user_accounts_as("count_user_accounts")
    }

    pub fn count_user_accounts_as(self, alias: impl Into<String>) -> Self {
        self.count_user_accounts_with(alias, crate::Q::user_accounts().unlimited())
    }

    pub fn count_user_accounts_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "user_account_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_user_accounts(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_user_accounts_as("refinements", request)
    }

    pub fn stats_from_user_accounts_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "user_account_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_user_accounts_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_user_accounts(request)
    }


    pub fn min_create_time_of_user_accounts(self) -> Self {
        self.min_create_time_of_user_accounts_as("min_create_time_of_user_accounts", crate::Q::user_accounts().unlimited())
    }

    pub fn min_create_time_of_user_accounts_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_user_accounts_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_user_accounts(self) -> Self {
        self.max_create_time_of_user_accounts_as("max_create_time_of_user_accounts", crate::Q::user_accounts().unlimited())
    }

    pub fn max_create_time_of_user_accounts_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_user_accounts_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_user_accounts(self) -> Self {
        self.min_update_time_of_user_accounts_as("min_update_time_of_user_accounts", crate::Q::user_accounts().unlimited())
    }

    pub fn min_update_time_of_user_accounts_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_user_accounts_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_user_accounts(self) -> Self {
        self.max_update_time_of_user_accounts_as("max_update_time_of_user_accounts", crate::Q::user_accounts().unlimited())
    }

    pub fn max_update_time_of_user_accounts_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_user_accounts_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }

    pub fn count_role_definitions(self) -> Self {
        self.count_role_definitions_as("count_role_definitions")
    }

    pub fn count_role_definitions_as(self, alias: impl Into<String>) -> Self {
        self.count_role_definitions_with(alias, crate::Q::role_definitions().unlimited())
    }

    pub fn count_role_definitions_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "role_definition_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_role_definitions(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_role_definitions_as("refinements", request)
    }

    pub fn stats_from_role_definitions_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "role_definition_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_role_definitions_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_role_definitions(request)
    }


    pub fn min_create_time_of_role_definitions(self) -> Self {
        self.min_create_time_of_role_definitions_as("min_create_time_of_role_definitions", crate::Q::role_definitions().unlimited())
    }

    pub fn min_create_time_of_role_definitions_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_role_definitions_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_role_definitions(self) -> Self {
        self.max_create_time_of_role_definitions_as("max_create_time_of_role_definitions", crate::Q::role_definitions().unlimited())
    }

    pub fn max_create_time_of_role_definitions_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_role_definitions_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_role_definitions(self) -> Self {
        self.min_update_time_of_role_definitions_as("min_update_time_of_role_definitions", crate::Q::role_definitions().unlimited())
    }

    pub fn min_update_time_of_role_definitions_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_role_definitions_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_role_definitions(self) -> Self {
        self.max_update_time_of_role_definitions_as("max_update_time_of_role_definitions", crate::Q::role_definitions().unlimited())
    }

    pub fn max_update_time_of_role_definitions_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_role_definitions_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }

    pub fn count_private_customers(self) -> Self {
        self.count_private_customers_as("count_private_customers")
    }

    pub fn count_private_customers_as(self, alias: impl Into<String>) -> Self {
        self.count_private_customers_with(alias, crate::Q::private_customers().unlimited())
    }

    pub fn count_private_customers_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "private_customer_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_private_customers(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_private_customers_as("refinements", request)
    }

    pub fn stats_from_private_customers_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "private_customer_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_private_customers_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_private_customers(request)
    }


    pub fn min_create_time_of_private_customers(self) -> Self {
        self.min_create_time_of_private_customers_as("min_create_time_of_private_customers", crate::Q::private_customers().unlimited())
    }

    pub fn min_create_time_of_private_customers_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_private_customers_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_private_customers(self) -> Self {
        self.max_create_time_of_private_customers_as("max_create_time_of_private_customers", crate::Q::private_customers().unlimited())
    }

    pub fn max_create_time_of_private_customers_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_private_customers_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_private_customers(self) -> Self {
        self.min_update_time_of_private_customers_as("min_update_time_of_private_customers", crate::Q::private_customers().unlimited())
    }

    pub fn min_update_time_of_private_customers_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_private_customers_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_private_customers(self) -> Self {
        self.max_update_time_of_private_customers_as("max_update_time_of_private_customers", crate::Q::private_customers().unlimited())
    }

    pub fn max_update_time_of_private_customers_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_private_customers_as(alias, request.into().into_query().max("update_time", "max_update_time"))
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

    pub fn count_vehicle_assets(self) -> Self {
        self.count_vehicle_assets_as("count_vehicle_assets")
    }

    pub fn count_vehicle_assets_as(self, alias: impl Into<String>) -> Self {
        self.count_vehicle_assets_with(alias, crate::Q::vehicle_assets().unlimited())
    }

    pub fn count_vehicle_assets_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "vehicle_asset_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_vehicle_assets(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_vehicle_assets_as("refinements", request)
    }

    pub fn stats_from_vehicle_assets_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "vehicle_asset_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_vehicle_assets_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_vehicle_assets(request)
    }


    pub fn min_create_time_of_vehicle_assets(self) -> Self {
        self.min_create_time_of_vehicle_assets_as("min_create_time_of_vehicle_assets", crate::Q::vehicle_assets().unlimited())
    }

    pub fn min_create_time_of_vehicle_assets_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_vehicle_assets_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_vehicle_assets(self) -> Self {
        self.max_create_time_of_vehicle_assets_as("max_create_time_of_vehicle_assets", crate::Q::vehicle_assets().unlimited())
    }

    pub fn max_create_time_of_vehicle_assets_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_vehicle_assets_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_vehicle_assets(self) -> Self {
        self.min_update_time_of_vehicle_assets_as("min_update_time_of_vehicle_assets", crate::Q::vehicle_assets().unlimited())
    }

    pub fn min_update_time_of_vehicle_assets_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_vehicle_assets_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_vehicle_assets(self) -> Self {
        self.max_update_time_of_vehicle_assets_as("max_update_time_of_vehicle_assets", crate::Q::vehicle_assets().unlimited())
    }

    pub fn max_update_time_of_vehicle_assets_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_vehicle_assets_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }

    pub fn count_consumable_items(self) -> Self {
        self.count_consumable_items_as("count_consumable_items")
    }

    pub fn count_consumable_items_as(self, alias: impl Into<String>) -> Self {
        self.count_consumable_items_with(alias, crate::Q::consumable_items().unlimited())
    }

    pub fn count_consumable_items_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "consumable_item_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_consumable_items(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_consumable_items_as("refinements", request)
    }

    pub fn stats_from_consumable_items_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "consumable_item_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_consumable_items_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_consumable_items(request)
    }


    pub fn sum_quantity_in_stock_of_consumable_items(self) -> Self {
        self.sum_quantity_in_stock_of_consumable_items_as("sum_quantity_in_stock_of_consumable_items", crate::Q::consumable_items().unlimited())
    }

    pub fn sum_quantity_in_stock_of_consumable_items_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_consumable_items_as(alias, request.into().into_query().sum("quantity_in_stock", "sum_quantity_in_stock"))
    }
    pub fn min_quantity_in_stock_of_consumable_items(self) -> Self {
        self.min_quantity_in_stock_of_consumable_items_as("min_quantity_in_stock_of_consumable_items", crate::Q::consumable_items().unlimited())
    }

    pub fn min_quantity_in_stock_of_consumable_items_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_consumable_items_as(alias, request.into().into_query().min("quantity_in_stock", "min_quantity_in_stock"))
    }
    pub fn max_quantity_in_stock_of_consumable_items(self) -> Self {
        self.max_quantity_in_stock_of_consumable_items_as("max_quantity_in_stock_of_consumable_items", crate::Q::consumable_items().unlimited())
    }

    pub fn max_quantity_in_stock_of_consumable_items_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_consumable_items_as(alias, request.into().into_query().max("quantity_in_stock", "max_quantity_in_stock"))
    }
    pub fn avg_quantity_in_stock_of_consumable_items(self) -> Self {
        self.avg_quantity_in_stock_of_consumable_items_as("avg_quantity_in_stock_of_consumable_items", crate::Q::consumable_items().unlimited())
    }

    pub fn avg_quantity_in_stock_of_consumable_items_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_consumable_items_as(alias, request.into().into_query().avg("quantity_in_stock", "avg_quantity_in_stock"))
    }
    pub fn standard_deviation_quantity_in_stock_of_consumable_items(self) -> Self {
        self.standard_deviation_quantity_in_stock_of_consumable_items_as("standard_deviation_quantity_in_stock_of_consumable_items", crate::Q::consumable_items().unlimited())
    }

    pub fn standard_deviation_quantity_in_stock_of_consumable_items_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_consumable_items_as(alias, request.into().into_query().stddev("quantity_in_stock", "stdDev_quantity_in_stock"))
    }
    pub fn square_root_of_population_standard_deviation_quantity_in_stock_of_consumable_items(self) -> Self {
        self.square_root_of_population_standard_deviation_quantity_in_stock_of_consumable_items_as("square_root_of_population_standard_deviation_quantity_in_stock_of_consumable_items", crate::Q::consumable_items().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_quantity_in_stock_of_consumable_items_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_consumable_items_as(alias, request.into().into_query().stddev_pop("quantity_in_stock", "stdDevPop_quantity_in_stock"))
    }
    pub fn sample_variance_quantity_in_stock_of_consumable_items(self) -> Self {
        self.sample_variance_quantity_in_stock_of_consumable_items_as("sample_variance_quantity_in_stock_of_consumable_items", crate::Q::consumable_items().unlimited())
    }

    pub fn sample_variance_quantity_in_stock_of_consumable_items_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_consumable_items_as(alias, request.into().into_query().var_samp("quantity_in_stock", "varSamp_quantity_in_stock"))
    }
    pub fn sample_population_variance_quantity_in_stock_of_consumable_items(self) -> Self {
        self.sample_population_variance_quantity_in_stock_of_consumable_items_as("sample_population_variance_quantity_in_stock_of_consumable_items", crate::Q::consumable_items().unlimited())
    }

    pub fn sample_population_variance_quantity_in_stock_of_consumable_items_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_consumable_items_as(alias, request.into().into_query().var_pop("quantity_in_stock", "varPop_quantity_in_stock"))
    }
    pub fn min_create_time_of_consumable_items(self) -> Self {
        self.min_create_time_of_consumable_items_as("min_create_time_of_consumable_items", crate::Q::consumable_items().unlimited())
    }

    pub fn min_create_time_of_consumable_items_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_consumable_items_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_consumable_items(self) -> Self {
        self.max_create_time_of_consumable_items_as("max_create_time_of_consumable_items", crate::Q::consumable_items().unlimited())
    }

    pub fn max_create_time_of_consumable_items_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_consumable_items_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_consumable_items(self) -> Self {
        self.min_update_time_of_consumable_items_as("min_update_time_of_consumable_items", crate::Q::consumable_items().unlimited())
    }

    pub fn min_update_time_of_consumable_items_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_consumable_items_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_consumable_items(self) -> Self {
        self.max_update_time_of_consumable_items_as("max_update_time_of_consumable_items", crate::Q::consumable_items().unlimited())
    }

    pub fn max_update_time_of_consumable_items_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_consumable_items_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }

    pub fn count_address_records(self) -> Self {
        self.count_address_records_as("count_address_records")
    }

    pub fn count_address_records_as(self, alias: impl Into<String>) -> Self {
        self.count_address_records_with(alias, crate::Q::address_records().unlimited())
    }

    pub fn count_address_records_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "address_record_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_address_records(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_address_records_as("refinements", request)
    }

    pub fn stats_from_address_records_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "address_record_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_address_records_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_address_records(request)
    }


    pub fn sum_postal_code_of_address_records(self) -> Self {
        self.sum_postal_code_of_address_records_as("sum_postal_code_of_address_records", crate::Q::address_records().unlimited())
    }

    pub fn sum_postal_code_of_address_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_address_records_as(alias, request.into().into_query().sum("postal_code", "sum_postal_code"))
    }
    pub fn min_postal_code_of_address_records(self) -> Self {
        self.min_postal_code_of_address_records_as("min_postal_code_of_address_records", crate::Q::address_records().unlimited())
    }

    pub fn min_postal_code_of_address_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_address_records_as(alias, request.into().into_query().min("postal_code", "min_postal_code"))
    }
    pub fn max_postal_code_of_address_records(self) -> Self {
        self.max_postal_code_of_address_records_as("max_postal_code_of_address_records", crate::Q::address_records().unlimited())
    }

    pub fn max_postal_code_of_address_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_address_records_as(alias, request.into().into_query().max("postal_code", "max_postal_code"))
    }
    pub fn avg_postal_code_of_address_records(self) -> Self {
        self.avg_postal_code_of_address_records_as("avg_postal_code_of_address_records", crate::Q::address_records().unlimited())
    }

    pub fn avg_postal_code_of_address_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_address_records_as(alias, request.into().into_query().avg("postal_code", "avg_postal_code"))
    }
    pub fn standard_deviation_postal_code_of_address_records(self) -> Self {
        self.standard_deviation_postal_code_of_address_records_as("standard_deviation_postal_code_of_address_records", crate::Q::address_records().unlimited())
    }

    pub fn standard_deviation_postal_code_of_address_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_address_records_as(alias, request.into().into_query().stddev("postal_code", "stdDev_postal_code"))
    }
    pub fn square_root_of_population_standard_deviation_postal_code_of_address_records(self) -> Self {
        self.square_root_of_population_standard_deviation_postal_code_of_address_records_as("square_root_of_population_standard_deviation_postal_code_of_address_records", crate::Q::address_records().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_postal_code_of_address_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_address_records_as(alias, request.into().into_query().stddev_pop("postal_code", "stdDevPop_postal_code"))
    }
    pub fn sample_variance_postal_code_of_address_records(self) -> Self {
        self.sample_variance_postal_code_of_address_records_as("sample_variance_postal_code_of_address_records", crate::Q::address_records().unlimited())
    }

    pub fn sample_variance_postal_code_of_address_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_address_records_as(alias, request.into().into_query().var_samp("postal_code", "varSamp_postal_code"))
    }
    pub fn sample_population_variance_postal_code_of_address_records(self) -> Self {
        self.sample_population_variance_postal_code_of_address_records_as("sample_population_variance_postal_code_of_address_records", crate::Q::address_records().unlimited())
    }

    pub fn sample_population_variance_postal_code_of_address_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_address_records_as(alias, request.into().into_query().var_pop("postal_code", "varPop_postal_code"))
    }
    pub fn min_create_time_of_address_records(self) -> Self {
        self.min_create_time_of_address_records_as("min_create_time_of_address_records", crate::Q::address_records().unlimited())
    }

    pub fn min_create_time_of_address_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_address_records_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_address_records(self) -> Self {
        self.max_create_time_of_address_records_as("max_create_time_of_address_records", crate::Q::address_records().unlimited())
    }

    pub fn max_create_time_of_address_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_address_records_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_address_records(self) -> Self {
        self.min_update_time_of_address_records_as("min_update_time_of_address_records", crate::Q::address_records().unlimited())
    }

    pub fn min_update_time_of_address_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_address_records_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_address_records(self) -> Self {
        self.max_update_time_of_address_records_as("max_update_time_of_address_records", crate::Q::address_records().unlimited())
    }

    pub fn max_update_time_of_address_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_address_records_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }

    pub fn count_service_catalogs(self) -> Self {
        self.count_service_catalogs_as("count_service_catalogs")
    }

    pub fn count_service_catalogs_as(self, alias: impl Into<String>) -> Self {
        self.count_service_catalogs_with(alias, crate::Q::service_catalogs().unlimited())
    }

    pub fn count_service_catalogs_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "service_catalog_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_service_catalogs(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_catalogs_as("refinements", request)
    }

    pub fn stats_from_service_catalogs_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "service_catalog_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_service_catalogs_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_catalogs(request)
    }


    pub fn sum_base_price_of_service_catalogs(self) -> Self {
        self.sum_base_price_of_service_catalogs_as("sum_base_price_of_service_catalogs", crate::Q::service_catalogs().unlimited())
    }

    pub fn sum_base_price_of_service_catalogs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_catalogs_as(alias, request.into().into_query().sum("base_price", "sum_base_price"))
    }
    pub fn min_base_price_of_service_catalogs(self) -> Self {
        self.min_base_price_of_service_catalogs_as("min_base_price_of_service_catalogs", crate::Q::service_catalogs().unlimited())
    }

    pub fn min_base_price_of_service_catalogs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_catalogs_as(alias, request.into().into_query().min("base_price", "min_base_price"))
    }
    pub fn max_base_price_of_service_catalogs(self) -> Self {
        self.max_base_price_of_service_catalogs_as("max_base_price_of_service_catalogs", crate::Q::service_catalogs().unlimited())
    }

    pub fn max_base_price_of_service_catalogs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_catalogs_as(alias, request.into().into_query().max("base_price", "max_base_price"))
    }
    pub fn avg_base_price_of_service_catalogs(self) -> Self {
        self.avg_base_price_of_service_catalogs_as("avg_base_price_of_service_catalogs", crate::Q::service_catalogs().unlimited())
    }

    pub fn avg_base_price_of_service_catalogs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_catalogs_as(alias, request.into().into_query().avg("base_price", "avg_base_price"))
    }
    pub fn standard_deviation_base_price_of_service_catalogs(self) -> Self {
        self.standard_deviation_base_price_of_service_catalogs_as("standard_deviation_base_price_of_service_catalogs", crate::Q::service_catalogs().unlimited())
    }

    pub fn standard_deviation_base_price_of_service_catalogs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_catalogs_as(alias, request.into().into_query().stddev("base_price", "stdDev_base_price"))
    }
    pub fn square_root_of_population_standard_deviation_base_price_of_service_catalogs(self) -> Self {
        self.square_root_of_population_standard_deviation_base_price_of_service_catalogs_as("square_root_of_population_standard_deviation_base_price_of_service_catalogs", crate::Q::service_catalogs().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_base_price_of_service_catalogs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_catalogs_as(alias, request.into().into_query().stddev_pop("base_price", "stdDevPop_base_price"))
    }
    pub fn sample_variance_base_price_of_service_catalogs(self) -> Self {
        self.sample_variance_base_price_of_service_catalogs_as("sample_variance_base_price_of_service_catalogs", crate::Q::service_catalogs().unlimited())
    }

    pub fn sample_variance_base_price_of_service_catalogs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_catalogs_as(alias, request.into().into_query().var_samp("base_price", "varSamp_base_price"))
    }
    pub fn sample_population_variance_base_price_of_service_catalogs(self) -> Self {
        self.sample_population_variance_base_price_of_service_catalogs_as("sample_population_variance_base_price_of_service_catalogs", crate::Q::service_catalogs().unlimited())
    }

    pub fn sample_population_variance_base_price_of_service_catalogs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_catalogs_as(alias, request.into().into_query().var_pop("base_price", "varPop_base_price"))
    }
    pub fn min_create_time_of_service_catalogs(self) -> Self {
        self.min_create_time_of_service_catalogs_as("min_create_time_of_service_catalogs", crate::Q::service_catalogs().unlimited())
    }

    pub fn min_create_time_of_service_catalogs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_catalogs_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_service_catalogs(self) -> Self {
        self.max_create_time_of_service_catalogs_as("max_create_time_of_service_catalogs", crate::Q::service_catalogs().unlimited())
    }

    pub fn max_create_time_of_service_catalogs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_catalogs_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_service_catalogs(self) -> Self {
        self.min_update_time_of_service_catalogs_as("min_update_time_of_service_catalogs", crate::Q::service_catalogs().unlimited())
    }

    pub fn min_update_time_of_service_catalogs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_catalogs_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_service_catalogs(self) -> Self {
        self.max_update_time_of_service_catalogs_as("max_update_time_of_service_catalogs", crate::Q::service_catalogs().unlimited())
    }

    pub fn max_update_time_of_service_catalogs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_catalogs_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }

    pub fn count_marketing_campaigns(self) -> Self {
        self.count_marketing_campaigns_as("count_marketing_campaigns")
    }

    pub fn count_marketing_campaigns_as(self, alias: impl Into<String>) -> Self {
        self.count_marketing_campaigns_with(alias, crate::Q::marketing_campaigns().unlimited())
    }

    pub fn count_marketing_campaigns_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "marketing_campaign_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_marketing_campaigns(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_marketing_campaigns_as("refinements", request)
    }

    pub fn stats_from_marketing_campaigns_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "marketing_campaign_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_marketing_campaigns_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_marketing_campaigns(request)
    }


    pub fn min_start_date_of_marketing_campaigns(self) -> Self {
        self.min_start_date_of_marketing_campaigns_as("min_start_date_of_marketing_campaigns", crate::Q::marketing_campaigns().unlimited())
    }

    pub fn min_start_date_of_marketing_campaigns_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_marketing_campaigns_as(alias, request.into().into_query().min("start_date", "min_start_date"))
    }
    pub fn max_start_date_of_marketing_campaigns(self) -> Self {
        self.max_start_date_of_marketing_campaigns_as("max_start_date_of_marketing_campaigns", crate::Q::marketing_campaigns().unlimited())
    }

    pub fn max_start_date_of_marketing_campaigns_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_marketing_campaigns_as(alias, request.into().into_query().max("start_date", "max_start_date"))
    }
    pub fn min_create_time_of_marketing_campaigns(self) -> Self {
        self.min_create_time_of_marketing_campaigns_as("min_create_time_of_marketing_campaigns", crate::Q::marketing_campaigns().unlimited())
    }

    pub fn min_create_time_of_marketing_campaigns_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_marketing_campaigns_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_marketing_campaigns(self) -> Self {
        self.max_create_time_of_marketing_campaigns_as("max_create_time_of_marketing_campaigns", crate::Q::marketing_campaigns().unlimited())
    }

    pub fn max_create_time_of_marketing_campaigns_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_marketing_campaigns_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_marketing_campaigns(self) -> Self {
        self.min_update_time_of_marketing_campaigns_as("min_update_time_of_marketing_campaigns", crate::Q::marketing_campaigns().unlimited())
    }

    pub fn min_update_time_of_marketing_campaigns_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_marketing_campaigns_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_marketing_campaigns(self) -> Self {
        self.max_update_time_of_marketing_campaigns_as("max_update_time_of_marketing_campaigns", crate::Q::marketing_campaigns().unlimited())
    }

    pub fn max_update_time_of_marketing_campaigns_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_marketing_campaigns_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }
}

impl<R> Default for CompanyRequest<R> {
    fn default() -> Self {
        Self::new()
    }
}

impl<R> From< CompanyRequest<R> > for SelectQuery {
    fn from(request: CompanyRequest<R>) -> Self {
        QuerySelection::from(request).into_query()
    }
}

impl<R> From< CompanyRequest<R> > for QuerySelection {
    fn from(request: CompanyRequest<R>) -> Self {
        Self {
            query: request.query,
            relation_selections: request.relation_selections,
            relation_filters: request.relation_filters,
            child_enhancements: request.child_enhancements,
            query_options: request.query_options,
        }
    }
}


impl<'a, C> crate::request_support::AuditedSave<'a, C> for teaql_core::Audited<crate::Company> 
where C: crate::request_support::TeaqlRepositoryProvider + ?Sized + 'a
{
    type Error = crate::TeaqlDataServiceError<C::CompanyRepository<'a>>;
    fn save(self, ctx: &'a C) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<teaql_runtime::GraphNode, Self::Error>> + '_>> {
        Box::pin(async move {
            teaql_runtime::save_audited_ledger_entity(self, ctx.user_context())
                .await
                .map_err(DataServiceError::Runtime)
        })
    }
}

impl<R: teaql_core::Entity> crate::PurposedQuery<CompanyRequest<R>> {
    pub fn new_entity<C>(&self, ctx: &C) -> crate::Company
    where
        C: crate::TeaqlRuntime + ?Sized,
    {
        crate::Company::runtime_new(ctx.user_context().entity_root())
    }

    fn into_inner_with_trace(mut self) -> CompanyRequest<R> {
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
    ) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::CompanyRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_page(ctx, offset, limit).await
    }

    pub async fn execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, crate::request_support::TeaqlDataServiceError<C::CompanyRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_exists(ctx).await
    }

    pub async fn execute_for_list<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::CompanyRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_list(ctx).await
    }

    /// Execute query in streaming mode (chunked).
    /// Returns a Vec of StreamChunk, each containing up to chunk_size rows.
    /// Set chunk size via .stream(chunk_size) or .stream_default() on the query.
    pub async fn execute_for_stream<'a, C>(self, ctx: &'a C) -> Result<Vec<teaql_data_service::StreamChunk>, crate::request_support::TeaqlDataServiceError<C::CompanyRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_stream(ctx).await
    }

    pub async fn execute_for_first<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::CompanyRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_first(ctx).await
    }

    pub async fn execute_for_one<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::CompanyRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_one(ctx).await
    }


    pub async fn execute_for_records<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::CompanyRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_records(ctx).await
    }

    pub async fn execute_for_record<'a, C>(self, ctx: &'a C) -> Result<Option<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::CompanyRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_record(ctx).await
    }

    pub async fn execute_for_count<'a, C>(self, ctx: &'a C) -> Result<u64, crate::request_support::TeaqlDataServiceError<C::CompanyRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_count(ctx).await
    }
}
