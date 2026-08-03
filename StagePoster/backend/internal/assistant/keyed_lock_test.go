package assistant

import (
	"testing"
	"time"
)

func TestKeyedLockSerializesSameKey(
	t *testing.T,
) {
	var locks keyedLock

	unlockFirst := locks.Lock("session-a")

	acquired := make(chan struct{})
	releaseSecond := make(chan struct{})
	done := make(chan struct{})

	go func() {
		unlockSecond := locks.Lock("session-a")
		close(acquired)

		<-releaseSecond

		unlockSecond()
		close(done)
	}()

	select {
	case <-acquired:
		t.Fatal(
			"second lock with same key acquired too early",
		)

	case <-time.After(50 * time.Millisecond):
	}

	unlockFirst()

	select {
	case <-acquired:

	case <-time.After(time.Second):
		t.Fatal(
			"second lock with same key was not released",
		)
	}

	close(releaseSecond)

	select {
	case <-done:

	case <-time.After(time.Second):
		t.Fatal(
			"second lock did not finish",
		)
	}

	locks.mu.Lock()
	remaining := len(locks.entries)
	locks.mu.Unlock()

	if remaining != 0 {
		t.Fatalf(
			"remaining lock entries = %d, want 0",
			remaining,
		)
	}
}

func TestKeyedLockAllowsDifferentKeys(
	t *testing.T,
) {
	var locks keyedLock

	unlockFirst := locks.Lock("session-a")
	defer unlockFirst()

	acquired := make(chan struct{})
	done := make(chan struct{})

	go func() {
		unlockSecond := locks.Lock("session-b")
		close(acquired)

		unlockSecond()
		close(done)
	}()

	select {
	case <-acquired:

	case <-time.After(time.Second):
		t.Fatal(
			"different lock key was unexpectedly blocked",
		)
	}

	select {
	case <-done:

	case <-time.After(time.Second):
		t.Fatal(
			"different lock key did not finish",
		)
	}
}
