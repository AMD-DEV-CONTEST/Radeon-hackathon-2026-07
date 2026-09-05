//! Generated TeaQL domain crate for `platform-modules-core`.
//!
//! **Before writing queries**, read the `AGENTS.md` at the workspace root.
//! It contains the entity list and the exact `cargo teaql` commands to fetch API prompts.
//!
//! AI coding agents must read this crate's `AGENTS.md` before using generated
//! APIs. If this crate was downloaded from a Cargo registry, locate the
//! unpacked crate source or vendor the dependency, then read `AGENTS.md` from
//! the crate root before writing code against it.

pub mod e;
pub mod q;
pub mod request_support;
pub mod runtime;
pub mod sample_data;
pub mod address;
pub mod moving_event;
pub mod route;
pub mod time_slot;
pub mod fulfillment_event;
pub mod staff;
pub mod job_assignment;
pub mod worked_hours;
pub mod payroll;
pub mod bonus;
pub mod leave_tracking;
pub mod private_customer;
pub mod corporate_customer;
pub mod customer_contact;
pub mod moving_service;
pub mod cleaning_service;
pub mod campaign;
pub mod discount_code;
pub mod lead;
pub mod conversion_metric;
pub mod payment;
pub mod invoice;
pub mod expense;
pub mod vat_record;
pub mod financial_summary;
pub mod vehicle;
pub mod equipment;
pub mod consumable;
pub mod user;
pub mod role;
pub mod permission;
pub mod user_role;
pub mod role_permission;
pub mod authentication_log;
pub mod activity_log;
pub mod notification;
pub mod api_endpoint;
pub mod webhook;

pub use teaql_core;
pub use e::*;
pub use q::*;
pub use request_support::*;
pub use runtime::*;
pub use sample_data::*;
pub use address::*;
pub use moving_event::*;
pub use route::*;
pub use time_slot::*;
pub use fulfillment_event::*;
pub use staff::*;
pub use job_assignment::*;
pub use worked_hours::*;
pub use payroll::*;
pub use bonus::*;
pub use leave_tracking::*;
pub use private_customer::*;
pub use corporate_customer::*;
pub use customer_contact::*;
pub use moving_service::*;
pub use cleaning_service::*;
pub use campaign::*;
pub use discount_code::*;
pub use lead::*;
pub use conversion_metric::*;
pub use payment::*;
pub use invoice::*;
pub use expense::*;
pub use vat_record::*;
pub use financial_summary::*;
pub use vehicle::*;
pub use equipment::*;
pub use consumable::*;
pub use user::*;
pub use role::*;
pub use permission::*;
pub use user_role::*;
pub use role_permission::*;
pub use authentication_log::*;
pub use activity_log::*;
pub use notification::*;
pub use api_endpoint::*;
pub use webhook::*;