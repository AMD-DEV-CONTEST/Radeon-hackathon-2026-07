package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/rvbernucci/signalforge/internal/casestore"
	"github.com/rvbernucci/signalforge/internal/golden"
	"github.com/rvbernucci/signalforge/internal/workspace"
)

func main() {
	listenAddress := flag.String("listen", "127.0.0.1:8080", "loopback HTTP listen address")
	mode := flag.String("mode", workspace.ModeFixture, "workspace mode: fixture or live")
	fixturePath := flag.String("fixture", "fixtures/workspace/golden-case.json", "safe public workspace fixture")
	staticDir := flag.String("static-dir", "", "optional built frontend directory")
	eventDelay := flag.Duration("event-delay", 100*time.Millisecond, "fixture progress-event replay delay")
	snapshotPath := flag.String("snapshot", "fixtures/golden/financial-snapshot.json", "frozen point-in-time financial snapshot")
	retrievalPath := flag.String("retrieval", "fixtures/retrieval/golden-eval.json", "frozen authoritative qualitative evidence")
	priceInputsPath := flag.String("price-inputs", "fixtures/golden/market-price-inputs.json", "frozen point-in-time price-set JSON")
	traceDir := flag.String("trace-dir", ".signalforge/traces", "private live trace directory")
	caseDB := flag.String("case-db", ".signalforge/cases.db", "private local SQLite research-case database")
	disableCaseStore := flag.Bool("disable-case-store", false, "disable durable local case retention")
	baseURL := flag.String("base-url", "http://127.0.0.1:8000/v1", "loopback-local OpenAI-compatible endpoint")
	model := flag.String("model", "signalforge-gemma4-26b-q4", "local model identifier")
	codeCommit := flag.String("code-commit", "working-tree", "code revision recorded in receipts")
	timeout := flag.Duration("timeout", 6*time.Minute, "complete local run timeout")
	contextConcurrency := flag.Int("context-concurrency", 4, "concurrent local specialist calls, from 1 to 4")
	flag.Parse()

	if err := validateLoopbackListen(*listenAddress); err != nil {
		fatal(err)
	}
	prices, err := loadPrices(*priceInputsPath)
	if err != nil {
		fatal(err)
	}
	var store *casestore.Store
	if !*disableCaseStore {
		store, err = casestore.Open(*caseDB)
		if err != nil {
			fatal(err)
		}
		defer store.Close()
	}
	workspaceServer, err := workspace.NewServer(workspace.ServerConfig{
		Mode: *mode, FixturePath: *fixturePath, StaticDir: *staticDir,
		EventDelay: *eventDelay, RunTimeout: *timeout, CaseStore: store,
		Golden: golden.RunConfig{
			SnapshotPath: *snapshotPath, RetrievalPath: *retrievalPath,
			TraceDir: *traceDir, BaseURL: *baseURL, Model: *model,
			CodeCommit: *codeCommit, Timeout: *timeout, Prices: prices,
			ContextConcurrency: *contextConcurrency,
		},
	})
	if err != nil {
		fatal(err)
	}

	listener, err := net.Listen("tcp", *listenAddress)
	if err != nil {
		fatal(err)
	}
	httpServer := &http.Server{
		Handler: workspaceServer.Handler(), ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout: 15 * time.Second, WriteTimeout: 8 * time.Minute,
		IdleTimeout: 60 * time.Second,
	}
	shutdownSignal, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-shutdownSignal.Done()
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_ = httpServer.Shutdown(ctx)
	}()

	fmt.Fprintf(os.Stderr, "SignalForge workspace listening on http://%s (%s mode)\n", listener.Addr(), *mode)
	if err := httpServer.Serve(listener); err != nil && !errors.Is(err, http.ErrServerClosed) {
		fatal(err)
	}
}

func validateLoopbackListen(address string) error {
	host, _, err := net.SplitHostPort(address)
	if err != nil {
		return fmt.Errorf("parse --listen: %w", err)
	}
	if strings.EqualFold(host, "localhost") {
		return nil
	}
	ip := net.ParseIP(host)
	if ip == nil || !ip.IsLoopback() {
		return errors.New("--listen must use a loopback host; expose the workspace only through an authenticated tunnel")
	}
	return nil
}

func loadPrices(path string) ([]golden.PriceInput, error) {
	if strings.TrimSpace(path) == "" {
		return nil, nil
	}
	set, err := golden.LoadPriceSet(path)
	if err != nil {
		return nil, err
	}
	return set.Prices, nil
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
