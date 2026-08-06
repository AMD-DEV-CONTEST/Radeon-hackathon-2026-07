package keeper

import (
	"context"
	"errors"
	"fmt"
	"strings"
)

// KeeperDecisionRequest is the input to a keeper decision. The keeper
// is asked a Question with a closed set of Options; the LLM proposes
// one, and the rule checker accepts or overrides. Constraints carry
// ironlaw context the checker may consult (unused by the simple
// whitelist today, but reserved so future rule complexity doesn't
// change the request shape).
type KeeperDecisionRequest struct {
	Context     string                 `json:"context"`
	Question    string                 `json:"question"`
	Options     []string               `json:"options"`
	Constraints map[string]interface{} `json:"constraints,omitempty"`
}

// KeeperDecisionResult captures both stages: what the LLM proposed and
// what the rule checker ultimately decided. Both are recorded so an
// audit trail can distinguish "LLM was right" from "LLM was wrong but
// rules saved us" from "LLM was down, we defaulted".
type KeeperDecisionResult struct {
	Proposal      string `json:"proposal"`       // raw LLM output (empty if LLM failed)
	FinalDecision string `json:"final_decision"` // after rule check
	Accepted      bool   `json:"accepted"`       // rules accepted the LLM proposal
	Reason        string `json:"reason"`         // why accepted or rejected
	Provider      string `json:"provider"`       // which LLM answered (empty if none)
}

// ErrNoOptions is returned by MakeDecision when the request has no
// options — a caller bug, not a runtime condition worth defaulting.
var ErrNoOptions = errors.New("keeper: decision request has no options")

// MakeDecision runs the two-stage keeper decision:
//
//  1. Ask the LLM (via provider, which may be a FallbackChain) for a
//     proposal given the context + question + options.
//  2. Run the proposal through the rule checker. Today the rule is a
//     whitelist: if the proposal exactly matches one of Options (trimmed,
//     case-insensitive), accept it; otherwise reject and default to
//     Options[0].
//
// LLM failure is NOT propagated: a keeper decision always returns an
// answer. When the LLM is unavailable, the result defaults to Options[0]
// with Accepted=false and a reason explaining the LLM was down. This is
// the "graceful degrade" contract — an LLM outage slows the keeper, it
// doesn't stop it.
func MakeDecision(ctx context.Context, provider LLMProvider, req KeeperDecisionRequest) (*KeeperDecisionResult, error) {
	if len(req.Options) == 0 {
		return nil, ErrNoOptions
	}
	defaultDecision := req.Options[0]

	res := &KeeperDecisionResult{
		FinalDecision: defaultDecision,
		Accepted:      false,
		Reason:        "default (no LLM proposal yet)",
	}

	// Stage 1: LLM proposal.
	proposal, providerName, err := askLLM(ctx, provider, req)
	if err != nil {
		res.Reason = fmt.Sprintf("llm unavailable: %v; defaulted to first option", err)
		return res, nil
	}
	res.Proposal = proposal
	res.Provider = providerName

	// Stage 2: rule check (whitelist).
	matched, ok := matchOption(proposal, req.Options)
	if ok {
		res.FinalDecision = matched
		res.Accepted = true
		res.Reason = "proposal matched an allowed option"
		return res, nil
	}

	// Rejected: keep the default, record why.
	res.FinalDecision = defaultDecision
	res.Reason = fmt.Sprintf("proposal %q not in allowed options; defaulted", proposal)
	return res, nil
}

// askLLM calls the provider with a prompt built from the request. It
// returns the raw proposal text + the provider name. Errors here are
// expected (LLM down) and handled by the caller.
func askLLM(ctx context.Context, provider LLMProvider, req KeeperDecisionRequest) (proposal, providerName string, err error) {
	if provider == nil {
		return "", "", errors.New("no provider configured")
	}
	prompt := buildPrompt(req)
	resp, err := provider.Chat(ctx, []ChatMessage{
		{Role: "system", Content: "You are a keeper agent. Reply with exactly one of the listed options and nothing else."},
		{Role: "user", Content: prompt},
	})
	if err != nil {
		return "", "", err
	}
	return strings.TrimSpace(resp.Content), resp.Provider, nil
}

// buildPrompt assembles the user-facing prompt. The options are listed
// verbatim so the LLM's reply can be matched against them.
func buildPrompt(req KeeperDecisionRequest) string {
	var b strings.Builder
	b.WriteString("Context: ")
	b.WriteString(req.Context)
	b.WriteString("\nQuestion: ")
	b.WriteString(req.Question)
	b.WriteString("\nOptions (reply with exactly one):")
	for _, o := range req.Options {
		b.WriteString("\n- ")
		b.WriteString(o)
	}
	return b.String()
}

// matchOption returns the canonical form of the option the proposal
// matches, case-insensitively and after trimming whitespace. Returns
// ok=false when the proposal isn't any of the options.
func matchOption(proposal string, options []string) (string, bool) {
	p := strings.ToLower(strings.TrimSpace(proposal))
	for _, o := range options {
		if strings.ToLower(strings.TrimSpace(o)) == p {
			return o, true
		}
	}
	return "", false
}
