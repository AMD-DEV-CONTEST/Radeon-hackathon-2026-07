package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/benchmark"
)

func TestRunCasesPreservesDeterministicOrderUnderConcurrency(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		var payload struct {
			Messages []benchmark.Message `json:"messages"`
		}
		if err := json.NewDecoder(request.Body).Decode(&payload); err != nil {
			http.Error(writer, err.Error(), http.StatusBadRequest)
			return
		}
		writer.Header().Set("Content-Type", "text/event-stream")
		fmt.Fprintf(writer, "data: {\"choices\":[{\"delta\":{\"content\":%q},\"finish_reason\":\"stop\"}],\"usage\":{\"prompt_tokens\":1,\"completion_tokens\":1,\"total_tokens\":2}}\n\n", payload.Messages[0].Content)
		fmt.Fprint(writer, "data: [DONE]\n\n")
	}))
	defer server.Close()

	cases := []benchmark.Case{
		{CaseID: "first", WorkloadClass: "test", Messages: []benchmark.Message{{Role: "user", Content: "first"}}, MaxTokens: 1},
		{CaseID: "second", WorkloadClass: "test", Messages: []benchmark.Message{{Role: "user", Content: "second"}}, MaxTokens: 1},
	}
	observations := runCases(benchmark.Client{BaseURL: server.URL}, "suite", "run", "model",
		cases, 2, time.Second, "fixture.json", false, 4)
	want := []string{"first-r01", "second-r01", "first-r02", "second-r02"}
	if len(observations) != len(want) {
		t.Fatalf("observations=%d want %d", len(observations), len(want))
	}
	for index, expected := range want {
		if observations[index].Row.CaseID != expected {
			t.Fatalf("observation[%d].case_id=%q want %q", index, observations[index].Row.CaseID, expected)
		}
		if !observations[index].Row.Success {
			t.Fatalf("observation[%d] failed: %+v", index, observations[index])
		}
	}
}
