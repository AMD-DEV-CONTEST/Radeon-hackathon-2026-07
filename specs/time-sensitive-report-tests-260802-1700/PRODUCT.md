# Product specification

- Change ID: time-sensitive-report-tests-260802-1700
- Status: implemented

## Problem

Two report-evaluation tests used historical fixed deadlines while asserting a completed outcome. Once the calendar passed those dates, the production rule correctly classified the tasks as delayed and the tests failed.

## Acceptance criteria

- Completion scenarios use a future deadline relative to the test execution date.
- Tests continue to verify completed-task evidence and LLM explanation behavior.
- The overdue-to-delayed production rule is unchanged.
