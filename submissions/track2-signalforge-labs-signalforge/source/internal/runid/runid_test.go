package runid

import (
	"strings"
	"testing"
	"time"
)

func TestUUIDv7RoundTrip(t *testing.T) {
	now := time.Date(2026, 7, 21, 12, 34, 56, 789000000, time.UTC)
	value, err := New(now)
	if err != nil {
		t.Fatal(err)
	}
	if len(value) != 36 || !strings.HasPrefix(value, "019") {
		t.Fatalf("unexpected UUIDv7 %q", value)
	}
	parsed, err := Timestamp(value)
	if err != nil {
		t.Fatal(err)
	}
	if !parsed.Equal(now) {
		t.Fatalf("timestamp mismatch: got %s want %s", parsed, now)
	}
}

func TestRunIDsAreUnique(t *testing.T) {
	now := time.Now().UTC().Truncate(time.Millisecond)
	first, err := New(now)
	if err != nil {
		t.Fatal(err)
	}
	second, err := New(now)
	if err != nil {
		t.Fatal(err)
	}
	if first == second {
		t.Fatal("run IDs generated in the same millisecond must remain unique")
	}
}
