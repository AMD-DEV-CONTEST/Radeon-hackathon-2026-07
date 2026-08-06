package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestAcquireProfileLockSucceedsFirstTime(t *testing.T) {
	dir := t.TempDir()
	lockPath := filepath.Join(dir, "daemon.lock")
	release, err := acquireProfileLock(lockPath)
	if err != nil {
		t.Fatalf("acquire: %v", err)
	}
	if _, err := os.Stat(lockPath); err != nil {
		t.Fatalf("lock file not created: %v", err)
	}
	if err := release(); err != nil {
		t.Fatalf("release: %v", err)
	}
	if _, err := os.Stat(lockPath); !os.IsNotExist(err) {
		t.Fatalf("lock file should be removed after release, got err=%v", err)
	}
}

func TestAcquireProfileLockRejectsSecond(t *testing.T) {
	dir := t.TempDir()
	lockPath := filepath.Join(dir, "daemon.lock")
	rel1, err := acquireProfileLock(lockPath)
	if err != nil {
		t.Fatalf("first acquire: %v", err)
	}
	// Second acquire on same path must fail WITHOUT releasing the first.
	_, err = acquireProfileLock(lockPath)
	if err == nil {
		t.Fatal("second acquire should fail with lock held")
	}
	_ = rel1()
}

func TestAcquireProfileLockMkdirAll(t *testing.T) {
	// lockPath in a not-yet-existing nested dir; acquire must create it.
	dir := t.TempDir()
	lockPath := filepath.Join(dir, "nested", "deep", "daemon.lock")
	rel, err := acquireProfileLock(lockPath)
	if err != nil {
		t.Fatalf("acquire with missing dir: %v", err)
	}
	if _, err := os.Stat(lockPath); err != nil {
		t.Fatalf("lock file not created: %v", err)
	}
	_ = rel()
}
