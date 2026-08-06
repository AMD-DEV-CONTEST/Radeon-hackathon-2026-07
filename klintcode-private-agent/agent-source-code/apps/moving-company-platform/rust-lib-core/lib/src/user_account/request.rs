use std::marker::PhantomData;

use serde_json::Value as JsonValue;
use teaql_core::{Aggregate, AggregateFunction, EntityDescriptor, Expr, Record, SelectQuery, SmartList};
use teaql_runtime::{DataServiceError, RuntimeError};

use crate::request_support::*;

impl EntityReference for crate::UserAccount {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(&self)
    }
}

impl EntityReference for &crate::UserAccount {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(self)
    }
}

// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/user_account
#[derive(Debug)]
pub struct UserAccountRequest<R = crate::UserAccount> {
    query: SelectQuery,
    relation_selections: Vec<RelationSelection>,
    relation_filters: Vec<RelationFilter>,
    child_enhancements: Vec<QuerySelection>,
    query_options: QueryOptions,
    marker: PhantomData<R>,
}

impl<R> Clone for UserAccountRequest<R> {
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

impl<R> UserAccountRequest<R> {
    pub(crate) fn new() -> Self {
        Self {
            query: SelectQuery::new("UserAccount")
                .project("id")
                .project("version"),
            relation_selections: Vec::new(),
            relation_filters: Vec::new(),
            child_enhancements: Vec::new(),
            query_options: QueryOptions::default(),
            marker: PhantomData,
        }
    }

    pub fn return_type<T>(self) -> UserAccountRequest<T> {
        UserAccountRequest {
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::UserAccountRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
        R: teaql_core::Entity,
    {
        let repository = ctx
            .user_account_repository()
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
    ) -> Result<Vec<teaql_data_service::StreamChunk>, TeaqlDataServiceError<C::UserAccountRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .user_account_repository()
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::UserAccountRepository<'a>>>
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::UserAccountRepository<'a>>>
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::UserAccountRepository<'a>>>
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
    ) -> Result<u64, TeaqlDataServiceError<C::UserAccountRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .user_account_repository()
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
            .ok_or_else(|| DataServiceError::Runtime(RuntimeError::Graph(format!("count result for UserAccount is missing or not numeric"))))
    }

    pub(crate) async fn _execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, TeaqlDataServiceError<C::UserAccountRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .user_account_repository()
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
    ) -> Result<SmartList<Record>, TeaqlDataServiceError<C::UserAccountRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .user_account_repository()
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
    ) -> Result<Option<Record>, TeaqlDataServiceError<C::UserAccountRepository<'a>>>
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
            "username" => Some("username"),
            "password_hash" => Some("password_hash"),
            "mobile_phone" => Some("mobile_phone"),
            "create_time" => Some("create_time"),
            "update_time" => Some("update_time"),
            "version" => Some("version"),
            "company" | "company_id" => Some("company_id"),
            _ => None,
        }
    }

    fn apply_dynamic_json_chain_filter(self, head: &str, tail: &str, value: &JsonValue) -> Self {
        let _ = (tail, value);
        match head {
            "company" => {
                self.with_company_matching(
                    crate::Q::companies_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "user_role_list" => {
                self.with_user_role_list_matching(
                    crate::Q::user_roles_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "audit_log_list" => {
                self.with_audit_log_list_matching(
                    crate::Q::audit_logs_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "notification_rule_list" => {
                self.with_notification_rule_list_matching(
                    crate::Q::notification_rules_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "document_storage_list" => {
                self.with_document_storage_list_matching(
                    crate::Q::document_storage_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "employee_record_list" => {
                self.with_employee_record_list_matching(
                    crate::Q::employee_records_minimal()
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
        self.query = self.query.project("username");
        self.query = self.query.project("password_hash");
        self.query = self.query.project("mobile_phone");
        self.query = self.query.project("create_time");
        self.query = self.query.project("update_time");
        self.query = self.query.project("version");
        self.query = self.query.project("company_id");
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
        request = request.select_company();
        request
    }

    pub fn select_children(self) -> Self {
        let mut request = self.select_all();
        request = request.select_user_role_list();
        request = request.select_audit_log_list();
        request = request.select_notification_rule_list();
        request = request.select_document_storage_list();
        request = request.select_employee_record_list();
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


    pub fn select_username(mut self) -> Self {
        self.query = self.query.project("username");
        self
    }

    pub fn project_username(self) -> Self {
        self.select_username()
    }

    pub fn select_username_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_username_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_username_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("username", raw_sql_segment));
        self
    }

    pub fn group_by_username(self) -> Self {
        self.group_by("username")
    }

    pub fn group_by_username_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("username");
        request.query = request
            .query
            .project_expr(alias, Expr::column("username"));
        request
    }

    pub fn group_by_username_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("username")
            .aggregate_with_function("username", alias, function)
    }

    pub fn count_username(self) -> Self {
        self.count_username_as("username_count")
    }

    pub fn count_username_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("username", alias)
    }

    pub fn sum_username(self) -> Self {
        self.sum_username_as("sum_username")
    }

    pub fn sum_username_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("username", alias)
    }

    pub fn avg_username(self) -> Self {
        self.avg_username_as("avg_username")
    }

    pub fn avg_username_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("username", alias)
    }

    pub fn min_username(self) -> Self {
        self.min_username_as("min_username")
    }

    pub fn min_username_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("username", alias)
    }

    pub fn max_username(self) -> Self {
        self.max_username_as("max_username")
    }

    pub fn max_username_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("username", alias)
    }

    pub fn unselect_username(mut self) -> Self {
        self.query.projection.retain(|field| field != "username");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "username");
        self
    }


    pub fn with_username(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "username",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_username_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "username",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_username_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("username", value));
        self
    }



    pub fn with_username_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("username", value));
        self
    }

    pub fn with_username_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("username", value));
        self
    }

    pub fn with_username_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("username", value));
        self
    }

    pub fn with_username_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("username", value));
        self
    }

    pub fn with_username_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("username", value));
        self
    }

    pub fn with_username_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("username", lower, upper));
        self
    }

    pub fn with_username_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "username",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_username_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "username",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_username_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "username",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_username_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("username", value));
        self
    }

    pub fn with_username_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("username", value));
        self
    }

    pub fn with_username_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("username", value));
        self
    }

    pub fn with_username_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("username", value));
        self
    }

    pub fn with_username_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("username", value));
        self
    }

    pub fn with_username_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("username", value));
        self
    }

    pub fn with_username_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("username", value));
        self
    }
    pub fn with_username_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("username", value));
        self
    }

    pub fn with_username_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("username", value));
        self
    }

    pub fn with_username_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("username"));
        self
    }



    pub fn with_username_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("username"));
        self
    }


    pub fn order_by_username_asc(mut self) -> Self {
        self.query = self.query.order_asc("username");
        self
    }

    pub fn order_by_username_desc(mut self) -> Self {
        self.query = self.query.order_desc("username");
        self
    }

    pub fn order_by_username_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("username");
        self
    }

    pub fn order_by_username_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("username");
        self
    }


    pub fn select_password_hash(mut self) -> Self {
        self.query = self.query.project("password_hash");
        self
    }

    pub fn project_password_hash(self) -> Self {
        self.select_password_hash()
    }

    pub fn select_password_hash_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_password_hash_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_password_hash_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("password_hash", raw_sql_segment));
        self
    }

    pub fn group_by_password_hash(self) -> Self {
        self.group_by("password_hash")
    }

    pub fn group_by_password_hash_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("password_hash");
        request.query = request
            .query
            .project_expr(alias, Expr::column("password_hash"));
        request
    }

    pub fn group_by_password_hash_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("password_hash")
            .aggregate_with_function("password_hash", alias, function)
    }

    pub fn count_password_hash(self) -> Self {
        self.count_password_hash_as("password_hash_count")
    }

    pub fn count_password_hash_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("password_hash", alias)
    }

    pub fn sum_password_hash(self) -> Self {
        self.sum_password_hash_as("sum_password_hash")
    }

    pub fn sum_password_hash_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("password_hash", alias)
    }

    pub fn avg_password_hash(self) -> Self {
        self.avg_password_hash_as("avg_password_hash")
    }

    pub fn avg_password_hash_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("password_hash", alias)
    }

    pub fn min_password_hash(self) -> Self {
        self.min_password_hash_as("min_password_hash")
    }

    pub fn min_password_hash_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("password_hash", alias)
    }

    pub fn max_password_hash(self) -> Self {
        self.max_password_hash_as("max_password_hash")
    }

    pub fn max_password_hash_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("password_hash", alias)
    }

    pub fn unselect_password_hash(mut self) -> Self {
        self.query.projection.retain(|field| field != "password_hash");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "password_hash");
        self
    }


    pub fn with_password_hash(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "password_hash",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_password_hash_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "password_hash",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_password_hash_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("password_hash", value));
        self
    }



    pub fn with_password_hash_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("password_hash", value));
        self
    }

    pub fn with_password_hash_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("password_hash", value));
        self
    }

    pub fn with_password_hash_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("password_hash", value));
        self
    }

    pub fn with_password_hash_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("password_hash", value));
        self
    }

    pub fn with_password_hash_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("password_hash", value));
        self
    }

    pub fn with_password_hash_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("password_hash", lower, upper));
        self
    }

    pub fn with_password_hash_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "password_hash",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_password_hash_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "password_hash",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_password_hash_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "password_hash",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_password_hash_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("password_hash", value));
        self
    }

    pub fn with_password_hash_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("password_hash", value));
        self
    }

    pub fn with_password_hash_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("password_hash", value));
        self
    }

    pub fn with_password_hash_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("password_hash", value));
        self
    }

    pub fn with_password_hash_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("password_hash", value));
        self
    }

    pub fn with_password_hash_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("password_hash", value));
        self
    }

    pub fn with_password_hash_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("password_hash", value));
        self
    }
    pub fn with_password_hash_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("password_hash", value));
        self
    }

    pub fn with_password_hash_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("password_hash", value));
        self
    }

    pub fn with_password_hash_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("password_hash"));
        self
    }



    pub fn with_password_hash_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("password_hash"));
        self
    }


    pub fn order_by_password_hash_asc(mut self) -> Self {
        self.query = self.query.order_asc("password_hash");
        self
    }

    pub fn order_by_password_hash_desc(mut self) -> Self {
        self.query = self.query.order_desc("password_hash");
        self
    }

    pub fn order_by_password_hash_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("password_hash");
        self
    }

    pub fn order_by_password_hash_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("password_hash");
        self
    }


    pub fn select_mobile_phone(mut self) -> Self {
        self.query = self.query.project("mobile_phone");
        self
    }

    pub fn project_mobile_phone(self) -> Self {
        self.select_mobile_phone()
    }

    pub fn select_mobile_phone_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_mobile_phone_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_mobile_phone_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("mobile_phone", raw_sql_segment));
        self
    }

    pub fn group_by_mobile_phone(self) -> Self {
        self.group_by("mobile_phone")
    }

    pub fn group_by_mobile_phone_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("mobile_phone");
        request.query = request
            .query
            .project_expr(alias, Expr::column("mobile_phone"));
        request
    }

    pub fn group_by_mobile_phone_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("mobile_phone")
            .aggregate_with_function("mobile_phone", alias, function)
    }

    pub fn count_mobile_phone(self) -> Self {
        self.count_mobile_phone_as("mobile_phone_count")
    }

    pub fn count_mobile_phone_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("mobile_phone", alias)
    }

    pub fn sum_mobile_phone(self) -> Self {
        self.sum_mobile_phone_as("sum_mobile_phone")
    }

    pub fn sum_mobile_phone_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("mobile_phone", alias)
    }

    pub fn avg_mobile_phone(self) -> Self {
        self.avg_mobile_phone_as("avg_mobile_phone")
    }

    pub fn avg_mobile_phone_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("mobile_phone", alias)
    }

    pub fn min_mobile_phone(self) -> Self {
        self.min_mobile_phone_as("min_mobile_phone")
    }

    pub fn min_mobile_phone_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("mobile_phone", alias)
    }

    pub fn max_mobile_phone(self) -> Self {
        self.max_mobile_phone_as("max_mobile_phone")
    }

    pub fn max_mobile_phone_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("mobile_phone", alias)
    }

    pub fn unselect_mobile_phone(mut self) -> Self {
        self.query.projection.retain(|field| field != "mobile_phone");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "mobile_phone");
        self
    }


    pub fn with_mobile_phone(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "mobile_phone",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_mobile_phone_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "mobile_phone",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_mobile_phone_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("mobile_phone", value));
        self
    }



    pub fn with_mobile_phone_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("mobile_phone", value));
        self
    }

    pub fn with_mobile_phone_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("mobile_phone", value));
        self
    }

    pub fn with_mobile_phone_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("mobile_phone", value));
        self
    }

    pub fn with_mobile_phone_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("mobile_phone", value));
        self
    }

    pub fn with_mobile_phone_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("mobile_phone", value));
        self
    }

    pub fn with_mobile_phone_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("mobile_phone", lower, upper));
        self
    }

    pub fn with_mobile_phone_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "mobile_phone",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_mobile_phone_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "mobile_phone",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_mobile_phone_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "mobile_phone",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_mobile_phone_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("mobile_phone", value));
        self
    }

    pub fn with_mobile_phone_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("mobile_phone", value));
        self
    }

    pub fn with_mobile_phone_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("mobile_phone", value));
        self
    }

    pub fn with_mobile_phone_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("mobile_phone", value));
        self
    }

    pub fn with_mobile_phone_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("mobile_phone", value));
        self
    }

    pub fn with_mobile_phone_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("mobile_phone", value));
        self
    }

    pub fn with_mobile_phone_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("mobile_phone", value));
        self
    }
    pub fn with_mobile_phone_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("mobile_phone", value));
        self
    }

    pub fn with_mobile_phone_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("mobile_phone", value));
        self
    }

    pub fn with_mobile_phone_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("mobile_phone"));
        self
    }



    pub fn with_mobile_phone_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("mobile_phone"));
        self
    }


    pub fn order_by_mobile_phone_asc(mut self) -> Self {
        self.query = self.query.order_asc("mobile_phone");
        self
    }

    pub fn order_by_mobile_phone_desc(mut self) -> Self {
        self.query = self.query.order_desc("mobile_phone");
        self
    }

    pub fn order_by_mobile_phone_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("mobile_phone");
        self
    }

    pub fn order_by_mobile_phone_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("mobile_phone");
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
    pub fn filter_by_company(mut self, value: impl EntityReference) -> Self {
        self.query = self.query.and_filter(Expr::eq("company_id", value.entity_id_value()));
        self
    }

    pub fn with_company_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "company_id",
            <crate::Company as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("company", selection));
        self
    }


    pub fn without_company_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "company_id",
            <crate::Company as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("company", selection));
        self
    }


    pub fn have_company(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("company_id"));
        self
    }

    pub fn have_no_company(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("company_id"));
        self
    }


    pub fn group_by_company(self) -> Self {
        self.group_by("company_id")
    }

    pub fn group_by_company_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("company_id");
        request.query = request
            .query
            .project_expr(alias, Expr::column("company_id"));
        request
    }

    pub fn group_by_company_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("company_id")
            .aggregate_with_function("company_id", alias, function)
    }

    pub fn group_by_company_with(mut self, request: impl Into<QuerySelection>) -> Self {
        self.query = self.query.group_by("company_id");
        self.query_options.object_group_bys.push(ObjectGroupBy::new(
            "company",
            "company_id",
            request,
        ));
        self
    }

    pub fn group_by_company_with_details(self) -> Self {
        self.group_by_company_with_details_from(crate::Q::companies().unlimited())
    }

    pub fn group_by_company_with_details_from(self, request: impl Into<QuerySelection>) -> Self {
        self.group_by_company_with(request)
    }


    pub fn roll_up_to_company(self) -> Self {
        self.roll_up_to_company_with(crate::Q::companies().unlimited())
    }

    pub fn roll_up_to_company_with(self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.with_company_matching(selection.clone())
            .group_by_company_with(selection)
    }

    pub fn count_company(self) -> Self {
        self.count_company_as("company_count")
    }

    pub fn count_company_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("company_id", alias)
    }

    pub fn unselect_company(mut self) -> Self {
        self.query.projection.retain(|field| field != "company_id");
        self.query.relations.retain(|relation| relation.name != "company");
        self
    }
    pub fn select_company(mut self) -> Self {
        self.query = self.query.relation("company");
        self
    }

    pub fn select_company_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("company", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("company", selection));
        self
}

    pub fn facet_by_company_as(self, facet_name: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.facet_by_company_as_with_options(facet_name, request, true)
    }

    pub fn facet_by_company_as_with_options(
        mut self,
        facet_name: impl Into<String>,
        request: impl Into<QuerySelection>,
        include_all_facets: bool,
    ) -> Self {
        self.query_options.facets.push(FacetRequest::new(
            facet_name,
            "company",
            request,
            include_all_facets,
        ));
        self
    }
    pub fn have_user_roles(self) -> Self {
        self.with_user_role_list_matching(SelectQuery::new("UserRole"))
    }

    pub fn have_no_user_roles(self) -> Self {
        self.without_user_role_list_matching(SelectQuery::new("UserRole"))
    }

    pub fn with_user_role_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::UserRole as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "user_account_id",
        ));
        self.relation_filters.push(RelationFilter::new("user_role_list", selection));
        self
    }

    pub fn without_user_role_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::UserRole as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "user_account_id",
        ));
        self.relation_filters.push(RelationFilter::new("user_role_list", selection));
        self
    }

    pub fn select_user_role_list(mut self) -> Self {
        self.query = self.query.relation("user_role_list");
        self
    }

    pub fn select_user_role_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("user_role_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("user_role_list", selection));
        self
}

    pub fn have_audit_logs(self) -> Self {
        self.with_audit_log_list_matching(SelectQuery::new("AuditLog"))
    }

    pub fn have_no_audit_logs(self) -> Self {
        self.without_audit_log_list_matching(SelectQuery::new("AuditLog"))
    }

    pub fn with_audit_log_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::AuditLog as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "action_operator_id",
        ));
        self.relation_filters.push(RelationFilter::new("audit_log_list", selection));
        self
    }

    pub fn without_audit_log_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::AuditLog as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "action_operator_id",
        ));
        self.relation_filters.push(RelationFilter::new("audit_log_list", selection));
        self
    }

    pub fn select_audit_log_list(mut self) -> Self {
        self.query = self.query.relation("audit_log_list");
        self
    }

    pub fn select_audit_log_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("audit_log_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("audit_log_list", selection));
        self
}

    pub fn have_notification_rules(self) -> Self {
        self.with_notification_rule_list_matching(SelectQuery::new("NotificationRule"))
    }

    pub fn have_no_notification_rules(self) -> Self {
        self.without_notification_rule_list_matching(SelectQuery::new("NotificationRule"))
    }

    pub fn with_notification_rule_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::NotificationRule as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "user_account_id",
        ));
        self.relation_filters.push(RelationFilter::new("notification_rule_list", selection));
        self
    }

    pub fn without_notification_rule_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::NotificationRule as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "user_account_id",
        ));
        self.relation_filters.push(RelationFilter::new("notification_rule_list", selection));
        self
    }

    pub fn select_notification_rule_list(mut self) -> Self {
        self.query = self.query.relation("notification_rule_list");
        self
    }

    pub fn select_notification_rule_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("notification_rule_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("notification_rule_list", selection));
        self
}

    pub fn have_document_storage(self) -> Self {
        self.with_document_storage_list_matching(SelectQuery::new("DocumentStorage"))
    }

    pub fn have_no_document_storage(self) -> Self {
        self.without_document_storage_list_matching(SelectQuery::new("DocumentStorage"))
    }

    pub fn with_document_storage_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::DocumentStorage as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "user_account_id",
        ));
        self.relation_filters.push(RelationFilter::new("document_storage_list", selection));
        self
    }

    pub fn without_document_storage_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::DocumentStorage as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "user_account_id",
        ));
        self.relation_filters.push(RelationFilter::new("document_storage_list", selection));
        self
    }

    pub fn select_document_storage_list(mut self) -> Self {
        self.query = self.query.relation("document_storage_list");
        self
    }

    pub fn select_document_storage_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("document_storage_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("document_storage_list", selection));
        self
}

    pub fn have_employee_records(self) -> Self {
        self.with_employee_record_list_matching(SelectQuery::new("EmployeeRecord"))
    }

    pub fn have_no_employee_records(self) -> Self {
        self.without_employee_record_list_matching(SelectQuery::new("EmployeeRecord"))
    }

    pub fn with_employee_record_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::EmployeeRecord as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "user_account_id",
        ));
        self.relation_filters.push(RelationFilter::new("employee_record_list", selection));
        self
    }

    pub fn without_employee_record_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::EmployeeRecord as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "user_account_id",
        ));
        self.relation_filters.push(RelationFilter::new("employee_record_list", selection));
        self
    }

    pub fn select_employee_record_list(mut self) -> Self {
        self.query = self.query.relation("employee_record_list");
        self
    }

    pub fn select_employee_record_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("employee_record_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("employee_record_list", selection));
        self
}
    pub fn count_user_roles(self) -> Self {
        self.count_user_roles_as("count_user_roles")
    }

    pub fn count_user_roles_as(self, alias: impl Into<String>) -> Self {
        self.count_user_roles_with(alias, crate::Q::user_roles().unlimited())
    }

    pub fn count_user_roles_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "user_role_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_user_roles(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_user_roles_as("refinements", request)
    }

    pub fn stats_from_user_roles_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "user_role_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_user_roles_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_user_roles(request)
    }


    pub fn min_create_time_of_user_roles(self) -> Self {
        self.min_create_time_of_user_roles_as("min_create_time_of_user_roles", crate::Q::user_roles().unlimited())
    }

    pub fn min_create_time_of_user_roles_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_user_roles_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_user_roles(self) -> Self {
        self.max_create_time_of_user_roles_as("max_create_time_of_user_roles", crate::Q::user_roles().unlimited())
    }

    pub fn max_create_time_of_user_roles_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_user_roles_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_user_roles(self) -> Self {
        self.min_update_time_of_user_roles_as("min_update_time_of_user_roles", crate::Q::user_roles().unlimited())
    }

    pub fn min_update_time_of_user_roles_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_user_roles_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_user_roles(self) -> Self {
        self.max_update_time_of_user_roles_as("max_update_time_of_user_roles", crate::Q::user_roles().unlimited())
    }

    pub fn max_update_time_of_user_roles_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_user_roles_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }

    pub fn count_audit_logs(self) -> Self {
        self.count_audit_logs_as("count_audit_logs")
    }

    pub fn count_audit_logs_as(self, alias: impl Into<String>) -> Self {
        self.count_audit_logs_with(alias, crate::Q::audit_logs().unlimited())
    }

    pub fn count_audit_logs_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "audit_log_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_audit_logs(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_audit_logs_as("refinements", request)
    }

    pub fn stats_from_audit_logs_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "audit_log_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_audit_logs_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_audit_logs(request)
    }


    pub fn min_log_timestamp_of_audit_logs(self) -> Self {
        self.min_log_timestamp_of_audit_logs_as("min_log_timestamp_of_audit_logs", crate::Q::audit_logs().unlimited())
    }

    pub fn min_log_timestamp_of_audit_logs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_audit_logs_as(alias, request.into().into_query().min("log_timestamp", "min_log_timestamp"))
    }
    pub fn max_log_timestamp_of_audit_logs(self) -> Self {
        self.max_log_timestamp_of_audit_logs_as("max_log_timestamp_of_audit_logs", crate::Q::audit_logs().unlimited())
    }

    pub fn max_log_timestamp_of_audit_logs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_audit_logs_as(alias, request.into().into_query().max("log_timestamp", "max_log_timestamp"))
    }

    pub fn count_notification_rules(self) -> Self {
        self.count_notification_rules_as("count_notification_rules")
    }

    pub fn count_notification_rules_as(self, alias: impl Into<String>) -> Self {
        self.count_notification_rules_with(alias, crate::Q::notification_rules().unlimited())
    }

    pub fn count_notification_rules_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "notification_rule_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_notification_rules(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_notification_rules_as("refinements", request)
    }

    pub fn stats_from_notification_rules_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "notification_rule_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_notification_rules_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_notification_rules(request)
    }


    pub fn min_create_time_of_notification_rules(self) -> Self {
        self.min_create_time_of_notification_rules_as("min_create_time_of_notification_rules", crate::Q::notification_rules().unlimited())
    }

    pub fn min_create_time_of_notification_rules_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_notification_rules_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_notification_rules(self) -> Self {
        self.max_create_time_of_notification_rules_as("max_create_time_of_notification_rules", crate::Q::notification_rules().unlimited())
    }

    pub fn max_create_time_of_notification_rules_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_notification_rules_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_notification_rules(self) -> Self {
        self.min_update_time_of_notification_rules_as("min_update_time_of_notification_rules", crate::Q::notification_rules().unlimited())
    }

    pub fn min_update_time_of_notification_rules_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_notification_rules_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_notification_rules(self) -> Self {
        self.max_update_time_of_notification_rules_as("max_update_time_of_notification_rules", crate::Q::notification_rules().unlimited())
    }

    pub fn max_update_time_of_notification_rules_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_notification_rules_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }

    pub fn count_document_storage(self) -> Self {
        self.count_document_storage_as("count_document_storage")
    }

    pub fn count_document_storage_as(self, alias: impl Into<String>) -> Self {
        self.count_document_storage_with(alias, crate::Q::document_storage().unlimited())
    }

    pub fn count_document_storage_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "document_storage_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_document_storage(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_document_storage_as("refinements", request)
    }

    pub fn stats_from_document_storage_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "document_storage_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_document_storage_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_document_storage(request)
    }


    pub fn min_create_time_of_document_storage(self) -> Self {
        self.min_create_time_of_document_storage_as("min_create_time_of_document_storage", crate::Q::document_storage().unlimited())
    }

    pub fn min_create_time_of_document_storage_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_document_storage_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_document_storage(self) -> Self {
        self.max_create_time_of_document_storage_as("max_create_time_of_document_storage", crate::Q::document_storage().unlimited())
    }

    pub fn max_create_time_of_document_storage_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_document_storage_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_document_storage(self) -> Self {
        self.min_update_time_of_document_storage_as("min_update_time_of_document_storage", crate::Q::document_storage().unlimited())
    }

    pub fn min_update_time_of_document_storage_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_document_storage_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_document_storage(self) -> Self {
        self.max_update_time_of_document_storage_as("max_update_time_of_document_storage", crate::Q::document_storage().unlimited())
    }

    pub fn max_update_time_of_document_storage_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_document_storage_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }

    pub fn count_employee_records(self) -> Self {
        self.count_employee_records_as("count_employee_records")
    }

    pub fn count_employee_records_as(self, alias: impl Into<String>) -> Self {
        self.count_employee_records_with(alias, crate::Q::employee_records().unlimited())
    }

    pub fn count_employee_records_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "employee_record_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_employee_records(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_employee_records_as("refinements", request)
    }

    pub fn stats_from_employee_records_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "employee_record_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_employee_records_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_employee_records(request)
    }


    pub fn min_hire_date_of_employee_records(self) -> Self {
        self.min_hire_date_of_employee_records_as("min_hire_date_of_employee_records", crate::Q::employee_records().unlimited())
    }

    pub fn min_hire_date_of_employee_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_employee_records_as(alias, request.into().into_query().min("hire_date", "min_hire_date"))
    }
    pub fn max_hire_date_of_employee_records(self) -> Self {
        self.max_hire_date_of_employee_records_as("max_hire_date_of_employee_records", crate::Q::employee_records().unlimited())
    }

    pub fn max_hire_date_of_employee_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_employee_records_as(alias, request.into().into_query().max("hire_date", "max_hire_date"))
    }
    pub fn min_create_time_of_employee_records(self) -> Self {
        self.min_create_time_of_employee_records_as("min_create_time_of_employee_records", crate::Q::employee_records().unlimited())
    }

    pub fn min_create_time_of_employee_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_employee_records_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_employee_records(self) -> Self {
        self.max_create_time_of_employee_records_as("max_create_time_of_employee_records", crate::Q::employee_records().unlimited())
    }

    pub fn max_create_time_of_employee_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_employee_records_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_employee_records(self) -> Self {
        self.min_update_time_of_employee_records_as("min_update_time_of_employee_records", crate::Q::employee_records().unlimited())
    }

    pub fn min_update_time_of_employee_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_employee_records_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_employee_records(self) -> Self {
        self.max_update_time_of_employee_records_as("max_update_time_of_employee_records", crate::Q::employee_records().unlimited())
    }

    pub fn max_update_time_of_employee_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_employee_records_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }
}

impl<R> Default for UserAccountRequest<R> {
    fn default() -> Self {
        Self::new()
    }
}

impl<R> From< UserAccountRequest<R> > for SelectQuery {
    fn from(request: UserAccountRequest<R>) -> Self {
        QuerySelection::from(request).into_query()
    }
}

impl<R> From< UserAccountRequest<R> > for QuerySelection {
    fn from(request: UserAccountRequest<R>) -> Self {
        Self {
            query: request.query,
            relation_selections: request.relation_selections,
            relation_filters: request.relation_filters,
            child_enhancements: request.child_enhancements,
            query_options: request.query_options,
        }
    }
}


impl<'a, C> crate::request_support::AuditedSave<'a, C> for teaql_core::Audited<crate::UserAccount> 
where C: crate::request_support::TeaqlRepositoryProvider + ?Sized + 'a
{
    type Error = crate::TeaqlDataServiceError<C::UserAccountRepository<'a>>;
    fn save(self, ctx: &'a C) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<teaql_runtime::GraphNode, Self::Error>> + '_>> {
        Box::pin(async move {
            teaql_runtime::save_audited_ledger_entity(self, ctx.user_context())
                .await
                .map_err(DataServiceError::Runtime)
        })
    }
}

impl<R: teaql_core::Entity> crate::PurposedQuery<UserAccountRequest<R>> {
    pub fn new_entity<C>(&self, ctx: &C) -> crate::UserAccount
    where
        C: crate::TeaqlRuntime + ?Sized,
    {
        crate::UserAccount::runtime_new(ctx.user_context().entity_root())
    }

    fn into_inner_with_trace(mut self) -> UserAccountRequest<R> {
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
    ) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::UserAccountRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_page(ctx, offset, limit).await
    }

    pub async fn execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, crate::request_support::TeaqlDataServiceError<C::UserAccountRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_exists(ctx).await
    }

    pub async fn execute_for_list<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::UserAccountRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_list(ctx).await
    }

    /// Execute query in streaming mode (chunked).
    /// Returns a Vec of StreamChunk, each containing up to chunk_size rows.
    /// Set chunk size via .stream(chunk_size) or .stream_default() on the query.
    pub async fn execute_for_stream<'a, C>(self, ctx: &'a C) -> Result<Vec<teaql_data_service::StreamChunk>, crate::request_support::TeaqlDataServiceError<C::UserAccountRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_stream(ctx).await
    }

    pub async fn execute_for_first<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::UserAccountRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_first(ctx).await
    }

    pub async fn execute_for_one<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::UserAccountRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_one(ctx).await
    }


    pub async fn execute_for_records<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::UserAccountRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_records(ctx).await
    }

    pub async fn execute_for_record<'a, C>(self, ctx: &'a C) -> Result<Option<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::UserAccountRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_record(ctx).await
    }

    pub async fn execute_for_count<'a, C>(self, ctx: &'a C) -> Result<u64, crate::request_support::TeaqlDataServiceError<C::UserAccountRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_count(ctx).await
    }
}
