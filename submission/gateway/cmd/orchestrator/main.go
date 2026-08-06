package main

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"os"
	"time"

	"github.com/konspace/unionagents-go/internal/boundary"
	"github.com/konspace/unionagents-go/internal/db"
	"github.com/konspace/unionagents-go/internal/orchestrator"
	"github.com/konspace/unionagents-go/packages/asset-substrate/lifememory"
)

func main() {
	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelInfo})))
	slog.Info("UnionAgents Go — Orchestrator starting...")

	// ── Database ──────────────────────────────────────────────────
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	pool, err := db.Connect(ctx)
	if err != nil {
		slog.Error("db connect failed", "err", err)
		os.Exit(1)
	}
	defer pool.Close()

	if err := db.RunMigrations(context.Background()); err != nil {
		slog.Warn("migrations warning", "err", err)
	}

	orchestrator.SetPool(pool)

	// ── Scanner background loop ──────────────────────────────────
	scannerCtx, scannerCancel := context.WithCancel(context.Background())
	defer scannerCancel()
	go orchestrator.RunScanLoop(scannerCtx, pool)

	// ── Cron scheduler background loop (T2) ─────────────────────
	cronCtx, cronCancel := context.WithCancel(context.Background())
	defer cronCancel()
	go orchestrator.RunCronLoop(cronCtx, pool)

	// ── Peer sync background loop (Phase 2.4) ───────────────────
	// Pulls other bases' agent lists into the in-memory peer cache.
	// No-op when PEER_ORCHESTRATORS is unset (single-base mode).
	peerCtx, peerCancel := context.WithCancel(context.Background())
	defer peerCancel()
	go orchestrator.RunPeerSyncLoop(peerCtx)

	// ── HTTP Router (stdlib) ─────────────────────────────────────
	mux := http.NewServeMux()

	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"status":"ok","service":"unionagents-go-orchestrator"}`))
	})

	mux.HandleFunc("GET /boundary", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(boundary.NewSnapshot(
			"orchestrator",
			"UAS-owned JD-ECS coordinator for agent registry, heartbeat, task lease, task state, and scheduling.",
		))
	})

	mux.HandleFunc("POST /tasks", orchestrator.CreateTask)
	mux.HandleFunc("GET /tasks/{taskID}", orchestrator.GetTask)
	mux.HandleFunc("POST /tasks/poll", orchestrator.PollTask)
	mux.HandleFunc("POST /tasks/inject", orchestrator.InjectTask)
	mux.HandleFunc("POST /tasks/{taskID}/complete", orchestrator.CompleteTask)
	mux.HandleFunc("POST /tasks/{taskID}/heartbeat", orchestrator.TaskHeartbeat)
	mux.HandleFunc("POST /tasks/{taskID}/extend-lease", orchestrator.ExtendTaskLease)
	mux.HandleFunc("GET /tasks/stats", orchestrator.TaskStats)
	mux.HandleFunc("POST /agents/register", orchestrator.AgentRegister)
	mux.HandleFunc("POST /agents/{agentID}/heartbeat", orchestrator.Heartbeat)
	mux.HandleFunc("GET /agents", orchestrator.AgentList)
	mux.HandleFunc("GET /agents/discover", orchestrator.AgentDiscover)
	mux.HandleFunc("GET /agents/{agentID}", orchestrator.AgentGet)
	mux.HandleFunc("GET /config/feishu-webhook", orchestrator.ConfigFeishuWebhookGet)
	mux.HandleFunc("PUT /config/feishu-webhook", orchestrator.ConfigFeishuWebhookPut)
	mux.HandleFunc("GET /metrics", orchestrator.Metrics)
	mux.HandleFunc("POST /cron-schedules", orchestrator.CreateCronSchedule)
	mux.HandleFunc("GET /cron-schedules", orchestrator.ListCronSchedules)
	mux.HandleFunc("GET /cron-schedules/{id}", orchestrator.GetCronSchedule)
	mux.HandleFunc("DELETE /cron-schedules/{id}", orchestrator.DeleteCronSchedule)
	mux.HandleFunc("GET /cron-events", orchestrator.ListCronEvents)
	mux.HandleFunc("GET /events/timeline", orchestrator.EventTimeline)

	// ── Memory subsystem (Phase 3.5) ─────────────────────────────
	// PGStore when DB is up; MemStore fallback keeps memory working in
	// dev/test without a database. Either way the 3.3 protocol hooks
	// wire against the chosen store.
	if pool != nil {
		orchestrator.SetMemoryStore(lifememory.NewPGStore(pool))
		slog.Info("memory store initialized", "backend", "pg")
	} else {
		orchestrator.SetMemoryStore(lifememory.NewMemStore())
		slog.Info("memory store initialized", "backend", "mem (fallback)")
	}

	mux.HandleFunc("POST /memory/nodes", orchestrator.MemoryCreateNode)
	mux.HandleFunc("GET /memory/nodes", orchestrator.MemoryQueryNodes)
	mux.HandleFunc("GET /memory/nodes/{nodeID}", orchestrator.MemoryGetNode)
	mux.HandleFunc("DELETE /memory/nodes/{nodeID}", orchestrator.MemoryDeleteNode)


	// Middleware chain: recover → log → timeout
	handler := recoverMiddleware(loggingMiddleware(mux))
	handler = http.TimeoutHandler(handler, 60*time.Second, "")

	// ── Start HTTP server ────────────────────────────────────────
	port := os.Getenv("ORCHESTRATOR_PORT")
	if port == "" {
		port = "8000"
	}

	srv := &http.Server{
		Addr:         ":" + port,
		Handler:      handler,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 60 * time.Second,
		IdleTimeout:  120 * time.Second,
	}

	slog.Info("Orchestrator listening", "port", port)
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		slog.Error("orchestrator failed", "err", err)
		os.Exit(1)
	}
}

// loggingMiddleware logs every request.
func loggingMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		next.ServeHTTP(w, r)
		slog.Info("http",
			"method", r.Method,
			"path", r.URL.Path,
			"duration_ms", time.Since(start).Milliseconds(),
		)
	})
}

// recoverMiddleware recovers from panics in handlers.
func recoverMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if rv := recover(); rv != nil {
				slog.Error("handler panic", "path", r.URL.Path, "panic", rv)
				http.Error(w, `{"error":"internal server error"}`, http.StatusInternalServerError)
			}
		}()
		next.ServeHTTP(w, r)
	})
}
