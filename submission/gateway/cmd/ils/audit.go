package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"net/http"
	"os"
	"sort"
	"strings"
	"time"
)

// cmdAudit implements `ils audit verify`. It is the first slice of the
// Sprint 0 acceptance tooling: a read-only check against the one audit
// trail that is actually real today — the cron dispatcher's cron_events
// table (added in PR #15). It does NOT attempt hash-chain or multi-node
// quorum verification: no audit_chain/hash fields exist in the schema
// yet, and that design is deferred until Sprint 1 protocols (#1/#2/#3)
// land and there's a real multi-node scenario to verify against.
func cmdAudit(args []string) {
	if len(args) == 0 || args[0] != "verify" {
		fmt.Fprintln(os.Stderr, "用法: ils audit verify [--orchestrator-url URL] [--schedule-id ID] [--json]")
		os.Exit(2)
	}

	fs := flag.NewFlagSet("audit verify", flag.ExitOnError)
	orchestratorURL := fs.String("orchestrator-url", envOr("ORCHESTRATOR_URL", "http://111.228.42.18:8000"), "UAS Orchestrator URL")
	scheduleID := fs.String("schedule-id", "", "filter to one cron schedule")
	jsonOutput := fs.Bool("json", true, "print JSON output")
	if err := fs.Parse(args[1:]); err != nil {
		fmt.Fprintf(os.Stderr, "parse flags: %v\n", err)
		os.Exit(2)
	}

	url := strings.TrimRight(*orchestratorURL, "/") + "/cron-events"
	if *scheduleID != "" {
		url += "?schedule_id=" + *scheduleID
	}

	events, err := fetchCronEvents(url)
	if err != nil {
		fmt.Fprintf(os.Stderr, "fetch cron-events: %v\n", err)
		os.Exit(1)
	}

	anomalies := verifyCronEvents(events)

	result := map[string]interface{}{
		"status":           "ok",
		"orchestrator_url": *orchestratorURL,
		"events_checked":   len(events),
		"anomalies":        anomalies,
	}
	if len(anomalies) > 0 {
		result["status"] = "fail"
	}

	out, _ := json.MarshalIndent(result, "", "  ")
	if *jsonOutput {
		fmt.Println(string(out))
	} else {
		fmt.Println(string(out))
	}
	if len(anomalies) > 0 {
		os.Exit(1)
	}
}

type cronEvent struct {
	ID           string    `json:"id"`
	ScheduleID   string    `json:"schedule_id"`
	ScheduleName string    `json:"schedule_name"`
	CronExpr     string    `json:"cron_expr"`
	TaskID       *string   `json:"task_id,omitempty"`
	Status       string    `json:"status"`
	Message      string    `json:"message"`
	TriggeredAt  time.Time `json:"triggered_at"`
}

func fetchCronEvents(url string) ([]cronEvent, error) {
	client := &http.Client{Timeout: ilsShortHTTPTimeout()}
	resp, err := client.Get(url)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return nil, fmt.Errorf("HTTP %d", resp.StatusCode)
	}
	var body struct {
		Events []cronEvent `json:"events"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return nil, err
	}
	return body.Events, nil
}

// verifyCronEvents checks the cron_events audit trail for internal
// consistency. It does not require a DB connection — it works purely
// off what the orchestrator's own /cron-events endpoint reports.
func verifyCronEvents(events []cronEvent) []string {
	var anomalies []string
	now := time.Now().UTC()

	for _, e := range events {
		if e.Status == "dispatched" && (e.TaskID == nil || *e.TaskID == "") {
			anomalies = append(anomalies, fmt.Sprintf("cron_event %s: status=dispatched but task_id is empty", e.ID))
		}
		if e.TriggeredAt.After(now.Add(time.Minute)) {
			anomalies = append(anomalies, fmt.Sprintf("cron_event %s: triggered_at %s is in the future", e.ID, e.TriggeredAt.Format(time.RFC3339)))
		}
	}

	anomalies = append(anomalies, detectDuplicateTriggers(events)...)
	return anomalies
}

// detectDuplicateTriggers flags two "dispatched" events for the same
// schedule within the same minute window — the scheduler's own dedup
// logic (isCronDue in internal/orchestrator/cron_scheduler.go) is
// supposed to prevent this.
func detectDuplicateTriggers(events []cronEvent) []string {
	bySchedule := make(map[string][]cronEvent)
	for _, e := range events {
		if e.Status != "dispatched" {
			continue
		}
		bySchedule[e.ScheduleID] = append(bySchedule[e.ScheduleID], e)
	}

	var anomalies []string
	for scheduleID, evts := range bySchedule {
		sort.Slice(evts, func(i, j int) bool { return evts[i].TriggeredAt.Before(evts[j].TriggeredAt) })
		for i := 1; i < len(evts); i++ {
			prev, cur := evts[i-1].TriggeredAt.UTC(), evts[i].TriggeredAt.UTC()
			if prev.Truncate(time.Minute).Equal(cur.Truncate(time.Minute)) {
				anomalies = append(anomalies, fmt.Sprintf(
					"schedule %s: duplicate dispatch in same minute window (%s, %s)",
					scheduleID, evts[i-1].ID, evts[i].ID))
			}
		}
	}
	return anomalies
}
