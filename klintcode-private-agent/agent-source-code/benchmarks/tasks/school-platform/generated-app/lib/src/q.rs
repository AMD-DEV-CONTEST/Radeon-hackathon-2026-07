use teaql_core::Expr;

use crate::*;

pub struct PurposedQuery<T> {
    pub inner: T,
    pub purpose: String,
}

impl<T> PurposedQuery<T> {
    pub fn new(inner: T, purpose: impl Into<String>) -> Self {
        Self { inner, purpose: purpose.into() }
    }
}

pub struct Q;

impl Q {
    pub fn platforms() -> PlatformRequest {
        PlatformRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn platforms_minimal() -> PlatformRequest {
        PlatformRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn platforms_with_children() -> PlatformRequest {
        PlatformRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn school_types() -> SchoolTypeRequest {
        SchoolTypeRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn school_types_minimal() -> SchoolTypeRequest {
        SchoolTypeRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn school_types_with_children() -> SchoolTypeRequest {
        SchoolTypeRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }

    pub fn schools() -> SchoolRequest {
        SchoolRequest::new()
            .select_self()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn schools_minimal() -> SchoolRequest {
        SchoolRequest::new()
            .and_filter(Expr::gt("version", 0_i64))
    }

    pub fn schools_with_children() -> SchoolRequest {
        SchoolRequest::new()
            .unlimited()
            .select_self_fields()
            .enhance_children_if_needed()
    }
}