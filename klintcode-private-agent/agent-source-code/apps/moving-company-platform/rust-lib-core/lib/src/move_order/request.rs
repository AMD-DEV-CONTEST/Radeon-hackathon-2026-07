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
            "order_status" => Some("order_status"),
            "create_time" => Some("create_time"),
            "update_time" => Some("update_time"),
            "version" => Some("version"),
            "private_customer" | "private_customer_id" => Some("private_customer_id"),
            "corporate_customer" | "corporate_customer_id" => Some("corporate_customer_id"),
            "origin_address" | "origin_address_id" => Some("origin_address_id"),
            "dest_address" | "dest_address_id" => Some("dest_address_id"),
            "assigned_vehicle" | "assigned_vehicle_id" => Some("assigned_vehicle_id"),
            _ => None,
        }
    }

    fn apply_dynamic_json_chain_filter(self, head: &str, tail: &str, value: &JsonValue) -> Self {
        let _ = (tail, value);
        match head {
            "private_customer" => {
                self.with_private_customer_matching(
                    crate::Q::private_customers_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "corporate_customer" => {
                self.with_corporate_customer_matching(
                    crate::Q::corporate_customers_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "origin_address" => {
                self.with_origin_address_matching(
                    crate::Q::address_records_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "dest_address" => {
                self.with_dest_address_matching(
                    crate::Q::address_records_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "assigned_vehicle" => {
                self.with_assigned_vehicle_matching(
                    crate::Q::vehicle_assets_minimal()
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
            "job_assignment_list" => {
                self.with_job_assignment_list_matching(
                    crate::Q::job_assignments_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "service_config_list" => {
                self.with_service_config_list_matching(
                    crate::Q::service_configs_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "box_rental_list" => {
                self.with_box_rental_list_matching(
                    crate::Q::box_rentals_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "conversion_metric_list" => {
                self.with_conversion_metric_list_matching(
                    crate::Q::conversion_metrics_minimal()
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
        self.query = self.query.project("order_status");
        self.query = self.query.project("create_time");
        self.query = self.query.project("update_time");
        self.query = self.query.project("version");
        self.query = self.query.project("private_customer_id");
        self.query = self.query.project("corporate_customer_id");
        self.query = self.query.project("origin_address_id");
        self.query = self.query.project("dest_address_id");
        self.query = self.query.project("assigned_vehicle_id");
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
        request = request.select_private_customer();
        request = request.select_corporate_customer();
        request = request.select_origin_address();
        request = request.select_dest_address();
        request = request.select_assigned_vehicle();
        request
    }

    pub fn select_children(self) -> Self {
        let mut request = self.select_all();
        request = request.select_route_plan_list();
        request = request.select_time_slot_list();
        request = request.select_fulfillment_event_list();
        request = request.select_job_assignment_list();
        request = request.select_service_config_list();
        request = request.select_box_rental_list();
        request = request.select_conversion_metric_list();
        request = request.select_invoice_document_list();
        request = request.select_payment_record_list();
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


    pub fn select_order_status(mut self) -> Self {
        self.query = self.query.project("order_status");
        self
    }

    pub fn project_order_status(self) -> Self {
        self.select_order_status()
    }

    pub fn select_order_status_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_order_status_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_order_status_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("order_status", raw_sql_segment));
        self
    }

    pub fn group_by_order_status(self) -> Self {
        self.group_by("order_status")
    }

    pub fn group_by_order_status_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("order_status");
        request.query = request
            .query
            .project_expr(alias, Expr::column("order_status"));
        request
    }

    pub fn group_by_order_status_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("order_status")
            .aggregate_with_function("order_status", alias, function)
    }

    pub fn count_order_status(self) -> Self {
        self.count_order_status_as("order_status_count")
    }

    pub fn count_order_status_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("order_status", alias)
    }

    pub fn sum_order_status(self) -> Self {
        self.sum_order_status_as("sum_order_status")
    }

    pub fn sum_order_status_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("order_status", alias)
    }

    pub fn avg_order_status(self) -> Self {
        self.avg_order_status_as("avg_order_status")
    }

    pub fn avg_order_status_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("order_status", alias)
    }

    pub fn min_order_status(self) -> Self {
        self.min_order_status_as("min_order_status")
    }

    pub fn min_order_status_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("order_status", alias)
    }

    pub fn max_order_status(self) -> Self {
        self.max_order_status_as("max_order_status")
    }

    pub fn max_order_status_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("order_status", alias)
    }

    pub fn unselect_order_status(mut self) -> Self {
        self.query.projection.retain(|field| field != "order_status");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "order_status");
        self
    }


    pub fn with_order_status(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "order_status",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_order_status_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "order_status",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_order_status_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("order_status", value));
        self
    }



    pub fn with_order_status_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("order_status", value));
        self
    }

    pub fn with_order_status_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("order_status", value));
        self
    }

    pub fn with_order_status_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("order_status", value));
        self
    }

    pub fn with_order_status_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("order_status", value));
        self
    }

    pub fn with_order_status_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("order_status", value));
        self
    }

    pub fn with_order_status_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("order_status", lower, upper));
        self
    }

    pub fn with_order_status_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "order_status",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_order_status_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "order_status",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_order_status_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "order_status",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_order_status_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("order_status", value));
        self
    }

    pub fn with_order_status_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("order_status", value));
        self
    }

    pub fn with_order_status_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("order_status", value));
        self
    }

    pub fn with_order_status_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("order_status", value));
        self
    }

    pub fn with_order_status_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("order_status", value));
        self
    }

    pub fn with_order_status_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("order_status", value));
        self
    }

    pub fn with_order_status_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("order_status", value));
        self
    }
    pub fn with_order_status_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("order_status", value));
        self
    }

    pub fn with_order_status_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("order_status", value));
        self
    }

    pub fn with_order_status_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("order_status"));
        self
    }



    pub fn with_order_status_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("order_status"));
        self
    }


    pub fn order_by_order_status_asc(mut self) -> Self {
        self.query = self.query.order_asc("order_status");
        self
    }

    pub fn order_by_order_status_desc(mut self) -> Self {
        self.query = self.query.order_desc("order_status");
        self
    }

    pub fn order_by_order_status_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("order_status");
        self
    }

    pub fn order_by_order_status_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("order_status");
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
    pub fn filter_by_private_customer(mut self, value: impl EntityReference) -> Self {
        self.query = self.query.and_filter(Expr::eq("private_customer_id", value.entity_id_value()));
        self
    }

    pub fn with_private_customer_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "private_customer_id",
            <crate::PrivateCustomer as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("private_customer", selection));
        self
    }


    pub fn without_private_customer_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "private_customer_id",
            <crate::PrivateCustomer as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("private_customer", selection));
        self
    }


    pub fn have_private_customer(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("private_customer_id"));
        self
    }

    pub fn have_no_private_customer(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("private_customer_id"));
        self
    }


    pub fn group_by_private_customer(self) -> Self {
        self.group_by("private_customer_id")
    }

    pub fn group_by_private_customer_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("private_customer_id");
        request.query = request
            .query
            .project_expr(alias, Expr::column("private_customer_id"));
        request
    }

    pub fn group_by_private_customer_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("private_customer_id")
            .aggregate_with_function("private_customer_id", alias, function)
    }

    pub fn group_by_private_customer_with(mut self, request: impl Into<QuerySelection>) -> Self {
        self.query = self.query.group_by("private_customer_id");
        self.query_options.object_group_bys.push(ObjectGroupBy::new(
            "private_customer",
            "private_customer_id",
            request,
        ));
        self
    }

    pub fn group_by_private_customer_with_details(self) -> Self {
        self.group_by_private_customer_with_details_from(crate::Q::private_customers().unlimited())
    }

    pub fn group_by_private_customer_with_details_from(self, request: impl Into<QuerySelection>) -> Self {
        self.group_by_private_customer_with(request)
    }


    pub fn roll_up_to_private_customer(self) -> Self {
        self.roll_up_to_private_customer_with(crate::Q::private_customers().unlimited())
    }

    pub fn roll_up_to_private_customer_with(self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.with_private_customer_matching(selection.clone())
            .group_by_private_customer_with(selection)
    }

    pub fn count_private_customer(self) -> Self {
        self.count_private_customer_as("private_customer_count")
    }

    pub fn count_private_customer_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("private_customer_id", alias)
    }

    pub fn unselect_private_customer(mut self) -> Self {
        self.query.projection.retain(|field| field != "private_customer_id");
        self.query.relations.retain(|relation| relation.name != "private_customer");
        self
    }


    pub fn filter_by_corporate_customer(mut self, value: impl EntityReference) -> Self {
        self.query = self.query.and_filter(Expr::eq("corporate_customer_id", value.entity_id_value()));
        self
    }

    pub fn with_corporate_customer_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "corporate_customer_id",
            <crate::CorporateCustomer as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("corporate_customer", selection));
        self
    }


    pub fn without_corporate_customer_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "corporate_customer_id",
            <crate::CorporateCustomer as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("corporate_customer", selection));
        self
    }


    pub fn have_corporate_customer(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("corporate_customer_id"));
        self
    }

    pub fn have_no_corporate_customer(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("corporate_customer_id"));
        self
    }


    pub fn group_by_corporate_customer(self) -> Self {
        self.group_by("corporate_customer_id")
    }

    pub fn group_by_corporate_customer_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("corporate_customer_id");
        request.query = request
            .query
            .project_expr(alias, Expr::column("corporate_customer_id"));
        request
    }

    pub fn group_by_corporate_customer_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("corporate_customer_id")
            .aggregate_with_function("corporate_customer_id", alias, function)
    }

    pub fn group_by_corporate_customer_with(mut self, request: impl Into<QuerySelection>) -> Self {
        self.query = self.query.group_by("corporate_customer_id");
        self.query_options.object_group_bys.push(ObjectGroupBy::new(
            "corporate_customer",
            "corporate_customer_id",
            request,
        ));
        self
    }

    pub fn group_by_corporate_customer_with_details(self) -> Self {
        self.group_by_corporate_customer_with_details_from(crate::Q::corporate_customers().unlimited())
    }

    pub fn group_by_corporate_customer_with_details_from(self, request: impl Into<QuerySelection>) -> Self {
        self.group_by_corporate_customer_with(request)
    }


    pub fn roll_up_to_corporate_customer(self) -> Self {
        self.roll_up_to_corporate_customer_with(crate::Q::corporate_customers().unlimited())
    }

    pub fn roll_up_to_corporate_customer_with(self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.with_corporate_customer_matching(selection.clone())
            .group_by_corporate_customer_with(selection)
    }

    pub fn count_corporate_customer(self) -> Self {
        self.count_corporate_customer_as("corporate_customer_count")
    }

    pub fn count_corporate_customer_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("corporate_customer_id", alias)
    }

    pub fn unselect_corporate_customer(mut self) -> Self {
        self.query.projection.retain(|field| field != "corporate_customer_id");
        self.query.relations.retain(|relation| relation.name != "corporate_customer");
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
            <crate::AddressRecord as teaql_core::TeaqlEntity>::entity_descriptor(),
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
            <crate::AddressRecord as teaql_core::TeaqlEntity>::entity_descriptor(),
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
        self.group_by_origin_address_with_details_from(crate::Q::address_records().unlimited())
    }

    pub fn group_by_origin_address_with_details_from(self, request: impl Into<QuerySelection>) -> Self {
        self.group_by_origin_address_with(request)
    }


    pub fn roll_up_to_origin_address(self) -> Self {
        self.roll_up_to_origin_address_with(crate::Q::address_records().unlimited())
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


    pub fn filter_by_dest_address(mut self, value: impl EntityReference) -> Self {
        self.query = self.query.and_filter(Expr::eq("dest_address_id", value.entity_id_value()));
        self
    }

    pub fn with_dest_address_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "dest_address_id",
            <crate::AddressRecord as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("dest_address", selection));
        self
    }


    pub fn without_dest_address_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "dest_address_id",
            <crate::AddressRecord as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("dest_address", selection));
        self
    }


    pub fn have_dest_address(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("dest_address_id"));
        self
    }

    pub fn have_no_dest_address(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("dest_address_id"));
        self
    }


    pub fn group_by_dest_address(self) -> Self {
        self.group_by("dest_address_id")
    }

    pub fn group_by_dest_address_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("dest_address_id");
        request.query = request
            .query
            .project_expr(alias, Expr::column("dest_address_id"));
        request
    }

    pub fn group_by_dest_address_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("dest_address_id")
            .aggregate_with_function("dest_address_id", alias, function)
    }

    pub fn group_by_dest_address_with(mut self, request: impl Into<QuerySelection>) -> Self {
        self.query = self.query.group_by("dest_address_id");
        self.query_options.object_group_bys.push(ObjectGroupBy::new(
            "dest_address",
            "dest_address_id",
            request,
        ));
        self
    }

    pub fn group_by_dest_address_with_details(self) -> Self {
        self.group_by_dest_address_with_details_from(crate::Q::address_records().unlimited())
    }

    pub fn group_by_dest_address_with_details_from(self, request: impl Into<QuerySelection>) -> Self {
        self.group_by_dest_address_with(request)
    }


    pub fn roll_up_to_dest_address(self) -> Self {
        self.roll_up_to_dest_address_with(crate::Q::address_records().unlimited())
    }

    pub fn roll_up_to_dest_address_with(self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.with_dest_address_matching(selection.clone())
            .group_by_dest_address_with(selection)
    }

    pub fn count_dest_address(self) -> Self {
        self.count_dest_address_as("dest_address_count")
    }

    pub fn count_dest_address_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("dest_address_id", alias)
    }

    pub fn unselect_dest_address(mut self) -> Self {
        self.query.projection.retain(|field| field != "dest_address_id");
        self.query.relations.retain(|relation| relation.name != "dest_address");
        self
    }


    pub fn filter_by_assigned_vehicle(mut self, value: impl EntityReference) -> Self {
        self.query = self.query.and_filter(Expr::eq("assigned_vehicle_id", value.entity_id_value()));
        self
    }

    pub fn with_assigned_vehicle_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "assigned_vehicle_id",
            <crate::VehicleAsset as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("assigned_vehicle", selection));
        self
    }


    pub fn without_assigned_vehicle_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "assigned_vehicle_id",
            <crate::VehicleAsset as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "id",
        ));
        self.relation_filters.push(RelationFilter::new("assigned_vehicle", selection));
        self
    }


    pub fn have_assigned_vehicle(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("assigned_vehicle_id"));
        self
    }

    pub fn have_no_assigned_vehicle(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("assigned_vehicle_id"));
        self
    }


    pub fn group_by_assigned_vehicle(self) -> Self {
        self.group_by("assigned_vehicle_id")
    }

    pub fn group_by_assigned_vehicle_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("assigned_vehicle_id");
        request.query = request
            .query
            .project_expr(alias, Expr::column("assigned_vehicle_id"));
        request
    }

    pub fn group_by_assigned_vehicle_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("assigned_vehicle_id")
            .aggregate_with_function("assigned_vehicle_id", alias, function)
    }

    pub fn group_by_assigned_vehicle_with(mut self, request: impl Into<QuerySelection>) -> Self {
        self.query = self.query.group_by("assigned_vehicle_id");
        self.query_options.object_group_bys.push(ObjectGroupBy::new(
            "assigned_vehicle",
            "assigned_vehicle_id",
            request,
        ));
        self
    }

    pub fn group_by_assigned_vehicle_with_details(self) -> Self {
        self.group_by_assigned_vehicle_with_details_from(crate::Q::vehicle_assets().unlimited())
    }

    pub fn group_by_assigned_vehicle_with_details_from(self, request: impl Into<QuerySelection>) -> Self {
        self.group_by_assigned_vehicle_with(request)
    }


    pub fn roll_up_to_assigned_vehicle(self) -> Self {
        self.roll_up_to_assigned_vehicle_with(crate::Q::vehicle_assets().unlimited())
    }

    pub fn roll_up_to_assigned_vehicle_with(self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.with_assigned_vehicle_matching(selection.clone())
            .group_by_assigned_vehicle_with(selection)
    }

    pub fn count_assigned_vehicle(self) -> Self {
        self.count_assigned_vehicle_as("assigned_vehicle_count")
    }

    pub fn count_assigned_vehicle_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("assigned_vehicle_id", alias)
    }

    pub fn unselect_assigned_vehicle(mut self) -> Self {
        self.query.projection.retain(|field| field != "assigned_vehicle_id");
        self.query.relations.retain(|relation| relation.name != "assigned_vehicle");
        self
    }
    pub fn select_private_customer(mut self) -> Self {
        self.query = self.query.relation("private_customer");
        self
    }

    pub fn select_private_customer_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("private_customer", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("private_customer", selection));
        self
}

    pub fn facet_by_private_customer_as(self, facet_name: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.facet_by_private_customer_as_with_options(facet_name, request, true)
    }

    pub fn facet_by_private_customer_as_with_options(
        mut self,
        facet_name: impl Into<String>,
        request: impl Into<QuerySelection>,
        include_all_facets: bool,
    ) -> Self {
        self.query_options.facets.push(FacetRequest::new(
            facet_name,
            "private_customer",
            request,
            include_all_facets,
        ));
        self
    }

    pub fn select_corporate_customer(mut self) -> Self {
        self.query = self.query.relation("corporate_customer");
        self
    }

    pub fn select_corporate_customer_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("corporate_customer", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("corporate_customer", selection));
        self
}

    pub fn facet_by_corporate_customer_as(self, facet_name: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.facet_by_corporate_customer_as_with_options(facet_name, request, true)
    }

    pub fn facet_by_corporate_customer_as_with_options(
        mut self,
        facet_name: impl Into<String>,
        request: impl Into<QuerySelection>,
        include_all_facets: bool,
    ) -> Self {
        self.query_options.facets.push(FacetRequest::new(
            facet_name,
            "corporate_customer",
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

    pub fn select_dest_address(mut self) -> Self {
        self.query = self.query.relation("dest_address");
        self
    }

    pub fn select_dest_address_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("dest_address", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("dest_address", selection));
        self
}

    pub fn facet_by_dest_address_as(self, facet_name: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.facet_by_dest_address_as_with_options(facet_name, request, true)
    }

    pub fn facet_by_dest_address_as_with_options(
        mut self,
        facet_name: impl Into<String>,
        request: impl Into<QuerySelection>,
        include_all_facets: bool,
    ) -> Self {
        self.query_options.facets.push(FacetRequest::new(
            facet_name,
            "dest_address",
            request,
            include_all_facets,
        ));
        self
    }

    pub fn select_assigned_vehicle(mut self) -> Self {
        self.query = self.query.relation("assigned_vehicle");
        self
    }

    pub fn select_assigned_vehicle_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("assigned_vehicle", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("assigned_vehicle", selection));
        self
}

    pub fn facet_by_assigned_vehicle_as(self, facet_name: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.facet_by_assigned_vehicle_as_with_options(facet_name, request, true)
    }

    pub fn facet_by_assigned_vehicle_as_with_options(
        mut self,
        facet_name: impl Into<String>,
        request: impl Into<QuerySelection>,
        include_all_facets: bool,
    ) -> Self {
        self.query_options.facets.push(FacetRequest::new(
            facet_name,
            "assigned_vehicle",
            request,
            include_all_facets,
        ));
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

    pub fn have_service_configs(self) -> Self {
        self.with_service_config_list_matching(SelectQuery::new("ServiceConfig"))
    }

    pub fn have_no_service_configs(self) -> Self {
        self.without_service_config_list_matching(SelectQuery::new("ServiceConfig"))
    }

    pub fn with_service_config_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::ServiceConfig as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "move_order_id",
        ));
        self.relation_filters.push(RelationFilter::new("service_config_list", selection));
        self
    }

    pub fn without_service_config_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::ServiceConfig as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "move_order_id",
        ));
        self.relation_filters.push(RelationFilter::new("service_config_list", selection));
        self
    }

    pub fn select_service_config_list(mut self) -> Self {
        self.query = self.query.relation("service_config_list");
        self
    }

    pub fn select_service_config_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("service_config_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("service_config_list", selection));
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
            "move_order_id",
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
            "move_order_id",
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
    pub fn min_update_time_of_route_plans(self) -> Self {
        self.min_update_time_of_route_plans_as("min_update_time_of_route_plans", crate::Q::route_plans().unlimited())
    }

    pub fn min_update_time_of_route_plans_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_route_plans_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_route_plans(self) -> Self {
        self.max_update_time_of_route_plans_as("max_update_time_of_route_plans", crate::Q::route_plans().unlimited())
    }

    pub fn max_update_time_of_route_plans_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_route_plans_as(alias, request.into().into_query().max("update_time", "max_update_time"))
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
    pub fn min_update_time_of_time_slots(self) -> Self {
        self.min_update_time_of_time_slots_as("min_update_time_of_time_slots", crate::Q::time_slots().unlimited())
    }

    pub fn min_update_time_of_time_slots_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_time_slots_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_time_slots(self) -> Self {
        self.max_update_time_of_time_slots_as("max_update_time_of_time_slots", crate::Q::time_slots().unlimited())
    }

    pub fn max_update_time_of_time_slots_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_time_slots_as(alias, request.into().into_query().max("update_time", "max_update_time"))
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
    pub fn min_update_time_of_fulfillment_events(self) -> Self {
        self.min_update_time_of_fulfillment_events_as("min_update_time_of_fulfillment_events", crate::Q::fulfillment_events().unlimited())
    }

    pub fn min_update_time_of_fulfillment_events_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_fulfillment_events_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_fulfillment_events(self) -> Self {
        self.max_update_time_of_fulfillment_events_as("max_update_time_of_fulfillment_events", crate::Q::fulfillment_events().unlimited())
    }

    pub fn max_update_time_of_fulfillment_events_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_fulfillment_events_as(alias, request.into().into_query().max("update_time", "max_update_time"))
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
    pub fn min_update_time_of_job_assignments(self) -> Self {
        self.min_update_time_of_job_assignments_as("min_update_time_of_job_assignments", crate::Q::job_assignments().unlimited())
    }

    pub fn min_update_time_of_job_assignments_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_job_assignments_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_job_assignments(self) -> Self {
        self.max_update_time_of_job_assignments_as("max_update_time_of_job_assignments", crate::Q::job_assignments().unlimited())
    }

    pub fn max_update_time_of_job_assignments_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_job_assignments_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }

    pub fn count_service_configs(self) -> Self {
        self.count_service_configs_as("count_service_configs")
    }

    pub fn count_service_configs_as(self, alias: impl Into<String>) -> Self {
        self.count_service_configs_with(alias, crate::Q::service_configs().unlimited())
    }

    pub fn count_service_configs_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "service_config_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_service_configs(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_configs_as("refinements", request)
    }

    pub fn stats_from_service_configs_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "service_config_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_service_configs_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_configs(request)
    }


    pub fn sum_agreed_price_of_service_configs(self) -> Self {
        self.sum_agreed_price_of_service_configs_as("sum_agreed_price_of_service_configs", crate::Q::service_configs().unlimited())
    }

    pub fn sum_agreed_price_of_service_configs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_configs_as(alias, request.into().into_query().sum("agreed_price", "sum_agreed_price"))
    }
    pub fn min_agreed_price_of_service_configs(self) -> Self {
        self.min_agreed_price_of_service_configs_as("min_agreed_price_of_service_configs", crate::Q::service_configs().unlimited())
    }

    pub fn min_agreed_price_of_service_configs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_configs_as(alias, request.into().into_query().min("agreed_price", "min_agreed_price"))
    }
    pub fn max_agreed_price_of_service_configs(self) -> Self {
        self.max_agreed_price_of_service_configs_as("max_agreed_price_of_service_configs", crate::Q::service_configs().unlimited())
    }

    pub fn max_agreed_price_of_service_configs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_configs_as(alias, request.into().into_query().max("agreed_price", "max_agreed_price"))
    }
    pub fn avg_agreed_price_of_service_configs(self) -> Self {
        self.avg_agreed_price_of_service_configs_as("avg_agreed_price_of_service_configs", crate::Q::service_configs().unlimited())
    }

    pub fn avg_agreed_price_of_service_configs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_configs_as(alias, request.into().into_query().avg("agreed_price", "avg_agreed_price"))
    }
    pub fn standard_deviation_agreed_price_of_service_configs(self) -> Self {
        self.standard_deviation_agreed_price_of_service_configs_as("standard_deviation_agreed_price_of_service_configs", crate::Q::service_configs().unlimited())
    }

    pub fn standard_deviation_agreed_price_of_service_configs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_configs_as(alias, request.into().into_query().stddev("agreed_price", "stdDev_agreed_price"))
    }
    pub fn square_root_of_population_standard_deviation_agreed_price_of_service_configs(self) -> Self {
        self.square_root_of_population_standard_deviation_agreed_price_of_service_configs_as("square_root_of_population_standard_deviation_agreed_price_of_service_configs", crate::Q::service_configs().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_agreed_price_of_service_configs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_configs_as(alias, request.into().into_query().stddev_pop("agreed_price", "stdDevPop_agreed_price"))
    }
    pub fn sample_variance_agreed_price_of_service_configs(self) -> Self {
        self.sample_variance_agreed_price_of_service_configs_as("sample_variance_agreed_price_of_service_configs", crate::Q::service_configs().unlimited())
    }

    pub fn sample_variance_agreed_price_of_service_configs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_configs_as(alias, request.into().into_query().var_samp("agreed_price", "varSamp_agreed_price"))
    }
    pub fn sample_population_variance_agreed_price_of_service_configs(self) -> Self {
        self.sample_population_variance_agreed_price_of_service_configs_as("sample_population_variance_agreed_price_of_service_configs", crate::Q::service_configs().unlimited())
    }

    pub fn sample_population_variance_agreed_price_of_service_configs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_configs_as(alias, request.into().into_query().var_pop("agreed_price", "varPop_agreed_price"))
    }
    pub fn min_create_time_of_service_configs(self) -> Self {
        self.min_create_time_of_service_configs_as("min_create_time_of_service_configs", crate::Q::service_configs().unlimited())
    }

    pub fn min_create_time_of_service_configs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_configs_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_service_configs(self) -> Self {
        self.max_create_time_of_service_configs_as("max_create_time_of_service_configs", crate::Q::service_configs().unlimited())
    }

    pub fn max_create_time_of_service_configs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_configs_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_service_configs(self) -> Self {
        self.min_update_time_of_service_configs_as("min_update_time_of_service_configs", crate::Q::service_configs().unlimited())
    }

    pub fn min_update_time_of_service_configs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_configs_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_service_configs(self) -> Self {
        self.max_update_time_of_service_configs_as("max_update_time_of_service_configs", crate::Q::service_configs().unlimited())
    }

    pub fn max_update_time_of_service_configs_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_service_configs_as(alias, request.into().into_query().max("update_time", "max_update_time"))
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


    pub fn sum_box_count_of_box_rentals(self) -> Self {
        self.sum_box_count_of_box_rentals_as("sum_box_count_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn sum_box_count_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().sum("box_count", "sum_box_count"))
    }
    pub fn min_box_count_of_box_rentals(self) -> Self {
        self.min_box_count_of_box_rentals_as("min_box_count_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn min_box_count_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().min("box_count", "min_box_count"))
    }
    pub fn max_box_count_of_box_rentals(self) -> Self {
        self.max_box_count_of_box_rentals_as("max_box_count_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn max_box_count_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().max("box_count", "max_box_count"))
    }
    pub fn avg_box_count_of_box_rentals(self) -> Self {
        self.avg_box_count_of_box_rentals_as("avg_box_count_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn avg_box_count_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().avg("box_count", "avg_box_count"))
    }
    pub fn standard_deviation_box_count_of_box_rentals(self) -> Self {
        self.standard_deviation_box_count_of_box_rentals_as("standard_deviation_box_count_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn standard_deviation_box_count_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().stddev("box_count", "stdDev_box_count"))
    }
    pub fn square_root_of_population_standard_deviation_box_count_of_box_rentals(self) -> Self {
        self.square_root_of_population_standard_deviation_box_count_of_box_rentals_as("square_root_of_population_standard_deviation_box_count_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_box_count_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().stddev_pop("box_count", "stdDevPop_box_count"))
    }
    pub fn sample_variance_box_count_of_box_rentals(self) -> Self {
        self.sample_variance_box_count_of_box_rentals_as("sample_variance_box_count_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn sample_variance_box_count_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().var_samp("box_count", "varSamp_box_count"))
    }
    pub fn sample_population_variance_box_count_of_box_rentals(self) -> Self {
        self.sample_population_variance_box_count_of_box_rentals_as("sample_population_variance_box_count_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn sample_population_variance_box_count_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().var_pop("box_count", "varPop_box_count"))
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
    pub fn min_update_time_of_box_rentals(self) -> Self {
        self.min_update_time_of_box_rentals_as("min_update_time_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn min_update_time_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_box_rentals(self) -> Self {
        self.max_update_time_of_box_rentals_as("max_update_time_of_box_rentals", crate::Q::box_rentals().unlimited())
    }

    pub fn max_update_time_of_box_rentals_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_box_rentals_as(alias, request.into().into_query().max("update_time", "max_update_time"))
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


    pub fn min_conversion_date_of_conversion_metrics(self) -> Self {
        self.min_conversion_date_of_conversion_metrics_as("min_conversion_date_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn min_conversion_date_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().min("conversion_date", "min_conversion_date"))
    }
    pub fn max_conversion_date_of_conversion_metrics(self) -> Self {
        self.max_conversion_date_of_conversion_metrics_as("max_conversion_date_of_conversion_metrics", crate::Q::conversion_metrics().unlimited())
    }

    pub fn max_conversion_date_of_conversion_metrics_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_conversion_metrics_as(alias, request.into().into_query().max("conversion_date", "max_conversion_date"))
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


    pub fn sum_total_due_of_invoice_documents(self) -> Self {
        self.sum_total_due_of_invoice_documents_as("sum_total_due_of_invoice_documents", crate::Q::invoice_documents().unlimited())
    }

    pub fn sum_total_due_of_invoice_documents_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_invoice_documents_as(alias, request.into().into_query().sum("total_due", "sum_total_due"))
    }
    pub fn min_total_due_of_invoice_documents(self) -> Self {
        self.min_total_due_of_invoice_documents_as("min_total_due_of_invoice_documents", crate::Q::invoice_documents().unlimited())
    }

    pub fn min_total_due_of_invoice_documents_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_invoice_documents_as(alias, request.into().into_query().min("total_due", "min_total_due"))
    }
    pub fn max_total_due_of_invoice_documents(self) -> Self {
        self.max_total_due_of_invoice_documents_as("max_total_due_of_invoice_documents", crate::Q::invoice_documents().unlimited())
    }

    pub fn max_total_due_of_invoice_documents_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_invoice_documents_as(alias, request.into().into_query().max("total_due", "max_total_due"))
    }
    pub fn avg_total_due_of_invoice_documents(self) -> Self {
        self.avg_total_due_of_invoice_documents_as("avg_total_due_of_invoice_documents", crate::Q::invoice_documents().unlimited())
    }

    pub fn avg_total_due_of_invoice_documents_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_invoice_documents_as(alias, request.into().into_query().avg("total_due", "avg_total_due"))
    }
    pub fn standard_deviation_total_due_of_invoice_documents(self) -> Self {
        self.standard_deviation_total_due_of_invoice_documents_as("standard_deviation_total_due_of_invoice_documents", crate::Q::invoice_documents().unlimited())
    }

    pub fn standard_deviation_total_due_of_invoice_documents_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_invoice_documents_as(alias, request.into().into_query().stddev("total_due", "stdDev_total_due"))
    }
    pub fn square_root_of_population_standard_deviation_total_due_of_invoice_documents(self) -> Self {
        self.square_root_of_population_standard_deviation_total_due_of_invoice_documents_as("square_root_of_population_standard_deviation_total_due_of_invoice_documents", crate::Q::invoice_documents().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_total_due_of_invoice_documents_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_invoice_documents_as(alias, request.into().into_query().stddev_pop("total_due", "stdDevPop_total_due"))
    }
    pub fn sample_variance_total_due_of_invoice_documents(self) -> Self {
        self.sample_variance_total_due_of_invoice_documents_as("sample_variance_total_due_of_invoice_documents", crate::Q::invoice_documents().unlimited())
    }

    pub fn sample_variance_total_due_of_invoice_documents_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_invoice_documents_as(alias, request.into().into_query().var_samp("total_due", "varSamp_total_due"))
    }
    pub fn sample_population_variance_total_due_of_invoice_documents(self) -> Self {
        self.sample_population_variance_total_due_of_invoice_documents_as("sample_population_variance_total_due_of_invoice_documents", crate::Q::invoice_documents().unlimited())
    }

    pub fn sample_population_variance_total_due_of_invoice_documents_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_invoice_documents_as(alias, request.into().into_query().var_pop("total_due", "varPop_total_due"))
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
    pub fn min_update_time_of_invoice_documents(self) -> Self {
        self.min_update_time_of_invoice_documents_as("min_update_time_of_invoice_documents", crate::Q::invoice_documents().unlimited())
    }

    pub fn min_update_time_of_invoice_documents_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_invoice_documents_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_invoice_documents(self) -> Self {
        self.max_update_time_of_invoice_documents_as("max_update_time_of_invoice_documents", crate::Q::invoice_documents().unlimited())
    }

    pub fn max_update_time_of_invoice_documents_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_invoice_documents_as(alias, request.into().into_query().max("update_time", "max_update_time"))
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


    pub fn sum_amount_paid_of_payment_records(self) -> Self {
        self.sum_amount_paid_of_payment_records_as("sum_amount_paid_of_payment_records", crate::Q::payment_records().unlimited())
    }

    pub fn sum_amount_paid_of_payment_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payment_records_as(alias, request.into().into_query().sum("amount_paid", "sum_amount_paid"))
    }
    pub fn min_amount_paid_of_payment_records(self) -> Self {
        self.min_amount_paid_of_payment_records_as("min_amount_paid_of_payment_records", crate::Q::payment_records().unlimited())
    }

    pub fn min_amount_paid_of_payment_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payment_records_as(alias, request.into().into_query().min("amount_paid", "min_amount_paid"))
    }
    pub fn max_amount_paid_of_payment_records(self) -> Self {
        self.max_amount_paid_of_payment_records_as("max_amount_paid_of_payment_records", crate::Q::payment_records().unlimited())
    }

    pub fn max_amount_paid_of_payment_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payment_records_as(alias, request.into().into_query().max("amount_paid", "max_amount_paid"))
    }
    pub fn avg_amount_paid_of_payment_records(self) -> Self {
        self.avg_amount_paid_of_payment_records_as("avg_amount_paid_of_payment_records", crate::Q::payment_records().unlimited())
    }

    pub fn avg_amount_paid_of_payment_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payment_records_as(alias, request.into().into_query().avg("amount_paid", "avg_amount_paid"))
    }
    pub fn standard_deviation_amount_paid_of_payment_records(self) -> Self {
        self.standard_deviation_amount_paid_of_payment_records_as("standard_deviation_amount_paid_of_payment_records", crate::Q::payment_records().unlimited())
    }

    pub fn standard_deviation_amount_paid_of_payment_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payment_records_as(alias, request.into().into_query().stddev("amount_paid", "stdDev_amount_paid"))
    }
    pub fn square_root_of_population_standard_deviation_amount_paid_of_payment_records(self) -> Self {
        self.square_root_of_population_standard_deviation_amount_paid_of_payment_records_as("square_root_of_population_standard_deviation_amount_paid_of_payment_records", crate::Q::payment_records().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_amount_paid_of_payment_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payment_records_as(alias, request.into().into_query().stddev_pop("amount_paid", "stdDevPop_amount_paid"))
    }
    pub fn sample_variance_amount_paid_of_payment_records(self) -> Self {
        self.sample_variance_amount_paid_of_payment_records_as("sample_variance_amount_paid_of_payment_records", crate::Q::payment_records().unlimited())
    }

    pub fn sample_variance_amount_paid_of_payment_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payment_records_as(alias, request.into().into_query().var_samp("amount_paid", "varSamp_amount_paid"))
    }
    pub fn sample_population_variance_amount_paid_of_payment_records(self) -> Self {
        self.sample_population_variance_amount_paid_of_payment_records_as("sample_population_variance_amount_paid_of_payment_records", crate::Q::payment_records().unlimited())
    }

    pub fn sample_population_variance_amount_paid_of_payment_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payment_records_as(alias, request.into().into_query().var_pop("amount_paid", "varPop_amount_paid"))
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
    pub fn min_update_time_of_payment_records(self) -> Self {
        self.min_update_time_of_payment_records_as("min_update_time_of_payment_records", crate::Q::payment_records().unlimited())
    }

    pub fn min_update_time_of_payment_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payment_records_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_payment_records(self) -> Self {
        self.max_update_time_of_payment_records_as("max_update_time_of_payment_records", crate::Q::payment_records().unlimited())
    }

    pub fn max_update_time_of_payment_records_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_payment_records_as(alias, request.into().into_query().max("update_time", "max_update_time"))
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
