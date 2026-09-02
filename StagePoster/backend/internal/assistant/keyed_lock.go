package assistant

import "sync"

type keyedLock struct {
	mu      sync.Mutex
	entries map[string]*keyedLockEntry
}

type keyedLockEntry struct {
	mu   sync.Mutex
	refs int
}

func (locks *keyedLock) Lock(
	key string,
) func() {
	locks.mu.Lock()

	if locks.entries == nil {
		locks.entries = make(
			map[string]*keyedLockEntry,
		)
	}

	entry, ok := locks.entries[key]
	if !ok {
		entry = &keyedLockEntry{}
		locks.entries[key] = entry
	}

	entry.refs++

	locks.mu.Unlock()

	entry.mu.Lock()

	return func() {
		entry.mu.Unlock()

		locks.mu.Lock()
		defer locks.mu.Unlock()

		entry.refs--

		if entry.refs == 0 {
			delete(locks.entries, key)
		}
	}
}
