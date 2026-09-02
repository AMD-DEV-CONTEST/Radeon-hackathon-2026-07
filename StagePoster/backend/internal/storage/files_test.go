package storage

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

// 记录还在、文件没了，以前会被包成 *fs.PathError 一路冒到 500 分支，响应体里
// 带着服务器绝对路径。现在必须是 ErrOutputMissing，且错误文本里不能出现路径。
func TestOpenMissingOutputIsSentinelWithoutPath(
	t *testing.T,
) {
	t.Parallel()

	root := t.TempDir()

	store, err := NewFileStore(root)
	if err != nil {
		t.Fatalf("new file store: %v", err)
	}

	missing := filepath.Join(
		root,
		"job_secret",
		"poster.png",
	)

	_, err = store.Open(domain.Output{
		StoragePath: missing,
	})

	if !errors.Is(err, ErrOutputMissing) {
		t.Fatalf(
			"expected ErrOutputMissing, got %v",
			err,
		)
	}

	if strings.Contains(err.Error(), root) ||
		strings.Contains(err.Error(), "job_secret") {
		t.Fatalf(
			"error message leaks filesystem path: %q",
			err.Error(),
		)
	}
}

// 越界路径检查必须早于文件打开，否则 ErrOutputMissing 会掩盖掉一次穿越尝试。
func TestOpenRejectsPathOutsideRoot(
	t *testing.T,
) {
	t.Parallel()

	store, err := NewFileStore(t.TempDir())
	if err != nil {
		t.Fatalf("new file store: %v", err)
	}

	_, err = store.Open(domain.Output{
		StoragePath: "/etc/passwd",
	})

	if err == nil {
		t.Fatal("expected rejection for path outside root")
	}

	if errors.Is(err, ErrOutputMissing) {
		t.Fatalf(
			"traversal reported as missing output: %v",
			err,
		)
	}
}

// 正常情况仍要能打开。
func TestOpenReadsExistingOutput(
	t *testing.T,
) {
	t.Parallel()

	root := t.TempDir()

	store, err := NewFileStore(root)
	if err != nil {
		t.Fatalf("new file store: %v", err)
	}

	path := filepath.Join(root, "output.png")

	if err := os.WriteFile(
		path,
		[]byte("payload"),
		0o600,
	); err != nil {
		t.Fatalf("write output: %v", err)
	}

	file, err := store.Open(domain.Output{
		StoragePath: path,
	})
	if err != nil {
		t.Fatalf("open output: %v", err)
	}

	defer file.Close()

	contents, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read back: %v", err)
	}

	if string(contents) != "payload" {
		t.Fatalf("unexpected contents %q", contents)
	}
}
