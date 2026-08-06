
use teaql_runtime::EntityDataServiceBehavior;

#[derive(Clone, Debug, Default)]
pub struct AuditLogBehavior;

impl EntityDataServiceBehavior for AuditLogBehavior {}