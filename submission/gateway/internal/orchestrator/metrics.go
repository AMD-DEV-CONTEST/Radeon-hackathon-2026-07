package orchestrator

import (
	"context"
	"fmt"
	"net/http"
	"time"
)

// Metrics handles GET /metrics — Prometheus text format.
func Metrics(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
	defer cancel()

	// Count tasks by status
	rows, err := pool.Query(ctx, `SELECT status, count(*) FROM tasks GROUP BY status`)
	if err != nil {
		http.Error(w, "db error", http.StatusInternalServerError)
		return
	}
	defer rows.Close()

	taskByStatus := map[string]int{}
	for rows.Next() {
		var s string
		var n int
		rows.Scan(&s, &n)
		taskByStatus[s] = n
	}

	// Count agents by status
	var online, totalAgents int
	pool.QueryRow(ctx, `SELECT count(*), count(*) FILTER (WHERE status='online') FROM agents`).Scan(&totalAgents, &online)

	w.Header().Set("Content-Type", "text/plain; version=0.0.4")
	fmt.Fprintf(w, "# HELP ua_tasks_total Total tasks by status\n")
	fmt.Fprintf(w, "# TYPE ua_tasks_total gauge\n")
	for status, n := range taskByStatus {
		fmt.Fprintf(w, `ua_tasks_total{status="%s"} %d`+"\n", status, n)
	}
	fmt.Fprintf(w, "# HELP ua_agents_total Agent count\n")
	fmt.Fprintf(w, "# TYPE ua_agents_total gauge\n")
	fmt.Fprintf(w, "ua_agents_total %d\n", totalAgents)
	fmt.Fprintf(w, "ua_agents_online %d\n", online)
}
