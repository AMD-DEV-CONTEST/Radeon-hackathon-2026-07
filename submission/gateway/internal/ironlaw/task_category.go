package ironlaw

import (
	"regexp"
	"strings"
)

// TaskCategory is the six-class classification a task is tagged with at
// intake time. It drives routing (which agent type can handle it) and
// ILS gate behavior (e.g. ops_maintenance tasks must not enter the agent
// queue per ILS-R013). The value is stored in tasks.payload.task_category
// as a bare string — no schema change, just a jsonb field.
//
// The six classes:
//
//   - coding:          write/modify code (default fallback, matches the
//                      existing intake.go default task_type="coding")
//   - reasoning:       analysis/planning/research that needs no shell
//   - execution:       build/compile/package — needs a shell-capable
//                      agent (ILS-R008)
//   - ops_maintenance: systemctl/disk-clean/cert-renew — must NOT enter
//                      the agent queue (ILS-R013)
//   - chat:            conversational reply (OB chat:send path)
//   - review:          code/data review, often gate-exempt
type TaskCategory string

const (
	CategoryCoding         TaskCategory = "coding"
	CategoryReasoning      TaskCategory = "reasoning"
	CategoryExecution      TaskCategory = "execution"
	CategoryOpsMaintenance TaskCategory = "ops_maintenance"
	CategoryChat           TaskCategory = "chat"
	CategoryReview         TaskCategory = "review"
)

// reChatHint / reReviewHint detect conversational and review tasks from
// free text. ops and execution reuse the regexes already defined in
// pre_intake.go (reOpsMaintenance, reExecutionTask) so there is one
// source of truth for those categories; chat and review had no existing
// regex because they were handled by task_type alone.
var (
	reChatHint   = regexp.MustCompile(`(?i)\b(chat|回复|conversation)\b`)
	reReviewHint = regexp.MustCompile(`(?i)\b(review|code review|审查|评审)\b`)
)

// ClassifyTask assigns a TaskCategory. Decision order, most-specific first:
//
//  1. If taskType names a category (case-insensitive), use it — except
//     "coding", which is also the generic default and so falls through
//     to keyword detection (a coding-typed task mentioning "go build"
//     classifies as execution; see ILS-R008).
//  2. Ops-maintenance keywords → ops_maintenance (highest keyword
//     priority: ILS-R013 says these never enter the queue, so they win
//     over execution/coding signals in the same text).
//  3. Execution keywords → execution (needs shell agent, ILS-R008).
//  4. Chat keyword → chat.
//  5. Review keyword → review.
//  6. Default → coding (matches intake.go's taskType=="" → "coding").
func ClassifyTask(taskType, title, description string) TaskCategory {
	switch strings.ToLower(strings.TrimSpace(taskType)) {
	case "reasoning":
		return CategoryReasoning
	case "execution":
		return CategoryExecution
	case "ops_maintenance", "ops", "maintenance":
		return CategoryOpsMaintenance
	case "chat":
		return CategoryChat
	case "review":
		return CategoryReview
		// "coding" and unknown/empty fall through to keyword detection.
	}

	text := title + " " + description
	if reOpsMaintenance.MatchString(text) {
		return CategoryOpsMaintenance
	}
	if reExecutionTask.MatchString(text) {
		return CategoryExecution
	}
	if reChatHint.MatchString(text) {
		return CategoryChat
	}
	if reReviewHint.MatchString(text) {
		return CategoryReview
	}
	return CategoryCoding
}
