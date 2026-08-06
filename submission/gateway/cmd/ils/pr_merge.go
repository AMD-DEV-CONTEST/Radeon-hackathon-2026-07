package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
)

type ghRunner func(args ...string) ([]byte, error)

var prMergeGh ghRunner = runPrMergeGh

var allowedPrMergeRepos = map[string]struct{}{
	"Porphyrioon/union_agents": {},
	"Porphyrioon/omima":        {},
}

func runPrMergeGh(args ...string) ([]byte, error) {
	cmd := exec.Command("gh", args...)
	return cmd.CombinedOutput()
}

func cmdPr(args []string) {
	if len(args) < 1 || args[0] != "merge" {
		fmt.Fprintln(os.Stderr, "usage: ils pr merge <pr-number> [--repo OWNER/NAME] [--dry-run]")
		os.Exit(2)
	}
	if code := runPrMergeCommand(args[1:], os.Stdout, os.Stderr, prMergeGh); code != 0 {
		os.Exit(code)
	}
}

type prMergeOptions struct {
	number string
	repo   string
	dryRun bool
}

type prMergeResult struct {
	ruleA bool
	ruleB bool
	ruleC bool
	ruleD bool
	warn  string
}

type prMergeFailure struct {
	code    string
	message string
}

func (f *prMergeFailure) Error() string {
	return fmt.Sprintf("%s: %s", f.code, f.message)
}

func runPrMergeCommand(args []string, stdout, stderr io.Writer, gh ghRunner) int {
	opts, err := parsePrMergeArgs(args)
	if err != nil {
		fmt.Fprintf(stderr, "[ils pr merge] ARG_ERROR: %v\n", err)
		return 2
	}

	result, err := evaluatePrMerge(opts, gh)
	if result.warn != "" {
		fmt.Fprintf(stderr, "[ils pr merge] WARN: %s\n", result.warn)
	}
	if opts.dryRun {
		writePrMergeDryRun(stdout, result, err)
	}
	if err != nil {
		var gateErr *prMergeFailure
		if errors.As(err, &gateErr) {
			fmt.Fprintf(stderr, "[ils pr merge] %s: %s\n", gateErr.code, gateErr.message)
		} else {
			fmt.Fprintf(stderr, "[ils pr merge] ERROR: %v\n", err)
		}
		return 1
	}
	if opts.dryRun {
		fmt.Fprintln(stdout, "[ils pr merge] all gates passed, would merge")
		return 0
	}

	fmt.Fprintln(stdout, "[ils pr merge] all gates passed, merging...")
	if _, err := gh("pr", "merge", opts.number, "--repo", opts.repo, "--merge", "--delete-branch"); err != nil {
		fmt.Fprintf(stderr, "[ils pr merge] MERGE_FAILED: %v\n", err)
		return 1
	}
	return 0
}

func parsePrMergeArgs(args []string) (prMergeOptions, error) {
	var opts prMergeOptions
	fs := flag.NewFlagSet("pr merge", flag.ContinueOnError)
	fs.SetOutput(io.Discard)

	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--dry-run":
			opts.dryRun = true
		case "--repo":
			if i+1 >= len(args) {
				return opts, fmt.Errorf("--repo requires OWNER/NAME")
			}
			opts.repo = args[i+1]
			i++
		default:
			if strings.HasPrefix(args[i], "-") {
				return opts, fmt.Errorf("unknown flag %s", args[i])
			}
			if opts.number != "" {
				return opts, fmt.Errorf("unexpected argument %s", args[i])
			}
			opts.number = args[i]
		}
	}
	if opts.number == "" {
		return opts, fmt.Errorf("missing PR number")
	}
	if _, err := strconv.Atoi(opts.number); err != nil {
		return opts, fmt.Errorf("invalid PR number %q", opts.number)
	}
	return opts, nil
}

func evaluatePrMerge(opts prMergeOptions, gh ghRunner) (prMergeResult, error) {
	var result prMergeResult
	repo := opts.repo
	if repo == "" {
		resolved, err := detectPrMergeRepo(gh)
		if err != nil {
			return result, err
		}
		repo = resolved
	}
	opts.repo = repo

	if _, ok := allowedPrMergeRepos[repo]; !ok {
		return result, &prMergeFailure{
			code:    "RULE_REPO_NOT_ALLOWED",
			message: "unauthorized repo, this gate only manages OMIMA-system repos",
		}
	}

	bodies, err := collectPrMergeCommentBodies(opts, gh)
	if err != nil {
		return result, err
	}
	verdict := findC1FinalVerdict(bodies)
	if verdict == "" {
		return result, &prMergeFailure{
			code:    "RULE_A_NO_C1_VERDICT",
			message: "no comment matches C1 final verdict APPROVED marker",
		}
	}
	result.ruleA = true

	if !hasSpecSectionReference(verdict) {
		return result, &prMergeFailure{
			code:    "RULE_B_NO_SPEC_REF",
			message: "C1 verdict comment exists but no spec section reference",
		}
	}
	result.ruleB = true

	if err := validatePrMergeCount(verdict); err != nil {
		return result, err
	}
	result.ruleC = true

	warn, err := validatePrMergeChecks(opts, gh)
	if warn != "" {
		result.warn = warn
	}
	if err != nil {
		return result, err
	}
	result.ruleD = true
	return result, nil
}

func detectPrMergeRepo(gh ghRunner) (string, error) {
	out, err := gh("repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner")
	if err != nil {
		return "", fmt.Errorf("detect repo: %w", err)
	}
	repo := strings.TrimSpace(string(out))
	if repo == "" {
		return "", fmt.Errorf("detect repo: empty gh repo")
	}
	return repo, nil
}

type prMergeComment struct {
	Body string `json:"body"`
}

type prMergeReview struct {
	Body string `json:"body"`
}

type prMergeView struct {
	Comments []prMergeComment `json:"comments"`
	Reviews  []prMergeReview  `json:"reviews"`
}

func collectPrMergeCommentBodies(opts prMergeOptions, gh ghRunner) ([]string, error) {
	var bodies []string

	apiPath := fmt.Sprintf("repos/%s/pulls/%s/comments", opts.repo, opts.number)
	out, err := gh("api", apiPath)
	if err != nil {
		return nil, fmt.Errorf("load review comments: %w", err)
	}
	var reviewComments []prMergeComment
	if err := json.Unmarshal(out, &reviewComments); err != nil {
		return nil, fmt.Errorf("parse review comments: %w", err)
	}
	for _, c := range reviewComments {
		bodies = append(bodies, c.Body)
	}

	out, err = gh("pr", "view", opts.number, "--repo", opts.repo, "--json", "comments,reviews")
	if err != nil {
		return nil, fmt.Errorf("load pr view: %w", err)
	}
	var view prMergeView
	if err := json.Unmarshal(out, &view); err != nil {
		return nil, fmt.Errorf("parse pr view: %w", err)
	}
	for _, c := range view.Comments {
		bodies = append(bodies, c.Body)
	}
	for _, r := range view.Reviews {
		bodies = append(bodies, r.Body)
	}
	return bodies, nil
}

var c1FinalVerdictRe = regexp.MustCompile(`(?im)^[#>*\-\s]*C1\s*(?:\x{7ec8}\x{5ba1}|final\s*verdict)\s*(?:--|-|—|–)\s*(?:APPROVED|\x{901a}\x{8fc7})(?:\s|$)`)

func findC1FinalVerdict(bodies []string) string {
	for _, body := range bodies {
		if c1FinalVerdictRe.MatchString(body) {
			return body
		}
	}
	return ""
}

var specSectionRe = regexp.MustCompile(`(?i)(?:spec|per\s+spec|\x{6309}\s*spec)\s*\x{00a7}\s*\d+(?:\.\d+)*`)

func hasSpecSectionReference(body string) bool {
	return specSectionRe.MatchString(body)
}

var countPassRe = regexp.MustCompile(`(?is)-count=(\d+)\b[\s\S]*?\bPASS\b`)

func validatePrMergeCount(body string) error {
	required := 50
	if strings.Contains(body, "[no-flake-risk]") {
		required = 1
	}
	best := 0
	for _, m := range countPassRe.FindAllStringSubmatch(body, -1) {
		n, _ := strconv.Atoi(m[1])
		if n > best {
			best = n
		}
		if n >= required {
			return nil
		}
	}
	return &prMergeFailure{
		code:    "RULE_C_INSUFFICIENT_COUNT",
		message: fmt.Sprintf("comment has -count=%d PASS but rule requires -count>=%d", best, required),
	}
}

type prMergeCheck struct {
	Name  string `json:"name"`
	State string `json:"state"`
}

func validatePrMergeChecks(opts prMergeOptions, gh ghRunner) (string, error) {
	out, err := gh("pr", "checks", opts.number, "--repo", opts.repo, "--json", "state,name")
	if err != nil {
		if strings.Contains(strings.ToLower(string(out)), "no checks reported") {
			return "no CI checks configured on this repo, skipping rule D", nil
		}
		return "", fmt.Errorf("load pr checks: %w: %s", err, strings.TrimSpace(string(out)))
	}
	var checks []prMergeCheck
	if err := json.Unmarshal(out, &checks); err != nil {
		return "", fmt.Errorf("parse pr checks: %w", err)
	}
	if len(checks) == 0 {
		return "no CI checks configured on this repo, skipping rule D", nil
	}
	var bad []string
	for _, check := range checks {
		state := strings.ToUpper(check.State)
		switch state {
		case "SUCCESS", "NEUTRAL", "SKIPPED":
			continue
		case "PENDING", "QUEUED", "IN_PROGRESS":
			name := check.Name
			if name == "" {
				name = state
			}
			return "", &prMergeFailure{
				code:    "RULE_D_CI_PENDING",
				message: fmt.Sprintf("check still pending: %s", name),
			}
		default:
			name := check.Name
			if name == "" {
				name = state
			}
			bad = append(bad, name)
		}
	}
	if len(bad) > 0 {
		return "", &prMergeFailure{
			code:    "RULE_D_CI_NOT_GREEN",
			message: fmt.Sprintf("%d checks failed (%s)", len(bad), strings.Join(bad, " / ")),
		}
	}
	return "", nil
}

func writePrMergeDryRun(w io.Writer, result prMergeResult, err error) {
	fmt.Fprintf(w, "RULE_A_C1_VERDICT=%s\n", passFail(result.ruleA))
	fmt.Fprintf(w, "RULE_B_SPEC_REF=%s\n", passFail(result.ruleB))
	fmt.Fprintf(w, "RULE_C_COUNT_PASS=%s\n", passFail(result.ruleC))
	fmt.Fprintf(w, "RULE_D_CI_GREEN=%s\n", passFail(result.ruleD))
	if err != nil {
		fmt.Fprintln(w, "DRY_RUN_RESULT=fail")
	}
}

func passFail(ok bool) string {
	if ok {
		return "pass"
	}
	return "fail"
}
