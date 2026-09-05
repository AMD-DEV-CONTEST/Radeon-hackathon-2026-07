use teaql_runtime::EntityDataServiceBehavior;

#[derive(Clone, Debug, Default)]
pub struct LeaveTrackingBehavior;

impl EntityDataServiceBehavior for LeaveTrackingBehavior {}