use std::marker::PhantomData;

use serde_json::Value as JsonValue;
use teaql_core::{Aggregate, AggregateFunction, EntityDescriptor, Expr, Record, SelectQuery, SmartList};
use teaql_runtime::{DataServiceError, RuntimeError};

use crate::request_support::*;

impl EntityReference for crate::Notification {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(&self)
    }
}

impl EntityReference for &crate::Notification {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(self)
    }
}

// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/notification
#[derive(Debug)]
pub struct NotificationRequest<R = crate::Notification> {
    query: SelectQuery,
    relation_selections: Vec<RelationSelection>,
    relation_filters: Vec<RelationFilter>,
    child_enhancements: Vec<QuerySelection>,
    query_options: QueryOptions,
    marker: PhantomData<R>,
}

impl<R> Clone for NotificationRequest<R> {
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

impl<R> NotificationRequest<R> {
    pub(crate) fn new() -> Self {
        Self {
            query: SelectQuery::new("Notification")
                .project("id")
                .project("version"),
            relation_selections: Vec::new(),
            relation_filters: Vec::new(),
            child_enhancements: Vec::new(),
            query_options: QueryOptions::default(),
            marker: PhantomData,
        }
    }

    pub fn return_type<T>(self) -> NotificationRequest<T> {
        NotificationRequest {
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::NotificationRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
        R: teaql_core::Entity,
    {
        let repository = ctx
            .notification_repository()
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
    ) -> Result<Vec<teaql_data_service::StreamChunk>, TeaqlDataServiceError<C::NotificationRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .notification_repository()
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::NotificationRepository<'a>>>
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::NotificationRepository<'a>>>
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::NotificationRepository<'a>>>
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
    ) -> Result<u64, TeaqlDataServiceError<C::NotificationRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .notification_repository()
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
            .ok_or_else(|| DataServiceError::Runtime(RuntimeError::Graph(format!("count result for Notification is missing or not numeric"))))
    }

    pub(crate) async fn _execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, TeaqlDataServiceError<C::NotificationRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .notification_repository()
            .map_err(|err| DataServiceError::Runtime(RuntimeError::Graph(err.to_string())))?;
        let mut query = self.query.limit(1);
        query.relations.clear();
        let rows = repository.fetch_all(&query).await?;
        Ok(!rows.is_empty())
    }

    pub(crate) async fn _execute_for_records<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<SmartList<Record>, TeaqlDataServiceError<C::NotificationRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .notification_repository()
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
    ) -> Result<Option<Record>, TeaqlDataServiceError<C::NotificationRepository<'a>>>
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
            "subject" => Some("subject"),
            "body" => Some("body"),
            "notification_type" => Some("notification_type"),
            "status" => Some("status"),
            "scheduled_time" => Some("scheduled_time"),
            "sent_time" => Some("sent_time"),
            "create_time" => Some("create_time"),
            "update_time" => Some("update_time"),
            "version" => Some("version"),
            "recipient" | "recipient_id" => Some("recipient_id"),
            _ => None,
        }
    }

    fn apply_dynamic_json_chain_filter(self, head: &str, tail: &str, value: &JsonValue) -> Self {
        let _ = (tail, value);
        match head {
            "recipient" => {
                self.with_recipient_matching(
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
        self.query = self.query.project("subject");
        self.query = self.query.project("body");
        self.query = self.query.project("notification_type");
        self.query = self.query.project("status");
        self.query = self.query.project("scheduled_time");
        self.query = self.query.project("sent_time");
        self.query = self.query.project("create_time");
        self.query = self.query.project("update_time");
        self.query = self.query.project("version");
        self.query = self.query.project("recipient_id");
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
        request = request.select_recipient();
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


    pub fn select_subject(mut self) -> Self {
        self.query = self.query.project("subject");
        self
    }

    pub fn project_subject(self) -> Self {
        self.select_subject()
    }

    pub fn select_subject_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_subject_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_subject_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("subject", raw_sql_segment));
        self
    }

    pub fn group_by_subject(self) -> Self {
        self.group_by("subject")
    }

    pub fn group_by_subject_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("subject");
        request.query = request
            .query
            .project_expr(alias, Expr::column("subject"));
        request
    }

    pub fn group_by_subject_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("subject")
            .aggregate_with_function("subject", alias, function)
    }

    pub fn count_subject(self) -> Self {
        self.count_subject_as("subject_count")
    }

    pub fn count_subject_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("subject", alias)
    }

    pub fn sum_subject(self) -> Self {
        self.sum_subject_as("sum_subject")
    }

    pub fn sum_subject_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("subject", alias)
    }

    pub fn avg_subject(self) -> Self {
        self.avg_subject_as("avg_subject")
    }

    pub fn avg_subject_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("subject", alias)
    }

    pub fn min_subject(self) -> Self {
        self.min_subject_as("min_subject")
    }

    pub fn min_subject_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("subject", alias)
    }

    pub fn max_subject(self) -> Self {
        self.max_subject_as("max_subject")
    }

    pub fn max_subject_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("subject", alias)
    }

    pub fn unselect_subject(mut self) -> Self {
        self.query.projection.retain(|field| field != "subject");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "subject");
        self
    }


    pub fn with_subject(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "subject",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_subject_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "subject",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_subject_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("subject", value));
        self
    }



    pub fn with_subject_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("subject", value));
        self
    }

    pub fn with_subject_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("subject", value));
        self
    }

    pub fn with_subject_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("subject", value));
        self
    }

    pub fn with_subject_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("subject", value));
        self
    }

    pub fn with_subject_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("subject", value));
        self
    }

    pub fn with_subject_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("subject", lower, upper));
        self
    }

    pub fn with_subject_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "subject",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_subject_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "subject",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_subject_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "subject",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_subject_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("subject", value));
        self
    }

    pub fn with_subject_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("subject", value));
        self
    }

    pub fn with_subject_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("subject", value));
        self
    }

    pub fn with_subject_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("subject", value));
        self
    }

    pub fn with_subject_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("subject", value));
        self
    }

    pub fn with_subject_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("subject", value));
        self
    }

    pub fn with_subject_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("subject", value));
        self
    }
    pub fn with_subject_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("subject", value));
        self
    }

    pub fn with_subject_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("subject", value));
        self
    }

    pub fn with_subject_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("subject"));
        self
    }



    pub fn with_subject_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("subject"));
        self
    }


    pub fn order_by_subject_asc(mut self) -> Self {
        self.query = self.query.order_asc("subject");
        self
    }

    pub fn order_by_subject_desc(mut self) -> Self {
        self.query = self.query.order_desc("subject");
        self
    }

    pub fn order_by_subject_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("subject");
        self
    }

    pub fn order_by_subject_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("subject");
        self
    }


    pub fn select_body(mut self) -> Self {
        self.query = self.query.project("body");
        self
    }

    pub fn project_body(self) -> Self {
        self.select_body()
    }

    pub fn select_body_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_body_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_body_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("body", raw_sql_segment));
        self
    }

    pub fn group_by_body(self) -> Self {
        self.group_by("body")
    }

    pub fn group_by_body_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("body");
        request.query = request
            .query
            .project_expr(alias, Expr::column("body"));
        request
    }

    pub fn group_by_body_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("body")
            .aggregate_with_function("body", alias, function)
    }

    pub fn count_body(self) -> Self {
        self.count_body_as("body_count")
    }

    pub fn count_body_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("body", alias)
    }

    pub fn sum_body(self) -> Self {
        self.sum_body_as("sum_body")
    }

    pub fn sum_body_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("body", alias)
    }

    pub fn avg_body(self) -> Self {
        self.avg_body_as("avg_body")
    }

    pub fn avg_body_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("body", alias)
    }

    pub fn min_body(self) -> Self {
        self.min_body_as("min_body")
    }

    pub fn min_body_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("body", alias)
    }

    pub fn max_body(self) -> Self {
        self.max_body_as("max_body")
    }

    pub fn max_body_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("body", alias)
    }

    pub fn unselect_body(mut self) -> Self {
        self.query.projection.retain(|field| field != "body");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "body");
        self
    }


    pub fn with_body(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "body",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_body_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "body",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_body_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("body", value));
        self
    }



    pub fn with_body_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("body", value));
        self
    }

    pub fn with_body_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("body", value));
        self
    }

    pub fn with_body_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("body", value));
        self
    }

    pub fn with_body_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("body", value));
        self
    }

    pub fn with_body_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("body", value));
        self
    }

    pub fn with_body_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("body", lower, upper));
        self
    }

    pub fn with_body_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "body",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_body_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "body",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_body_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "body",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_body_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("body", value));
        self
    }

    pub fn with_body_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("body", value));
        self
    }

    pub fn with_body_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("body", value));
        self
    }

    pub fn with_body_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("body", value));
        self
    }

    pub fn with_body_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("body", value));
        self
    }

    pub fn with_body_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("body", value));
        self
    }

    pub fn with_body_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("body", value));
        self
    }
    pub fn with_body_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("body", value));
        self
    }

    pub fn with_body_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("body", value));
        self
    }

    pub fn with_body_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("body"));
        self
    }



    pub fn with_body_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("body"));
        self
    }


    pub fn order_by_body_asc(mut self) -> Self {
        self.query = self.query.order_asc("body");
        self
    }

    pub fn order_by_body_desc(mut self) -> Self {
        self.query = self.query.order_desc("body");
        self
    }

    pub fn order_by_body_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("body");
        self
    }

    pub fn order_by_body_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("body");
        self
    }


    pub fn select_notification_type(mut self) -> Self {
        self.query = self.query.project("notification_type");
        self
    }

    pub fn project_notification_type(self) -> Self {
        self.select_notification_type()
    }

    pub fn select_notification_type_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_notification_type_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_notification_type_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("notification_type", raw_sql_segment));
        self
    }

    pub fn group_by_notification_type(self) -> Self {
        self.group_by("notification_type")
    }

    pub fn group_by_notification_type_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("notification_type");
        request.query = request
            .query
            .project_expr(alias, Expr::column("notification_type"));
        request
    }

    pub fn group_by_notification_type_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("notification_type")
            .aggregate_with_function("notification_type", alias, function)
    }

    pub fn count_notification_type(self) -> Self {
        self.count_notification_type_as("notification_type_count")
    }

    pub fn count_notification_type_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("notification_type", alias)
    }

    pub fn sum_notification_type(self) -> Self {
        self.sum_notification_type_as("sum_notification_type")
    }

    pub fn sum_notification_type_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("notification_type", alias)
    }

    pub fn avg_notification_type(self) -> Self {
        self.avg_notification_type_as("avg_notification_type")
    }

    pub fn avg_notification_type_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("notification_type", alias)
    }

    pub fn min_notification_type(self) -> Self {
        self.min_notification_type_as("min_notification_type")
    }

    pub fn min_notification_type_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("notification_type", alias)
    }

    pub fn max_notification_type(self) -> Self {
        self.max_notification_type_as("max_notification_type")
    }

    pub fn max_notification_type_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("notification_type", alias)
    }

    pub fn unselect_notification_type(mut self) -> Self {
        self.query.projection.retain(|field| field != "notification_type");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "notification_type");
        self
    }


    pub fn with_notification_type(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "notification_type",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_notification_type_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "notification_type",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_notification_type_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("notification_type", value));
        self
    }



    pub fn with_notification_type_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("notification_type", value));
        self
    }

    pub fn with_notification_type_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("notification_type", value));
        self
    }

    pub fn with_notification_type_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("notification_type", value));
        self
    }

    pub fn with_notification_type_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("notification_type", value));
        self
    }

    pub fn with_notification_type_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("notification_type", value));
        self
    }

    pub fn with_notification_type_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("notification_type", lower, upper));
        self
    }

    pub fn with_notification_type_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "notification_type",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_notification_type_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "notification_type",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_notification_type_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "notification_type",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_notification_type_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("notification_type", value));
        self
    }

    pub fn with_notification_type_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("notification_type", value));
        self
    }

    pub fn with_notification_type_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("notification_type", value));
        self
    }

    pub fn with_notification_type_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("notification_type", value));
        self
    }

    pub fn with_notification_type_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("notification_type", value));
        self
    }

    pub fn with_notification_type_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("notification_type", value));
        self
    }

    pub fn with_notification_type_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("notification_type", value));
        self
    }
    pub fn with_notification_type_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("notification_type", value));
        self
    }

    pub fn with_notification_type_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("notification_type", value));
        self
    }

    pub fn with_notification_type_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("notification_type"));
        self
    }



    pub fn with_notification_type_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("notification_type"));
        self
    }


    pub fn order_by_notification_type_asc(mut self) -> Self {
        self.query = self.query.order_asc("notification_type");
        self
    }

    pub fn order_by_notification_type_desc(mut self) -> Self {
        self.query = self.query.order_desc("notification_type");
        self
    }

    pub fn order_by_notification_type_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("notification_type");
        self
    }

    pub fn order_by_notification_type_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("notification_type");
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


    pub fn select_scheduled_time(mut self) -> Self {
        self.query = self.query.project("scheduled_time");
        self
    }

    pub fn project_scheduled_time(self) -> Self {
        self.select_scheduled_time()
    }

    pub fn select_scheduled_time_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_scheduled_time_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_scheduled_time_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("scheduled_time", raw_sql_segment));
        self
    }

    pub fn group_by_scheduled_time(self) -> Self {
        self.group_by("scheduled_time")
    }

    pub fn group_by_scheduled_time_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("scheduled_time");
        request.query = request
            .query
            .project_expr(alias, Expr::column("scheduled_time"));
        request
    }

    pub fn group_by_scheduled_time_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("scheduled_time")
            .aggregate_with_function("scheduled_time", alias, function)
    }

    pub fn count_scheduled_time(self) -> Self {
        self.count_scheduled_time_as("scheduled_time_count")
    }

    pub fn count_scheduled_time_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("scheduled_time", alias)
    }

    pub fn sum_scheduled_time(self) -> Self {
        self.sum_scheduled_time_as("sum_scheduled_time")
    }

    pub fn sum_scheduled_time_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("scheduled_time", alias)
    }

    pub fn avg_scheduled_time(self) -> Self {
        self.avg_scheduled_time_as("avg_scheduled_time")
    }

    pub fn avg_scheduled_time_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("scheduled_time", alias)
    }

    pub fn min_scheduled_time(self) -> Self {
        self.min_scheduled_time_as("min_scheduled_time")
    }

    pub fn min_scheduled_time_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("scheduled_time", alias)
    }

    pub fn max_scheduled_time(self) -> Self {
        self.max_scheduled_time_as("max_scheduled_time")
    }

    pub fn max_scheduled_time_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("scheduled_time", alias)
    }

    pub fn unselect_scheduled_time(mut self) -> Self {
        self.query.projection.retain(|field| field != "scheduled_time");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "scheduled_time");
        self
    }


    pub fn with_scheduled_time(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "scheduled_time",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_scheduled_time_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "scheduled_time",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_scheduled_time_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("scheduled_time", value));
        self
    }



    pub fn with_scheduled_time_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("scheduled_time", value));
        self
    }

    pub fn with_scheduled_time_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("scheduled_time", value));
        self
    }

    pub fn with_scheduled_time_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("scheduled_time", value));
        self
    }

    pub fn with_scheduled_time_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("scheduled_time", value));
        self
    }

    pub fn with_scheduled_time_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("scheduled_time", value));
        self
    }

    pub fn with_scheduled_time_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("scheduled_time", lower, upper));
        self
    }

    pub fn with_scheduled_time_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "scheduled_time",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_scheduled_time_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "scheduled_time",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_scheduled_time_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "scheduled_time",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_scheduled_time_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("scheduled_time", value));
        self
    }

    pub fn with_scheduled_time_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("scheduled_time", value));
        self
    }

    pub fn with_scheduled_time_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("scheduled_time"));
        self
    }



    pub fn with_scheduled_time_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("scheduled_time"));
        self
    }


    pub fn order_by_scheduled_time_asc(mut self) -> Self {
        self.query = self.query.order_asc("scheduled_time");
        self
    }

    pub fn order_by_scheduled_time_desc(mut self) -> Self {
        self.query = self.query.order_desc("scheduled_time");
        self
    }

    pub fn order_by_scheduled_time_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("scheduled_time");
        self
    }

    pub fn order_by_scheduled_time_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("scheduled_time");
        self
    }


    pub fn select_sent_time(mut self) -> Self {
        self.query = self.query.project("sent_time");
        self
    }

    pub fn project_sent_time(self) -> Self {
        self.select_sent_time()
    }

    pub fn select_sent_time_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_sent_time_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_sent_time_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("sent_time", raw_sql_segment));
        self
    }

    pub fn group_by_sent_time(self) -> Self {
        self.group_by("sent_time")
    }

    pub fn group_by_sent_time_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("sent_time");
        request.query = request
            .query
            .project_expr(alias, Expr::column("sent_time"));
        request
    }

    pub fn group_by_sent_time_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("sent_time")
            .aggregate_with_function("sent_time", alias, function)
    }

    pub fn count_sent_time(self) -> Self {
        self.count_sent_time_as("sent_time_count")
    }

    pub fn count_sent_time_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("sent_time", alias)
    }

    pub fn sum_sent_time(self) -> Self {
        self.sum_sent_time_as("sum_sent_time")
    }

    pub fn sum_sent_time_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("sent_time", alias)
    }

    pub fn avg_sent_time(self) -> Self {
        self.avg_sent_time_as("avg_sent_time")
    }

    pub fn avg_sent_time_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("sent_time", alias)
    }

    pub fn min_sent_time(self) -> Self {
        self.min_sent_time_as("min_sent_time")
    }

    pub fn min_sent_time_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("sent_time", alias)
    }

    pub fn max_sent_time(self) -> Self {
        self.max_sent_time_as("max_sent_time")
    }

    pub fn max_sent_time_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("sent_time", alias)
    }

    pub fn unselect_sent_time(mut self) -> Self {
        self.query.projection.retain(|field| field != "sent_time");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "sent_time");
        self
    }


    pub fn with_sent_time(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "sent_time",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_sent_time_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "sent_time",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_sent_time_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("sent_time", value));
        self
    }



    pub fn with_sent_time_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("sent_time", value));
        self
    }

    pub fn with_sent_time_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("sent_time", value));
        self
    }

    pub fn with_sent_time_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("sent_time", value));
        self
    }

    pub fn with_sent_time_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("sent_time", value));
        self
    }

    pub fn with_sent_time_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("sent_time", value));
        self
    }

    pub fn with_sent_time_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("sent_time", lower, upper));
        self
    }

    pub fn with_sent_time_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "sent_time",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_sent_time_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "sent_time",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_sent_time_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "sent_time",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_sent_time_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("sent_time", value));
        self
    }

    pub fn with_sent_time_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("sent_time", value));
        self
    }

    pub fn with_sent_time_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("sent_time"));
        self
    }



    pub fn with_sent_time_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("sent_time"));
        self
    }


    pub fn order_by_sent_time_asc(mut self) -> Self {
        self.query = self.query.order_asc("sent_time");
        self
    }

    pub fn order_by_sent_time_desc(mut self) -> Self {
        self.query = self.query.order_desc("sent_time");
        self
    }

    pub fn order_by_sent_time_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("sent_time");
        self
    }

    pub fn order_by_sent_time_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("sent_time");
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
    pub fn filter_by_recipient(mut self, value: impl EntityReference) -> Self {
        self.query = self.query.and_filter(Expr::eq("recipient_id", value.entity_id_value()));
        self
    }

    pub fn with_recipient_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "recipient_id",
            <crate::User as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("recipient", selection));
        self
    }


    pub fn without_recipient_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "recipient_id",
            <crate::User as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("recipient", selection));
        self
    }


    pub fn have_recipient(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("recipient_id"));
        self
    }

    pub fn have_no_recipient(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("recipient_id"));
        self
    }


    pub fn group_by_recipient(self) -> Self {
        self.group_by("recipient_id")
    }

    pub fn group_by_recipient_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("recipient_id");
        request.query = request
            .query
            .project_expr(alias, Expr::column("recipient_id"));
        request
    }

    pub fn group_by_recipient_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("recipient_id")
            .aggregate_with_function("recipient_id", alias, function)
    }

    pub fn group_by_recipient_with(mut self, request: impl Into<QuerySelection>) -> Self {
        self.query = self.query.group_by("recipient_id");
        self.query_options.object_group_bys.push(ObjectGroupBy::new(
            "recipient",
            "recipient_id",
            request,
        ));
        self
    }

    pub fn group_by_recipient_with_details(self) -> Self {
        self.group_by_recipient_with_details_from(crate::Q::users().unlimited())
    }

    pub fn group_by_recipient_with_details_from(self, request: impl Into<QuerySelection>) -> Self {
        self.group_by_recipient_with(request)
    }


    pub fn roll_up_to_recipient(self) -> Self {
        self.roll_up_to_recipient_with(crate::Q::users().unlimited())
    }

    pub fn roll_up_to_recipient_with(self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.with_recipient_matching(selection.clone())
            .group_by_recipient_with(selection)
    }

    pub fn count_recipient(self) -> Self {
        self.count_recipient_as("recipient_count")
    }

    pub fn count_recipient_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("recipient_id", alias)
    }

    pub fn unselect_recipient(mut self) -> Self {
        self.query.projection.retain(|field| field != "recipient_id");
        self.query.relations.retain(|relation| relation.name != "recipient");
        self
    }
    pub fn select_recipient(mut self) -> Self {
        self.query = self.query.relation("recipient");
        self
    }

    pub fn select_recipient_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("recipient", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("recipient", selection));
        self
}

    pub fn facet_by_recipient_as(self, facet_name: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.facet_by_recipient_as_with_options(facet_name, request, true)
    }

    pub fn facet_by_recipient_as_with_options(
        mut self,
        facet_name: impl Into<String>,
        request: impl Into<QuerySelection>,
        include_all_facets: bool,
    ) -> Self {
        self.query_options.facets.push(FacetRequest::new(
            facet_name,
            "recipient",
            request,
            include_all_facets,
        ));
        self
    }
}

impl<R> Default for NotificationRequest<R> {
    fn default() -> Self {
        Self::new()
    }
}

impl<R> From< NotificationRequest<R> > for SelectQuery {
    fn from(request: NotificationRequest<R>) -> Self {
        QuerySelection::from(request).into_query()
    }
}

impl<R> From< NotificationRequest<R> > for QuerySelection {
    fn from(request: NotificationRequest<R>) -> Self {
        Self {
            query: request.query,
            relation_selections: request.relation_selections,
            relation_filters: request.relation_filters,
            child_enhancements: request.child_enhancements,
            query_options: request.query_options,
        }
    }
}


impl<'a, C> crate::request_support::AuditedSave<'a, C> for teaql_core::Audited<crate::Notification> 
where C: crate::request_support::TeaqlRepositoryProvider + ?Sized + 'a
{
    type Error = crate::TeaqlDataServiceError<C::NotificationRepository<'a>>;
    fn save(self, ctx: &'a C) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<teaql_runtime::GraphNode, Self::Error>> + '_>> {
        Box::pin(async move { self.into_entity().save(ctx).await })
    }
}

impl<R: teaql_core::Entity> crate::PurposedQuery<NotificationRequest<R>> {
    pub fn new_entity<C>(&self, ctx: &C) -> crate::Notification
    where
        C: crate::TeaqlRuntime + ?Sized,
    {
        crate::Notification::runtime_new(ctx.user_context().entity_root())
    }

    fn into_inner_with_trace(mut self) -> NotificationRequest<R> {
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
    ) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::NotificationRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_page(ctx, offset, limit).await
    }

    pub async fn execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, crate::request_support::TeaqlDataServiceError<C::NotificationRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_exists(ctx).await
    }

    pub async fn execute_for_list<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::NotificationRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_list(ctx).await
    }

    /// Execute query in streaming mode (chunked).
    /// Returns a Vec of StreamChunk, each containing up to chunk_size rows.
    /// Set chunk size via .stream(chunk_size) or .stream_default() on the query.
    pub async fn execute_for_stream<'a, C>(self, ctx: &'a C) -> Result<Vec<teaql_data_service::StreamChunk>, crate::request_support::TeaqlDataServiceError<C::NotificationRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_stream(ctx).await
    }

    pub async fn execute_for_first<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::NotificationRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_first(ctx).await
    }

    pub async fn execute_for_one<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::NotificationRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_one(ctx).await
    }


    pub async fn execute_for_records<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::NotificationRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_records(ctx).await
    }

    pub async fn execute_for_record<'a, C>(self, ctx: &'a C) -> Result<Option<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::NotificationRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_record(ctx).await
    }

    pub async fn execute_for_count<'a, C>(self, ctx: &'a C) -> Result<u64, crate::request_support::TeaqlDataServiceError<C::NotificationRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_count(ctx).await
    }
}
