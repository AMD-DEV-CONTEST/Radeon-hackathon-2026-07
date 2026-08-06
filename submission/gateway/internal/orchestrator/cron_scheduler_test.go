package orchestrator

import (
	"testing"
	"time"
)

func TestParseCronExprRejectsInvalidFields(t *testing.T) {
	tests := []string{
		"60 * * * *",
		"* 24 * * *",
		"* * 0 * *",
		"* * * 13 *",
		"* * * * 8",
		"* * * * 5-2",
	}

	for _, expr := range tests {
		if _, err := parseCronExpr(expr); err == nil {
			t.Fatalf("parseCronExpr(%q) succeeded, want error", expr)
		}
	}
}

func TestIsCronDueTreatsSevenAsSunday(t *testing.T) {
	now := time.Date(2026, 6, 21, 9, 30, 0, 0, time.UTC) // Sunday

	if !isCronDue("30 9 * * 0", nil, now) {
		t.Fatal("expected day-of-week 0 to match Sunday")
	}
	if !isCronDue("30 9 * * 7", nil, now) {
		t.Fatal("expected day-of-week 7 to match Sunday")
	}
}

func TestIsCronDueSkipsAlreadyTriggeredMinute(t *testing.T) {
	now := time.Date(2026, 6, 22, 9, 30, 45, 0, time.UTC)
	lastTriggered := time.Date(2026, 6, 22, 9, 30, 0, 0, time.UTC)

	if isCronDue("30 9 * * *", &lastTriggered, now) {
		t.Fatal("expected schedule to skip duplicate trigger in same minute")
	}
}
