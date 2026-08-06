package orchestrator

import (
	"sync"
	"time"
)

// Priority is the three-level semantic priority used by the in-process
// TaskQueue. It is deliberately coarse — the orchestrator's PG-side
// `tasks.priority` int column already supports fine-grained ordering via
// `ORDER BY priority DESC`; this layer exists to give dispatchers a
// "high jumps ahead of low" knob without everyone hardcoding ints.
//
// The mapping to the DB int column is fixed by PriorityToInt / IntToPriority
// and chosen to be consistent with the existing convention (larger = higher
// priority, default ~50): high→90, medium→50, low→10.
type Priority int

const (
	PriorityLow    Priority = 1
	PriorityMedium Priority = 5
	PriorityHigh   Priority = 9
)

// PriorityToInt maps a semantic Priority to the DB int column value.
// Used by InjectTask (Phase 2.2) when writing tasks.priority.
func PriorityToInt(p Priority) int {
	switch p {
	case PriorityHigh:
		return 90
	case PriorityMedium:
		return 50
	case PriorityLow:
		return 10
	default:
		// Unknown level → safest is "don't starve", treat as medium.
		return 50
	}
}

// IntToPriority maps a DB int priority back to the nearest semantic level.
// Buckets: <30 → Low, <70 → Medium, >=70 → High. Any int (including
// negative) is safely bucketed; there is no "unknown" return.
func IntToPriority(n int) Priority {
	switch {
	case n >= 70:
		return PriorityHigh
	case n >= 30:
		return PriorityMedium
	default:
		return PriorityLow
	}
}

// QueuedTask is an item held in the in-memory TaskQueue. It is a thin
// envelope around a task ID — the full task row lives in PG; this struct
// is what the scheduler touches when deciding what to dispatch next.
type QueuedTask struct {
	TaskID     string
	Priority   Priority
	EnqueuedAt time.Time
}

// TaskQueue is a three-bucket in-memory priority queue. High-priority
// tasks always dequeue before medium, medium before low; within a bucket
// it is strict FIFO by EnqueuedAt (ties broken by enqueue order, which
// append preserves).
//
// It does NOT persist, does NOT race with PG, and does NOT replace the
// `ORDER BY priority DESC` query in PollTask. It is a scheduler-side
// staging area for batch pre-warming and explicit high-priority插队.
// Persistence is PG's job.
type TaskQueue struct {
	mu      sync.Mutex
	high    []QueuedTask
	medium  []QueuedTask
	low     []QueuedTask
}

// NewTaskQueue returns an empty TaskQueue.
func NewTaskQueue() *TaskQueue {
	return &TaskQueue{}
}

// Enqueue appends t to the bucket matching its Priority.
func (q *TaskQueue) Enqueue(t QueuedTask) {
	q.mu.Lock()
	defer q.mu.Unlock()
	switch t.Priority {
	case PriorityHigh:
		q.high = append(q.high, t)
	case PriorityMedium:
		q.medium = append(q.medium, t)
	default:
		// Treat unknown levels as low rather than dropping them — a
		// mislabeled task should still get dispatched, just last.
		q.low = append(q.low, t)
	}
}

// Dequeue removes and returns the highest-priority, oldest task. The
// second return is false when the queue is empty.
func (q *TaskQueue) Dequeue() (QueuedTask, bool) {
	q.mu.Lock()
	defer q.mu.Unlock()
	if t, ok := popHead(&q.high); ok {
		return t, true
	}
	if t, ok := popHead(&q.medium); ok {
		return t, true
	}
	if t, ok := popHead(&q.low); ok {
		return t, true
	}
	return QueuedTask{}, false
}

// Peek returns the next task that Dequeue would return, without
// removing it. ok is false on an empty queue.
func (q *TaskQueue) Peek() (QueuedTask, bool) {
	q.mu.Lock()
	defer q.mu.Unlock()
	if len(q.high) > 0 {
		return q.high[0], true
	}
	if len(q.medium) > 0 {
		return q.medium[0], true
	}
	if len(q.low) > 0 {
		return q.low[0], true
	}
	return QueuedTask{}, false
}

// Len returns the total number of queued tasks across all buckets.
func (q *TaskQueue) Len() int {
	q.mu.Lock()
	defer q.mu.Unlock()
	return len(q.high) + len(q.medium) + len(q.low)
}

// LenByPriority returns the per-bucket counts as (high, medium, low).
func (q *TaskQueue) LenByPriority() (int, int, int) {
	q.mu.Lock()
	defer q.mu.Unlock()
	return len(q.high), len(q.medium), len(q.low)
}

// Remove deletes the task with the given ID from whichever bucket holds
// it. Returns true if found and removed, false if the ID is not present.
func (q *TaskQueue) Remove(taskID string) bool {
	q.mu.Lock()
	defer q.mu.Unlock()
	return removeFrom(&q.high, taskID) || removeFrom(&q.medium, taskID) || removeFrom(&q.low, taskID)
}

// popHead removes and returns the first element of *s. ok is false when
// the slice is empty.
func popHead(s *[]QueuedTask) (QueuedTask, bool) {
	if len(*s) == 0 {
		return QueuedTask{}, false
	}
	t := (*s)[0]
	*s = (*s)[1:]
	return t, true
}

// removeFrom scans *s for taskID, deletes it preserving order, and
// returns true. False if not found.
func removeFrom(s *[]QueuedTask, taskID string) bool {
	for i, t := range *s {
		if t.TaskID == taskID {
			*s = append((*s)[:i], (*s)[i+1:]...)
			return true
		}
	}
	return false
}
