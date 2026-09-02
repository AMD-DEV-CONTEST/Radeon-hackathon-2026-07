package telemetry

import (
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"

	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/semconv/v1.34.0"
	"go.opentelemetry.io/otel/trace"
)

type Config struct {
	Enabled        bool
	Endpoint       string
	Insecure       bool
	AllowPrivate   bool
	ServiceName    string
	ServiceVersion string
}

type Runtime struct {
	enabled  bool
	provider *sdktrace.TracerProvider
}

func LoadFromEnv(serviceVersion string) (Config, error) {
	enabled, err := parseBool("SIGNALFORGE_OTEL_ENABLED", os.Getenv("SIGNALFORGE_OTEL_ENABLED"))
	if err != nil {
		return Config{}, err
	}
	insecure, err := parseBool("SIGNALFORGE_OTEL_INSECURE", os.Getenv("SIGNALFORGE_OTEL_INSECURE"))
	if err != nil {
		return Config{}, err
	}
	allowPrivate, err := parseBool("SIGNALFORGE_OTEL_ALLOW_PRIVATE_NETWORK", os.Getenv("SIGNALFORGE_OTEL_ALLOW_PRIVATE_NETWORK"))
	if err != nil {
		return Config{}, err
	}
	config := Config{
		Enabled: enabled, Endpoint: strings.TrimSpace(os.Getenv("OTEL_EXPORTER_OTLP_ENDPOINT")),
		Insecure: insecure, AllowPrivate: allowPrivate,
		ServiceName: "signalforge-workspace", ServiceVersion: serviceVersion,
	}
	if !enabled {
		return config, nil
	}
	if config.Endpoint == "" {
		return Config{}, errors.New("enabled OpenTelemetry requires OTEL_EXPORTER_OTLP_ENDPOINT")
	}
	parsed, err := url.Parse(config.Endpoint)
	if err != nil || parsed.Hostname() == "" {
		return Config{}, errors.New("OTLP endpoint is invalid")
	}
	if insecure && !loopback(parsed.Hostname()) && !(allowPrivate && privateServiceName(parsed.Hostname())) {
		return Config{}, errors.New("insecure OTLP transport requires loopback or an explicitly allowed single-label private service")
	}
	if !insecure && parsed.Scheme != "https" {
		return Config{}, errors.New("external OTLP endpoint must use HTTPS")
	}
	return config, nil
}

func Setup(ctx context.Context, config Config) (*Runtime, error) {
	if !config.Enabled {
		return &Runtime{}, nil
	}
	options := []otlptracehttp.Option{otlptracehttp.WithEndpointURL(traceEndpointURL(config.Endpoint))}
	if config.Insecure {
		options = append(options, otlptracehttp.WithInsecure())
	}
	exporter, err := otlptracehttp.New(ctx, options...)
	if err != nil {
		return nil, fmt.Errorf("create OTLP trace exporter: %w", err)
	}
	res, err := resource.New(ctx,
		resource.WithAttributes(
			semconv.ServiceName(config.ServiceName),
			semconv.ServiceVersion(config.ServiceVersion),
			attribute.String("deployment.environment.name", "signalforge"),
		),
	)
	if err != nil {
		return nil, fmt.Errorf("create telemetry resource: %w", err)
	}
	provider := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter,
			sdktrace.WithBatchTimeout(time.Second),
			sdktrace.WithExportTimeout(3*time.Second),
			sdktrace.WithMaxExportBatchSize(256),
		),
		sdktrace.WithResource(res),
		sdktrace.WithSampler(sdktrace.ParentBased(sdktrace.AlwaysSample())),
	)
	otel.SetTracerProvider(provider)
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{}, propagation.Baggage{},
	))
	return &Runtime{enabled: true, provider: provider}, nil
}

func (runtime *Runtime) Shutdown(ctx context.Context) error {
	if runtime == nil || runtime.provider == nil {
		return nil
	}
	return runtime.provider.Shutdown(ctx)
}

func (runtime *Runtime) WrapHTTP(handler http.Handler) http.Handler {
	if runtime == nil || !runtime.enabled {
		return handler
	}
	return otelhttp.NewHandler(handler, "signalforge.http",
		otelhttp.WithMessageEvents(otelhttp.ReadEvents, otelhttp.WriteEvents))
}

func StartJourney(parent context.Context, runID, requestID, mode string) (context.Context, trace.Span) {
	if parent == nil {
		parent = context.Background()
	}
	if !trace.SpanContextFromContext(parent).IsValid() {
		traceID, err := trace.TraceIDFromHex(TraceIDForRun(runID))
		if err == nil {
			parent = trace.ContextWithRemoteSpanContext(parent, trace.NewSpanContext(trace.SpanContextConfig{
				TraceID:    traceID,
				SpanID:     deterministicParentSpanID(runID),
				TraceFlags: trace.FlagsSampled,
				Remote:     true,
			}))
		}
	}
	return otel.Tracer("signalforge/journey").Start(parent, "signalforge.journey",
		trace.WithAttributes(
			attribute.String("signalforge.run_id", runID),
			attribute.String("signalforge.request_id", requestID),
			attribute.String("signalforge.execution.mode", mode),
		))
}

func parseBool(name, value string) (bool, error) {
	value = strings.TrimSpace(value)
	if value == "" {
		return false, nil
	}
	parsed, err := strconv.ParseBool(value)
	if err != nil {
		return false, fmt.Errorf("%s must be true or false", name)
	}
	return parsed, nil
}

// TraceIDForRun is the canonical public-to-W3C trace identity mapping.
func TraceIDForRun(runID string) string {
	sum := sha256.Sum256([]byte("trace:" + runID))
	return fmt.Sprintf("%x", sum[:16])
}

func deterministicParentSpanID(runID string) trace.SpanID {
	sum := sha256.Sum256([]byte("parent-span:" + runID))
	var spanID trace.SpanID
	copy(spanID[:], sum[:8])
	return spanID
}

func traceEndpointURL(endpoint string) string {
	parsed, err := url.Parse(endpoint)
	if err != nil {
		return endpoint
	}
	if parsed.Path == "" || parsed.Path == "/" {
		parsed.Path = "/v1/traces"
	}
	return parsed.String()
}

func loopback(host string) bool {
	if strings.EqualFold(host, "localhost") {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func privateServiceName(host string) bool {
	if host == "" || strings.ContainsAny(host, ".:/") || len(host) > 63 {
		return false
	}
	for _, character := range host {
		if character >= 'a' && character <= 'z' || character >= 'A' && character <= 'Z' ||
			character >= '0' && character <= '9' || character == '-' {
			continue
		}
		return false
	}
	return host[0] != '-' && host[len(host)-1] != '-'
}
