package orchestrator

import (
	"context"
	"errors"
	"sync"
	"testing"

	"github.com/konspace/unionagents-go/packages/asset-substrate/lifememory"
)

// TestHookRegistry_RegisterAndFire: a registered hook is called when
// its event type fires, with the event map passed through verbatim.
func TestHookRegistry_RegisterAndFire(t *testing.T) {
	reg := NewHookRegistry()
	var got map[string]interface{}
	reg.Register("test.event", func(ctx context.Context, e map[string]interface{}) error {
		got = e
		return nil
	})

	reg.Fire(context.Background(), "test.event", map[string]interface{}{"k": "v"})

	if got == nil || got["k"] != "v" {
		t.Fatalf("hook did not receive event: %+v", got)
	}
}

// TestHookRegistry_MultipleHooksSameEvent: multiple hooks for one event
// all fire, in registration order.
func TestHookRegistry_MultipleHooksSameEvent(t *testing.T) {
	reg := NewHookRegistry()
	var order []string
	var mu sync.Mutex
	add := func(name string) {
		reg.Register("e", func(ctx context.Context, e map[string]interface{}) error {
			mu.Lock()
			order = append(order, name)
			mu.Unlock()
			return nil
		})
	}
	add("first")
	add("second")
	add("third")

	reg.Fire(context.Background(), "e", nil)

	if len(order) != 3 || order[0] != "first" || order[1] != "second" || order[2] != "third" {
		t.Fatalf("order = %v, want [first second third]", order)
	}
}

// TestHookRegistry_NoHooksForEvent: firing an event with no registered
// hooks is a no-op, not an error. (The system fires many event types;
// most have no listener.)
func TestHookRegistry_NoHooksForEvent(t *testing.T) {
	reg := NewHookRegistry()
	reg.Fire(context.Background(), "nobody.listening", map[string]interface{}{"x": 1})
	// Reaching here without panic is the assertion.
}

// TestHookRegistry_HookErrorDoesNotPropagate: a hook returning an error
// is logged but does NOT stop later hooks in the same event, nor does
// Fire return the error. This is the "best-effort" contract.
func TestHookRegistry_HookErrorDoesNotPropagate(t *testing.T) {
	reg := NewHookRegistry()
	var secondCalled bool
	reg.Register("e", func(ctx context.Context, e map[string]interface{}) error {
		return errors.New("boom")
	})
	reg.Register("e", func(ctx context.Context, e map[string]interface{}) error {
		secondCalled = true
		return nil
	})

	reg.Fire(context.Background(), "e", nil)

	if !secondCalled {
		t.Fatal("second hook did not run after first errored — best-effort broken")
	}
}

// TestHookRegistry_HookPanicDoesNotCrash: a panicking hook is recovered
// and logged; subsequent hooks still fire. A bad hook must not take down
// the orchestrator's request path.
func TestHookRegistry_HookPanicDoesNotCrash(t *testing.T) {
	reg := NewHookRegistry()
	var recovered bool
	reg.Register("e", func(ctx context.Context, e map[string]interface{}) error {
		panic("hook exploded")
	})
	reg.Register("e", func(ctx context.Context, e map[string]interface{}) error {
		recovered = true
		return nil
	})

	reg.Fire(context.Background(), "e", nil)

	if !recovered {
		t.Fatal("second hook did not run after first panicked")
	}
}

// TestTaskDoneHook_CreatesMemoryNode: when fired with a done task that
// has a summary, the hook creates a memory node tagged with the task id.
// Uses a real MemStore (not a mock) so the Insert path is exercised.
func TestTaskDoneHook_CreatesMemoryNode(t *testing.T) {
	store := lifememory.NewMemStore()
	hook := newTaskDoneMemoryHook(store)

	err := hook(context.Background(), map[string]interface{}{
		"task_id": "task-123",
		"title":   "deploy gateway",
		"summary": "rolled out v1.2.3, health checks green",
	})
	if err != nil {
		t.Fatalf("task.done hook: %v", err)
	}

	count, _ := store.Count()
	if count != 1 {
		t.Fatalf("store count = %d, want 1", count)
	}
	// The node should be findable by the task-id tag.
	nodes, _ := store.QueryByTag("task-123")
	if len(nodes) != 1 {
		t.Fatalf("QueryByTag(task-123) = %d nodes, want 1", len(nodes))
	}
	if nodes[0].Title != "deploy gateway" {
		t.Fatalf("node title = %q, want 'deploy gateway'", nodes[0].Title)
	}
	if nodes[0].Content != "rolled out v1.2.3, health checks green" {
		t.Fatalf("node content = %q", nodes[0].Content)
	}
}

// TestTaskDoneHook_SkipsWhenNoSummary: a done task with no summary
// produces no memory node. (No point recording "task finished, nothing
// to say".)
func TestTaskDoneHook_SkipsWhenNoSummary(t *testing.T) {
	store := lifememory.NewMemStore()
	hook := newTaskDoneMemoryHook(store)

	err := hook(context.Background(), map[string]interface{}{
		"task_id": "task-456",
		"title":   "noop task",
		// no summary
	})
	if err != nil {
		t.Fatalf("hook returned err on no-summary: %v", err)
	}

	if count, _ := store.Count(); count != 0 {
		t.Fatalf("expected 0 nodes for summaryless task, got %d", count)
	}
}

// TestSparkCompletedHook_CreatesMemoryNode: the spark hook creates a
// node tagged with "spark" + the spark id.
func TestSparkCompletedHook_CreatesMemoryNode(t *testing.T) {
	store := lifememory.NewMemStore()
	hook := newSparkCompletedMemoryHook(store)

	err := hook(context.Background(), map[string]interface{}{
		"spark_id": "spark-789",
		"title":    "auth refactor spark",
		"summary":  "moved to JWT, dropped session table",
	})
	if err != nil {
		t.Fatalf("spark.completed hook: %v", err)
	}

	nodes, _ := store.QueryByTags([]string{"spark", "spark-789"})
	if len(nodes) != 1 {
		t.Fatalf("QueryByTags([spark, spark-789]) = %d, want 1", len(nodes))
	}
	if nodes[0].Content != "moved to JWT, dropped session table" {
		t.Fatalf("content = %q", nodes[0].Content)
	}
}

// TestRegisterMemoryHooks: the convenience installer wires both hooks
// into a registry against the given store.
func TestRegisterMemoryHooks(t *testing.T) {
	reg := NewHookRegistry()
	store := lifememory.NewMemStore()
	RegisterMemoryHooks(reg, store)

	// Fire task.done → one node.
	reg.Fire(context.Background(), "task.done", map[string]interface{}{
		"task_id": "t1", "title": "T1", "summary": "done T1",
	})
	// Fire spark.completed → another node.
	reg.Fire(context.Background(), "spark.completed", map[string]interface{}{
		"spark_id": "s1", "title": "S1", "summary": "done S1",
	})

	if count, _ := store.Count(); count != 2 {
		t.Fatalf("expected 2 memory nodes, got %d", count)
	}
}
