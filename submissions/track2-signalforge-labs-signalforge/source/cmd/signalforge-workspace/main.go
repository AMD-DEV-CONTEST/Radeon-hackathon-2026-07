package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/rvbernucci/signalforge/internal/casestore"
	"github.com/rvbernucci/signalforge/internal/golden"
	"github.com/rvbernucci/signalforge/internal/intelligenceaudit"
	"github.com/rvbernucci/signalforge/internal/modelapi"
	"github.com/rvbernucci/signalforge/internal/telemetry"
	"github.com/rvbernucci/signalforge/internal/workspace"
)

var buildCommit = "working-tree"

func main() {
	listenAddress := flag.String("listen", "127.0.0.1:8080", "loopback HTTP listen address")
	allowContainerListen := flag.Bool("allow-container-listen", false, "allow a non-loopback listener for an explicitly host-bound container")
	mode := flag.String("mode", workspace.ModeFixture, "workspace mode: fixture or live")
	fixturePath := flag.String("fixture", "fixtures/workspace/golden-case.json", "safe public workspace fixture")
	catalogPath := flag.String("catalog", "fixtures/productscope/technology20-catalog.json", "public-safe Technology 20 catalog")
	staticDir := flag.String("static-dir", "", "optional built frontend directory")
	eventDelay := flag.Duration("event-delay", 100*time.Millisecond, "fixture progress-event replay delay")
	snapshotPath := flag.String("snapshot", "fixtures/golden/financial-snapshot.json", "frozen point-in-time financial snapshot")
	retrievalPath := flag.String("retrieval", "fixtures/retrieval/golden-eval.json", "frozen authoritative qualitative evidence")
	priceInputsPath := flag.String("price-inputs", "fixtures/golden/market-price-inputs.json", "frozen point-in-time price-set JSON")
	traceDir := flag.String("trace-dir", ".signalforge/traces", "private live trace directory")
	caseDB := flag.String("case-db", ".signalforge/cases.db", "private local SQLite research-case database")
	disableCaseStore := flag.Bool("disable-case-store", false, "disable durable local case retention")
	auditDir := flag.String("audit-dir", ".signalforge/intelligence-audit", "private intelligence-lineage directory")
	auditCapture := flag.Bool("audit-capture", false, "capture sanitized prompt and response bodies for the local operator")
	auditTokenFile := flag.String("audit-token-file", "", "read protected audit inspector token from this file")
	auditTTL := flag.Duration("audit-ttl", 15*time.Minute, "protected audit artifact retention")
	auditMaxBytes := flag.Int64("audit-max-bytes", 16<<20, "maximum protected audit bytes per run")
	eventLog := flag.String("event-log", "", "optional privacy-safe JSONL event log for a local collector")
	baseURL := flag.String("base-url", "http://127.0.0.1:8000/v1", "loopback-local OpenAI-compatible endpoint")
	model := flag.String("model", "signalforge-gemma4-26b-q4", "local model identifier")
	codeCommit := flag.String("code-commit", buildCommit, "code revision recorded in receipts")
	timeout := flag.Duration("timeout", 6*time.Minute, "complete local run timeout")
	contextConcurrency := flag.Int("context-concurrency", 4, "concurrent local specialist calls, from 1 to 4")
	flag.Parse()

	if err := validateListen(*listenAddress, *allowContainerListen); err != nil {
		fatal(err)
	}
	logWriter, closeLog, err := openEventLog(*eventLog)
	if err != nil {
		fatal(err)
	}
	defer closeLog()
	auditToken, err := loadAuditToken(*auditTokenFile, *auditCapture)
	if err != nil {
		fatal(err)
	}
	auditStore, err := intelligenceaudit.NewStore(intelligenceaudit.Config{
		Directory: *auditDir, Enabled: *auditCapture, Token: auditToken,
		TTL: *auditTTL, MaxBytes: *auditMaxBytes, LogWriter: logWriter,
	})
	if err != nil {
		fatal(err)
	}
	telemetryConfig, err := telemetry.LoadFromEnv(*codeCommit)
	if err != nil {
		fatal(err)
	}
	telemetryRuntime, err := telemetry.Setup(context.Background(), telemetryConfig)
	if err != nil {
		fatal(err)
	}
	defer func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = telemetryRuntime.Shutdown(ctx)
	}()
	specialist, err := modelapi.LoadFromEnv()
	if err != nil {
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
		Mode: *mode, FixturePath: *fixturePath, CatalogPath: *catalogPath, StaticDir: *staticDir,
		EventDelay: *eventDelay, RunTimeout: *timeout, CaseStore: store,
		AuditStore: auditStore, BuildVersion: *codeCommit,
		Golden: golden.RunConfig{
			SnapshotPath: *snapshotPath, RetrievalPath: *retrievalPath,
			TraceDir: *traceDir, BaseURL: *baseURL, Model: *model,
			CodeCommit: *codeCommit, Timeout: *timeout, Prices: prices,
			ContextConcurrency: *contextConcurrency,
			SpecialistProvider: specialist.Provider, SpecialistBaseURL: specialist.BaseURL,
			SpecialistModel: specialist.TextModel, SpecialistAPIKey: specialist.APIKey,
			SpecialistHTTPClient: specialistHTTPClient(specialist),
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
		Handler: telemetryRuntime.WrapHTTP(workspaceServer.Handler()), ReadHeaderTimeout: 5 * time.Second,
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

func loadAuditToken(path string, enabled bool) (string, error) {
	path = strings.TrimSpace(path)
	if !enabled {
		if path != "" {
			return "", errors.New("--audit-token-file requires --audit-capture")
		}
		return "", nil
	}
	if path == "" {
		return "", errors.New("--audit-capture requires --audit-token-file")
	}
	payload, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Errorf("read audit token file: %w", err)
	}
	token := strings.TrimSpace(string(payload))
	if token == "" {
		return "", errors.New("audit token file is empty")
	}
	return token, nil
}

func specialistHTTPClient(config modelapi.Config) *http.Client {
	if !config.Enabled {
		return nil
	}
	return &http.Client{Timeout: config.Timeout}
}

func validateLoopbackListen(address string) error {
	return validateListen(address, false)
}

func validateListen(address string, allowContainerListen bool) error {
	host, _, err := net.SplitHostPort(address)
	if err != nil {
		return fmt.Errorf("parse --listen: %w", err)
	}
	if allowContainerListen {
		ip := net.ParseIP(host)
		if host == "" || ip != nil {
			return nil
		}
		return errors.New("--listen host must be an IP address when --allow-container-listen is enabled")
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

func openEventLog(path string) (io.Writer, func(), error) {
	path = strings.TrimSpace(path)
	if path == "" {
		return os.Stdout, func() {}, nil
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return nil, func() {}, fmt.Errorf("create event log directory: %w", err)
	}
	file, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o600)
	if err != nil {
		return nil, func() {}, fmt.Errorf("open event log: %w", err)
	}
	return io.MultiWriter(os.Stdout, file), func() { _ = file.Close() }, nil
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
