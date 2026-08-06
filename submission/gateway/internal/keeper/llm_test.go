package keeper

import (
	"context"
	"errors"
	"testing"
)

// flakyProvider is a test helper: Available + Chat behavior controlled
// by fields, so we can simulate "up but errors", "down", and "happy".
type flakyProvider struct {
	name      string
	available bool
	chatErr   error
	reply     *ChatResponse
	calls     int
}

func (f *flakyProvider) Name() string { return f.name }
func (f *flakyProvider) Available() bool {
	f.calls++
	return f.available
}
func (f *flakyProvider) Chat(ctx context.Context, msgs []ChatMessage) (*ChatResponse, error) {
	f.calls++
	if f.chatErr != nil {
		return nil, f.chatErr
	}
	if f.reply == nil {
		return &ChatResponse{Content: "default-reply", Provider: f.name}, nil
	}
	return f.reply, nil
}

// TestFallbackChain_UsesFirstAvailable: the chain picks the first
// provider whose Available() is true and whose Chat succeeds.
func TestFallbackChain_UsesFirstAvailable(t *testing.T) {
	down := &flakyProvider{name: "down", available: false}
	up := &flakyProvider{name: "up", available: true, reply: &ChatResponse{Content: "from-up", Provider: "up"}}
	fc := NewFallbackChain(down, up)

	resp, err := fc.Chat(context.Background(), []ChatMessage{{Role: "user", Content: "hi"}})
	if err != nil {
		t.Fatalf("Chat: %v", err)
	}
	if resp.Provider != "up" {
		t.Fatalf("provider = %s, want up (first available)", resp.Provider)
	}
	if resp.Content != "from-up" {
		t.Fatalf("content = %s, want from-up", resp.Content)
	}
}

// TestFallbackChain_SkipsProviderThatErrors: Available() true but Chat
// errors → chain moves to the next provider rather than returning the
// error.
func TestFallbackChain_SkipsProviderThatErrors(t *testing.T) {
	broken := &flakyProvider{name: "broken", available: true, chatErr: errors.New("500")}
	good := &flakyProvider{name: "good", available: true, reply: &ChatResponse{Content: "ok", Provider: "good"}}
	fc := NewFallbackChain(broken, good)

	resp, err := fc.Chat(context.Background(), nil)
	if err != nil {
		t.Fatalf("expected fallback to good, got err: %v", err)
	}
	if resp.Provider != "good" {
		t.Fatalf("provider = %s, want good (broken should be skipped)", resp.Provider)
	}
}

// TestFallbackChain_AllFail: every provider down or erroring → the
// chain returns an error naming the last failure, NOT nil.
func TestFallbackChain_AllFail(t *testing.T) {
	down := &flakyProvider{name: "down", available: false}
	broken := &flakyProvider{name: "broken", available: true, chatErr: errors.New("boom")}
	fc := NewFallbackChain(down, broken)

	_, err := fc.Chat(context.Background(), nil)
	if err == nil {
		t.Fatal("expected error when all providers fail, got nil")
	}
}

// TestFallbackChain_Empty: a chain with no providers errors immediately
// rather than nil-deref.
func TestFallbackChain_Empty(t *testing.T) {
	fc := NewFallbackChain()
	_, err := fc.Chat(context.Background(), nil)
	if err == nil {
		t.Fatal("empty chain must error")
	}
}

// TestMakeDecision_AcceptsProposalInOptions: when the LLM proposes an
// option that's in the allowed list, the rule checker accepts and the
// final decision equals the proposal.
func TestMakeDecision_AcceptsProposalInOptions(t *testing.T) {
	provider := &MockLLMProvider{Reply: &ChatResponse{Content: "option_b", Provider: "mock"}}
	req := KeeperDecisionRequest{
		Context: "ctx",
		Question: "which?",
		Options: []string{"option_a", "option_b", "option_c"},
	}
	res, err := MakeDecision(context.Background(), provider, req)
	if err != nil {
		t.Fatalf("MakeDecision: %v", err)
	}
	if !res.Accepted {
		t.Fatalf("expected Accepted=true, got false (proposal was in options)")
	}
	if res.FinalDecision != "option_b" {
		t.Fatalf("FinalDecision = %s, want option_b", res.FinalDecision)
	}
	if res.Proposal != "option_b" {
		t.Fatalf("Proposal = %s, want option_b", res.Proposal)
	}
	if res.Provider != "mock" {
		t.Fatalf("Provider = %s, want mock", res.Provider)
	}
}

// TestMakeDecision_RejectsProposalNotInOptions: when the LLM proposes
// something outside the allowed options, the rule checker rejects and
// falls back to the first option as a safe default.
func TestMakeDecision_RejectsProposalNotInOptions(t *testing.T) {
	provider := &MockLLMProvider{Reply: &ChatResponse{Content: "option_z", Provider: "mock"}}
	req := KeeperDecisionRequest{
		Options: []string{"option_a", "option_b"},
	}
	res, _ := MakeDecision(context.Background(), provider, req)
	if res.Accepted {
		t.Fatal("expected Accepted=false (proposal not in options)")
	}
	if res.FinalDecision != "option_a" {
		t.Fatalf("FinalDecision = %s, want option_a (first option as default)", res.FinalDecision)
	}
	if res.Proposal != "option_z" {
		t.Fatalf("Proposal should still record what LLM said = %s, want option_z", res.Proposal)
	}
}

// TestMakeDecision_LLMFailureFallsBackToDefault: when the LLM call
// itself errors, MakeDecision does NOT propagate the error — it falls
// back to the first option with Accepted=false. A keeper decision
// always produces an answer; an LLM outage degrades to default, it
// doesn't block.
func TestMakeDecision_LLMFailureFallsBackToDefault(t *testing.T) {
	provider := &MockLLMProvider{Err: errors.New("llm down")}
	req := KeeperDecisionRequest{Options: []string{"safe_default", "risky"}}
	res, err := MakeDecision(context.Background(), provider, req)
	if err != nil {
		t.Fatalf("LLM failure should not propagate err: %v", err)
	}
	if res.Accepted {
		t.Fatal("expected Accepted=false on LLM failure")
	}
	if res.FinalDecision != "safe_default" {
		t.Fatalf("FinalDecision = %s, want safe_default", res.FinalDecision)
	}
	if res.Proposal != "" {
		t.Fatalf("Proposal should be empty on LLM failure, got %s", res.Proposal)
	}
}

// TestMakeDecision_NoOptions: an empty options list is a caller bug.
// MakeDecision should error rather than silently picking a phantom
// default.
func TestMakeDecision_NoOptions(t *testing.T) {
	provider := &MockLLMProvider{Reply: &ChatResponse{Content: "anything", Provider: "mock"}}
	_, err := MakeDecision(context.Background(), provider, KeeperDecisionRequest{Options: nil})
	if err == nil {
		t.Fatal("expected error for empty options, got nil")
	}
}

// TestMockLLMProvider_DirectUse: the mock returns the configured reply
// and reports Available() true by default — it's the test stand-in for
// a real provider.
func TestMockLLMProvider_DirectUse(t *testing.T) {
	m := &MockLLMProvider{Reply: &ChatResponse{Content: "mocked", Provider: "mock"}}
	if !m.Available() {
		t.Fatal("default mock should be Available")
	}
	if m.Name() != "mock" {
		t.Fatalf("Name = %s, want mock", m.Name())
	}
	resp, err := m.Chat(context.Background(), []ChatMessage{{Role: "user", Content: "x"}})
	if err != nil {
		t.Fatalf("Chat: %v", err)
	}
	if resp.Content != "mocked" {
		t.Fatalf("content = %s, want mocked", resp.Content)
	}
}
