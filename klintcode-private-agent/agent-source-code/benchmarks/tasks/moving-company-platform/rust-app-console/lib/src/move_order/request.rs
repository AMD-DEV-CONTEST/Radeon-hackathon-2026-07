use std::marker::PhantomData;

use serde_json::Value as JsonValue;
use teaql_core::{Aggregate, AggregateFunction, EntityDescriptor, Expr, Record, SelectQuery, SmartList};
use teaql_runtime::{DataServiceError, RuntimeError};

use crate::request_support::*;

impl EntityReference for crate::MoveOrder {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(&self)
    }
}

impl EntityReference for &crate::MoveOrder {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(self)
    }
}

// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/move_order
#[derive(Debug)]
pub struct MoveOrderRequest<R = crate::MoveOrder> {
    query: SelectQuery,
    relation_selections: Vec<RelationSelection>,
    relation_filters: Vec<RelationFilter>,
    child_enhancements: Vec<QuerySelection>,
    query_options: QueryOptions,
    marker: PhantomData<R>,
}

impl<R> Clone for MoveOrderRequest<R> {
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

impl<R> MoveOrderRequest<R> {
    pub(crate) fn new() -> Self {
        Self {
            query: SelectQuery::new("MoveOrder")
                .project("id")
                .project("version"),
            relation_selections: Vec::new(),
            relation_filters: Vec::new(),
            child_enhancements: Vec::new(),
            query_options: QueryOptions::default(),
            marker: PhantomData,
        }
    }

    pub fn return_type<T>(self) -> MoveOrderRequest<T> {
        MoveOrderRequest {
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::MoveOrderRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
        R: teaql_core::Entity,
    {
        let repository = ctx
            .move_order_repository()
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
    ) -> Result<Vec<teaql_data_service::StreamChunk>, TeaqlDataServiceError<C::MoveOrderRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .move_order_repository()
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::MoveOrderRepository<'a>>>
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::MoveOrderRepository<'a>>>
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::MoveOrderRepository<'a>>>
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
    ) -> Result<u64, TeaqlDataServiceError<C::MoveOrderRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .move_order_repository()
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
            .ok_or_else(|| DataServiceError::Runtime(RuntimeError::Graph(format!("count result for MoveOrder is missing or not numeric"))))
    }

    pub(crate) async fn _execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, TeaqlDataServiceError<C::MoveOrderRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .move_order_repository()
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
    ) -> Result<SmartList<Record>, TeaqlDataServiceError<C::MoveOrderRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .move_order_repository()
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
    ) -> Result<Option<Record>, TeaqlDataServiceError<C::MoveOrderRepository<'a>>>
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
            "move_date" => Some("move_date"),
            "create_time" => Some("create_time"),
            "update_time" => Some("update_time"),
            "version" => Some("version"),
            "customer_profile" | "customer_profile_id" => Some("customer_profile_id"),
            "origin_address" | "origin_address_id" => Some("origin_address_id"),
            "destination_address" | "destination_address_id" => Some("destination_address_id"),
            "asset_vehicle" | "asset_vehicle_id" => Some("asset_vehicle_id"),
            "order_status" | "order_status_id" => Some("order_status_id"),
            _ => None,
        }
    }

    fn apply_dynamic_json_chain_filter(self, head: &str, tail: &str, value: &JsonValue) -> Self {
        let _ = (tail, value);
        match head {
            "customer_profile" => {
                self.with_customer_profile_matching(
                    crate::Q::customer_profiles_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "origin_address" => {
                self.with_origin_address_matching(
                    crate::Q::location_addresses_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "destination_address" => {
                self.with_destination_address_matching(
                    crate::Q::location_addresses_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "asset_vehicle" => {
                self.with_asset_vehicle_matching(
                    crate::Q::fleet_vehicles_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "order_status" => {
                self.with_order_status_matching(
                    crate::Q::order_statuses_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "audit_log_list" => {
                self.with_audit_log_list_matching(
                    crate::Q::audit_logs_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "job_assignment_list" => {
                self.with_job_assignment_list_matching(
                    crate::Q::job_assignments_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "route_plan_list" => {
                self.with_route_plan_list_matching(
                    crate::Q::route_plans_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "time_slot_list" => {
                self.with_time_slot_list_matching(
                    crate::Q::time_slots_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "fulfillment_event_list" => {
                self.with_fulfillment_event_list_matching(
                    crate::Q::fulfillment_events_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "box_rental_list" => {
                self.with_box_rental_list_matching(
                    crate::Q::box_rentals_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "invoice_document_list" => {
                self.with_invoice_document_list_matching(
                    crate::Q::invoice_documents_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "payment_record_list" => {
                self.with_payment_record_list_matching(
                    crate::Q::payment_records_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "expense_record_list" => {
                self.with_expense_record_list_matching(
                    crate::Q::expense_records_minimal()
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
        self.query = self.query.project("move_date");
        self.query = self.query.project("create_time");
        self.query = self.query.project("update_time");
        self.query = self.query.project("version");
        self.query = self.query.project("customer_profile_id");
        self.query = self.query.project("origin_address_id");
        self.query = self.query.project("destination_address_id");
        self.query = self.query.project("asset_vehicle_id");
        self.query = self.query.project("order_status_id");
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
        request = request.select_customer_profile();
        request = request.select_origin_address();
        request = request.select_destination_address();
        request = request.select_asset_vehicle();
        request = request.select_order_status();
        request
    }

    pub fn select_children(self) -> Self {
        let mut request = self.select_all();
        request = request.select_audit_log_list();
        request = request.select_job_assignment_list();
        request = request.select_route_plan_list();
        request = request.select_time_slot_list();
        request = request.select_fulfillment_event_list();
        request = request.select_box_rental_list();
        request = request.select_invoice_document_list();
        request = request.select_payment_record_list();
        request = request.select_expense_record_list();
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


    pub fn select_move_date(mut self) -> Self {
        self.query = self.query.project("move_date");
        self
    }

    pub fn project_move_date(self) -> Self {
        self.select_move_date()
    }

    pub fn select_move_date_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_move_date_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_move_date_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("move_date", raw_sql_segment));
        self
    }

    pub fn group_by_move_date(self) -> Self {
        self.group_by("move_date")
    }

    pub fn group_by_move_date_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("move_date");
        request.query = request
            .query
            .project_expr(alias, Expr::column("move_date"));
        request
    }

    pub fn group_by_move_date_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("move_date")
            .aggregate_with_function("move_date", alias, function)
    }

    pub fn count_move_date(self) -> Self {
        self.count_move_date_as("move_date_count")
    }

    pub fn count_move_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("move_date", alias)
    }

    pub fn sum_move_date(self) -> Self {
        self.sum_move_date_as("sum_move_date")
    }

    pub fn sum_move_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("move_date", alias)
    }

    pub fn avg_move_date(self) -> Self {
        self.avg_move_date_as("avg_move_date")
    }

    pub fn avg_move_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("move_date", alias)
    }

    pub fn min_move_date(self) -> Self {
        self.min_move_date_as("min_move_date")
    }

    pub fn min_move_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("move_date", alias)
    }

    pub fn max_move_date(self) -> Self {
        self.max_move_date_as("max_move_date")
    }

    pub fn max_move_date_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("move_date", alias)
    }

    pub fn unselect_move_date(mut self) -> Self {
        self.query.projection.retain(|field| field != "move_date");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "move_date");
        self
    }


    pub fn with_move_date(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "move_date",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_move_date_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "move_date",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_move_date_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("move_date", value));
        self
    }



    pub fn with_move_date_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("move_date", value));
        self
    }

    pub fn with_move_date_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("move_date", value));
        self
    }

    pub fn with_move_date_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("move_date", value));
        self
    }

    pub fn with_move_date_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("move_date", value));
        self
    }

    pub fn with_move_date_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("move_date", value));
        self
    }

    pub fn with_move_date_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("move_date", lower, upper));
        self
    }

    pub fn with_move_date_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "move_date",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_move_date_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "move_date",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_move_date_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "move_date",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_move_date_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("move_date", value));
        self
    }

    pub fn with_move_date_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("move_date", value));
        self
    }

    pub fn with_move_date_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("move_date"));
        self
    }



    pub fn with_move_date_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("move_date"));
        self
    }


    pub fn order_by_move_date_asc(mut self) -> Self {
        self.query = self.query.order_asc("move_date");
        self
    }

    pub fn order_by_move_date_desc(mut self) -> Self {
        self.query = self.query.order_desc("move_date");
        self
    }

    pub fn order_by_move_date_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("move_date");
        self
    }

    pub fn order_by_move_date_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("move_date");
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
    pub fn filter_by_customer_profile(mut self, value: impl EntityReference) -> Self {
        self.query = self.query.and_filter(Expr::eq("customer_profile_id", value.entity_id_value()));
        self
    }

    pub fn with_customer_profile_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "customer_profile_id",
            <crate::CustomerProfile as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("customer_profile", selection));
        self
    }


    pub fn without_customer_profile_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "customer_profile_id",
            <crate::CustomerProfile as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("customer_profile", selection));
        self
    }


    pub fn have_customer_profile(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("customer_profile_id"));
        self
    }

    pub fn have_no_customer_profile(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("customer_profile_id"));
        self
    }


    pub fn group_by_customer_profile(self) -> Self {
        self.group_by("customer_profile_id")
    }

    pub fn group_by_customer_profile_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("customer_profile_id");
        request.query = request
            .query
            .project_expr(alias, Expr::column("customer_profile_id"));
        request
    }

    pub fn group_by_customer_profile_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("customer_profile_id")
            .aggregate_with_function("customer_profile_id", alias, function)
    }

    pub fn group_by_customer_profile_with(mut self, request: impl Into<QuerySelection>) -> Self {
        self.query = self.query.group_by("customer_profile_id");
        self.query_options.object_group_bys.push(ObjectGroupBy::new(
            "customer_profile",
            "customer_profile_id",
            request,
        ));
        self
    }

    pub fn group_by_customer_profile_with_details(self) -> Self {
        self.group_by_customer_profile_with_details_from(crate::Q::customer_profiles().unlimited())
    }

    pub fn group_by_customer_profile_with_details_from(self, request: impl Into<QuerySelection>) -> Self {
        self.group_by_customer_profile_with(request)
    }


    pub fn roll_up_to_customer_profile(self) -> Self {
        self.roll_up_to_customer_profile_with(crate::Q::customer_profiles().unlimited())
    }

    pub fn roll_up_to_customer_profile_with(self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.with_customer_profile_matching(selection.clone())
            .group_by_customer_profile_with(selection)
    }

    pub fn count_customer_profile(self) -> Self {
        self.count_customer_profile_as("customer_profile_count")
    }

    pub fn count_customer_profile_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("customer_profile_id", alias)
    }

    pub fn unselect_customer_profile(mut self) -> Self {
        self.query.projection.retain(|field| field != "customer_profile_id");
        self.query.relations.retain(|relation| relation.name != "customer_profile");
        self
    }


    pub fn filter_by_origin_address(mut self, value: impl EntityReference) -> Self {
        self.query = self.query.and_filter(Expr::eq("origin_address_id", value.entity_id_value()));
        self
    }

    pub fn with_origin_address_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "origin_address_id",
            <crate::LocationAddress as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("origin_address", selection));
        self
    }


    pub fn without_origin_address_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "origin_address_id",
            <crate::LocationAddress as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("origin_address", selection));
        self
    }


    pub fn have_origin_address(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("origin_address_id"));
        self
    }

    pub fn have_no_origin_address(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("origin_address_id"));
        self
    }


    pub fn group_by_origin_address(self) -> Self {
        self.group_by("origin_address_id")
    }

    pub fn group_by_origin_address_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("origin_address_id");
        request.query = request
            .query
            .project_expr(alias, Expr::column("origin_address_id"));
        request
    }

    pub fn group_by_origin_address_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("origin_address_id")
            .aggregate_with_function("origin_address_id", alias, function)
    }

    pub fn group_by_origin_address_with(mut self, request: impl Into<QuerySelection>) -> Self {
        self.query = self.query.group_by("origin_address_id");
        self.query_options.object_group_bys.push(ObjectGroupBy::new(
            "origin_address",
            "origin_address_id",
            request,
        ));
        self
    }

    pub fn group_by_origin_address_with_details(self) -> Self {
        self.group_by_origin_address_with_details_from(crate::Q::location_addresses().unlimited())
    }

    pub fn group_by_origin_address_with_details_from(self, request: impl Into<QuerySelection>) -> Self {
        self.group_by_origin_address_with(request)
    }


    pub fn roll_up_to_origin_address(self) -> Self {
        self.roll_up_to_origin_address_with(crate::Q::location_addresses().unlimited())
    }

    pub fn roll_up_to_origin_address_with(self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.with_origin_address_matching(selection.clone())
            .group_by_origin_address_with(selection)
    }

    pub fn count_origin_address(self) -> Self {
        self.count_origin_address_as("origin_address_count")
    }

    pub fn count_origin_address_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("origin_address_id", alias)
    }

    pub fn unselect_origin_address(mut self) -> Self {
        self.query.projection.retain(|field| field != "origin_address_id");
        self.query.relations.retain(|relation| relation.name != "origin_address");
        self
    }


    pub fn filter_by_destination_address(mut self, value: impl EntityReference) -> Self {
        self.query = self.query.and_filter(Expr::eq("destination_address_id", value.entity_id_value()));
        self
    }

    pub fn with_destination_address_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "destination_address_id",
            <crate::LocationAddress as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("destination_address", selection));
        self
    }


    pub fn without_destination_address_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "destination_address_id",
            <crate::LocationAddress as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("destination_address", selection));
        self
    }


    pub fn have_destination_address(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("destination_address_id"));
        self
    }

    pub fn have_no_destination_address(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("destination_address_id"));
        self
    }


    pub fn group_by_destination_address(self) -> Self {
        self.group_by("destination_address_id")
    }

    pub fn group_by_destination_address_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("destination_address_id");
        request.query = request
            .query
            .project_expr(alias, Expr::column("destination_address_id"));
        request
    }

    pub fn group_by_destination_address_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("destination_address_id")
            .aggregate_with_function("destination_address_id", alias, function)
    }

    pub fn group_by_destination_address_with(mut self, request: impl Into<QuerySelection>) -> Self {
        self.query = self.query.group_by("destination_address_id");
        self.query_options.object_group_bys.push(ObjectGroupBy::new(
            "destination_address",
            "destination_address_id",
            request,
        ));
        self
    }

    pub fn group_by_destination_address_with_details(self) -> Self {
        self.group_by_destination_address_with_details_from(crate::Q::location_addresses().unlimited())
    }

    pub fn group_by_destination_address_with_details_from(self, request: impl Into<QuerySelection>) -> Self {
        self.group_by_destination_address_with(request)
    }


    pub fn roll_up_to_destination_address(self) -> Self {
        self.roll_up_to_destination_address_with(crate::Q::location_addresses().unlimited())
    }

    pub fn roll_up_to_destination_address_with(self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.with_destination_address_matching(selection.clone())
            .group_by_destination_address_with(selection)
    }

    pub fn count_destination_address(self) -> Self {
        self.count_destination_address_as("destination_address_count")
    }

    pub fn count_destination_address_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("destination_address_id", alias)
    }

    pub fn unselect_destination_address(mut self) -> Self {
        self.query.projection.retain(|field| field != "destination_address_id");
        self.query.relations.retain(|relation| relation.name != "destination_address");
        self
    }


    pub fn filter_by_asset_vehicle(mut self, value: impl EntityReference) -> Self {
        self.query = self.query.and_filter(Expr::eq("asset_vehicle_id", value.entity_id_value()));
        self
    }

    pub fn with_asset_vehicle_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "asset_vehicle_id",
            <crate::FleetVehicle as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("asset_vehicle", selection));
        self
    }


    pub fn without_asset_vehicle_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "asset_vehicle_id",
            <crate::FleetVehicle as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("asset_vehicle", selection));
        self
    }


    pub fn have_asset_vehicle(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("asset_vehicle_id"));
        self
    }

    pub fn have_no_asset_vehicle(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("asset_vehicle_id"));
        self
    }


    pub fn group_by_asset_vehicle(self) -> Self {
        self.group_by("asset_vehicle_id")
    }

    pub fn group_by_asset_vehicle_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("asset_vehicle_id");
        request.query = request
            .query
            .project_expr(alias, Expr::column("asset_vehicle_id"));
        request
    }

    pub fn group_by_asset_vehicle_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("asset_vehicle_id")
            .aggregate_with_function("asset_vehicle_id", alias, function)
    }

    pub fn group_by_asset_vehicle_with(mut self, request: impl Into<QuerySelection>) -> Self {
        self.query = self.query.group_by("asset_vehicle_id");
        self.query_options.object_group_bys.push(ObjectGroupBy::new(
            "asset_vehicle",
            "asset_vehicle_id",
            request,
        ));
        self
    }

    pub fn group_by_asset_vehicle_with_details(self) -> Self {
        self.group_by_asset_vehicle_with_details_from(crate::Q::fleet_vehicles().unlimited())
    }

    pub fn group_by_asset_vehicle_with_details_from(self, request: impl Into<QuerySelection>) -> Self {
        self.group_by_asset_vehicle_with(request)
    }


    pub fn roll_up_to_asset_vehicle(self) -> Self {
        self.roll_up_to_asset_vehicle_with(crate::Q::fleet_vehicles().unlimited())
    }

    pub fn roll_up_to_asset_vehicle_with(self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.with_asset_vehicle_matching(selection.clone())
            .group_by_asset_vehicle_with(selection)
    }

    pub fn count_asset_vehicle(self) -> Self {
        self.count_asset_vehicle_as("asset_vehicle_count")
    }

    pub fn count_asset_vehicle_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("asset_vehicle_id", alias)
    }

    pub fn unselect_asset_vehicle(mut self) -> Self {
        self.query.projection.retain(|field| field != "asset_vehicle_id");
        self.query.relations.retain(|relation| relation.name != "asset_vehicle");
        self
    }


    /// Please use `with_order_status_is` instead
    pub(crate) fn filter_by_order_status(mut self, value: impl EntityReference) -> Self {
        self.query = self.query.and_filter(Expr::eq("order_status_id", value.entity_id_value()));
        self
    }
    /// Complex relation filter for `order_status`.
    ///
    /// **Usage Priority:**
    ///
    /// 1. **Preferred**: If you only want to filter by specific known constants, please **prefer** the generated semantic shortcut methods, such as:
    ///    - [`Self::with_order_status_is_xxx`]
    ///
    ///    This gives the best code readability.
    ///
    /// 2. **Advanced**: Only use this method when you need to perform advanced searches, dynamic subqueries, or filter based on complex relation conditions.
    ///
    /// # Example
    /// ```rust
    /// // Only use when building dynamic queries
    /// let dynamic_query = crate::Q::order_statuses_minimal().filter(...);
    /// let request = crate::Q::move_orders().with_order_status_matching(dynamic_query);
    /// ```
    pub fn with_order_status_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "order_status_id",
            <crate::OrderStatus as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("order_status", selection));
        self
    }


    /// Complex relation filter for `order_status`.
    ///
    /// **Usage Priority:**
    ///
    /// 1. **Preferred**: If you only want to filter by specific known constants, please **prefer** the generated semantic shortcut methods, such as:
    ///    - [`Self::with_order_status_is_not_xxx`]
    ///
    ///    This gives the best code readability.
    ///
    /// 2. **Advanced**: Only use this method when you need to perform advanced searches, dynamic subqueries, or filter based on complex relation conditions.
    ///
    /// # Example
    /// ```rust
    /// // Only use when building dynamic queries
    /// let dynamic_query = crate::Q::order_statuses_minimal().filter(...);
    /// let request = crate::Q::move_orders().without_order_status_matching(dynamic_query);
    /// ```
    pub fn without_order_status_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "order_status_id",
            <crate::OrderStatus as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("order_status", selection));
        self
    }


    pub fn have_order_status(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("order_status_id"));
        self
    }

    pub fn have_no_order_status(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("order_status_id"));
        self
    }


    pub fn group_by_order_status(self) -> Self {
        self.group_by("order_status_id")
    }

    pub fn group_by_order_status_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("order_status_id");
        request.query = request
            .query
            .project_expr(alias, Expr::column("order_status_id"));
        request
    }

    pub fn group_by_order_status_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("order_status_id")
            .aggregate_with_function("order_status_id", alias, function)
    }

    pub fn group_by_order_status_with(mut self, request: impl Into<QuerySelection>) -> Self {
        self.query = self.query.group_by("order_status_id");
        self.query_options.object_group_bys.push(ObjectGroupBy::new(
            "order_status",
            "order_status_id",
            request,
        ));
        self
    }

    pub fn group_by_order_status_with_details(self) -> Self {
        self.group_by_order_status_with_details_from(crate::Q::order_statuses().unlimited())
    }

    pub fn group_by_order_status_with_details_from(self, request: impl Into<QuerySelection>) -> Self {
        self.group_by_order_status_with(request)
    }


    pub fn roll_up_to_order_status(self) -> Self {
        self.roll_up_to_order_status_with(crate::Q::order_statuses().unlimited())
    }

    pub fn roll_up_to_order_status_with(self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.with_order_status_matching(selection.clone())
            .group_by_order_status_with(selection)
    }

    pub fn count_order_status(self) -> Self {
        self.count_order_status_as("order_status_count")
    }

    pub fn count_order_status_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("order_status_id", alias)
    }

    pub fn unselect_order_status(mut self) -> Self {
        self.query.projection.retain(|field| field != "order_status_id");
        self.query.relations.retain(|relation| relation.name != "order_status");
        self
    }
    pub fn order_status_is_scheduled(self) -> Self {
        self.filter_by_order_status(1001_u64)
    }

    pub fn with_order_status_is_scheduled(self) -> Self {
        self.filter_by_order_status(1001_u64)
    }



    pub fn with_order_status_is_not_scheduled(mut self) -> Self {
        self.query = self.query.and_filter(Expr::ne("order_status_id", 1001_u64));
        self
    }


    pub fn order_status_is_in_progress(self) -> Self {
        self.filter_by_order_status(1002_u64)
    }

    pub fn with_order_status_is_in_progress(self) -> Self {
        self.filter_by_order_status(1002_u64)
    }



    pub fn with_order_status_is_not_in_progress(mut self) -> Self {
        self.query = self.query.and_filter(Expr::ne("order_status_id", 1002_u64));
        self
    }


    pub fn order_status_is_completed(self) -> Self {
        self.filter_by_order_status(1003_u64)
    }

    pub fn with_order_status_is_completed(self) -> Self {
        self.filter_by_order_status(1003_u64)
    }



    pub fn with_order_status_is_not_completed(mut self) -> Self {
        self.query = self.query.and_filter(Expr::ne("order_status_id", 1003_u64));
        self
    }


    pub fn select_customer_profile(mut self) -> Self {
        self.query = self.query.relation("customer_profile");
        self
    }

    pub fn select_customer_profile_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("customer_profile", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("customer_profile", selection));
        self
}

    pub fn facet_by_customer_profile_as(self, facet_name: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.facet_by_customer_profile_as_with_options(facet_name, request, true)
    }

    pub fn facet_by_customer_profile_as_with_options(
        mut self,
        facet_name: impl Into<String>,
        request: impl Into<QuerySelection>,
        include_all_facets: bool,
    ) -> Self {
        self.query_options.facets.push(FacetRequest::new(
            facet_name,
            "customer_profile",
            request,
            include_all_facets,
        ));
        self
    }

    pub fn select_origin_address(mut self) -> Self {
        self.query = self.query.relation("origin_address");
        self
    }

    pub fn select_origin_address_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("origin_address", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("origin_address", selection));
        self
}

    pub fn facet_by_origin_address_as(self, facet_name: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.facet_by_origin_address_as_with_options(facet_name, request, true)
    }

    pub fn facet_by_origin_address_as_with_options(
        mut self,
        facet_name: impl Into<String>,
        request: impl Into<QuerySelection>,
        include_all_facets: bool,
    ) -> Self {
        self.query_options.facets.push(FacetRequest::new(
            facet_name,
            "origin_address",
            request,
            include_all_facets,
        ));
        self
    }

    pub fn select_destination_address(mut self) -> Self {
        self.query = self.query.relation("destination_address");
        self
    }

    pub fn select_destination_address_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("destination_address", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("destination_address", selection));
        self
}

    pub fn facet_by_destination_address_as(self, facet_name: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.facet_by_destination_address_as_with_options(facet_name, request, true)
    }

    pub fn facet_by_destination_address_as_with_options(
        mut self,
        facet_name: impl Into<String>,
        request: impl Into<QuerySelection>,
        include_all_facets: bool,
    ) -> Self {
        self.query_options.facets.push(FacetRequest::new(
            facet_name,
            "destination_address",
            request,
            include_all_facets,
        ));
        self
    }

    pub fn select_asset_vehicle(mut self) -> Self {
        self.query = self.query.relation("asset_vehicle");
        self
    }

    pub fn select_asset_vehicle_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("asset_vehicle", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("asset_vehicle", selection));
        self
}

    pub fn facet_by_asset_vehicle_as(self, facet_name: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.facet_by_asset_vehicle_as_with_options(facet_name, request, true)
    }

    pub fn facet_by_asset_vehicle_as_with_options(
        mut self,
        facet_name: impl Into<String>,
        request: impl Into<QuerySelection>,
        include_all_facets: bool,
    ) -> Self {
        self.query_options.facets.push(FacetRequest::new(
            facet_name,
            "asset_vehicle",
            request,
            include_all_facets,
        ));
        self
    }

    pub fn select_order_status(mut self) -> Self {
        self.query = self.query.relation("order_status");
        self
    }

    pub fn select_order_status_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("order_status", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("order_status", selection));
        self
}

    pub fn facet_by_order_status_as(self, facet_name: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.facet_by_order_status_as_with_options(facet_name, request, true)
    }

    pub fn facet_by_order_status_as_with_options(
        mut self,
        facet_name: impl Into<String>,
        request: impl Into<QuerySelection>,
        include_all_facets: bool,
    ) -> Self {
        self.query_options.facets.push(FacetRequest::new(
            facet_name,
            "order_status",
            request,
            include_all_facets,
        ));
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
            "entity_reference_id",
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
            "entity_reference_id",
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

    pub fn have_job_assignments(self) -> Self {
        self.with_job_assignment_list_matching(SelectQuery::new("JobAssignment"))
    }

    pub fn have_no_job_assignments(self) -> Self {
        self.without_job_assignment_list_matching(SelectQuery::new("JobAssignment"))
    }

    pub fn with_job_assignment_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::JobAssignment as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "move_order_id",
        ));
        self.relation_filters.push(RelationFilter::new("job_assignment_list", selection));
        self
    }

    pub fn without_job_assignment_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::JobAssignment as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "move_order_id",
        ));
        self.relation_filters.push(RelationFilter::new("job_assignment_list", selection));
        self
    }

    pub fn select_job_assignment_list(mut self) -> Self {
        self.query = self.query.relation("job_assignment_list");
        self
    }

    pub fn select_job_assignment_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("job_assignment_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("job_assignment_list", selection));
        self
}

    pub fn have_route_plans(self) -> Self {
        self.with_route_plan_list_matching(SelectQuery::new("RoutePlan"))
    }

    pub fn have_no_route_plans(self) -> Self {
        self.without_route_plan_list_matching(SelectQuery::new("RoutePlan"))
    }

    pub fn with_route_plan_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::RoutePlan as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "move_order_id",
        ));
        self.relation_filters.push(RelationFilter::new("route_plan_list", selection));
        self
    }

    pub fn without_route_plan_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::RoutePlan as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "move_order_id",
        ));
        self.relation_filters.push(RelationFilter::new("route_plan_list", selection));
        self
    }

    pub fn select_route_plan_list(mut self) -> Self {
        self.query = self.query.relation("route_plan_list");
        self
    }

    pub fn select_route_plan_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("route_plan_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("route_plan_list", selection));
        self
}

    pub fn have_time_slots(self) -> Self {
        self.with_time_slot_list_matching(SelectQuery::new("TimeSlot"))
    }

    pub fn have_no_time_slots(self) -> Self {
        self.without_time_slot_list_matching(SelectQuery::new("TimeSlot"))
    }

    pub fn with_time_slot_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::TimeSlot as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "move_order_id",
        ));
        self.relation_filters.push(RelationFilter::new("time_slot_list", selection));
        self
    }

    pub fn without_time_slot_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::TimeSlot as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "move_order_id",
        ));
        self.relation_filters.push(RelationFilter::new("time_slot_list", selection));
        self
    }

    pub fn select_time_slot_list(mut self) -> Self {
        self.query = self.query.relation("time_slot_list");
        self
    }

    pub fn select_time_slot_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("time_slot_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("time_slot_list", selection));
        self
}

    pub fn have_fulfillment_events(self) -> Self {
        self.with_fulfillment_event_list_matching(SelectQuery::new("FulfillmentEvent"))
    }

    pub fn have_no_fulfillment_events(self) -> Self {
        self.without_fulfillment_event_list_matching(SelectQuery::new("FulfillmentEvent"))
    }

    pub fn with_fulfillment_event_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::FulfillmentEvent as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "move_order_id",
        ));
        self.relation_filters.push(RelationFilter::new("fulfillment_event_list", selection));
        self
    }

    pub fn without_fulfillment_event_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::FulfillmentEvent as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "move_order_id",
        ));
        self.relation_filters.push(RelationFilter::new("fulfillment_event_list", selection));
        self
    }

    pub fn select_fulfillment_event_list(mut self) -> Self {
        self.query = self.query.relation("fulfillment_event_list");
        self
    }

    pub fn select_fulfillment_event_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("fulfillment_event_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("fulfillment_event_list", selection));
        self
}

    pub fn have_box_rentals(self) -> Self {
        self.with_box_rental_list_matching(SelectQuery::new("BoxRental"))
    }

    pub fn have_no_box_rentals(self) -> Self {
        self.without_box_rental_list_matching(SelectQuery::new("BoxRental"))
    }

    pub fn with_box_rental_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::BoxRental as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "move_order_id",
        ));
        self.relation_filters.push(RelationFilter::new("box_rental_list", selection));
        self
    }

    pub fn without_box_rental_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::BoxRental as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "move_order_id",
        ));
        self.relation_filters.push(RelationFilter::new("box_rental_list", selection));
        self
    }

    pub fn select_box_rental_list(mut self) -> Self {
        self.query = self.query.relation("box_rental_list");
        self
    }

    pub fn select_box_rental_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("box_rental_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("box_rental_list", selection));
        self
}

    pub fn have_invoice_documents(self) -> Self {
        self.with_invoice_document_list_matching(SelectQuery::new("InvoiceDocument"))
    }

    pub fn have_no_invoice_documents(self) -> Self {
        self.without_invoice_document_list_matching(SelectQuery::new("InvoiceDocument"))
    }

    pub fn with_invoice_document_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::InvoiceDocument as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "move_order_id",
        ));
        self.relation_filters.push(RelationFilter::new("invoice_document_list", selection));
        self
    }

    pub fn without_invoice_document_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::InvoiceDocument as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "move_order_id",
        ));
        self.relation_filters.push(RelationFilter::new("invoice_document_list", selection));
        self
    }

    pub fn select_invoice_document_list(mut self) -> Self {
        self.query = self.query.relation("invoice_document_list");
        self
    }

    pub fn select_invoice_document_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("invoice_document_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("invoice_document_list", selection));
        self
}

    pub fn have_payment_records(self) -> Self {
        self.with_payment_record_list_matching(SelectQuery::new("PaymentRecord"))
    }

    pub fn have_no_payment_records(self) -> Self {
        self.without_payment_record_list_matching(SelectQuery::new("PaymentRecord"))
    }

    pub fn with_payment_record_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::PaymentRecord as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "move_order_id",
        ));
        self.relation_filters.push(RelationFilter::new("payment_record_list", selection));
        self
    }

    pub fn without_payment_record_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::PaymentRecord as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "move_order_id",
        ));
        self.relation_filters.push(RelationFilter::new("payment_record_list", selection));
        self
    }

    pub fn select_payment_record_list(mut self) -> Self {
        self.query = self.query.relation("payment_record_list");
        self
    }

    pub fn select_payment_record_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("payment_record_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("payment_record_list", selection));
        self
}

    pub fn have_expense_records(self) -> Self {
        self.with_expense_record_list_matching(SelectQuery::new("ExpenseRecord"))
    }

    pub fn have_no_expense_records(self) -> Self {
        self.without_expense_record_list_matching(SelectQuery::new("ExpenseRecord"))
    }

    pub fn with_expense_record_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::ExpenseRecord as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "move_order_id",
        ));
        self.relation_filters.push(RelationFilter::new("expense_record_list", selection));
        self
    }

    pub fn without_expense_record_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::ExpenseRecord as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "move_order_id",
        ));
        self.relation_filters.push(RelationFilter::new("expense_record_list", selection));
        self
    }

    pub fn select_expense_record_list(mut self) -> Self {
        self.query = self.query.relation("expense_record_list");
        self
    }

    pub fn select_expense_record_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("expense_record_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("expense_record_list", selection));
        self
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
    pub fn min_create_time_of_audit_logs(self) -> Self {
        self.min_create_time_of_audit_logs_as("min_create_time_of_audit_logs", crate::Q::audit_logs().unlimited())
    }

    pub fn min_create_time_of_audit_logs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_audit_logs_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_audit_logs(self) -> Self {
        self.max_create_time_of_audit_logs_as("max_create_time_of_audit_logs", crate::Q::audit_logs().unlimited())
    }

    pub fn max_create_time_of_audit_logs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_audit_logs_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }

    pub fn count_job_assignments(self) -> Self {
        self.count_job_assignments_as("count_job_assignments")
    }

    pub fn count_job_assignments_as(self, alias: impl Into<String>) -> Self {
        self.count_job_assignments_with(alias, crate::Q::job_assignments().unlimited())
    }

    pub fn count_job_assignments_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "job_assignment_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_job_assignments(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_job_assignments_as("refinements", request)
    }

    pub fn stats_from_job_assignments_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "job_assignment_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_job_assignments_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_job_assignments(request)
    }


    pub fn min_create_time_of_job_assignments(self) -> Self {
        self.min_create_time_of_job_assignments_as("min_create_time_of_job_assignments", crate::Q::job_assignments().unlimited())
    }

    pub fn min_create_time_of_job_assignments_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_job_assignments_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_job_assignments(self) -> Self {
        self.max_create_time_of_job_assignments_as("max_create_time_of_job_assignments", crate::Q::job_assignments().unlimited())
    }

    pub fn max_create_time_of_job_assignments_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_job_assignments_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }

    pub fn count_route_plans(self) -> Self {
        self.count_route_plans_as("count_route_plans")
    }

    pub fn count_route_plans_as(self, alias: impl Into<String>) -> Self {
        self.count_route_plans_with(alias, crate::Q::route_plans().unlimited())
    }

    pub fn count_route_plans_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "route_plan_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_route_plans(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_route_plans_as("refinements", request)
    }

    pub fn stats_from_route_plans_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "route_plan_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_route_plans_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_route_plans(request)
    }


    pub fn sum_estimated_distance_of_route_plans(self) -> Self {
        self.sum_estimated_distance_of_route_plans_as("sum_estimated_distance_of_route_plans", crate::Q::route_plans().unlimited())
    }

    pub fn sum_estimated_distance_of_route_plans_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_route_plans_as(alias, request.into().into_query().sum("estimated_distance", "sum_estimated_distance"))
    }
    pub fn min_estimated_distance_of_route_plans(self) -> Self {
        self.min_estimated_distance_of_route_plans_as("min_estimated_distance_of_route_plans", crate::Q::route_plans().unlimited())
    }

    pub fn min_estimated_distance_of_route_plans_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_route_plans_as(alias, request.into().into_query().min("estimated_distance", "min_estimated_distance"))
    }
    pub fn max_estimated_distance_of_route_plans(self) -> Self {
        self.max_estimated_distance_of_route_plans_as("max_estimated_distance_of_route_plans", crate::Q::route_plans().unlimited())
    }

    pub fn max_estimated_distance_of_route_plans_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_route_plans_as(alias, request.into().into_query().max("estimated_distance", "max_estimated_distance"))
    }
    pub fn avg_estimated_distance_of_route_plans(self) -> Self {
        self.avg_estimated_distance_of_route_plans_as("avg_estimated_distance_of_route_plans", crate::Q::route_plans().unlimited())
    }

    pub fn avg_estimated_distance_of_route_plans_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_route_plans_as(alias, request.into().into_query().avg("estimated_distance", "avg_estimated_distance"))
    }
    pub fn standard_deviation_estimated_distance_of_route_plans(self) -> Self {
        self.standard_deviation_estimated_distance_of_route_plans_as("standard_deviation_estimated_distance_of_route_plans", crate::Q::route_plans().unlimited())
    }

    pub fn standard_deviation_estimated_distance_of_route_plans_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_route_plans_as(alias, request.into().into_query().stddev("estimated_distance", "stdDev_estimated_distance"))
    }
    pub fn square_root_of_population_standard_deviation_estimated_distance_of_route_plans(self) -> Self {
        self.square_root_of_population_standard_deviation_estimated_distance_of_route_plans_as("square_root_of_population_standard_deviation_estimated_distance_of_route_plans", crate::Q::route_plans().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_estimated_distance_of_route_plans_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_route_plans_as(alias, request.into().into_query().stddev_pop("estimated_distance", "stdDevPop_estimated_distance"))
    }
    pub fn sample_variance_estimated_distance_of_route_plans(self) -> Self {
        self.sample_variance_estimated_distance_of_route_plans_as("sample_variance_estimated_distance_of_route_plans", crate::Q::route_plans().unlimited())
    }

    pub fn sample_variance_estimated_distance_of_route_plans_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_route_plans_as(alias, request.into().into_query().var_samp("estimated_distance", "varSamp_estimated_distance"))
    }
    pub fn sample_population_variance_estimated_distance_of_route_plans(self) -> Self {
        self.sample_population_variance_estimated_distance_of_route_plans_as("sample_population_variance_estimated_distance_of_route_plans", crate::Q::route_plans().unlimited())
    }

    pub fn sample_population_variance_estimated_distance_of_route_plans_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_route_plans_as(alias, request.into().into_query().var_pop("estimated_distance", "varPop_estimated_distance"))
    }
    pub fn sum_estimated_duration_of_route_plans(self) -> Self {
        self.sum_estimated_duration_of_route_plans_as("sum_estimated_duration_of_route_plans", crate::Q::route_plans().unlimited())
    }

    pub fn sum_estimated_duration_of_route_plans_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_route_plans_as(alias, request.into().into_query().sum("estimated_duration", "sum_estimated_duration"))
    }
    pub fn min_estimated_duration_of_route_plans(self) -> Self {
        self.min_estimated_duration_of_route_plans_as("min_estimated_duration_of_route_plans", crate::Q::route_plans().unlimited())
    }

    pub fn min_estimated_duration_of_route_plans_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_route_plans_as(alias, request.into().into_query().min("estimated_duration", "min_estimated_duration"))
    }
    pub fn max_estimated_duration_of_route_plans(self) -> Self {
        self.max_estimated_duration_of_route_plans_as("max_estimated_duration_of_route_plans", crate::Q::route_plans().unlimited())
    }

    pub fn max_estimated_duration_of_route_plans_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_route_plans_as(alias, request.into().into_query().max("estimated_duration", "max_estimated_duration"))
    }
    pub fn avg_estimated_duration_of_route_plans(self) -> Self {
        self.avg_estimated_duration_of_route_plans_as("avg_estimated_duration_of_route_plans", crate::Q::route_plans().unlimited())
    }

    pub fn avg_estimated_duration_of_route_plans_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_route_plans_as(alias, request.into().into_query().avg("estimated_duration", "avg_estimated_duration"))
    }
    pub fn standard_deviation_estimated_duration_of_route_plans(self) -> Self {
        self.standard_deviation_estimated_duration_of_route_plans_as("standard_deviation_estimated_duration_of_route_plans", crate::Q::route_plans().unlimited())
    }

    pub fn standard_deviation_estimated_duration_of_route_plans_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_route_plans_as(alias, request.into().into_query().stddev("estimated_duration", "stdDev_estimated_duration"))
    }
    pub fn square_root_of_population_standard_deviation_estimated_duration_of_route_plans(self) -> Self {
        self.square_root_of_population_standard_deviation_estimated_duration_of_route_plans_as("square_root_of_population_standard_deviation_estimated_duration_of_route_plans", crate::Q::route_plans().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_estimated_duration_of_route_plans_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_route_plans_as(alias, request.into().into_query().stddev_pop("estimated_duration", "stdDevPop_estimated_duration"))
    }
    pub fn sample_variance_estimated_duration_of_route_plans(self) -> Self {
        self.sample_variance_estimated_duration_of_route_plans_as("sample_variance_estimated_duration_of_route_plans", crate::Q::route_plans().unlimited())
    }

    pub fn sample_variance_estimated_duration_of_route_plans_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_route_plans_as(alias, request.into().into_query().var_samp("estimated_duration", "varSamp_estimated_duration"))
    }
    pub fn sample_population_variance_estimated_duration_of_route_plans(self) -> Self {
        self.sample_population_variance_estimated_duration_of_route_plans_as("sample_population_variance_estimated_duration_of_route_plans", crate::Q::route_plans().unlimited())
    }

    pub fn sample_population_variance_estimated_duration_of_route_plans_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_route_plans_as(alias, request.into().into_query().var_pop("estimated_duration", "varPop_estimated_duration"))
    }
    pub fn min_create_time_of_route_plans(self) -> Self {
        self.min_create_time_of_route_plans_as("min_create_time_of_route_plans", crate::Q::route_plans().unlimited())
    }

    pub fn min_create_time_of_route_plans_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_route_plans_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_route_plans(self) -> Self {
        self.max_create_time_of_route_plans_as("max_create_time_of_route_plans", crate::Q::route_plans().unlimited())
    }

    pub fn max_create_time_of_route_plans_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_route_plans_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }

    pub fn count_time_slots(self) -> Self {
        self.count_time_slots_as("count_time_slots")
    }

    pub fn count_time_slots_as(self, alias: impl Into<String>) -> Self {
        self.count_time_slots_with(alias, crate::Q::time_slots().unlimited())
    }

    pub fn count_time_slots_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "time_slot_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_time_slots(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_time_slots_as("refinements", request)
    }

    pub fn stats_from_time_slots_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "time_slot_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_time_slots_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_time_slots(request)
    }


    pub fn min_create_time_of_time_slots(self) -> Self {
        self.min_create_time_of_time_slots_as("min_create_time_of_time_slots", crate::Q::time_slots().unlimited())
    }

    pub fn min_create_time_of_time_slots_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_time_slots_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_time_slots(self) -> Self {
        self.max_create_time_of_time_slots_as("max_create_time_of_time_slots", crate::Q::time_slots().unlimited())
    }

    pub fn max_create_time_of_time_slots_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_time_slots_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }

    pub fn count_fulfillment_events(self) -> Self {
        self.count_fulfillment_events_as("count_fulfillment_events")
    }

    pub fn count_fulfillment_events_as(self, alias: impl Into<String>) -> Self {
        self.count_fulfillment_events_with(alias, crate::Q::fulfillment_events().unlimited())
    }

    pub fn count_fulfillment_events_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "fulfillment_event_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_fulfillment_events(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_fulfillment_events_as("refinements", request)
    }

    pub fn stats_from_fulfillment_events_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "fulfillment_event_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_fulfillment_events_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_fulfillment_events(request)
    }


    pub fn min_create_time_of_fulfillment_events(self) -> Self {
        self.min_create_time_of_fulfillment_events_as("min_create_time_of_fulfillment_events", crate::Q::fulfillment_events().unlimited())
    }

    pub fn min_create_time_of_fulfillment_events_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_fulfillment_events_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_fulfillment_events(self) -> Self {
        self.max_create_time_of_fulfillment_events_as("max_create_time_of_fulfillment_events", crate::Q::fulfillment_events().unlimited())
    }

    pub fn max_create_time_of_fulfillment_events_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_fulfillment_events_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }

    pub fn count_box_rentals(self) -> Self {
        self.count_box_rentals_as("count_box_rentals")
    }

    pub fn count_box_rentals_as(self, alias: impl Into<String>) -> Self {
        self.count_box_rentals_with(alias, crate::Q::box_rentals().unlimited())
    }

    pub fn count_box_rentals_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "box_rental_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_box_rentals(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as("refinements", request)
    }

    pub fn stats_from_box_rentals_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "box_rental_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_box_rentals_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals(request)
    }


    pub fn sum_box_quantity_of_box_rentals(self) -> Self {
        self.sum_box_quantity_of_box_rentals_as("sum_box_quantity_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn sum_box_quantity_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().sum("box_quantity", "sum_box_quantity"))
    }
    pub fn min_box_quantity_of_box_rentals(self) -> Self {
        self.min_box_quantity_of_box_rentals_as("min_box_quantity_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn min_box_quantity_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().min("box_quantity", "min_box_quantity"))
    }
    pub fn max_box_quantity_of_box_rentals(self) -> Self {
        self.max_box_quantity_of_box_rentals_as("max_box_quantity_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn max_box_quantity_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().max("box_quantity", "max_box_quantity"))
    }
    pub fn avg_box_quantity_of_box_rentals(self) -> Self {
        self.avg_box_quantity_of_box_rentals_as("avg_box_quantity_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn avg_box_quantity_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().avg("box_quantity", "avg_box_quantity"))
    }
    pub fn standard_deviation_box_quantity_of_box_rentals(self) -> Self {
        self.standard_deviation_box_quantity_of_box_rentals_as("standard_deviation_box_quantity_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn standard_deviation_box_quantity_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().stddev("box_quantity", "stdDev_box_quantity"))
    }
    pub fn square_root_of_population_standard_deviation_box_quantity_of_box_rentals(self) -> Self {
        self.square_root_of_population_standard_deviation_box_quantity_of_box_rentals_as("square_root_of_population_standard_deviation_box_quantity_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_box_quantity_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().stddev_pop("box_quantity", "stdDevPop_box_quantity"))
    }
    pub fn sample_variance_box_quantity_of_box_rentals(self) -> Self {
        self.sample_variance_box_quantity_of_box_rentals_as("sample_variance_box_quantity_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn sample_variance_box_quantity_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().var_samp("box_quantity", "varSamp_box_quantity"))
    }
    pub fn sample_population_variance_box_quantity_of_box_rentals(self) -> Self {
        self.sample_population_variance_box_quantity_of_box_rentals_as("sample_population_variance_box_quantity_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn sample_population_variance_box_quantity_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().var_pop("box_quantity", "varPop_box_quantity"))
    }
    pub fn sum_rental_fee_of_box_rentals(self) -> Self {
        self.sum_rental_fee_of_box_rentals_as("sum_rental_fee_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn sum_rental_fee_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().sum("rental_fee", "sum_rental_fee"))
    }
    pub fn min_rental_fee_of_box_rentals(self) -> Self {
        self.min_rental_fee_of_box_rentals_as("min_rental_fee_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn min_rental_fee_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().min("rental_fee", "min_rental_fee"))
    }
    pub fn max_rental_fee_of_box_rentals(self) -> Self {
        self.max_rental_fee_of_box_rentals_as("max_rental_fee_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn max_rental_fee_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().max("rental_fee", "max_rental_fee"))
    }
    pub fn avg_rental_fee_of_box_rentals(self) -> Self {
        self.avg_rental_fee_of_box_rentals_as("avg_rental_fee_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn avg_rental_fee_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().avg("rental_fee", "avg_rental_fee"))
    }
    pub fn standard_deviation_rental_fee_of_box_rentals(self) -> Self {
        self.standard_deviation_rental_fee_of_box_rentals_as("standard_deviation_rental_fee_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn standard_deviation_rental_fee_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().stddev("rental_fee", "stdDev_rental_fee"))
    }
    pub fn square_root_of_population_standard_deviation_rental_fee_of_box_rentals(self) -> Self {
        self.square_root_of_population_standard_deviation_rental_fee_of_box_rentals_as("square_root_of_population_standard_deviation_rental_fee_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_rental_fee_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().stddev_pop("rental_fee", "stdDevPop_rental_fee"))
    }
    pub fn sample_variance_rental_fee_of_box_rentals(self) -> Self {
        self.sample_variance_rental_fee_of_box_rentals_as("sample_variance_rental_fee_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn sample_variance_rental_fee_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().var_samp("rental_fee", "varSamp_rental_fee"))
    }
    pub fn sample_population_variance_rental_fee_of_box_rentals(self) -> Self {
        self.sample_population_variance_rental_fee_of_box_rentals_as("sample_population_variance_rental_fee_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn sample_population_variance_rental_fee_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().var_pop("rental_fee", "varPop_rental_fee"))
    }
    pub fn min_create_time_of_box_rentals(self) -> Self {
        self.min_create_time_of_box_rentals_as("min_create_time_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn min_create_time_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_box_rentals(self) -> Self {
        self.max_create_time_of_box_rentals_as("max_create_time_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn max_create_time_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }

    pub fn count_invoice_documents(self) -> Self {
        self.count_invoice_documents_as("count_invoice_documents")
    }

    pub fn count_invoice_documents_as(self, alias: impl Into<String>) -> Self {
        self.count_invoice_documents_with(alias, crate::Q::invoice_documents().unlimited())
    }

    pub fn count_invoice_documents_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "invoice_document_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_invoice_documents(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_invoice_documents_as("refinements", request)
    }

    pub fn stats_from_invoice_documents_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "invoice_document_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_invoice_documents_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_invoice_documents(request)
    }


    pub fn sum_invoice_total_of_invoice_documents(self) -> Self {
        self.sum_invoice_total_of_invoice_documents_as("sum_invoice_total_of_invoice_documents", crate::Q::invoice_documents().unlimited())
    }

    pub fn sum_invoice_total_of_invoice_documents_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_invoice_documents_as(alias, request.into().into_query().sum("invoice_total", "sum_invoice_total"))
    }
    pub fn min_invoice_total_of_invoice_documents(self) -> Self {
        self.min_invoice_total_of_invoice_documents_as("min_invoice_total_of_invoice_documents", crate::Q::invoice_documents().unlimited())
    }

    pub fn min_invoice_total_of_invoice_documents_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_invoice_documents_as(alias, request.into().into_query().min("invoice_total", "min_invoice_total"))
    }
    pub fn max_invoice_total_of_invoice_documents(self) -> Self {
        self.max_invoice_total_of_invoice_documents_as("max_invoice_total_of_invoice_documents", crate::Q::invoice_documents().unlimited())
    }

    pub fn max_invoice_total_of_invoice_documents_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_invoice_documents_as(alias, request.into().into_query().max("invoice_total", "max_invoice_total"))
    }
    pub fn avg_invoice_total_of_invoice_documents(self) -> Self {
        self.avg_invoice_total_of_invoice_documents_as("avg_invoice_total_of_invoice_documents", crate::Q::invoice_documents().unlimited())
    }

    pub fn avg_invoice_total_of_invoice_documents_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_invoice_documents_as(alias, request.into().into_query().avg("invoice_total", "avg_invoice_total"))
    }
    pub fn standard_deviation_invoice_total_of_invoice_documents(self) -> Self {
        self.standard_deviation_invoice_total_of_invoice_documents_as("standard_deviation_invoice_total_of_invoice_documents", crate::Q::invoice_documents().unlimited())
    }

    pub fn standard_deviation_invoice_total_of_invoice_documents_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_invoice_documents_as(alias, request.into().into_query().stddev("invoice_total", "stdDev_invoice_total"))
    }
    pub fn square_root_of_population_standard_deviation_invoice_total_of_invoice_documents(self) -> Self {
        self.square_root_of_population_standard_deviation_invoice_total_of_invoice_documents_as("square_root_of_population_standard_deviation_invoice_total_of_invoice_documents", crate::Q::invoice_documents().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_invoice_total_of_invoice_documents_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_invoice_documents_as(alias, request.into().into_query().stddev_pop("invoice_total", "stdDevPop_invoice_total"))
    }
    pub fn sample_variance_invoice_total_of_invoice_documents(self) -> Self {
        self.sample_variance_invoice_total_of_invoice_documents_as("sample_variance_invoice_total_of_invoice_documents", crate::Q::invoice_documents().unlimited())
    }

    pub fn sample_variance_invoice_total_of_invoice_documents_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_invoice_documents_as(alias, request.into().into_query().var_samp("invoice_total", "varSamp_invoice_total"))
    }
    pub fn sample_population_variance_invoice_total_of_invoice_documents(self) -> Self {
        self.sample_population_variance_invoice_total_of_invoice_documents_as("sample_population_variance_invoice_total_of_invoice_documents", crate::Q::invoice_documents().unlimited())
    }

    pub fn sample_population_variance_invoice_total_of_invoice_documents_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_invoice_documents_as(alias, request.into().into_query().var_pop("invoice_total", "varPop_invoice_total"))
    }
    pub fn min_issue_date_of_invoice_documents(self) -> Self {
        self.min_issue_date_of_invoice_documents_as("min_issue_date_of_invoice_documents", crate::Q::invoice_documents().unlimited())
    }

    pub fn min_issue_date_of_invoice_documents_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_invoice_documents_as(alias, request.into().into_query().min("issue_date", "min_issue_date"))
    }
    pub fn max_issue_date_of_invoice_documents(self) -> Self {
        self.max_issue_date_of_invoice_documents_as("max_issue_date_of_invoice_documents", crate::Q::invoice_documents().unlimited())
    }

    pub fn max_issue_date_of_invoice_documents_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_invoice_documents_as(alias, request.into().into_query().max("issue_date", "max_issue_date"))
    }
    pub fn min_create_time_of_invoice_documents(self) -> Self {
        self.min_create_time_of_invoice_documents_as("min_create_time_of_invoice_documents", crate::Q::invoice_documents().unlimited())
    }

    pub fn min_create_time_of_invoice_documents_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_invoice_documents_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_invoice_documents(self) -> Self {
        self.max_create_time_of_invoice_documents_as("max_create_time_of_invoice_documents", crate::Q::invoice_documents().unlimited())
    }

    pub fn max_create_time_of_invoice_documents_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_invoice_documents_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }

    pub fn count_payment_records(self) -> Self {
        self.count_payment_records_as("count_payment_records")
    }

    pub fn count_payment_records_as(self, alias: impl Into<String>) -> Self {
        self.count_payment_records_with(alias, crate::Q::payment_records().unlimited())
    }

    pub fn count_payment_records_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "payment_record_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_payment_records(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payment_records_as("refinements", request)
    }

    pub fn stats_from_payment_records_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "payment_record_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_payment_records_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payment_records(request)
    }


    pub fn sum_payment_amount_of_payment_records(self) -> Self {
        self.sum_payment_amount_of_payment_records_as("sum_payment_amount_of_payment_records", crate::Q::payment_records().unlimited())
    }

    pub fn sum_payment_amount_of_payment_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payment_records_as(alias, request.into().into_query().sum("payment_amount", "sum_payment_amount"))
    }
    pub fn min_payment_amount_of_payment_records(self) -> Self {
        self.min_payment_amount_of_payment_records_as("min_payment_amount_of_payment_records", crate::Q::payment_records().unlimited())
    }

    pub fn min_payment_amount_of_payment_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payment_records_as(alias, request.into().into_query().min("payment_amount", "min_payment_amount"))
    }
    pub fn max_payment_amount_of_payment_records(self) -> Self {
        self.max_payment_amount_of_payment_records_as("max_payment_amount_of_payment_records", crate::Q::payment_records().unlimited())
    }

    pub fn max_payment_amount_of_payment_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payment_records_as(alias, request.into().into_query().max("payment_amount", "max_payment_amount"))
    }
    pub fn avg_payment_amount_of_payment_records(self) -> Self {
        self.avg_payment_amount_of_payment_records_as("avg_payment_amount_of_payment_records", crate::Q::payment_records().unlimited())
    }

    pub fn avg_payment_amount_of_payment_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payment_records_as(alias, request.into().into_query().avg("payment_amount", "avg_payment_amount"))
    }
    pub fn standard_deviation_payment_amount_of_payment_records(self) -> Self {
        self.standard_deviation_payment_amount_of_payment_records_as("standard_deviation_payment_amount_of_payment_records", crate::Q::payment_records().unlimited())
    }

    pub fn standard_deviation_payment_amount_of_payment_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payment_records_as(alias, request.into().into_query().stddev("payment_amount", "stdDev_payment_amount"))
    }
    pub fn square_root_of_population_standard_deviation_payment_amount_of_payment_records(self) -> Self {
        self.square_root_of_population_standard_deviation_payment_amount_of_payment_records_as("square_root_of_population_standard_deviation_payment_amount_of_payment_records", crate::Q::payment_records().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_payment_amount_of_payment_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payment_records_as(alias, request.into().into_query().stddev_pop("payment_amount", "stdDevPop_payment_amount"))
    }
    pub fn sample_variance_payment_amount_of_payment_records(self) -> Self {
        self.sample_variance_payment_amount_of_payment_records_as("sample_variance_payment_amount_of_payment_records", crate::Q::payment_records().unlimited())
    }

    pub fn sample_variance_payment_amount_of_payment_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payment_records_as(alias, request.into().into_query().var_samp("payment_amount", "varSamp_payment_amount"))
    }
    pub fn sample_population_variance_payment_amount_of_payment_records(self) -> Self {
        self.sample_population_variance_payment_amount_of_payment_records_as("sample_population_variance_payment_amount_of_payment_records", crate::Q::payment_records().unlimited())
    }

    pub fn sample_population_variance_payment_amount_of_payment_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payment_records_as(alias, request.into().into_query().var_pop("payment_amount", "varPop_payment_amount"))
    }
    pub fn min_payment_date_of_payment_records(self) -> Self {
        self.min_payment_date_of_payment_records_as("min_payment_date_of_payment_records", crate::Q::payment_records().unlimited())
    }

    pub fn min_payment_date_of_payment_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payment_records_as(alias, request.into().into_query().min("payment_date", "min_payment_date"))
    }
    pub fn max_payment_date_of_payment_records(self) -> Self {
        self.max_payment_date_of_payment_records_as("max_payment_date_of_payment_records", crate::Q::payment_records().unlimited())
    }

    pub fn max_payment_date_of_payment_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payment_records_as(alias, request.into().into_query().max("payment_date", "max_payment_date"))
    }
    pub fn min_create_time_of_payment_records(self) -> Self {
        self.min_create_time_of_payment_records_as("min_create_time_of_payment_records", crate::Q::payment_records().unlimited())
    }

    pub fn min_create_time_of_payment_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payment_records_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_payment_records(self) -> Self {
        self.max_create_time_of_payment_records_as("max_create_time_of_payment_records", crate::Q::payment_records().unlimited())
    }

    pub fn max_create_time_of_payment_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payment_records_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }

    pub fn count_expense_records(self) -> Self {
        self.count_expense_records_as("count_expense_records")
    }

    pub fn count_expense_records_as(self, alias: impl Into<String>) -> Self {
        self.count_expense_records_with(alias, crate::Q::expense_records().unlimited())
    }

    pub fn count_expense_records_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "expense_record_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_expense_records(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records_as("refinements", request)
    }

    pub fn stats_from_expense_records_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "expense_record_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_expense_records_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records(request)
    }


    pub fn sum_expense_amount_of_expense_records(self) -> Self {
        self.sum_expense_amount_of_expense_records_as("sum_expense_amount_of_expense_records", crate::Q::expense_records().unlimited())
    }

    pub fn sum_expense_amount_of_expense_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records_as(alias, request.into().into_query().sum("expense_amount", "sum_expense_amount"))
    }
    pub fn min_expense_amount_of_expense_records(self) -> Self {
        self.min_expense_amount_of_expense_records_as("min_expense_amount_of_expense_records", crate::Q::expense_records().unlimited())
    }

    pub fn min_expense_amount_of_expense_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records_as(alias, request.into().into_query().min("expense_amount", "min_expense_amount"))
    }
    pub fn max_expense_amount_of_expense_records(self) -> Self {
        self.max_expense_amount_of_expense_records_as("max_expense_amount_of_expense_records", crate::Q::expense_records().unlimited())
    }

    pub fn max_expense_amount_of_expense_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records_as(alias, request.into().into_query().max("expense_amount", "max_expense_amount"))
    }
    pub fn avg_expense_amount_of_expense_records(self) -> Self {
        self.avg_expense_amount_of_expense_records_as("avg_expense_amount_of_expense_records", crate::Q::expense_records().unlimited())
    }

    pub fn avg_expense_amount_of_expense_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records_as(alias, request.into().into_query().avg("expense_amount", "avg_expense_amount"))
    }
    pub fn standard_deviation_expense_amount_of_expense_records(self) -> Self {
        self.standard_deviation_expense_amount_of_expense_records_as("standard_deviation_expense_amount_of_expense_records", crate::Q::expense_records().unlimited())
    }

    pub fn standard_deviation_expense_amount_of_expense_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records_as(alias, request.into().into_query().stddev("expense_amount", "stdDev_expense_amount"))
    }
    pub fn square_root_of_population_standard_deviation_expense_amount_of_expense_records(self) -> Self {
        self.square_root_of_population_standard_deviation_expense_amount_of_expense_records_as("square_root_of_population_standard_deviation_expense_amount_of_expense_records", crate::Q::expense_records().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_expense_amount_of_expense_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records_as(alias, request.into().into_query().stddev_pop("expense_amount", "stdDevPop_expense_amount"))
    }
    pub fn sample_variance_expense_amount_of_expense_records(self) -> Self {
        self.sample_variance_expense_amount_of_expense_records_as("sample_variance_expense_amount_of_expense_records", crate::Q::expense_records().unlimited())
    }

    pub fn sample_variance_expense_amount_of_expense_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records_as(alias, request.into().into_query().var_samp("expense_amount", "varSamp_expense_amount"))
    }
    pub fn sample_population_variance_expense_amount_of_expense_records(self) -> Self {
        self.sample_population_variance_expense_amount_of_expense_records_as("sample_population_variance_expense_amount_of_expense_records", crate::Q::expense_records().unlimited())
    }

    pub fn sample_population_variance_expense_amount_of_expense_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records_as(alias, request.into().into_query().var_pop("expense_amount", "varPop_expense_amount"))
    }
    pub fn min_create_time_of_expense_records(self) -> Self {
        self.min_create_time_of_expense_records_as("min_create_time_of_expense_records", crate::Q::expense_records().unlimited())
    }

    pub fn min_create_time_of_expense_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_expense_records(self) -> Self {
        self.max_create_time_of_expense_records_as("max_create_time_of_expense_records", crate::Q::expense_records().unlimited())
    }

    pub fn max_create_time_of_expense_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_expense_records_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
}

impl<R> Default for MoveOrderRequest<R> {
    fn default() -> Self {
        Self::new()
    }
}

impl<R> From< MoveOrderRequest<R> > for SelectQuery {
    fn from(request: MoveOrderRequest<R>) -> Self {
        QuerySelection::from(request).into_query()
    }
}

impl<R> From< MoveOrderRequest<R> > for QuerySelection {
    fn from(request: MoveOrderRequest<R>) -> Self {
        Self {
            query: request.query,
            relation_selections: request.relation_selections,
            relation_filters: request.relation_filters,
            child_enhancements: request.child_enhancements,
            query_options: request.query_options,
        }
    }
}


impl<'a, C> crate::request_support::AuditedSave<'a, C> for teaql_core::Audited<crate::MoveOrder> 
where C: crate::request_support::TeaqlRepositoryProvider + ?Sized + 'a
{
    type Error = crate::TeaqlDataServiceError<C::MoveOrderRepository<'a>>;
    fn save(self, ctx: &'a C) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<teaql_runtime::GraphNode, Self::Error>> + '_>> {
        Box::pin(async move {
            teaql_runtime::save_audited_ledger_entity(self, ctx.user_context())
                .await
                .map_err(DataServiceError::Runtime)
        })
    }
}

impl<R: teaql_core::Entity> crate::PurposedQuery<MoveOrderRequest<R>> {
    pub fn new_entity<C>(&self, ctx: &C) -> crate::MoveOrder
    where
        C: crate::TeaqlRuntime + ?Sized,
    {
        crate::MoveOrder::runtime_new(ctx.user_context().entity_root())
    }

    fn into_inner_with_trace(mut self) -> MoveOrderRequest<R> {
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
    ) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::MoveOrderRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_page(ctx, offset, limit).await
    }

    pub async fn execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, crate::request_support::TeaqlDataServiceError<C::MoveOrderRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_exists(ctx).await
    }

    pub async fn execute_for_list<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::MoveOrderRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_list(ctx).await
    }

    /// Execute query in streaming mode (chunked).
    /// Returns a Vec of StreamChunk, each containing up to chunk_size rows.
    /// Set chunk size via .stream(chunk_size) or .stream_default() on the query.
    pub async fn execute_for_stream<'a, C>(self, ctx: &'a C) -> Result<Vec<teaql_data_service::StreamChunk>, crate::request_support::TeaqlDataServiceError<C::MoveOrderRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_stream(ctx).await
    }

    pub async fn execute_for_first<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::MoveOrderRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_first(ctx).await
    }

    pub async fn execute_for_one<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::MoveOrderRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_one(ctx).await
    }


    pub async fn execute_for_records<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::MoveOrderRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_records(ctx).await
    }

    pub async fn execute_for_record<'a, C>(self, ctx: &'a C) -> Result<Option<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::MoveOrderRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_record(ctx).await
    }

    pub async fn execute_for_count<'a, C>(self, ctx: &'a C) -> Result<u64, crate::request_support::TeaqlDataServiceError<C::MoveOrderRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_count(ctx).await
    }
}
