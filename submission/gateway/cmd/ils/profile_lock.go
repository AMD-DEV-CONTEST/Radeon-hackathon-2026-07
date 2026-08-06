package main

import (
	"fmt"
	"os"
	"path/filepath"
	"time"
)

// acquireProfileLock creates lockPath with O_CREATE|O_EXCL (exclusive
// create). If it already exists, returns an error — the profile is
// already running under another daemon. Returns a release func that
// removes the lock file; a failed removal is non-fatal (just logged by
// the caller). On Windows, O_EXCL is mapped by Go to CREATE_NEW, which
// correctly fails when the file exists.
func acquireProfileLock(lockPath string) (func() error, error) {
	if err := os.MkdirAll(filepath.Dir(lockPath), 0o755); err != nil {
		return nil, fmt.Errorf("lock dir: %w", err)
	}
	f, err := os.OpenFile(lockPath, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o644)
	if err != nil {
		if os.IsExist(err) {
			return nil, fmt.Errorf("profile already locked (%s): another daemon may be running; remove %s only if certain it is stale", lockPath, lockPath)
		}
		return nil, fmt.Errorf("lock create: %w", err)
	}
	// Write PID + start time for diagnostics (not a credential).
	fmt.Fprintf(f, "pid=%d\nstarted=%s\n", os.Getpid(), time.Now().UTC().Format(time.RFC3339))
	_ = f.Close()
	return func() error {
		return os.Remove(lockPath)
	}, nil
}
