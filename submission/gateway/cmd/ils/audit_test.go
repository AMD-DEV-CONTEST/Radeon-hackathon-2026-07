package main

import (
	"testing"
	"time"
)

func TestVerifyCronEventsFlagsMissingTaskID(t *testing.T) {
	events := []cronEvent{
		{ID: "e1", ScheduleID: "s1", Status: "dispatched", TaskID: nil, TriggeredAt: time.Now().UTC()},
	}
	anomalies := verifyCronEvents(events)
	if len(anomalies) != 1 {
		t.Fatalf("expected 1 anomaly, got %d: %v", len(anomalies), anomalies)
	}
}

func TestVerifyCronEventsFlagsFutureTimestamp(t *testing.T) {
	taskID := "t1"
	events := []cronEvent{
		{ID: "e1", ScheduleID: "s1", Status: "dispatched", TaskID: &taskID, TriggeredAt: time.Now().UTC().Add(time.Hour)},
	}
	anomalies := verifyCronEvents(events)
	if len(anomalies) != 1 {
		t.Fatalf("expected 1 anomaly, got %d: %v", len(anomalies), anomalies)
	}
}

func TestVerifyCronEventsCleanTrailHasNoAnomalies(t *testing.T) {
	taskID := "t1"
	events := []cronEvent{
		{ID: "e1", ScheduleID: "s1", Status: "dispatched", TaskID: &taskID, TriggeredAt: time.Now().UTC().Add(-time.Hour)},
		{ID: "e2", ScheduleID: "s1", Status: "dispatched", TaskID: &taskID, TriggeredAt: time.Now().UTC().Add(-30 * time.Minute)},
	}
	anomalies := verifyCronEvents(events)
	if len(anomalies) != 0 {
		t.Fatalf("expected 0 anomalies, got %d: %v", len(anomalies), anomalies)
	}
}

func TestDetectDuplicateTriggersSameMinuteWindow(t *testing.T) {
	taskID := "t1"
	base := time.Date(2026, 6, 22, 9, 0, 10, 0, time.UTC)
	events := []cronEvent{
		{ID: "e1", ScheduleID: "s1", Status: "dispatched", TaskID: &taskID, TriggeredAt: base},
		{ID: "e2", ScheduleID: "s1", Status: "dispatched", TaskID: &taskID, TriggeredAt: base.Add(20 * time.Second)},
	}
	anomalies := detectDuplicateTriggers(events)
	if len(anomalies) != 1 {
		t.Fatalf("expected 1 duplicate anomaly, got %d: %v", len(anomalies), anomalies)
	}
}

func TestDetectDuplicateTriggersDifferentMinutesIsFine(t *testing.T) {
	taskID := "t1"
	base := time.Date(2026, 6, 22, 9, 0, 0, 0, time.UTC)
	events := []cronEvent{
		{ID: "e1", ScheduleID: "s1", Status: "dispatched", TaskID: &taskID, TriggeredAt: base},
		{ID: "e2", ScheduleID: "s1", Status: "dispatched", TaskID: &taskID, TriggeredAt: base.Add(time.Minute)},
	}
	anomalies := detectDuplicateTriggers(events)
	if len(anomalies) != 0 {
		t.Fatalf("expected 0 anomalies, got %d: %v", len(anomalies), anomalies)
	}
}
