package orchestrator

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"regexp"
)

var safeTraceID = regexp.MustCompile(`^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$`)

type TraceStore interface {
	Save(Trace) error
}

type FileTraceStore struct {
	Directory string
}

func (store FileTraceStore) Save(trace Trace) error {
	if store.Directory == "" || !safeTraceID.MatchString(trace.RunID) || trace.CompletedAt.IsZero() {
		return errors.New("trace directory, safe run_id, and completed_at are required")
	}
	if err := os.MkdirAll(store.Directory, 0o700); err != nil {
		return err
	}
	encoded, err := json.MarshalIndent(trace, "", "  ")
	if err != nil {
		return err
	}
	encoded = append(encoded, '\n')
	temporary, err := os.CreateTemp(store.Directory, ".trace-*.tmp")
	if err != nil {
		return err
	}
	temporaryName := temporary.Name()
	defer os.Remove(temporaryName)
	if err := temporary.Chmod(0o600); err != nil {
		temporary.Close()
		return err
	}
	if _, err := temporary.Write(encoded); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Sync(); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Close(); err != nil {
		return err
	}
	return os.Rename(temporaryName, filepath.Join(store.Directory, trace.RunID+".json"))
}
