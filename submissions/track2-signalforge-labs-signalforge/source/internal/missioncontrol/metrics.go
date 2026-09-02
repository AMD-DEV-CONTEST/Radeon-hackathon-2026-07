package missioncontrol

import (
	"fmt"
	"net/http"
	"sort"
	"strconv"
	"strings"

	"github.com/rvbernucci/signalforge/internal/intelligenceaudit"
)

type MetricsHandler struct {
	Store   *intelligenceaudit.Store
	Version string
}

func (handler MetricsHandler) ServeHTTP(writer http.ResponseWriter, _ *http.Request) {
	writer.Header().Set("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
	writer.Header().Set("Cache-Control", "no-store")
	records := []intelligenceaudit.Record{}
	if handler.Store != nil {
		records = handler.Store.Snapshot()
	}
	metrics := aggregate(records)
	fmt.Fprintln(writer, "# HELP signalforge_build_info SignalForge build identity.")
	fmt.Fprintln(writer, "# TYPE signalforge_build_info gauge")
	fmt.Fprintf(writer, "signalforge_build_info{version=%s} 1\n", quoteLabel(bounded(handler.Version, 96)))
	writeCounter(writer, "signalforge_journeys_total", "Completed and active SignalForge journeys.", metrics.journeys)
	writeHistogram(writer, "signalforge_journey_duration_seconds", "End-to-end journey duration.", metrics.journeyDuration)
	writeCounter(writer, "signalforge_model_calls_total", "Model calls by bounded execution dimensions.", metrics.modelCalls)
	writeHistogram(writer, "signalforge_model_call_duration_seconds", "Model call duration.", metrics.modelDuration)
	writeCounter(writer, "signalforge_model_tokens_total", "Model input and output tokens.", metrics.tokens)
	writeCounter(writer, "signalforge_retrievals_total", "Retrieval and context compilation executions.", metrics.retrievals)
	writeCounter(writer, "signalforge_engine_calls_total", "Deterministic engine calls.", metrics.engines)
	writeCounter(writer, "signalforge_releases_total", "Final release-gate outcomes.", metrics.releases)
	fmt.Fprintln(writer, "# HELP signalforge_audit_capture_bytes Protected audit bytes currently retained.")
	fmt.Fprintln(writer, "# TYPE signalforge_audit_capture_bytes gauge")
	fmt.Fprintf(writer, "signalforge_audit_capture_bytes %d\n", metrics.captureBytes)
}

type aggregateMetrics struct {
	journeys        map[string]float64
	journeyDuration map[string]histogramValue
	modelCalls      map[string]float64
	modelDuration   map[string]histogramValue
	tokens          map[string]float64
	retrievals      map[string]float64
	engines         map[string]float64
	releases        map[string]float64
	captureBytes    int64
}

type histogramValue struct {
	count float64
	sum   float64
}

func aggregate(records []intelligenceaudit.Record) aggregateMetrics {
	result := aggregateMetrics{
		journeys: map[string]float64{}, journeyDuration: map[string]histogramValue{},
		modelCalls: map[string]float64{}, modelDuration: map[string]histogramValue{},
		tokens: map[string]float64{}, retrievals: map[string]float64{},
		engines: map[string]float64{}, releases: map[string]float64{},
	}
	for _, record := range records {
		status := enum(record.Status, []string{"running", "completed", "failed", "cancelled"})
		capture := enum(record.Capture.Status, []string{"disabled", "active", "expired", "purged", "capacity_exceeded"})
		journeyLabels := labels("status", status, "capture", capture)
		result.journeys[journeyLabels]++
		result.captureBytes += record.Capture.StoredBytes
		if record.CompletedAt != nil && !record.CompletedAt.Before(record.StartedAt) {
			value := result.journeyDuration[journeyLabels]
			value.count++
			value.sum += record.CompletedAt.Sub(record.StartedAt).Seconds()
			result.journeyDuration[journeyLabels] = value
		}
		for _, call := range record.ModelCalls {
			callLabels := labels(
				"role_class", enum(call.RoleClass, []string{"interpreter", "planner", "context", "review", "synthesis"}),
				"provider", enum(call.ProviderID, []string{"local-rocm", "radeon-vllm"}),
				"route", enum(call.Route, []string{"local_rocm", "provided_radeon_api"}),
				"status", enum(call.Status, []string{"completed", "failed"}),
			)
			result.modelCalls[callLabels]++
			duration := result.modelDuration[callLabels]
			duration.count++
			duration.sum += call.DurationMS / 1000
			result.modelDuration[callLabels] = duration
			inputLabels := labels("direction", "input", "provider", enum(call.ProviderID, []string{"local-rocm", "radeon-vllm"}), "role_class", enum(call.RoleClass, []string{"interpreter", "planner", "context", "review", "synthesis"}))
			outputLabels := labels("direction", "output", "provider", enum(call.ProviderID, []string{"local-rocm", "radeon-vllm"}), "role_class", enum(call.RoleClass, []string{"interpreter", "planner", "context", "review", "synthesis"}))
			result.tokens[inputLabels] += float64(call.InputTokens)
			result.tokens[outputLabels] += float64(call.OutputTokens)
		}
		for _, retrieval := range record.Retrievals {
			key := labels("method", enum(retrieval.Method, []string{"authorized_context_packet", "public_fixture", "bm25", "dense", "rrf", "hyde", "graphrag"}), "status", enum(retrieval.Status, []string{"selected", "completed", "failed", "degraded"}))
			result.retrievals[key]++
		}
		for _, engine := range record.Engines {
			key := labels("engine", engineClass(engine.EngineID, engine.OperationID), "status", enum(engine.Status, []string{"success", "partial", "refused", "invalid", "non_convergent"}))
			result.engines[key]++
		}
		if record.Release != nil {
			result.releases[labels("status", enum(record.Release.Status, []string{"released", "rejected", "abstained"}))]++
		}
	}
	return result
}

func writeCounter(writer http.ResponseWriter, name, help string, values map[string]float64) {
	fmt.Fprintf(writer, "# HELP %s %s\n", name, help)
	fmt.Fprintf(writer, "# TYPE %s counter\n", name)
	for _, key := range sortedKeys(values) {
		fmt.Fprintf(writer, "%s%s %s\n", name, key, strconv.FormatFloat(values[key], 'f', -1, 64))
	}
}

func writeHistogram(writer http.ResponseWriter, name, help string, values map[string]histogramValue) {
	fmt.Fprintf(writer, "# HELP %s %s\n", name, help)
	fmt.Fprintf(writer, "# TYPE %s summary\n", name)
	for _, key := range sortedHistogramKeys(values) {
		fmt.Fprintf(writer, "%s_count%s %s\n", name, key, strconv.FormatFloat(values[key].count, 'f', -1, 64))
		fmt.Fprintf(writer, "%s_sum%s %s\n", name, key, strconv.FormatFloat(values[key].sum, 'f', -1, 64))
	}
}

func labels(values ...string) string {
	parts := make([]string, 0, len(values)/2)
	for index := 0; index+1 < len(values); index += 2 {
		parts = append(parts, values[index]+"="+quoteLabel(values[index+1]))
	}
	return "{" + strings.Join(parts, ",") + "}"
}

func quoteLabel(value string) string {
	return strconv.Quote(strings.NewReplacer("\\", "\\\\", "\n", "\\n").Replace(value))
}

func enum(value string, allowed []string) string {
	for _, candidate := range allowed {
		if value == candidate {
			return value
		}
	}
	return "unknown"
}

func engineClass(engineID, operationID string) string {
	for _, value := range []string{engineID, operationID} {
		for _, candidate := range []string{"financial", "valuation", "economics", "market", "comparison", "scenario", "accounting", "validation", "rendering"} {
			if value == candidate || strings.HasPrefix(value, candidate+".") || strings.Contains(value, candidate) {
				return candidate
			}
		}
	}
	return "other"
}

func bounded(value string, maximum int) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return "unknown"
	}
	if len(value) > maximum {
		return value[:maximum]
	}
	return value
}

func sortedKeys(values map[string]float64) []string {
	result := make([]string, 0, len(values))
	for key := range values {
		result = append(result, key)
	}
	sort.Strings(result)
	return result
}

func sortedHistogramKeys(values map[string]histogramValue) []string {
	result := make([]string, 0, len(values))
	for key := range values {
		result = append(result, key)
	}
	sort.Strings(result)
	return result
}
