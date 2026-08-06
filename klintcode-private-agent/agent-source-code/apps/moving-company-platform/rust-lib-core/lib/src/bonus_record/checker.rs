
use teaql_runtime::{CheckObjectStatus, CheckResults, ObjectLocation, TypedChecker, UserContext};

pub trait BonusRecordCheckerLogic: Send + Sync {
    fn check_and_fix_bonus_record(
        &self,
        _ctx: &UserContext,
        _entity: &mut crate::BonusRecord,
        _status: CheckObjectStatus,
        _location: &ObjectLocation,
        _results: &mut CheckResults,
    ) {
    }

    fn required(
        &self,
        value: bool,
        field: &str,
        location: &ObjectLocation,
        results: &mut CheckResults,
    ) {
        if !value {
            results.push(teaql_runtime::CheckResult::required(location.clone().member(field)));
        }
    }

    fn required_option<V>(
        &self,
        value: Option<&V>,
        field: &str,
        location: &ObjectLocation,
        results: &mut CheckResults,
    ) {
        if value.is_none() {
            results.push(teaql_runtime::CheckResult::required(location.clone().member(field)));
        }
    }

    fn required_text(
        &self,
        value: &str,
        field: &str,
        location: &ObjectLocation,
        results: &mut CheckResults,
    ) {
        if value.trim().is_empty() {
            results.push(teaql_runtime::CheckResult::required(location.clone().member(field)));
        }
    }

    fn min_string_length(
        &self,
        value: &str,
        field: &str,
        min_len: usize,
        location: &ObjectLocation,
        results: &mut CheckResults,
    ) {
        if value.chars().count() < min_len {
            results.push(teaql_runtime::CheckResult::min_str(
                location.clone().member(field),
                min_len as u64,
                value.to_owned(),
            ));
        }
    }

    fn max_string_length(
        &self,
        value: &str,
        field: &str,
        max_len: usize,
        location: &ObjectLocation,
        results: &mut CheckResults,
    ) {
        if value.chars().count() > max_len {
            results.push(teaql_runtime::CheckResult::max_str(
                location.clone().member(field),
                max_len as u64,
                value.to_owned(),
            ));
        }
    }
}

#[derive(Clone, Debug, Default)]
pub struct NoopBonusRecordChecker;

impl BonusRecordCheckerLogic for NoopBonusRecordChecker {}

#[derive(Clone, Debug)]
pub struct BonusRecordChecker<L = NoopBonusRecordChecker> {
    logic: L,
}

impl Default for BonusRecordChecker<NoopBonusRecordChecker> {
    fn default() -> Self {
        Self {
            logic: NoopBonusRecordChecker,
        }
    }
}

impl<L> BonusRecordChecker<L>
where
    L: BonusRecordCheckerLogic,
{
    pub fn new(logic: L) -> Self {
        Self { logic }
    }
}

impl<L> TypedChecker<crate::BonusRecord> for BonusRecordChecker<L>
where
    L: BonusRecordCheckerLogic,
{
    fn check_and_fix_typed(
        &self,
        ctx: &UserContext,
        entity: &mut crate::BonusRecord,
        status: CheckObjectStatus,
        location: &ObjectLocation,
        results: &mut CheckResults,
    ) {
        self.logic
            .check_and_fix_bonus_record(ctx, entity, status, location, results);
    }
}