package workspace

import (
	"bufio"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestFixtureServerSustainsExpectedDemoReadLoad(t *testing.T) {
	server, err := NewServer(ServerConfig{
		Mode:        ModeFixture,
		FixturePath: filepath.Join("..", "..", "fixtures", "workspace", "golden-case.json"),
		CatalogPath: filepath.Join("..", "..", "fixtures", "productscope", "technology20-catalog.json"),
		EventDelay:  0,
		RunTimeout:  time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}
	httpServer := httptest.NewServer(server.Handler())
	defer httpServer.Close()

	paths := []string{"/health/live", "/health/ready", "/api/v1/health", "/api/v1/config", "/api/v1/catalog", "/api/v1/financials", "/api/v1/peer-evaluations", "/api/v1/cases/golden"}
	const requests = 96
	started := time.Now()
	errors := make(chan error, requests)
	var wait sync.WaitGroup
	for index := 0; index < requests; index++ {
		wait.Add(1)
		go func(path string) {
			defer wait.Done()
			response, requestErr := http.Get(httpServer.URL + path)
			if requestErr != nil {
				errors <- requestErr
				return
			}
			defer response.Body.Close()
			if response.StatusCode != http.StatusOK {
				errors <- fmt.Errorf("%s returned %s", path, response.Status)
			}
		}(paths[index%len(paths)])
	}
	wait.Wait()
	close(errors)
	for err := range errors {
		t.Fatal(err)
	}
	if elapsed := time.Since(started); elapsed > 5*time.Second {
		t.Fatalf("fixture demo read load took %s", elapsed)
	}
}

func TestFixtureServerSustainsConcurrentDashboardJourneys(t *testing.T) {
	server, err := NewServer(ServerConfig{
		Mode:        ModeFixture,
		FixturePath: filepath.Join("..", "..", "fixtures", "workspace", "golden-case.json"),
		CatalogPath: filepath.Join("..", "..", "fixtures", "productscope", "technology20-catalog.json"),
		EventDelay:  2 * time.Millisecond,
		RunTimeout:  time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}
	httpServer := httptest.NewServer(server.Handler())
	defer httpServer.Close()

	type journeyResult struct {
		runID      string
		eventCount int
		err        error
	}
	const journeys = 12
	client := &http.Client{Timeout: 20 * time.Second}
	results := make(chan journeyResult, journeys)
	started := time.Now()
	for index := 0; index < journeys; index++ {
		go func(index int) {
			payload := fmt.Sprintf(`{"question":"Compare Microsoft and NVIDIA for dashboard journey %d."}`, index)
			response, requestErr := client.Post(httpServer.URL+"/api/v1/runs", "application/json", strings.NewReader(payload))
			if requestErr != nil {
				results <- journeyResult{err: requestErr}
				return
			}
			var run RunView
			decodeErr := json.NewDecoder(response.Body).Decode(&run)
			response.Body.Close()
			if response.StatusCode != http.StatusAccepted {
				results <- journeyResult{err: fmt.Errorf("create run returned %s", response.Status)}
				return
			}
			if decodeErr != nil {
				results <- journeyResult{err: decodeErr}
				return
			}

			stream, streamErr := client.Get(httpServer.URL + "/api/v1/runs/" + run.RunID + "/events")
			if streamErr != nil {
				results <- journeyResult{runID: run.RunID, err: streamErr}
				return
			}
			scanner := bufio.NewScanner(stream.Body)
			eventCount := 0
			terminal := false
			for scanner.Scan() {
				line := scanner.Text()
				if !strings.HasPrefix(line, "data: ") {
					continue
				}
				var event StreamEvent
				if err := json.Unmarshal([]byte(strings.TrimPrefix(line, "data: ")), &event); err != nil {
					stream.Body.Close()
					results <- journeyResult{runID: run.RunID, err: err}
					return
				}
				eventCount++
				if event.Type == "workspace" && event.Status == "completed" {
					terminal = true
				}
			}
			stream.Body.Close()
			if err := scanner.Err(); err != nil {
				results <- journeyResult{runID: run.RunID, err: err}
				return
			}
			if !terminal {
				results <- journeyResult{runID: run.RunID, err: fmt.Errorf("terminal event was not observed")}
				return
			}
			results <- journeyResult{runID: run.RunID, eventCount: eventCount}
		}(index)
	}

	seen := map[string]bool{}
	for index := 0; index < journeys; index++ {
		result := <-results
		if result.err != nil {
			t.Fatal(result.err)
		}
		if result.runID == "" || seen[result.runID] {
			t.Fatalf("invalid or duplicate run id %q", result.runID)
		}
		seen[result.runID] = true
		if result.eventCount < 8 || result.eventCount > maximumStoredRunEvents {
			t.Fatalf("run %s streamed %d events", result.runID, result.eventCount)
		}
		runResponse, requestErr := client.Get(httpServer.URL + "/api/v1/runs/" + result.runID)
		if requestErr != nil {
			t.Fatal(requestErr)
		}
		var run RunView
		decodeErr := json.NewDecoder(runResponse.Body).Decode(&run)
		runResponse.Body.Close()
		if decodeErr != nil {
			t.Fatal(decodeErr)
		}
		if run.Status != "completed" || run.Execution == nil || run.Execution.Status != "passed" {
			t.Fatalf("run %s did not preserve a completed execution projection: %+v", result.runID, run.Execution)
		}
	}
	// The complete verifier runs this test under the race detector, whose HTTP and
	// synchronization instrumentation is intentionally much slower than production.
	// Keep the gate below the 30-second product SLA without making race-enabled CI
	// depend on host scheduling near an arbitrary five-second client timeout.
	if elapsed := time.Since(started); elapsed > 20*time.Second {
		t.Fatalf("%d concurrent dashboard journeys took %s", journeys, elapsed)
	} else {
		t.Logf("%d concurrent dashboard journeys completed in %s", journeys, elapsed)
	}
}

func TestLongJourneyRetainsBoundedOperationalState(t *testing.T) {
	server := newFixtureTestServer(t)
	record, err := server.newRun("", false)
	if err != nil {
		t.Fatal(err)
	}
	const published = maximumStoredRunEvents * 4
	for sequence := 1; sequence <= published; sequence++ {
		server.publish(record, StreamEvent{
			Type:   "plan",
			Status: "accepted",
			Label:  "Bounded synthetic lifecycle event",
			Attributes: map[string]string{
				"plan_id": fmt.Sprintf("plan-%03d", sequence),
			},
		})
	}

	server.mu.RLock()
	events := append([]StreamEvent(nil), record.events...)
	execution := cloneExecutionPlanPointer(record.execution)
	view := record.view
	server.mu.RUnlock()
	if len(events) != maximumStoredRunEvents {
		t.Fatalf("retained events = %d, expected %d", len(events), maximumStoredRunEvents)
	}
	expectedFirst := published - maximumStoredRunEvents + 1
	if events[0].Sequence != expectedFirst || events[len(events)-1].Sequence != published {
		t.Fatalf("retained sequence range = %d..%d, expected %d..%d",
			events[0].Sequence, events[len(events)-1].Sequence, expectedFirst, published)
	}
	payload, err := json.Marshal(struct {
		Events    []StreamEvent `json:"events"`
		Execution any           `json:"execution"`
		View      RunView       `json:"view"`
	}{Events: events, Execution: execution, View: view})
	if err != nil {
		t.Fatal(err)
	}
	if len(payload) > 512<<10 {
		t.Fatalf("bounded retained state = %d bytes, expected <= 512 KiB", len(payload))
	}
	t.Logf("retained events=%d sequence=%d..%d serialized_state_bytes=%d",
		len(events), events[0].Sequence, events[len(events)-1].Sequence, len(payload))
}

func TestCompletedRunWindowIsBoundedWithoutEvictingActiveRuns(t *testing.T) {
	server := newFixtureTestServer(t)
	var activeRunID string
	for index := 0; index < maximumStoredRuns*2; index++ {
		record, err := server.newRun("", false)
		if err != nil {
			t.Fatal(err)
		}
		server.mu.Lock()
		if index == maximumStoredRuns {
			activeRunID = record.view.RunID
		} else {
			record.view.Status = "completed"
			server.evictCompletedRunsLocked()
		}
		server.mu.Unlock()
	}
	server.mu.RLock()
	stored := len(server.runs)
	_, activePreserved := server.runs[activeRunID]
	orderLength := len(server.runOrder)
	server.mu.RUnlock()
	if stored > maximumStoredRuns+1 {
		t.Fatalf("stored runs = %d, expected no more than %d completed plus one active", stored, maximumStoredRuns)
	}
	if !activePreserved {
		t.Fatal("active run was evicted")
	}
	if orderLength != stored {
		t.Fatalf("run order = %d, stored runs = %d", orderLength, stored)
	}
	t.Logf("completed run window retained %d records with active run preserved", stored)
}
