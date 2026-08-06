use std::marker::PhantomData;

use serde_json::Value as JsonValue;
use teaql_core::{Aggregate, AggregateFunction, EntityDescriptor, Expr, Record, SelectQuery, SmartList};
use teaql_runtime::{DataServiceError, RuntimeError};

use crate::request_support::*;

impl EntityReference for crate::Lead {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(&self)
    }
}

impl EntityReference for &crate::Lead {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(self)
    }
}

// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/lead
#[derive(Debug)]
pub struct LeadRequest<R = crate::Lead> {
    query: SelectQuery,
    relation_selections: Vec<RelationSelection>,
    relation_filters: Vec<RelationFilter>,
    child_enhancements: Vec<QuerySelection>,
    query_options: QueryOptions,
    marker: PhantomData<R>,
}

impl<R> Clone for LeadRequest<R> {
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

impl<R> LeadRequest<R> {
    pub(crate) fn new() -> Self {
        Self {
            query: SelectQuery::new("Lead")
                .project("id")
                .project("version"),
            relation_selections: Vec::new(),
            relation_filters: Vec::new(),
            child_enhancements: Vec::new(),
            query_options: QueryOptions::default(),
            marker: PhantomData,
        }
    }

    pub fn return_type<T>(self) -> LeadRequest<T> {
        LeadRequest {
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::LeadRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
        R: teaql_core::Entity,
    {
        let repository = ctx
            .lead_repository()
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
    ) -> Result<Vec<teaql_data_service::StreamChunk>, TeaqlDataServiceError<C::LeadRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .lead_repository()
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::LeadRepository<'a>>>
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::LeadRepository<'a>>>
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::LeadRepository<'a>>>
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
    ) -> Result<u64, TeaqlDataServiceError<C::LeadRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .lead_repository()
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
            .ok_or_else(|| DataServiceError::Runtime(RuntimeError::Graph(format!("count result for Lead is missing or not numeric"))))
    }

    pub(crate) async fn _execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, TeaqlDataServiceError<C::LeadRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .lead_repository()
            .map_err(|err| DataServiceError::Runtime(RuntimeError::Graph(err.to_string())))?;
        let mut query = self.query.limit(1);
        query.relations.clear();
        let rows = repository.fetch_all(&query).await?;
        Ok(!rows.is_empty())
    }

    pub(crate) async fn _execute_for_records<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<SmartList<Record>, TeaqlDataServiceError<C::LeadRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .lead_repository()
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
    ) -> Result<Option<Record>, TeaqlDataServiceError<C::LeadRepository<'a>>>
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
            "first_name" => Some("first_name"),
            "last_name" => Some("last_name"),
            "email" => Some("email"),
            "phone" => Some("phone"),
            "source" => Some("source"),
            "status" => Some("status"),
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
        self.query = self.query.project("first_name");
        self.query = self.query.project("last_name");
        self.query = self.query.project("email");
        self.query = self.query.project("phone");
        self.query = self.query.project("source");
        self.query = self.query.project("status");
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


    pub fn select_first_name(mut self) -> Self {
        self.query = self.query.project("first_name");
        self
    }

    pub fn project_first_name(self) -> Self {
        self.select_first_name()
    }

    pub fn select_first_name_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_first_name_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_first_name_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("first_name", raw_sql_segment));
        self
    }

    pub fn group_by_first_name(self) -> Self {
        self.group_by("first_name")
    }

    pub fn group_by_first_name_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("first_name");
        request.query = request
            .query
            .project_expr(alias, Expr::column("first_name"));
        request
    }

    pub fn group_by_first_name_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("first_name")
            .aggregate_with_function("first_name", alias, function)
    }

    pub fn count_first_name(self) -> Self {
        self.count_first_name_as("first_name_count")
    }

    pub fn count_first_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("first_name", alias)
    }

    pub fn sum_first_name(self) -> Self {
        self.sum_first_name_as("sum_first_name")
    }

    pub fn sum_first_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("first_name", alias)
    }

    pub fn avg_first_name(self) -> Self {
        self.avg_first_name_as("avg_first_name")
    }

    pub fn avg_first_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("first_name", alias)
    }

    pub fn min_first_name(self) -> Self {
        self.min_first_name_as("min_first_name")
    }

    pub fn min_first_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("first_name", alias)
    }

    pub fn max_first_name(self) -> Self {
        self.max_first_name_as("max_first_name")
    }

    pub fn max_first_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("first_name", alias)
    }

    pub fn unselect_first_name(mut self) -> Self {
        self.query.projection.retain(|field| field != "first_name");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "first_name");
        self
    }


    pub fn with_first_name(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "first_name",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_first_name_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "first_name",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_first_name_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("first_name", value));
        self
    }



    pub fn with_first_name_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("first_name", value));
        self
    }

    pub fn with_first_name_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("first_name", value));
        self
    }

    pub fn with_first_name_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("first_name", value));
        self
    }

    pub fn with_first_name_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("first_name", value));
        self
    }

    pub fn with_first_name_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("first_name", value));
        self
    }

    pub fn with_first_name_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("first_name", lower, upper));
        self
    }

    pub fn with_first_name_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "first_name",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_first_name_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "first_name",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_first_name_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "first_name",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_first_name_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("first_name", value));
        self
    }

    pub fn with_first_name_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("first_name", value));
        self
    }

    pub fn with_first_name_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("first_name", value));
        self
    }

    pub fn with_first_name_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("first_name", value));
        self
    }

    pub fn with_first_name_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("first_name", value));
        self
    }

    pub fn with_first_name_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("first_name", value));
        self
    }

    pub fn with_first_name_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("first_name", value));
        self
    }
    pub fn with_first_name_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("first_name", value));
        self
    }

    pub fn with_first_name_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("first_name", value));
        self
    }

    pub fn with_first_name_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("first_name"));
        self
    }



    pub fn with_first_name_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("first_name"));
        self
    }


    pub fn order_by_first_name_asc(mut self) -> Self {
        self.query = self.query.order_asc("first_name");
        self
    }

    pub fn order_by_first_name_desc(mut self) -> Self {
        self.query = self.query.order_desc("first_name");
        self
    }

    pub fn order_by_first_name_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("first_name");
        self
    }

    pub fn order_by_first_name_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("first_name");
        self
    }


    pub fn select_last_name(mut self) -> Self {
        self.query = self.query.project("last_name");
        self
    }

    pub fn project_last_name(self) -> Self {
        self.select_last_name()
    }

    pub fn select_last_name_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_last_name_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_last_name_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("last_name", raw_sql_segment));
        self
    }

    pub fn group_by_last_name(self) -> Self {
        self.group_by("last_name")
    }

    pub fn group_by_last_name_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("last_name");
        request.query = request
            .query
            .project_expr(alias, Expr::column("last_name"));
        request
    }

    pub fn group_by_last_name_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("last_name")
            .aggregate_with_function("last_name", alias, function)
    }

    pub fn count_last_name(self) -> Self {
        self.count_last_name_as("last_name_count")
    }

    pub fn count_last_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("last_name", alias)
    }

    pub fn sum_last_name(self) -> Self {
        self.sum_last_name_as("sum_last_name")
    }

    pub fn sum_last_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("last_name", alias)
    }

    pub fn avg_last_name(self) -> Self {
        self.avg_last_name_as("avg_last_name")
    }

    pub fn avg_last_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("last_name", alias)
    }

    pub fn min_last_name(self) -> Self {
        self.min_last_name_as("min_last_name")
    }

    pub fn min_last_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("last_name", alias)
    }

    pub fn max_last_name(self) -> Self {
        self.max_last_name_as("max_last_name")
    }

    pub fn max_last_name_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("last_name", alias)
    }

    pub fn unselect_last_name(mut self) -> Self {
        self.query.projection.retain(|field| field != "last_name");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "last_name");
        self
    }


    pub fn with_last_name(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "last_name",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_last_name_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "last_name",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_last_name_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("last_name", value));
        self
    }



    pub fn with_last_name_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("last_name", value));
        self
    }

    pub fn with_last_name_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("last_name", value));
        self
    }

    pub fn with_last_name_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("last_name", value));
        self
    }

    pub fn with_last_name_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("last_name", value));
        self
    }

    pub fn with_last_name_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("last_name", value));
        self
    }

    pub fn with_last_name_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("last_name", lower, upper));
        self
    }

    pub fn with_last_name_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "last_name",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_last_name_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "last_name",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_last_name_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "last_name",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_last_name_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("last_name", value));
        self
    }

    pub fn with_last_name_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("last_name", value));
        self
    }

    pub fn with_last_name_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("last_name", value));
        self
    }

    pub fn with_last_name_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("last_name", value));
        self
    }

    pub fn with_last_name_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("last_name", value));
        self
    }

    pub fn with_last_name_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("last_name", value));
        self
    }

    pub fn with_last_name_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("last_name", value));
        self
    }
    pub fn with_last_name_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("last_name", value));
        self
    }

    pub fn with_last_name_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("last_name", value));
        self
    }

    pub fn with_last_name_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("last_name"));
        self
    }



    pub fn with_last_name_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("last_name"));
        self
    }


    pub fn order_by_last_name_asc(mut self) -> Self {
        self.query = self.query.order_asc("last_name");
        self
    }

    pub fn order_by_last_name_desc(mut self) -> Self {
        self.query = self.query.order_desc("last_name");
        self
    }

    pub fn order_by_last_name_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("last_name");
        self
    }

    pub fn order_by_last_name_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("last_name");
        self
    }


    pub fn select_email(mut self) -> Self {
        self.query = self.query.project("email");
        self
    }

    pub fn project_email(self) -> Self {
        self.select_email()
    }

    pub fn select_email_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_email_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_email_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("email", raw_sql_segment));
        self
    }

    pub fn group_by_email(self) -> Self {
        self.group_by("email")
    }

    pub fn group_by_email_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("email");
        request.query = request
            .query
            .project_expr(alias, Expr::column("email"));
        request
    }

    pub fn group_by_email_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("email")
            .aggregate_with_function("email", alias, function)
    }

    pub fn count_email(self) -> Self {
        self.count_email_as("email_count")
    }

    pub fn count_email_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("email", alias)
    }

    pub fn sum_email(self) -> Self {
        self.sum_email_as("sum_email")
    }

    pub fn sum_email_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("email", alias)
    }

    pub fn avg_email(self) -> Self {
        self.avg_email_as("avg_email")
    }

    pub fn avg_email_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("email", alias)
    }

    pub fn min_email(self) -> Self {
        self.min_email_as("min_email")
    }

    pub fn min_email_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("email", alias)
    }

    pub fn max_email(self) -> Self {
        self.max_email_as("max_email")
    }

    pub fn max_email_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("email", alias)
    }

    pub fn unselect_email(mut self) -> Self {
        self.query.projection.retain(|field| field != "email");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "email");
        self
    }


    pub fn with_email(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "email",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_email_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "email",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_email_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("email", value));
        self
    }



    pub fn with_email_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("email", value));
        self
    }

    pub fn with_email_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("email", value));
        self
    }

    pub fn with_email_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("email", value));
        self
    }

    pub fn with_email_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("email", value));
        self
    }

    pub fn with_email_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("email", value));
        self
    }

    pub fn with_email_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("email", lower, upper));
        self
    }

    pub fn with_email_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "email",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_email_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "email",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_email_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "email",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_email_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("email", value));
        self
    }

    pub fn with_email_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("email", value));
        self
    }

    pub fn with_email_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("email", value));
        self
    }

    pub fn with_email_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("email", value));
        self
    }

    pub fn with_email_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("email", value));
        self
    }

    pub fn with_email_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("email", value));
        self
    }

    pub fn with_email_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("email", value));
        self
    }
    pub fn with_email_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("email", value));
        self
    }

    pub fn with_email_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("email", value));
        self
    }

    pub fn with_email_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("email"));
        self
    }



    pub fn with_email_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("email"));
        self
    }


    pub fn order_by_email_asc(mut self) -> Self {
        self.query = self.query.order_asc("email");
        self
    }

    pub fn order_by_email_desc(mut self) -> Self {
        self.query = self.query.order_desc("email");
        self
    }

    pub fn order_by_email_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("email");
        self
    }

    pub fn order_by_email_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("email");
        self
    }


    pub fn select_phone(mut self) -> Self {
        self.query = self.query.project("phone");
        self
    }

    pub fn project_phone(self) -> Self {
        self.select_phone()
    }

    pub fn select_phone_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_phone_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_phone_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("phone", raw_sql_segment));
        self
    }

    pub fn group_by_phone(self) -> Self {
        self.group_by("phone")
    }

    pub fn group_by_phone_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("phone");
        request.query = request
            .query
            .project_expr(alias, Expr::column("phone"));
        request
    }

    pub fn group_by_phone_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("phone")
            .aggregate_with_function("phone", alias, function)
    }

    pub fn count_phone(self) -> Self {
        self.count_phone_as("phone_count")
    }

    pub fn count_phone_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("phone", alias)
    }

    pub fn sum_phone(self) -> Self {
        self.sum_phone_as("sum_phone")
    }

    pub fn sum_phone_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("phone", alias)
    }

    pub fn avg_phone(self) -> Self {
        self.avg_phone_as("avg_phone")
    }

    pub fn avg_phone_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("phone", alias)
    }

    pub fn min_phone(self) -> Self {
        self.min_phone_as("min_phone")
    }

    pub fn min_phone_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("phone", alias)
    }

    pub fn max_phone(self) -> Self {
        self.max_phone_as("max_phone")
    }

    pub fn max_phone_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("phone", alias)
    }

    pub fn unselect_phone(mut self) -> Self {
        self.query.projection.retain(|field| field != "phone");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "phone");
        self
    }


    pub fn with_phone(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "phone",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_phone_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "phone",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_phone_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("phone", value));
        self
    }



    pub fn with_phone_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("phone", value));
        self
    }

    pub fn with_phone_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("phone", value));
        self
    }

    pub fn with_phone_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("phone", value));
        self
    }

    pub fn with_phone_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("phone", value));
        self
    }

    pub fn with_phone_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("phone", value));
        self
    }

    pub fn with_phone_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("phone", lower, upper));
        self
    }

    pub fn with_phone_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "phone",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_phone_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "phone",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_phone_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "phone",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_phone_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("phone", value));
        self
    }

    pub fn with_phone_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("phone", value));
        self
    }

    pub fn with_phone_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("phone", value));
        self
    }

    pub fn with_phone_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("phone", value));
        self
    }

    pub fn with_phone_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("phone", value));
        self
    }

    pub fn with_phone_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("phone", value));
        self
    }

    pub fn with_phone_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("phone", value));
        self
    }
    pub fn with_phone_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("phone", value));
        self
    }

    pub fn with_phone_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("phone", value));
        self
    }

    pub fn with_phone_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("phone"));
        self
    }



    pub fn with_phone_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("phone"));
        self
    }


    pub fn order_by_phone_asc(mut self) -> Self {
        self.query = self.query.order_asc("phone");
        self
    }

    pub fn order_by_phone_desc(mut self) -> Self {
        self.query = self.query.order_desc("phone");
        self
    }

    pub fn order_by_phone_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("phone");
        self
    }

    pub fn order_by_phone_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("phone");
        self
    }


    pub fn select_source(mut self) -> Self {
        self.query = self.query.project("source");
        self
    }

    pub fn project_source(self) -> Self {
        self.select_source()
    }

    pub fn select_source_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_source_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_source_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("source", raw_sql_segment));
        self
    }

    pub fn group_by_source(self) -> Self {
        self.group_by("source")
    }

    pub fn group_by_source_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("source");
        request.query = request
            .query
            .project_expr(alias, Expr::column("source"));
        request
    }

    pub fn group_by_source_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("source")
            .aggregate_with_function("source", alias, function)
    }

    pub fn count_source(self) -> Self {
        self.count_source_as("source_count")
    }

    pub fn count_source_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("source", alias)
    }

    pub fn sum_source(self) -> Self {
        self.sum_source_as("sum_source")
    }

    pub fn sum_source_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("source", alias)
    }

    pub fn avg_source(self) -> Self {
        self.avg_source_as("avg_source")
    }

    pub fn avg_source_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("source", alias)
    }

    pub fn min_source(self) -> Self {
        self.min_source_as("min_source")
    }

    pub fn min_source_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("source", alias)
    }

    pub fn max_source(self) -> Self {
        self.max_source_as("max_source")
    }

    pub fn max_source_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("source", alias)
    }

    pub fn unselect_source(mut self) -> Self {
        self.query.projection.retain(|field| field != "source");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "source");
        self
    }


    pub fn with_source(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "source",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_source_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "source",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_source_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("source", value));
        self
    }



    pub fn with_source_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("source", value));
        self
    }

    pub fn with_source_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("source", value));
        self
    }

    pub fn with_source_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("source", value));
        self
    }

    pub fn with_source_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("source", value));
        self
    }

    pub fn with_source_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("source", value));
        self
    }

    pub fn with_source_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("source", lower, upper));
        self
    }

    pub fn with_source_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "source",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_source_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "source",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_source_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "source",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_source_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("source", value));
        self
    }

    pub fn with_source_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("source", value));
        self
    }

    pub fn with_source_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("source", value));
        self
    }

    pub fn with_source_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("source", value));
        self
    }

    pub fn with_source_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("source", value));
        self
    }

    pub fn with_source_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("source", value));
        self
    }

    pub fn with_source_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("source", value));
        self
    }
    pub fn with_source_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("source", value));
        self
    }

    pub fn with_source_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("source", value));
        self
    }

    pub fn with_source_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("source"));
        self
    }



    pub fn with_source_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("source"));
        self
    }


    pub fn order_by_source_asc(mut self) -> Self {
        self.query = self.query.order_asc("source");
        self
    }

    pub fn order_by_source_desc(mut self) -> Self {
        self.query = self.query.order_desc("source");
        self
    }

    pub fn order_by_source_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("source");
        self
    }

    pub fn order_by_source_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("source");
        self
    }


    pub fn select_status(mut self) -> Self {
        self.query = self.query.project("status");
        self
    }

    pub fn project_status(self) -> Self {
        self.select_status()
    }

    pub fn select_status_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_status_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_status_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("status", raw_sql_segment));
        self
    }

    pub fn group_by_status(self) -> Self {
        self.group_by("status")
    }

    pub fn group_by_status_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("status");
        request.query = request
            .query
            .project_expr(alias, Expr::column("status"));
        request
    }

    pub fn group_by_status_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("status")
            .aggregate_with_function("status", alias, function)
    }

    pub fn count_status(self) -> Self {
        self.count_status_as("status_count")
    }

    pub fn count_status_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("status", alias)
    }

    pub fn sum_status(self) -> Self {
        self.sum_status_as("sum_status")
    }

    pub fn sum_status_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("status", alias)
    }

    pub fn avg_status(self) -> Self {
        self.avg_status_as("avg_status")
    }

    pub fn avg_status_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("status", alias)
    }

    pub fn min_status(self) -> Self {
        self.min_status_as("min_status")
    }

    pub fn min_status_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("status", alias)
    }

    pub fn max_status(self) -> Self {
        self.max_status_as("max_status")
    }

    pub fn max_status_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("status", alias)
    }

    pub fn unselect_status(mut self) -> Self {
        self.query.projection.retain(|field| field != "status");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "status");
        self
    }


    pub fn with_status(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "status",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_status_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "status",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_status_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("status", value));
        self
    }



    pub fn with_status_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("status", value));
        self
    }

    pub fn with_status_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("status", value));
        self
    }

    pub fn with_status_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("status", value));
        self
    }

    pub fn with_status_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("status", value));
        self
    }

    pub fn with_status_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("status", value));
        self
    }

    pub fn with_status_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("status", lower, upper));
        self
    }

    pub fn with_status_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "status",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_status_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "status",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_status_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "status",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_status_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("status", value));
        self
    }

    pub fn with_status_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("status", value));
        self
    }

    pub fn with_status_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("status", value));
        self
    }

    pub fn with_status_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("status", value));
        self
    }

    pub fn with_status_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("status", value));
        self
    }

    pub fn with_status_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("status", value));
        self
    }

    pub fn with_status_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("status", value));
        self
    }
    pub fn with_status_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("status", value));
        self
    }

    pub fn with_status_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("status", value));
        self
    }

    pub fn with_status_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("status"));
        self
    }



    pub fn with_status_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("status"));
        self
    }


    pub fn order_by_status_asc(mut self) -> Self {
        self.query = self.query.order_asc("status");
        self
    }

    pub fn order_by_status_desc(mut self) -> Self {
        self.query = self.query.order_desc("status");
        self
    }

    pub fn order_by_status_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("status");
        self
    }

    pub fn order_by_status_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("status");
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
    pub fn first_name_is_john(self) -> Self {
        self.with_first_name_is("John")
    }

    pub fn with_first_name_is_john(self) -> Self {
        self.with_first_name_is("John")
    }



    pub fn with_first_name_is_not_john(self) -> Self {
        self.with_first_name_is_not("John")
    }



    pub fn last_name_is_doe(self) -> Self {
        self.with_last_name_is("Doe")
    }

    pub fn with_last_name_is_doe(self) -> Self {
        self.with_last_name_is("Doe")
    }



    pub fn with_last_name_is_not_doe(self) -> Self {
        self.with_last_name_is_not("Doe")
    }



    pub fn email_is_john_doe_example_com(self) -> Self {
        self.with_email_is("john.doe@example.com")
    }

    pub fn with_email_is_john_doe_example_com(self) -> Self {
        self.with_email_is("john.doe@example.com")
    }



    pub fn with_email_is_not_john_doe_example_com(self) -> Self {
        self.with_email_is_not("john.doe@example.com")
    }



    pub fn phone_is_value_1234567890(self) -> Self {
        self.with_phone_is("+1234567890")
    }

    pub fn with_phone_is_value_1234567890(self) -> Self {
        self.with_phone_is("+1234567890")
    }



    pub fn with_phone_is_not_value_1234567890(self) -> Self {
        self.with_phone_is_not("+1234567890")
    }



    pub fn source_is_online_ad(self) -> Self {
        self.with_source_is("Online Ad")
    }

    pub fn with_source_is_online_ad(self) -> Self {
        self.with_source_is("Online Ad")
    }



    pub fn with_source_is_not_online_ad(self) -> Self {
        self.with_source_is_not("Online Ad")
    }



    pub fn status_is_new(self) -> Self {
        self.with_status_is("New")
    }

    pub fn with_status_is_new(self) -> Self {
        self.with_status_is("New")
    }



    pub fn with_status_is_not_new(self) -> Self {
        self.with_status_is_not("New")
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

impl<R> Default for LeadRequest<R> {
    fn default() -> Self {
        Self::new()
    }
}

impl<R> From< LeadRequest<R> > for SelectQuery {
    fn from(request: LeadRequest<R>) -> Self {
        QuerySelection::from(request).into_query()
    }
}

impl<R> From< LeadRequest<R> > for QuerySelection {
    fn from(request: LeadRequest<R>) -> Self {
        Self {
            query: request.query,
            relation_selections: request.relation_selections,
            relation_filters: request.relation_filters,
            child_enhancements: request.child_enhancements,
            query_options: request.query_options,
        }
    }
}


impl<'a, C> crate::request_support::AuditedSave<'a, C> for teaql_core::Audited<crate::Lead> 
where C: crate::request_support::TeaqlRepositoryProvider + ?Sized + 'a
{
    type Error = crate::TeaqlDataServiceError<C::LeadRepository<'a>>;
    fn save(self, ctx: &'a C) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<teaql_runtime::GraphNode, Self::Error>> + '_>> {
        Box::pin(async move { self.into_entity().save(ctx).await })
    }
}

impl<R: teaql_core::Entity> crate::PurposedQuery<LeadRequest<R>> {
    pub fn new_entity<C>(&self, ctx: &C) -> crate::Lead
    where
        C: crate::TeaqlRuntime + ?Sized,
    {
        crate::Lead::runtime_new(ctx.user_context().entity_root())
    }

    fn into_inner_with_trace(mut self) -> LeadRequest<R> {
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
    ) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::LeadRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_page(ctx, offset, limit).await
    }

    pub async fn execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, crate::request_support::TeaqlDataServiceError<C::LeadRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_exists(ctx).await
    }

    pub async fn execute_for_list<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::LeadRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_list(ctx).await
    }

    /// Execute query in streaming mode (chunked).
    /// Returns a Vec of StreamChunk, each containing up to chunk_size rows.
    /// Set chunk size via .stream(chunk_size) or .stream_default() on the query.
    pub async fn execute_for_stream<'a, C>(self, ctx: &'a C) -> Result<Vec<teaql_data_service::StreamChunk>, crate::request_support::TeaqlDataServiceError<C::LeadRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_stream(ctx).await
    }

    pub async fn execute_for_first<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::LeadRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_first(ctx).await
    }

    pub async fn execute_for_one<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::LeadRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_one(ctx).await
    }


    pub async fn execute_for_records<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::LeadRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_records(ctx).await
    }

    pub async fn execute_for_record<'a, C>(self, ctx: &'a C) -> Result<Option<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::LeadRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_record(ctx).await
    }

    pub async fn execute_for_count<'a, C>(self, ctx: &'a C) -> Result<u64, crate::request_support::TeaqlDataServiceError<C::LeadRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_count(ctx).await
    }
}
