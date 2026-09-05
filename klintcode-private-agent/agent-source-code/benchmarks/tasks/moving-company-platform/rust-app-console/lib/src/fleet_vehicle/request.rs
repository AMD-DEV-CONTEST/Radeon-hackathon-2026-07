use std::marker::PhantomData;

use serde_json::Value as JsonValue;
use teaql_core::{Aggregate, AggregateFunction, EntityDescriptor, Expr, Record, SelectQuery, SmartList};
use teaql_runtime::{DataServiceError, RuntimeError};

use crate::request_support::*;

impl EntityReference for crate::FleetVehicle {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(&self)
    }
}

impl EntityReference for &crate::FleetVehicle {
    fn entity_id_value(self) -> teaql_core::Value {
        teaql_core::IdentifiableEntity::id_value(self)
    }
}

// ⛔ AI agents: DO NOT read this file for API discovery. Instead run: cargo teaql --input modeling/MODEL.xml rust-assist-query/fleet_vehicle
#[derive(Debug)]
pub struct FleetVehicleRequest<R = crate::FleetVehicle> {
    query: SelectQuery,
    relation_selections: Vec<RelationSelection>,
    relation_filters: Vec<RelationFilter>,
    child_enhancements: Vec<QuerySelection>,
    query_options: QueryOptions,
    marker: PhantomData<R>,
}

impl<R> Clone for FleetVehicleRequest<R> {
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

impl<R> FleetVehicleRequest<R> {
    pub(crate) fn new() -> Self {
        Self {
            query: SelectQuery::new("FleetVehicle")
                .project("id")
                .project("version"),
            relation_selections: Vec::new(),
            relation_filters: Vec::new(),
            child_enhancements: Vec::new(),
            query_options: QueryOptions::default(),
            marker: PhantomData,
        }
    }

    pub fn return_type<T>(self) -> FleetVehicleRequest<T> {
        FleetVehicleRequest {
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::FleetVehicleRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
        R: teaql_core::Entity,
    {
        let repository = ctx
            .fleet_vehicle_repository()
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
    ) -> Result<Vec<teaql_data_service::StreamChunk>, TeaqlDataServiceError<C::FleetVehicleRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .fleet_vehicle_repository()
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::FleetVehicleRepository<'a>>>
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
    ) -> Result<Option<R>, TeaqlDataServiceError<C::FleetVehicleRepository<'a>>>
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
    ) -> Result<SmartList<R>, TeaqlDataServiceError<C::FleetVehicleRepository<'a>>>
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
    ) -> Result<u64, TeaqlDataServiceError<C::FleetVehicleRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .fleet_vehicle_repository()
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
            .ok_or_else(|| DataServiceError::Runtime(RuntimeError::Graph(format!("count result for FleetVehicle is missing or not numeric"))))
    }

    pub(crate) async fn _execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, TeaqlDataServiceError<C::FleetVehicleRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .fleet_vehicle_repository()
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
    ) -> Result<SmartList<Record>, TeaqlDataServiceError<C::FleetVehicleRepository<'a>>>
    where
        C: TeaqlRepositoryProvider + ?Sized,
    {
        let repository = ctx
            .fleet_vehicle_repository()
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
    ) -> Result<Option<Record>, TeaqlDataServiceError<C::FleetVehicleRepository<'a>>>
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
            "vehicle_registration" => Some("vehicle_registration"),
            "vehicle_model" => Some("vehicle_model"),
            "capacity_tons" => Some("capacity_tons"),
            "create_time" => Some("create_time"),
            "version" => Some("version"),
            "company_profile" | "company_profile_id" => Some("company_profile_id"),
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
            "insurance_policy_list" => {
                self.with_insurance_policy_list_matching(
                    crate::Q::insurance_policies_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "move_order_list" => {
                self.with_move_order_list_matching(
                    crate::Q::move_orders_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "equipment_item_list" => {
                self.with_equipment_item_list_matching(
                    crate::Q::equipment_items_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "consumable_item_list" => {
                self.with_consumable_item_list_matching(
                    crate::Q::consumable_items_minimal()
                        .apply_dynamic_json_filter(tail, value),
                )
            }
            "maintenance_schedule_list" => {
                self.with_maintenance_schedule_list_matching(
                    crate::Q::maintenance_schedules_minimal()
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
        self.query = self.query.project("vehicle_registration");
        self.query = self.query.project("vehicle_model");
        self.query = self.query.project("capacity_tons");
        self.query = self.query.project("create_time");
        self.query = self.query.project("version");
        self.query = self.query.project("company_profile_id");
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
        request
    }

    pub fn select_children(self) -> Self {
        let mut request = self.select_all();
        request = request.select_insurance_policy_list();
        request = request.select_move_order_list();
        request = request.select_equipment_item_list();
        request = request.select_consumable_item_list();
        request = request.select_maintenance_schedule_list();
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


    pub fn select_vehicle_registration(mut self) -> Self {
        self.query = self.query.project("vehicle_registration");
        self
    }

    pub fn project_vehicle_registration(self) -> Self {
        self.select_vehicle_registration()
    }

    pub fn select_vehicle_registration_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_vehicle_registration_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_vehicle_registration_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("vehicle_registration", raw_sql_segment));
        self
    }

    pub fn group_by_vehicle_registration(self) -> Self {
        self.group_by("vehicle_registration")
    }

    pub fn group_by_vehicle_registration_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("vehicle_registration");
        request.query = request
            .query
            .project_expr(alias, Expr::column("vehicle_registration"));
        request
    }

    pub fn group_by_vehicle_registration_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("vehicle_registration")
            .aggregate_with_function("vehicle_registration", alias, function)
    }

    pub fn count_vehicle_registration(self) -> Self {
        self.count_vehicle_registration_as("vehicle_registration_count")
    }

    pub fn count_vehicle_registration_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("vehicle_registration", alias)
    }

    pub fn sum_vehicle_registration(self) -> Self {
        self.sum_vehicle_registration_as("sum_vehicle_registration")
    }

    pub fn sum_vehicle_registration_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("vehicle_registration", alias)
    }

    pub fn avg_vehicle_registration(self) -> Self {
        self.avg_vehicle_registration_as("avg_vehicle_registration")
    }

    pub fn avg_vehicle_registration_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("vehicle_registration", alias)
    }

    pub fn min_vehicle_registration(self) -> Self {
        self.min_vehicle_registration_as("min_vehicle_registration")
    }

    pub fn min_vehicle_registration_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("vehicle_registration", alias)
    }

    pub fn max_vehicle_registration(self) -> Self {
        self.max_vehicle_registration_as("max_vehicle_registration")
    }

    pub fn max_vehicle_registration_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("vehicle_registration", alias)
    }

    pub fn unselect_vehicle_registration(mut self) -> Self {
        self.query.projection.retain(|field| field != "vehicle_registration");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "vehicle_registration");
        self
    }


    pub fn with_vehicle_registration(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "vehicle_registration",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_vehicle_registration_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "vehicle_registration",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_vehicle_registration_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("vehicle_registration", value));
        self
    }



    pub fn with_vehicle_registration_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("vehicle_registration", value));
        self
    }

    pub fn with_vehicle_registration_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("vehicle_registration", value));
        self
    }

    pub fn with_vehicle_registration_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("vehicle_registration", value));
        self
    }

    pub fn with_vehicle_registration_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("vehicle_registration", value));
        self
    }

    pub fn with_vehicle_registration_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("vehicle_registration", value));
        self
    }

    pub fn with_vehicle_registration_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("vehicle_registration", lower, upper));
        self
    }

    pub fn with_vehicle_registration_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "vehicle_registration",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_vehicle_registration_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "vehicle_registration",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_vehicle_registration_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "vehicle_registration",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_vehicle_registration_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("vehicle_registration", value));
        self
    }

    pub fn with_vehicle_registration_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("vehicle_registration", value));
        self
    }

    pub fn with_vehicle_registration_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("vehicle_registration", value));
        self
    }

    pub fn with_vehicle_registration_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("vehicle_registration", value));
        self
    }

    pub fn with_vehicle_registration_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("vehicle_registration", value));
        self
    }

    pub fn with_vehicle_registration_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("vehicle_registration", value));
        self
    }

    pub fn with_vehicle_registration_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("vehicle_registration", value));
        self
    }
    pub fn with_vehicle_registration_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("vehicle_registration", value));
        self
    }

    pub fn with_vehicle_registration_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("vehicle_registration", value));
        self
    }

    pub fn with_vehicle_registration_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("vehicle_registration"));
        self
    }



    pub fn with_vehicle_registration_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("vehicle_registration"));
        self
    }


    pub fn order_by_vehicle_registration_asc(mut self) -> Self {
        self.query = self.query.order_asc("vehicle_registration");
        self
    }

    pub fn order_by_vehicle_registration_desc(mut self) -> Self {
        self.query = self.query.order_desc("vehicle_registration");
        self
    }

    pub fn order_by_vehicle_registration_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("vehicle_registration");
        self
    }

    pub fn order_by_vehicle_registration_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("vehicle_registration");
        self
    }


    pub fn select_vehicle_model(mut self) -> Self {
        self.query = self.query.project("vehicle_model");
        self
    }

    pub fn project_vehicle_model(self) -> Self {
        self.select_vehicle_model()
    }

    pub fn select_vehicle_model_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_vehicle_model_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_vehicle_model_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("vehicle_model", raw_sql_segment));
        self
    }

    pub fn group_by_vehicle_model(self) -> Self {
        self.group_by("vehicle_model")
    }

    pub fn group_by_vehicle_model_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("vehicle_model");
        request.query = request
            .query
            .project_expr(alias, Expr::column("vehicle_model"));
        request
    }

    pub fn group_by_vehicle_model_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("vehicle_model")
            .aggregate_with_function("vehicle_model", alias, function)
    }

    pub fn count_vehicle_model(self) -> Self {
        self.count_vehicle_model_as("vehicle_model_count")
    }

    pub fn count_vehicle_model_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("vehicle_model", alias)
    }

    pub fn sum_vehicle_model(self) -> Self {
        self.sum_vehicle_model_as("sum_vehicle_model")
    }

    pub fn sum_vehicle_model_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("vehicle_model", alias)
    }

    pub fn avg_vehicle_model(self) -> Self {
        self.avg_vehicle_model_as("avg_vehicle_model")
    }

    pub fn avg_vehicle_model_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("vehicle_model", alias)
    }

    pub fn min_vehicle_model(self) -> Self {
        self.min_vehicle_model_as("min_vehicle_model")
    }

    pub fn min_vehicle_model_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("vehicle_model", alias)
    }

    pub fn max_vehicle_model(self) -> Self {
        self.max_vehicle_model_as("max_vehicle_model")
    }

    pub fn max_vehicle_model_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("vehicle_model", alias)
    }

    pub fn unselect_vehicle_model(mut self) -> Self {
        self.query.projection.retain(|field| field != "vehicle_model");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "vehicle_model");
        self
    }


    pub fn with_vehicle_model(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "vehicle_model",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_vehicle_model_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "vehicle_model",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_vehicle_model_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("vehicle_model", value));
        self
    }



    pub fn with_vehicle_model_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("vehicle_model", value));
        self
    }

    pub fn with_vehicle_model_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("vehicle_model", value));
        self
    }

    pub fn with_vehicle_model_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("vehicle_model", value));
        self
    }

    pub fn with_vehicle_model_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("vehicle_model", value));
        self
    }

    pub fn with_vehicle_model_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("vehicle_model", value));
        self
    }

    pub fn with_vehicle_model_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("vehicle_model", lower, upper));
        self
    }

    pub fn with_vehicle_model_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "vehicle_model",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_vehicle_model_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "vehicle_model",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_vehicle_model_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "vehicle_model",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_vehicle_model_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::contain("vehicle_model", value));
        self
    }

    pub fn with_vehicle_model_not_containing(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_contain("vehicle_model", value));
        self
    }

    pub fn with_vehicle_model_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::begin_with("vehicle_model", value));
        self
    }

    pub fn with_vehicle_model_not_starting_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_begin_with("vehicle_model", value));
        self
    }

    pub fn with_vehicle_model_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::end_with("vehicle_model", value));
        self
    }

    pub fn with_vehicle_model_not_ending_with(mut self, value: impl Into<String>) -> Self {
        self.query = self.query.and_filter(Expr::not_end_with("vehicle_model", value));
        self
    }

    pub fn with_vehicle_model_sounding_like(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::sound_like("vehicle_model", value));
        self
    }
    pub fn with_vehicle_model_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("vehicle_model", value));
        self
    }

    pub fn with_vehicle_model_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("vehicle_model", value));
        self
    }

    pub fn with_vehicle_model_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("vehicle_model"));
        self
    }



    pub fn with_vehicle_model_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("vehicle_model"));
        self
    }


    pub fn order_by_vehicle_model_asc(mut self) -> Self {
        self.query = self.query.order_asc("vehicle_model");
        self
    }

    pub fn order_by_vehicle_model_desc(mut self) -> Self {
        self.query = self.query.order_desc("vehicle_model");
        self
    }

    pub fn order_by_vehicle_model_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("vehicle_model");
        self
    }

    pub fn order_by_vehicle_model_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("vehicle_model");
        self
    }


    pub fn select_capacity_tons(mut self) -> Self {
        self.query = self.query.project("capacity_tons");
        self
    }

    pub fn project_capacity_tons(self) -> Self {
        self.select_capacity_tons()
    }

    pub fn select_capacity_tons_raw(self, raw_sql_segment: impl Into<String>) -> Self {
        self.select_capacity_tons_unsafe_raw(UnsafeRawSqlSegment::trusted(raw_sql_segment))
    }

    pub fn select_capacity_tons_unsafe_raw(mut self, raw_sql_segment: UnsafeRawSqlSegment) -> Self {
        self.query_options
            .raw_projections
            .push(RawProjection::new("capacity_tons", raw_sql_segment));
        self
    }

    pub fn select_capacity_tons_with_function(self, function: AggregateFunction) -> Self {
        self.select_capacity_tons_as_with_function("capacity_tons", function)
    }

    pub fn select_capacity_tons_as_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.aggregate_with_function("capacity_tons", alias, function)
    }

    pub fn group_by_capacity_tons(self) -> Self {
        self.group_by("capacity_tons")
    }

    pub fn group_by_capacity_tons_as(self, alias: impl Into<String>) -> Self {
        let alias = alias.into();
        let mut request = self.group_by("capacity_tons");
        request.query = request
            .query
            .project_expr(alias, Expr::column("capacity_tons"));
        request
    }

    pub fn group_by_capacity_tons_with_function(
        self,
        alias: impl Into<String>,
        function: AggregateFunction,
    ) -> Self {
        self.group_by("capacity_tons")
            .aggregate_with_function("capacity_tons", alias, function)
    }

    pub fn count_capacity_tons(self) -> Self {
        self.count_capacity_tons_as("capacity_tons_count")
    }

    pub fn count_capacity_tons_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_count_field("capacity_tons", alias)
    }

    pub fn sum_capacity_tons(self) -> Self {
        self.sum_capacity_tons_as("sum_capacity_tons")
    }

    pub fn sum_capacity_tons_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_sum("capacity_tons", alias)
    }

    pub fn avg_capacity_tons(self) -> Self {
        self.avg_capacity_tons_as("avg_capacity_tons")
    }

    pub fn avg_capacity_tons_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_avg("capacity_tons", alias)
    }

    pub fn min_capacity_tons(self) -> Self {
        self.min_capacity_tons_as("min_capacity_tons")
    }

    pub fn min_capacity_tons_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_min("capacity_tons", alias)
    }

    pub fn max_capacity_tons(self) -> Self {
        self.max_capacity_tons_as("max_capacity_tons")
    }

    pub fn max_capacity_tons_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_max("capacity_tons", alias)
    }

    pub fn standard_deviation_capacity_tons(self) -> Self {
        self.standard_deviation_capacity_tons_as("stdDev_capacity_tons")
    }

    pub fn standard_deviation_capacity_tons_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev("capacity_tons", alias)
    }

    pub fn square_root_of_population_standard_deviation_capacity_tons(self) -> Self {
        self.square_root_of_population_standard_deviation_capacity_tons_as("stdDevPop_capacity_tons")
    }

    pub fn square_root_of_population_standard_deviation_capacity_tons_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_stddev_pop("capacity_tons", alias)
    }

    pub fn sample_variance_capacity_tons(self) -> Self {
        self.sample_variance_capacity_tons_as("varSamp_capacity_tons")
    }

    pub fn sample_variance_capacity_tons_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_samp("capacity_tons", alias)
    }

    pub fn sample_population_variance_capacity_tons(self) -> Self {
        self.sample_population_variance_capacity_tons_as("varPop_capacity_tons")
    }

    pub fn sample_population_variance_capacity_tons_as(self, alias: impl Into<String>) -> Self {
        self.aggregate_var_pop("capacity_tons", alias)
    }

    pub fn unselect_capacity_tons(mut self) -> Self {
        self.query.projection.retain(|field| field != "capacity_tons");
        self.query_options.raw_projections.retain(|projection| projection.property_name != "capacity_tons");
        self
    }


    pub fn with_capacity_tons(
        mut self,
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(field_operator_expr(
            "capacity_tons",
            operator,
            values.into_iter().map(Into::into).collect(),
        ));
        self
    }

    pub fn create_capacity_tons_criteria(
        operator: FieldOperator,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Expr {
        field_operator_expr(
            "capacity_tons",
            operator,
            values.into_iter().map(Into::into).collect(),
        )
    }

    pub fn with_capacity_tons_is(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::eq("capacity_tons", value));
        self
    }



    pub fn with_capacity_tons_is_not(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::ne("capacity_tons", value));
        self
    }

    pub fn with_capacity_tons_greater_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("capacity_tons", value));
        self
    }

    pub fn with_capacity_tons_greater_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gte("capacity_tons", value));
        self
    }

    pub fn with_capacity_tons_less_than(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("capacity_tons", value));
        self
    }

    pub fn with_capacity_tons_less_than_or_equal_to(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lte("capacity_tons", value));
        self
    }

    pub fn with_capacity_tons_between(
        mut self,
        lower: impl Into<teaql_core::Value>,
        upper: impl Into<teaql_core::Value>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::between("capacity_tons", lower, upper));
        self
    }

    pub fn with_capacity_tons_between_range<T>(mut self, range: DateRange<T>) -> Self
    where
        T: Into<teaql_core::Value>,
    {
        self.query = self.query.and_filter(Expr::between(
            "capacity_tons",
            range.start,
            range.end,
        ));
        self
    }

    pub fn with_capacity_tons_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::in_list(
            "capacity_tons",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_capacity_tons_not_in(
        mut self,
        values: impl IntoIterator<Item = impl Into<teaql_core::Value>>,
    ) -> Self {
        self.query = self.query.and_filter(Expr::not_in_list(
            "capacity_tons",
            values.into_iter().map(Into::into),
        ));
        self
    }

    pub fn with_capacity_tons_before(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::lt("capacity_tons", value));
        self
    }

    pub fn with_capacity_tons_after(mut self, value: impl Into<teaql_core::Value>) -> Self {
        self.query = self.query.and_filter(Expr::gt("capacity_tons", value));
        self
    }

    pub fn with_capacity_tons_is_unknown(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_null("capacity_tons"));
        self
    }



    pub fn with_capacity_tons_is_known(mut self) -> Self {
        self.query = self.query.and_filter(Expr::is_not_null("capacity_tons"));
        self
    }


    pub fn order_by_capacity_tons_asc(mut self) -> Self {
        self.query = self.query.order_asc("capacity_tons");
        self
    }

    pub fn order_by_capacity_tons_desc(mut self) -> Self {
        self.query = self.query.order_desc("capacity_tons");
        self
    }

    pub fn order_by_capacity_tons_asc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_asc("capacity_tons");
        self
    }

    pub fn order_by_capacity_tons_desc_using_gbk(mut self) -> Self {
        self.query = self.query.order_gbk_desc("capacity_tons");
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
    pub fn have_insurance_policies(self) -> Self {
        self.with_insurance_policy_list_matching(SelectQuery::new("InsurancePolicy"))
    }

    pub fn have_no_insurance_policies(self) -> Self {
        self.without_insurance_policy_list_matching(SelectQuery::new("InsurancePolicy"))
    }

    pub fn with_insurance_policy_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::InsurancePolicy as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "fleet_vehicle_id",
        ));
        self.relation_filters.push(RelationFilter::new("insurance_policy_list", selection));
        self
    }

    pub fn without_insurance_policy_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::InsurancePolicy as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "fleet_vehicle_id",
        ));
        self.relation_filters.push(RelationFilter::new("insurance_policy_list", selection));
        self
    }

    pub fn select_insurance_policy_list(mut self) -> Self {
        self.query = self.query.relation("insurance_policy_list");
        self
    }

    pub fn select_insurance_policy_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("insurance_policy_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("insurance_policy_list", selection));
        self
}

    pub fn have_move_orders(self) -> Self {
        self.with_move_order_list_matching(SelectQuery::new("MoveOrder"))
    }

    pub fn have_no_move_orders(self) -> Self {
        self.without_move_order_list_matching(SelectQuery::new("MoveOrder"))
    }

    pub fn with_move_order_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::MoveOrder as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "asset_vehicle_id",
        ));
        self.relation_filters.push(RelationFilter::new("move_order_list", selection));
        self
    }

    pub fn without_move_order_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::MoveOrder as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "asset_vehicle_id",
        ));
        self.relation_filters.push(RelationFilter::new("move_order_list", selection));
        self
    }

    pub fn select_move_order_list(mut self) -> Self {
        self.query = self.query.relation("move_order_list");
        self
    }

    pub fn select_move_order_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("move_order_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("move_order_list", selection));
        self
}

    pub fn have_equipment_items(self) -> Self {
        self.with_equipment_item_list_matching(SelectQuery::new("EquipmentItem"))
    }

    pub fn have_no_equipment_items(self) -> Self {
        self.without_equipment_item_list_matching(SelectQuery::new("EquipmentItem"))
    }

    pub fn with_equipment_item_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::EquipmentItem as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "asset_vehicle_id",
        ));
        self.relation_filters.push(RelationFilter::new("equipment_item_list", selection));
        self
    }

    pub fn without_equipment_item_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::EquipmentItem as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "asset_vehicle_id",
        ));
        self.relation_filters.push(RelationFilter::new("equipment_item_list", selection));
        self
    }

    pub fn select_equipment_item_list(mut self) -> Self {
        self.query = self.query.relation("equipment_item_list");
        self
    }

    pub fn select_equipment_item_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("equipment_item_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("equipment_item_list", selection));
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
            "asset_vehicle_id",
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
            "asset_vehicle_id",
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

    pub fn have_maintenance_schedules(self) -> Self {
        self.with_maintenance_schedule_list_matching(SelectQuery::new("MaintenanceSchedule"))
    }

    pub fn have_no_maintenance_schedules(self) -> Self {
        self.without_maintenance_schedule_list_matching(SelectQuery::new("MaintenanceSchedule"))
    }

    pub fn with_maintenance_schedule_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::in_subquery(
            "id",
            <crate::MaintenanceSchedule as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "asset_vehicle_id",
        ));
        self.relation_filters.push(RelationFilter::new("maintenance_schedule_list", selection));
        self
    }

    pub fn without_maintenance_schedule_list_matching(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.and_filter(Expr::not_in_subquery(
            "id",
            <crate::MaintenanceSchedule as teaql_core::TeaqlEntity>::entity_descriptor(),
            selection.query.clone(),
            "asset_vehicle_id",
        ));
        self.relation_filters.push(RelationFilter::new("maintenance_schedule_list", selection));
        self
    }

    pub fn select_maintenance_schedule_list(mut self) -> Self {
        self.query = self.query.relation("maintenance_schedule_list");
        self
    }

    pub fn select_maintenance_schedule_list_with(mut self, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query = self.query.relation_query("maintenance_schedule_list", selection.clone().into_query());
        self.relation_selections.push(RelationSelection::new("maintenance_schedule_list", selection));
        self
}
    pub fn count_insurance_policies(self) -> Self {
        self.count_insurance_policies_as("count_insurance_policies")
    }

    pub fn count_insurance_policies_as(self, alias: impl Into<String>) -> Self {
        self.count_insurance_policies_with(alias, crate::Q::insurance_policies().unlimited())
    }

    pub fn count_insurance_policies_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "insurance_policy_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_insurance_policies(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_insurance_policies_as("refinements", request)
    }

    pub fn stats_from_insurance_policies_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "insurance_policy_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_insurance_policies_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_insurance_policies(request)
    }


    pub fn min_expiry_date_of_insurance_policies(self) -> Self {
        self.min_expiry_date_of_insurance_policies_as("min_expiry_date_of_insurance_policies", crate::Q::insurance_policies().unlimited())
    }

    pub fn min_expiry_date_of_insurance_policies_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_insurance_policies_as(alias, request.into().into_query().min("expiry_date", "min_expiry_date"))
    }
    pub fn max_expiry_date_of_insurance_policies(self) -> Self {
        self.max_expiry_date_of_insurance_policies_as("max_expiry_date_of_insurance_policies", crate::Q::insurance_policies().unlimited())
    }

    pub fn max_expiry_date_of_insurance_policies_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_insurance_policies_as(alias, request.into().into_query().max("expiry_date", "max_expiry_date"))
    }
    pub fn min_create_time_of_insurance_policies(self) -> Self {
        self.min_create_time_of_insurance_policies_as("min_create_time_of_insurance_policies", crate::Q::insurance_policies().unlimited())
    }

    pub fn min_create_time_of_insurance_policies_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_insurance_policies_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_insurance_policies(self) -> Self {
        self.max_create_time_of_insurance_policies_as("max_create_time_of_insurance_policies", crate::Q::insurance_policies().unlimited())
    }

    pub fn max_create_time_of_insurance_policies_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_insurance_policies_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }

    pub fn count_move_orders(self) -> Self {
        self.count_move_orders_as("count_move_orders")
    }

    pub fn count_move_orders_as(self, alias: impl Into<String>) -> Self {
        self.count_move_orders_with(alias, crate::Q::move_orders().unlimited())
    }

    pub fn count_move_orders_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "move_order_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_move_orders(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_move_orders_as("refinements", request)
    }

    pub fn stats_from_move_orders_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "move_order_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_move_orders_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_move_orders(request)
    }


    pub fn min_move_date_of_move_orders(self) -> Self {
        self.min_move_date_of_move_orders_as("min_move_date_of_move_orders", crate::Q::move_orders().unlimited())
    }

    pub fn min_move_date_of_move_orders_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_move_orders_as(alias, request.into().into_query().min("move_date", "min_move_date"))
    }
    pub fn max_move_date_of_move_orders(self) -> Self {
        self.max_move_date_of_move_orders_as("max_move_date_of_move_orders", crate::Q::move_orders().unlimited())
    }

    pub fn max_move_date_of_move_orders_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_move_orders_as(alias, request.into().into_query().max("move_date", "max_move_date"))
    }
    pub fn min_create_time_of_move_orders(self) -> Self {
        self.min_create_time_of_move_orders_as("min_create_time_of_move_orders", crate::Q::move_orders().unlimited())
    }

    pub fn min_create_time_of_move_orders_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_move_orders_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_move_orders(self) -> Self {
        self.max_create_time_of_move_orders_as("max_create_time_of_move_orders", crate::Q::move_orders().unlimited())
    }

    pub fn max_create_time_of_move_orders_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_move_orders_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
    pub fn min_update_time_of_move_orders(self) -> Self {
        self.min_update_time_of_move_orders_as("min_update_time_of_move_orders", crate::Q::move_orders().unlimited())
    }

    pub fn min_update_time_of_move_orders_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_move_orders_as(alias, request.into().into_query().min("update_time", "min_update_time"))
    }
    pub fn max_update_time_of_move_orders(self) -> Self {
        self.max_update_time_of_move_orders_as("max_update_time_of_move_orders", crate::Q::move_orders().unlimited())
    }

    pub fn max_update_time_of_move_orders_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_move_orders_as(alias, request.into().into_query().max("update_time", "max_update_time"))
    }

    pub fn count_equipment_items(self) -> Self {
        self.count_equipment_items_as("count_equipment_items")
    }

    pub fn count_equipment_items_as(self, alias: impl Into<String>) -> Self {
        self.count_equipment_items_with(alias, crate::Q::equipment_items().unlimited())
    }

    pub fn count_equipment_items_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "equipment_item_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_equipment_items(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_equipment_items_as("refinements", request)
    }

    pub fn stats_from_equipment_items_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "equipment_item_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_equipment_items_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_equipment_items(request)
    }


    pub fn min_create_time_of_equipment_items(self) -> Self {
        self.min_create_time_of_equipment_items_as("min_create_time_of_equipment_items", crate::Q::equipment_items().unlimited())
    }

    pub fn min_create_time_of_equipment_items_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_equipment_items_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_equipment_items(self) -> Self {
        self.max_create_time_of_equipment_items_as("max_create_time_of_equipment_items", crate::Q::equipment_items().unlimited())
    }

    pub fn max_create_time_of_equipment_items_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_equipment_items_as(alias, request.into().into_query().max("create_time", "max_create_time"))
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


    pub fn sum_quantity_count_of_consumable_items(self) -> Self {
        self.sum_quantity_count_of_consumable_items_as("sum_quantity_count_of_consumable_items", crate::Q::consumable_items().unlimited())
    }

    pub fn sum_quantity_count_of_consumable_items_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_consumable_items_as(alias, request.into().into_query().sum("quantity_count", "sum_quantity_count"))
    }
    pub fn min_quantity_count_of_consumable_items(self) -> Self {
        self.min_quantity_count_of_consumable_items_as("min_quantity_count_of_consumable_items", crate::Q::consumable_items().unlimited())
    }

    pub fn min_quantity_count_of_consumable_items_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_consumable_items_as(alias, request.into().into_query().min("quantity_count", "min_quantity_count"))
    }
    pub fn max_quantity_count_of_consumable_items(self) -> Self {
        self.max_quantity_count_of_consumable_items_as("max_quantity_count_of_consumable_items", crate::Q::consumable_items().unlimited())
    }

    pub fn max_quantity_count_of_consumable_items_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_consumable_items_as(alias, request.into().into_query().max("quantity_count", "max_quantity_count"))
    }
    pub fn avg_quantity_count_of_consumable_items(self) -> Self {
        self.avg_quantity_count_of_consumable_items_as("avg_quantity_count_of_consumable_items", crate::Q::consumable_items().unlimited())
    }

    pub fn avg_quantity_count_of_consumable_items_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_consumable_items_as(alias, request.into().into_query().avg("quantity_count", "avg_quantity_count"))
    }
    pub fn standard_deviation_quantity_count_of_consumable_items(self) -> Self {
        self.standard_deviation_quantity_count_of_consumable_items_as("standard_deviation_quantity_count_of_consumable_items", crate::Q::consumable_items().unlimited())
    }

    pub fn standard_deviation_quantity_count_of_consumable_items_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_consumable_items_as(alias, request.into().into_query().stddev("quantity_count", "stdDev_quantity_count"))
    }
    pub fn square_root_of_population_standard_deviation_quantity_count_of_consumable_items(self) -> Self {
        self.square_root_of_population_standard_deviation_quantity_count_of_consumable_items_as("square_root_of_population_standard_deviation_quantity_count_of_consumable_items", crate::Q::consumable_items().unlimited())
    }

    pub fn square_root_of_population_standard_deviation_quantity_count_of_consumable_items_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_consumable_items_as(alias, request.into().into_query().stddev_pop("quantity_count", "stdDevPop_quantity_count"))
    }
    pub fn sample_variance_quantity_count_of_consumable_items(self) -> Self {
        self.sample_variance_quantity_count_of_consumable_items_as("sample_variance_quantity_count_of_consumable_items", crate::Q::consumable_items().unlimited())
    }

    pub fn sample_variance_quantity_count_of_consumable_items_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_consumable_items_as(alias, request.into().into_query().var_samp("quantity_count", "varSamp_quantity_count"))
    }
    pub fn sample_population_variance_quantity_count_of_consumable_items(self) -> Self {
        self.sample_population_variance_quantity_count_of_consumable_items_as("sample_population_variance_quantity_count_of_consumable_items", crate::Q::consumable_items().unlimited())
    }

    pub fn sample_population_variance_quantity_count_of_consumable_items_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_consumable_items_as(alias, request.into().into_query().var_pop("quantity_count", "varPop_quantity_count"))
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

    pub fn count_maintenance_schedules(self) -> Self {
        self.count_maintenance_schedules_as("count_maintenance_schedules")
    }

    pub fn count_maintenance_schedules_as(self, alias: impl Into<String>) -> Self {
        self.count_maintenance_schedules_with(alias, crate::Q::maintenance_schedules().unlimited())
    }

    pub fn count_maintenance_schedules_with(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "maintenance_schedule_list",
            alias,
            selection,
            true,
        ));
        self
    }

    pub fn stats_from_maintenance_schedules(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_maintenance_schedules_as("refinements", request)
    }

    pub fn stats_from_maintenance_schedules_as(mut self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        let selection = request.into();
        self.query_options.relation_aggregates.push(RelationAggregate::new(
            "maintenance_schedule_list",
            alias,
            selection,
            false,
        ));
        self
    }

    pub fn group_by_maintenance_schedules_with_details(self, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_maintenance_schedules(request)
    }


    pub fn min_scheduled_date_of_maintenance_schedules(self) -> Self {
        self.min_scheduled_date_of_maintenance_schedules_as("min_scheduled_date_of_maintenance_schedules", crate::Q::maintenance_schedules().unlimited())
    }

    pub fn min_scheduled_date_of_maintenance_schedules_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_maintenance_schedules_as(alias, request.into().into_query().min("scheduled_date", "min_scheduled_date"))
    }
    pub fn max_scheduled_date_of_maintenance_schedules(self) -> Self {
        self.max_scheduled_date_of_maintenance_schedules_as("max_scheduled_date_of_maintenance_schedules", crate::Q::maintenance_schedules().unlimited())
    }

    pub fn max_scheduled_date_of_maintenance_schedules_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_maintenance_schedules_as(alias, request.into().into_query().max("scheduled_date", "max_scheduled_date"))
    }
    pub fn min_create_time_of_maintenance_schedules(self) -> Self {
        self.min_create_time_of_maintenance_schedules_as("min_create_time_of_maintenance_schedules", crate::Q::maintenance_schedules().unlimited())
    }

    pub fn min_create_time_of_maintenance_schedules_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_maintenance_schedules_as(alias, request.into().into_query().min("create_time", "min_create_time"))
    }
    pub fn max_create_time_of_maintenance_schedules(self) -> Self {
        self.max_create_time_of_maintenance_schedules_as("max_create_time_of_maintenance_schedules", crate::Q::maintenance_schedules().unlimited())
    }

    pub fn max_create_time_of_maintenance_schedules_as(self, alias: impl Into<String>, request: impl Into<QuerySelection>) -> Self {
        self.stats_from_maintenance_schedules_as(alias, request.into().into_query().max("create_time", "max_create_time"))
    }
}

impl<R> Default for FleetVehicleRequest<R> {
    fn default() -> Self {
        Self::new()
    }
}

impl<R> From< FleetVehicleRequest<R> > for SelectQuery {
    fn from(request: FleetVehicleRequest<R>) -> Self {
        QuerySelection::from(request).into_query()
    }
}

impl<R> From< FleetVehicleRequest<R> > for QuerySelection {
    fn from(request: FleetVehicleRequest<R>) -> Self {
        Self {
            query: request.query,
            relation_selections: request.relation_selections,
            relation_filters: request.relation_filters,
            child_enhancements: request.child_enhancements,
            query_options: request.query_options,
        }
    }
}


impl<'a, C> crate::request_support::AuditedSave<'a, C> for teaql_core::Audited<crate::FleetVehicle> 
where C: crate::request_support::TeaqlRepositoryProvider + ?Sized + 'a
{
    type Error = crate::TeaqlDataServiceError<C::FleetVehicleRepository<'a>>;
    fn save(self, ctx: &'a C) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<teaql_runtime::GraphNode, Self::Error>> + '_>> {
        Box::pin(async move {
            teaql_runtime::save_audited_ledger_entity(self, ctx.user_context())
                .await
                .map_err(DataServiceError::Runtime)
        })
    }
}

impl<R: teaql_core::Entity> crate::PurposedQuery<FleetVehicleRequest<R>> {
    pub fn new_entity<C>(&self, ctx: &C) -> crate::FleetVehicle
    where
        C: crate::TeaqlRuntime + ?Sized,
    {
        crate::FleetVehicle::runtime_new(ctx.user_context().entity_root())
    }

    fn into_inner_with_trace(mut self) -> FleetVehicleRequest<R> {
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
    ) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::FleetVehicleRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_page(ctx, offset, limit).await
    }

    pub async fn execute_for_exists<'a, C>(
        self,
        ctx: &'a C,
    ) -> Result<bool, crate::request_support::TeaqlDataServiceError<C::FleetVehicleRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_exists(ctx).await
    }

    pub async fn execute_for_list<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<R>, crate::request_support::TeaqlDataServiceError<C::FleetVehicleRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_list(ctx).await
    }

    /// Execute query in streaming mode (chunked).
    /// Returns a Vec of StreamChunk, each containing up to chunk_size rows.
    /// Set chunk size via .stream(chunk_size) or .stream_default() on the query.
    pub async fn execute_for_stream<'a, C>(self, ctx: &'a C) -> Result<Vec<teaql_data_service::StreamChunk>, crate::request_support::TeaqlDataServiceError<C::FleetVehicleRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_stream(ctx).await
    }

    pub async fn execute_for_first<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::FleetVehicleRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_first(ctx).await
    }

    pub async fn execute_for_one<'a, C>(self, ctx: &'a C) -> Result<Option<R>, crate::request_support::TeaqlDataServiceError<C::FleetVehicleRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_one(ctx).await
    }


    pub async fn execute_for_records<'a, C>(self, ctx: &'a C) -> Result<teaql_core::SmartList<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::FleetVehicleRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_records(ctx).await
    }

    pub async fn execute_for_record<'a, C>(self, ctx: &'a C) -> Result<Option<teaql_core::Record>, crate::request_support::TeaqlDataServiceError<C::FleetVehicleRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_record(ctx).await
    }

    pub async fn execute_for_count<'a, C>(self, ctx: &'a C) -> Result<u64, crate::request_support::TeaqlDataServiceError<C::FleetVehicleRepository<'a>>>
    where
        C: crate::request_support::TeaqlRepositoryProvider + ?Sized,
    {
        self.into_inner_with_trace()._execute_for_count(ctx).await
    }
}
