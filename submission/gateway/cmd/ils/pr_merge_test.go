package main

import (
	"bytes"
	"errors"
	"strconv"
	"strings"
	"testing"
)

func TestPrMergeRequiresC1FinalVerdict(t *testing.T) {
	stdout, stderr, code, _ := runPrMergeTest(t, prMergeFixture{
		comments: []string{"X1 review: PASS per spec \u00a76.1 -count=50 PASS"},
		checks:   `[{"name":"test","state":"SUCCESS"}]`,
		dryRun:   true,
	})
	if code == 0 {
		t.Fatalf("expected rejection, stdout=%s stderr=%s", stdout, stderr)
	}
	if !strings.Contains(stderr, "RULE_A_NO_C1_VERDICT") {
		t.Fatalf("missing RULE_A prefix: %s", stderr)
	}
}

func TestPrMergeRequiresSpecSectionReference(t *testing.T) {
	stdout, stderr, code, _ := runPrMergeTest(t, prMergeFixture{
		comments: []string{"C1 final verdict -- APPROVED\n-count=50 PASS"},
		checks:   `[{"name":"test","state":"SUCCESS"}]`,
		dryRun:   true,
	})
	if code == 0 {
		t.Fatalf("expected rejection, stdout=%s stderr=%s", stdout, stderr)
	}
	if !strings.Contains(stderr, "RULE_B_NO_SPEC_REF") {
		t.Fatalf("missing RULE_B prefix: %s", stderr)
	}
}

func TestPrMergeRequiresCount50PassByDefault(t *testing.T) {
	_, stderr, code, _ := runPrMergeTest(t, prMergeFixture{
		comments: []string{"C1 final verdict -- APPROVED\nper spec \u00a76.1\ngo test ./cmd/ils -run TestPrMerge -count=10 PASS"},
		checks:   `[{"name":"test","state":"SUCCESS"}]`,
		dryRun:   true,
	})
	if code == 0 {
		t.Fatal("expected insufficient count rejection")
	}
	if !strings.Contains(stderr, "RULE_C_INSUFFICIENT_COUNT") {
		t.Fatalf("missing RULE_C prefix: %s", stderr)
	}
}

func TestPrMergeAcceptsCount50PassByDefault(t *testing.T) {
	stdout, stderr, code, _ := runPrMergeTest(t, prMergeFixture{
		comments: []string{"C1 final verdict -- APPROVED\nper spec \u00a76.1\ngo test ./cmd/ils -run TestPrMerge -count=50 PASS"},
		checks:   `[{"name":"test","state":"SUCCESS"}]`,
		dryRun:   true,
	})
	if code != 0 {
		t.Fatalf("expected pass, stdout=%s stderr=%s", stdout, stderr)
	}
	if !strings.Contains(stdout, "would merge") {
		t.Fatalf("dry-run should report would merge: %s", stdout)
	}
}

func TestPrMergeAcceptsMarkdownHeading(t *testing.T) {
	stdout, stderr, code, _ := runPrMergeTest(t, prMergeFixture{
		comments: []string{"## C1 final verdict — APPROVED\nper spec \u00a76.1\ngo test ./cmd/ils -run TestPrMerge -count=50 PASS"},
		checks:   `[{"name":"test","state":"SUCCESS"}]`,
		dryRun:   true,
	})
	if code != 0 {
		t.Fatalf("expected markdown heading verdict to pass, stdout=%s stderr=%s", stdout, stderr)
	}
}

func TestPrMergeAcceptsCount1WithNoFlakeRiskTag(t *testing.T) {
	stdout, stderr, code, _ := runPrMergeTest(t, prMergeFixture{
		comments: []string{"C1 final verdict -- APPROVED\nper spec \u00a76.1 [no-flake-risk]\ngo test ./cmd/ils -run TestPrMerge -count=1 PASS"},
		checks:   `[{"name":"lint","state":"SUCCESS"}]`,
		dryRun:   true,
	})
	if code != 0 {
		t.Fatalf("expected pass, stdout=%s stderr=%s", stdout, stderr)
	}
}

func TestPrMergeRejectsRequestChangesWithLaterApproved(t *testing.T) {
	_, stderr, code, _ := runPrMergeTest(t, prMergeFixture{
		comments: []string{"# C1 final verdict -- REQUEST_CHANGES\nper spec \u00a76.1\n\nFollow-up note: after these fixes this can become APPROVED.\ngo test ./cmd/ils -run TestPrMerge -count=50 PASS"},
		checks:   `[{"name":"test","state":"SUCCESS"}]`,
		dryRun:   true,
	})
	if code == 0 {
		t.Fatal("expected request-changes comment with later APPROVED text to be rejected")
	}
	if !strings.Contains(stderr, "RULE_A_NO_C1_VERDICT") {
		t.Fatalf("missing RULE_A prefix: %s", stderr)
	}
}

func TestPrMergeAcceptsEmDash(t *testing.T) {
	stdout, stderr, code, _ := runPrMergeTest(t, prMergeFixture{
		comments: []string{"> C1 终审 – 通过\n按 spec \u00a76.1\ngo test ./cmd/ils -run TestPrMerge -count=50 PASS"},
		checks:   `[{"name":"test","state":"SUCCESS"}]`,
		dryRun:   true,
	})
	if code != 0 {
		t.Fatalf("expected unicode dash verdict to pass, stdout=%s stderr=%s", stdout, stderr)
	}
}

func TestPrMergeRequiresCiGreen(t *testing.T) {
	_, stderr, code, _ := runPrMergeTest(t, prMergeFixture{
		comments: validPrMergeComment(),
		checks:   `[{"name":"build","state":"SUCCESS"},{"name":"test","state":"FAILURE"}]`,
		dryRun:   true,
	})
	if code == 0 {
		t.Fatal("expected failed CI rejection")
	}
	if !strings.Contains(stderr, "RULE_D_CI_NOT_GREEN") {
		t.Fatalf("missing RULE_D prefix: %s", stderr)
	}
}

func TestPrMergeRejectsPendingCi(t *testing.T) {
	_, stderr, code, _ := runPrMergeTest(t, prMergeFixture{
		comments: validPrMergeComment(),
		checks:   `[{"name":"test","state":"PENDING"}]`,
		dryRun:   true,
	})
	if code == 0 {
		t.Fatal("expected pending CI rejection")
	}
	if !strings.Contains(stderr, "RULE_D_CI_PENDING") {
		t.Fatalf("missing pending CI prefix: %s", stderr)
	}
}

func TestPrMergeAllowsEmptyChecksWithWarning(t *testing.T) {
	stdout, stderr, code, _ := runPrMergeTest(t, prMergeFixture{
		comments: validPrMergeComment(),
		checks:   `[]`,
		dryRun:   true,
	})
	if code != 0 {
		t.Fatalf("expected empty checks warning pass, stdout=%s stderr=%s", stdout, stderr)
	}
	if !strings.Contains(stderr, "WARN: no CI checks configured") {
		t.Fatalf("missing warning: %s", stderr)
	}
}

func TestPrMergeAllowsNoChecksExitWithWarning(t *testing.T) {
	stdout, stderr, code, _ := runPrMergeTest(t, prMergeFixture{
		comments:     validPrMergeComment(),
		checksErrOut: "no checks reported on the 'feature' branch",
		dryRun:       true,
	})
	if code != 0 {
		t.Fatalf("expected no-checks gh exit warning pass, stdout=%s stderr=%s", stdout, stderr)
	}
	if !strings.Contains(stderr, "WARN: no CI checks configured") {
		t.Fatalf("missing warning: %s", stderr)
	}
}

func TestPrMergeRejectsForeignRepo(t *testing.T) {
	_, stderr, code, _ := runPrMergeTest(t, prMergeFixture{
		repo:     "Other/repo",
		comments: validPrMergeComment(),
		checks:   `[{"name":"test","state":"SUCCESS"}]`,
		dryRun:   true,
	})
	if code == 0 {
		t.Fatal("expected foreign repo rejection")
	}
	if !strings.Contains(stderr, "RULE_REPO_NOT_ALLOWED") {
		t.Fatalf("missing repo rule prefix: %s", stderr)
	}
}

func TestPrMergeDryRunNeverMerges(t *testing.T) {
	stdout, stderr, code, calls := runPrMergeTest(t, prMergeFixture{
		comments: validPrMergeComment(),
		checks:   `[{"name":"test","state":"SUCCESS"}]`,
		dryRun:   true,
	})
	if code != 0 {
		t.Fatalf("expected pass, stdout=%s stderr=%s", stdout, stderr)
	}
	for _, call := range calls {
		if strings.HasPrefix(call, "pr merge ") {
			t.Fatalf("dry-run called merge: %v", calls)
		}
	}
}

func TestPrMergeOutputErrorPrefixIsParseable(t *testing.T) {
	_, stderr, code, _ := runPrMergeTest(t, prMergeFixture{
		comments: []string{"C1 final verdict -- APPROVED"},
		checks:   `[{"name":"test","state":"SUCCESS"}]`,
		dryRun:   true,
	})
	if code == 0 {
		t.Fatal("expected failure")
	}
	if !strings.Contains(stderr, "[ils pr merge] RULE_B_") {
		t.Fatalf("error is not parseable: %s", stderr)
	}
}

type prMergeFixture struct {
	repo         string
	comments     []string
	checks       string
	checksErrOut string
	dryRun       bool
}

func runPrMergeTest(t *testing.T, f prMergeFixture) (string, string, int, []string) {
	t.Helper()
	repo := f.repo
	if repo == "" {
		repo = "Porphyrioon/union_agents"
	}
	var calls []string
	gh := func(args ...string) ([]byte, error) {
		call := strings.Join(args, " ")
		calls = append(calls, call)
		switch {
		case call == "repo view --json nameWithOwner -q .nameWithOwner":
			return []byte(repo + "\n"), nil
		case strings.HasPrefix(call, "api repos/"):
			return []byte(`[]`), nil
		case strings.HasPrefix(call, "pr view "):
			return []byte(`{"comments":` + jsonBodyArray(f.comments) + `,"reviews":[]}`), nil
		case strings.HasPrefix(call, "pr checks "):
			if f.checksErrOut != "" {
				return []byte(f.checksErrOut), errors.New("exit status 1")
			}
			if f.checks == "" {
				return []byte(`[]`), nil
			}
			return []byte(f.checks), nil
		case strings.HasPrefix(call, "pr merge "):
			return []byte(`merged`), nil
		default:
			return nil, errors.New("unexpected gh call: " + call)
		}
	}

	args := []string{"1"}
	if f.dryRun {
		args = append(args, "--dry-run")
	}
	var stdout, stderr bytes.Buffer
	code := runPrMergeCommand(args, &stdout, &stderr, gh)
	return stdout.String(), stderr.String(), code, calls
}

func validPrMergeComment() []string {
	return []string{"C1 final verdict -- APPROVED\nper spec \u00a76.1\ngo test ./cmd/ils -run TestPrMerge -count=50 PASS"}
}

func jsonBodyArray(values []string) string {
	var b strings.Builder
	b.WriteByte('[')
	for i, value := range values {
		if i > 0 {
			b.WriteByte(',')
		}
		b.WriteString(`{"body":`)
		b.WriteString(strconv.Quote(value))
		b.WriteByte('}')
	}
	b.WriteByte(']')
	return b.String()
}
