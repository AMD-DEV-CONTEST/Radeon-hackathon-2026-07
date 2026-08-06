package orchestrator

import (
	"context"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"github.com/konspace/unionagents-go/packages/asset-substrate/lifememory"
)

// Phase 3.3: protocol-coordination hooks.
//
// The orchestrator emits events from several protocols (task FSM, spark,
// memory, agent phase-change). A HookRegistry lets one protocol's event
// trigger side effects in another WITHOUT the emitter knowing about the
// receiver. Today the only wiring is "task/spark completion → persist a
// life-memory node"; the registry is general so future hooks (decision
// recorded → link memory, etc.) plug in the same way.
//
// Contract: hooks are BEST-EFFORT. A hook error or panic is logged and
// swallowed — it must never block the event that fired it. A memory
// write failing should not roll back a task completion.

// ProtocolHook is a side effect triggered by an event. The event map
// carries whatever fields the emitter chose to publish; the hook reads
// the keys it cares about and ignores the rest.
type ProtocolHook func(ctx context.Context, event map[string]interface{}) error

// HookRegistry maps event_type → ordered list of hooks. Safe for
// concurrent Register/Fire.
type HookRegistry struct {
	mu    sync.RWMutex
	hooks map[string][]ProtocolHook
}

// NewHookRegistry returns an empty registry.
func NewHookRegistry() *HookRegistry {
	return &HookRegistry{hooks: map[string][]ProtocolHook{}}
}

// Register appends fn to the listeners for eventType. Registration
// order is preserved — hooks for one event fire in the order they were
// registered.
func (r *HookRegistry) Register(eventType string, fn ProtocolHook) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.hooks[eventType] = append(r.hooks[eventType], fn)
}

// Fire invokes every hook registered for eventType. Each hook runs
// under a recover guard so a panic in one hook cannot crash the caller
// or skip later hooks. Errors are logged at warn level and do not stop
// the chain. Fire itself never returns an error — by design, so callers
// don't have to branch on hook outcomes.
func (r *HookRegistry) Fire(ctx context.Context, eventType string, event map[string]interface{}) {
	r.mu.RLock()
	// Copy the slice so a Register during Fire (unlikely but possible)
	// doesn't mutate the slice we're iterating.
	hooks := append([]ProtocolHook(nil), r.hooks[eventType]...)
	r.mu.RUnlock()

	for _, fn := range hooks {
		func() {
			defer func() {
				if rec := recover(); rec != nil {
					slog.Error("protocol hook panicked",
						"event_type", eventType, "panic", rec)
				}
			}()
			if err := fn(ctx, event); err != nil {
				slog.Warn("protocol hook error",
					"event_type", eventType, "err", err)
			}
		}()
	}
}

// ── memory-persisting hooks ──────────────────────────────────────────

// newTaskDoneMemoryHook returns a hook for "task.done" that writes a
// life-memory node capturing the task's title + summary, tagged with
// "task" and the task id. Tasks without a summary are skipped — there's
// no lesson to record from a task that finished with nothing to say.
//
// The hook takes a lifememory.Store (not TimelineStore): it only writes,
// never queries. This keeps the hook testable with the bare MemStore
// and avoids coupling to PG-specific query paths.
func newTaskDoneMemoryHook(store lifememory.Store) ProtocolHook {
	return func(ctx context.Context, event map[string]interface{}) error {
		summary, _ := event["summary"].(string)
		if summary == "" {
			return nil
		}
		taskID, _ := event["task_id"].(string)
		title, _ := event["title"].(string)
		if title == "" {
			title = fmt.Sprintf("task %s", taskID)
		}
		node := &lifememory.MemoryNode{
			ID:      fmt.Sprintf("mem_task_%s_%d", taskID, time.Now().UnixNano()),
			Title:   title,
			Content: summary,
			Tags:    []string{"task", taskID},
		}
		return store.Insert(node)
	}
}

// newSparkCompletedMemoryHook returns a hook for "spark.completed" that
// writes a life-memory node for a finished spark, tagged "spark" + the
// spark id. Sparks always have a summary (a spark with no outcome is a
// bug in the spark protocol), so unlike task.done there's no skip.
func newSparkCompletedMemoryHook(store lifememory.Store) ProtocolHook {
	return func(ctx context.Context, event map[string]interface{}) error {
		sparkID, _ := event["spark_id"].(string)
		title, _ := event["title"].(string)
		summary, _ := event["summary"].(string)
		if title == "" {
			title = fmt.Sprintf("spark %s", sparkID)
		}
		node := &lifememory.MemoryNode{
			ID:      fmt.Sprintf("mem_spark_%s_%d", sparkID, time.Now().UnixNano()),
			Title:   title,
			Content: summary,
			Tags:    []string{"spark", sparkID},
		}
		return store.Insert(node)
	}
}

// RegisterMemoryHooks wires both memory-persisting hooks into reg
// against store. This is the one call the orchestrator makes at startup
// to install the protocol-coordination side effects.
func RegisterMemoryHooks(reg *HookRegistry, store lifememory.Store) {
	reg.Register("task.done", newTaskDoneMemoryHook(store))
	reg.Register("spark.completed", newSparkCompletedMemoryHook(store))
}

// ── package-global registry + store ──────────────────────────────────
//
// The orchestrator has one process-wide HookRegistry and one memory
// store. They are initialized at startup (InitMemorySubsystem) and read
// by the CompleteTask handler and the /memory/nodes handlers (3.5).
//
// Memory store selection: PGStore when a pool is available, MemStore
// otherwise. The MemStore fallback means tests and single-binary dev
// runs still get memory persistence (in-process, lost on restart) —
// the contract degrades gracefully rather than nil-derefing.

var (
	globalHooks       = NewHookRegistry()
	globalMemoryStore lifememory.Store
)

// SetMemoryStore installs the process-wide memory store and registers
// the protocol hooks against it. cmd/orchestrator calls this at startup
// with either a PGStore (when DB is up) or a MemStore (fallback).
func SetMemoryStore(store lifememory.Store) {
	globalMemoryStore = store
	RegisterMemoryHooks(globalHooks, store)
}

// fireTaskDone is the single call site CompleteTask uses to publish a
// task.done event. It is a no-op when no memory store was initialized
// (e.g. tests that don't care about memory).
func fireTaskDone(taskID, title, summary string) {
	if globalMemoryStore == nil {
		return
	}
	globalHooks.Fire(context.Background(), "task.done", map[string]interface{}{
		"task_id": taskID,
		"title":   title,
		"summary": summary,
	})
}
