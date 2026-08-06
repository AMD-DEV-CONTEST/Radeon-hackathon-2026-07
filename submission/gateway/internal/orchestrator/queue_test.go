package orchestrator

import (
	"testing"
	"time"
)

// TestPriorityRoundTrip: PriorityToInt / IntToPriority must invert each other
// for the three canonical levels, and IntToPriority must safely bucket any int
// (negative, zero, mid-range, huge) into one of the three levels without panic.
func TestPriorityRoundTrip(t *testing.T) {
	for _, p := range []Priority{PriorityLow, PriorityMedium, PriorityHigh} {
		n := PriorityToInt(p)
		back := IntToPriority(n)
		if back != p {
			t.Fatalf("PriorityToInt(%v)=%d → IntToPriority=%v, want %v", p, n, back, p)
		}
	}

	cases := []struct {
		n    int
		want Priority
	}{
		{-5, PriorityLow},
		{0, PriorityLow},
		{10, PriorityLow},
		{49, PriorityMedium},
		{50, PriorityMedium},
		{89, PriorityHigh},
		{90, PriorityHigh},
		{1000, PriorityHigh},
	}
	for _, c := range cases {
		if got := IntToPriority(c.n); got != c.want {
			t.Fatalf("IntToPriority(%d) = %v, want %v", c.n, got, c.want)
		}
	}
}

// TestTaskQueue_DequeueOrder: high → medium → low, FIFO within a bucket.
func TestTaskQueue_DequeueOrder(t *testing.T) {
	q := NewTaskQueue()
	t0 := time.Now()
	q.Enqueue(QueuedTask{TaskID: "low1", Priority: PriorityLow, EnqueuedAt: t0})
	q.Enqueue(QueuedTask{TaskID: "med1", Priority: PriorityMedium, EnqueuedAt: t0.Add(time.Millisecond)})
	q.Enqueue(QueuedTask{TaskID: "high1", Priority: PriorityHigh, EnqueuedAt: t0.Add(2 * time.Millisecond)})
	q.Enqueue(QueuedTask{TaskID: "low2", Priority: PriorityLow, EnqueuedAt: t0.Add(3 * time.Millisecond)})
	q.Enqueue(QueuedTask{TaskID: "high2", Priority: PriorityHigh, EnqueuedAt: t0.Add(4 * time.Millisecond)})
	q.Enqueue(QueuedTask{TaskID: "med2", Priority: PriorityMedium, EnqueuedAt: t0.Add(5 * time.Millisecond)})

	want := []string{"high1", "high2", "med1", "med2", "low1", "low2"}
	for i, w := range want {
		got, ok := q.Dequeue()
		if !ok {
			t.Fatalf("step %d: Dequeue returned empty, want %s", i, w)
		}
		if got.TaskID != w {
			t.Fatalf("step %d: got %s, want %s", i, got.TaskID, w)
		}
	}
	if _, ok := q.Dequeue(); ok {
		t.Fatal("Dequeue after drain should return ok=false")
	}
}

// TestTaskQueue_HighJumpsAheadOfLow: a high-priority task enqueued AFTER a
// low-priority one must dequeue first. This is the "插队" guarantee.
func TestTaskQueue_HighJumpsAheadOfLow(t *testing.T) {
	q := NewTaskQueue()
	t0 := time.Now()
	q.Enqueue(QueuedTask{TaskID: "low", Priority: PriorityLow, EnqueuedAt: t0})
	q.Enqueue(QueuedTask{TaskID: "high", Priority: PriorityHigh, EnqueuedAt: t0.Add(time.Second)})

	got, _ := q.Dequeue()
	if got.TaskID != "high" {
		t.Fatalf("expected high to jump ahead, got %s", got.TaskID)
	}
}

// TestTaskQueue_LenAndLenByPriority: counts stay correct after enqueues and dequeues.
func TestTaskQueue_LenAndLenByPriority(t *testing.T) {
	q := NewTaskQueue()
	if q.Len() != 0 {
		t.Fatalf("empty Len = %d, want 0", q.Len())
	}
	q.Enqueue(QueuedTask{TaskID: "h", Priority: PriorityHigh, EnqueuedAt: time.Now()})
	q.Enqueue(QueuedTask{TaskID: "m", Priority: PriorityMedium, EnqueuedAt: time.Now()})
	q.Enqueue(QueuedTask{TaskID: "l1", Priority: PriorityLow, EnqueuedAt: time.Now()})
	q.Enqueue(QueuedTask{TaskID: "l2", Priority: PriorityLow, EnqueuedAt: time.Now()})

	if h, m, l := q.LenByPriority(); h != 1 || m != 1 || l != 2 {
		t.Fatalf("LenByPriority = (%d,%d,%d), want (1,1,2)", h, m, l)
	}
	if q.Len() != 4 {
		t.Fatalf("Len = %d, want 4", q.Len())
	}

	q.Dequeue() // removes high
	if h, m, l := q.LenByPriority(); h != 0 || m != 1 || l != 2 {
		t.Fatalf("after dequeue LenByPriority = (%d,%d,%d), want (0,1,2)", h, m, l)
	}
}

// TestTaskQueue_PeekDoesNotRemove: Peek returns the next item without
// removing it; two Peeks in a row return the same task.
func TestTaskQueue_PeekDoesNotRemove(t *testing.T) {
	q := NewTaskQueue()
	q.Enqueue(QueuedTask{TaskID: "h", Priority: PriorityHigh, EnqueuedAt: time.Now()})
	q.Enqueue(QueuedTask{TaskID: "l", Priority: PriorityLow, EnqueuedAt: time.Now()})

	p1, ok := q.Peek()
	if !ok || p1.TaskID != "h" {
		t.Fatalf("Peek 1 = %+v ok=%v, want h", p1, ok)
	}
	p2, ok := q.Peek()
	if !ok || p2.TaskID != "h" {
		t.Fatalf("Peek 2 = %+v ok=%v, want h (Peek must not remove)", p2, ok)
	}
	if q.Len() != 2 {
		t.Fatalf("Len after two Peeks = %d, want 2", q.Len())
	}
}

// TestTaskQueue_PeekEmpty: Peek on an empty queue returns ok=false.
func TestTaskQueue_PeekEmpty(t *testing.T) {
	q := NewTaskQueue()
	_, ok := q.Peek()
	if ok {
		t.Fatal("Peek on empty queue should return ok=false")
	}
}

// TestTaskQueue_Remove: Remove by task ID finds the task in whichever
// bucket it lives in, deletes it, and returns true. Unknown ID → false.
func TestTaskQueue_Remove(t *testing.T) {
	q := NewTaskQueue()
	q.Enqueue(QueuedTask{TaskID: "h1", Priority: PriorityHigh, EnqueuedAt: time.Now()})
	q.Enqueue(QueuedTask{TaskID: "m1", Priority: PriorityMedium, EnqueuedAt: time.Now()})
	q.Enqueue(QueuedTask{TaskID: "l1", Priority: PriorityLow, EnqueuedAt: time.Now()})

	if !q.Remove("m1") {
		t.Fatal("Remove(m1) returned false, want true")
	}
	if h, m, l := q.LenByPriority(); h != 1 || m != 0 || l != 1 {
		t.Fatalf("after Remove(m1) LenByPriority = (%d,%d,%d), want (1,0,1)", h, m, l)
	}
	// Ensure m1 is really gone, not just head of its bucket.
	if q.Remove("m1") {
		t.Fatal("Remove(m1) second time returned true, want false")
	}
	if q.Remove("nonexistent") {
		t.Fatal("Remove(unknown) returned true, want false")
	}
	// Remaining dequeue order unaffected.
	got, _ := q.Dequeue()
	if got.TaskID != "h1" {
		t.Fatalf("after remove, Dequeue = %s, want h1", got.TaskID)
	}
	got, _ = q.Dequeue()
	if got.TaskID != "l1" {
		t.Fatalf("after remove, second Dequeue = %s, want l1", got.TaskID)
	}
}
