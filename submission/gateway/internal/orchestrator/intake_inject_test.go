package orchestrator

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/konspace/unionagents-go/internal/ironlaw"
)

// TestPrepareInject_PriorityMapping: the priority_level field on an
// inject request maps to the DB int priority via PriorityToInt. This
// is the contract InjectTask uses to translate the semantic level into
// the tasks.priority column value.
func TestPrepareInject_PriorityMapping(t *testing.T) {
	cases := []struct {
		level string
		want  int
	}{
		{"high", PriorityToInt(PriorityHigh)},
		{"medium", PriorityToInt(PriorityMedium)},
		{"low", PriorityToInt(PriorityLow)},
		{"", PriorityToInt(PriorityMedium)},       // default medium
		{"garbage", PriorityToInt(PriorityMedium)}, // unknown → medium
		{"HIGH", PriorityToInt(PriorityHigh)},     // case-insensitive
	}
	for _, c := range cases {
		req := InjectRequest{Title: "t", PriorityLevel: c.level}
		_, dbPriority, _ := prepareInject(req)
		if dbPriority != c.want {
			t.Fatalf("priority_level=%q → dbPriority=%d, want %d", c.level, dbPriority, c.want)
		}
	}
}

// TestPrepareInject_SourceDefaultsToAPI: when source is empty it defaults
// to "api"; a non-empty source is preserved. The source becomes the
// tasks.created_by value, which is how we distinguish injected tasks
// (scanner/chain/recovery) from user-created ones (api).
func TestPrepareInject_SourceDefaultsToAPI(t *testing.T) {
	if _, _, createdBy := prepareInject(InjectRequest{Title: "t"}); createdBy != "api" {
		t.Fatalf("empty source → createdBy=%q, want api", createdBy)
	}
	if _, _, createdBy := prepareInject(InjectRequest{Title: "t", Source: "scanner"}); createdBy != "scanner" {
		t.Fatalf("source=scanner → createdBy=%q, want scanner", createdBy)
	}
}

// TestPrepareInject_ClassifiesAndStampsCategory: prepareInject runs the
// task through ironlaw.ClassifyTask and returns the category, which
// InjectTask will stamp into payload.task_category. This is the
// "inject still classifies, even though it skips the ILS gate" guarantee.
func TestPrepareInject_ClassifiesAndStampsCategory(t *testing.T) {
	cases := []struct {
		name     string
		taskType string
		title    string
		desc     string
		want     ironlaw.TaskCategory
	}{
		{"ops_keyword", "", "restart", "systemctl restart nginx", ironlaw.CategoryOpsMaintenance},
		{"execution_keyword", "", "build", "go build ./...", ironlaw.CategoryExecution},
		{"explicit_chat", "chat", "reply", "", ironlaw.CategoryChat},
		{"default_coding", "", "vague", "no signal here", ironlaw.CategoryCoding},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			req := InjectRequest{Title: c.title, Description: c.desc, TaskType: c.taskType}
			cat, _, _ := prepareInject(req)
			if cat != c.want {
				t.Fatalf("category = %q, want %q", cat, c.want)
			}
		})
	}
}

// TestInjectTask_SkipsILSGate: the defining behavior of /tasks/inject —
// a task that CreateTask would REJECT (missing context.goal, ILS Rule 1)
// must be ACCEPTED by inject. We assert this by checking that inject's
// response is not the ILS_GATE 422 shape CreateTask produces, but
// instead the inject success shape (201 + category field).
//
// This test needs a real PG to complete the INSERT; without one it
// skips rather than pretending the DB path works.
func TestInjectTask_SkipsILSGate(t *testing.T) {
	pool := testPool(t)
	SetPool(pool)
	t.Cleanup(func() { SetPool(nil) })

	// A task CreateTask would reject: no payload.context.goal → Rule 1.
	body, _ := json.Marshal(InjectRequest{
		Title:       "inject-skip-gate-test",
		Description: "no context.goal, would fail ILS Rule 1",
		TaskType:    "coding",
	})
	req := httptest.NewRequest(http.MethodPost, "/tasks/inject", bytes.NewReader(body))
	rec := httptest.NewRecorder()

	InjectTask(rec, req)

	if rec.Code == http.StatusUnprocessableEntity {
		t.Fatalf("inject returned 422 — ILS gate fired, but inject must skip it. body=%s", rec.Body.String())
	}
	if rec.Code != http.StatusCreated {
		t.Fatalf("inject status = %d, want 201. body=%s", rec.Code, rec.Body.String())
	}
	var resp struct {
		TaskID   string `json:"task_id"`
		Status   string `json:"status"`
		Category string `json:"category"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode inject response: %v (body=%s)", err, rec.Body.String())
	}
	if resp.Status != "queued" {
		t.Fatalf("inject status field = %q, want queued", resp.Status)
	}
	if resp.Category == "" {
		t.Fatal("inject response missing category field")
	}
	if resp.TaskID == "" {
		t.Fatal("inject response missing task_id")
	}

	// Verify the row landed in the DB with the category stamped in payload
	// and created_by set to the default source.
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	var dbStatus, dbCreatedBy string
	var dbPayload []byte
	err := pool.QueryRow(ctx,
		`SELECT status, created_by, payload FROM tasks WHERE id = $1`, resp.TaskID,
	).Scan(&dbStatus, &dbCreatedBy, &dbPayload)
	if err != nil {
		t.Fatalf("query injected task: %v", err)
	}
	t.Cleanup(func() {
		pool.Exec(context.Background(), `DELETE FROM tasks WHERE id = $1`, resp.TaskID)
	})
	if dbStatus != "queued" {
		t.Fatalf("DB status = %q, want queued", dbStatus)
	}
	if dbCreatedBy != "api" {
		t.Fatalf("DB created_by = %q, want api (default source)", dbCreatedBy)
	}
	var p map[string]interface{}
	if err := json.Unmarshal(dbPayload, &p); err != nil {
		t.Fatalf("decode payload: %v", err)
	}
	if p["task_category"] != resp.Category {
		t.Fatalf("payload.task_category = %v, want %q", p["task_category"], resp.Category)
	}
}

// TestInjectTask_PriorityLevelHighWritesHighDBPriority: priority_level=high
// on the request must produce tasks.priority == PriorityToInt(High) in
// the DB row. PG-backed; skips without a DB.
func TestInjectTask_PriorityLevelHighWritesHighDBPriority(t *testing.T) {
	pool := testPool(t)
	SetPool(pool)
	t.Cleanup(func() { SetPool(nil) })

	body, _ := json.Marshal(InjectRequest{
		Title:         "inject-high-priority-test",
		PriorityLevel: "high",
	})
	req := httptest.NewRequest(http.MethodPost, "/tasks/inject", bytes.NewReader(body))
	rec := httptest.NewRecorder()
	InjectTask(rec, req)
	if rec.Code != http.StatusCreated {
		t.Fatalf("inject status = %d, want 201. body=%s", rec.Code, rec.Body.String())
	}
	var resp struct{ TaskID string `json:"task_id"` }
	json.Unmarshal(rec.Body.Bytes(), &resp)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	var dbPriority int
	pool.QueryRow(ctx, `SELECT priority FROM tasks WHERE id = $1`, resp.TaskID).Scan(&dbPriority)
	t.Cleanup(func() {
		pool.Exec(context.Background(), `DELETE FROM tasks WHERE id = $1`, resp.TaskID)
	})
	if dbPriority != PriorityToInt(PriorityHigh) {
		t.Fatalf("DB priority = %d, want %d (high)", dbPriority, PriorityToInt(PriorityHigh))
	}
}

// TestInjectTask_RejectsMissingTitle: a request with no title gets a 400,
// matching CreateTask's validation. Title is the one required field even
// on the gate-skipping inject path — everything else has defaults.
func TestInjectTask_RejectsMissingTitle(t *testing.T) {
	body, _ := json.Marshal(InjectRequest{Description: "no title"})
	req := httptest.NewRequest(http.MethodPost, "/tasks/inject", bytes.NewReader(body))
	rec := httptest.NewRecorder()
	InjectTask(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("missing-title status = %d, want 400. body=%s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "title") {
		t.Fatalf("missing-title body should mention title: %s", rec.Body.String())
	}
}

// TestInjectTask_MethodNotAllowed: GET on /tasks/inject returns 405,
// matching CreateTask's method guard.
func TestInjectTask_MethodNotAllowed(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/tasks/inject", nil)
	rec := httptest.NewRecorder()
	InjectTask(rec, req)
	if rec.Code != http.StatusMethodNotAllowed {
		t.Fatalf("GET inject status = %d, want 405", rec.Code)
	}
}
