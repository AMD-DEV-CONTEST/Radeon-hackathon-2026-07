// Package keeper implements the keeper role's decision-making layer.
//
// The keeper is a terminal executor (it does NOT dispatch sub-agents).
// Its job is to take a bounded decision request, ask an LLM for a
// proposal, then run that proposal through a deterministic rule check
// before acting. The LLM never makes the final call — ironlaw does.
//
// This package is deliberately provider-agnostic: only the LLMProvider
// interface and a Mock implementation ship here. Real providers (groq,
// Nvidia, Gemini, paid APIs) are added later by implementing the
// interface; the FallbackChain then rotates through them in order.
package keeper

import (
	"context"
	"errors"
	"fmt"
	"sync/atomic"
)

// ChatMessage is a single turn in a chat exchange. Mirrors the
// OpenAI/Anthropic role convention so a future real provider needs no
// translation.
type ChatMessage struct {
	Role    string `json:"role"`    // system | user | assistant
	Content string `json:"content"`
}

// ChatResponse is the LLM provider's reply. Provider names which
// provider actually answered (relevant under FallbackChain). LatencyMs
// and TokensUsed are observability fields; a provider that can't fill
// them leaves them zero.
type ChatResponse struct {
	Content    string `json:"content"`
	Provider   string `json:"provider"`
	LatencyMs  int64  `json:"latency_ms"`
	TokensUsed int    `json:"tokens_used,omitempty"`
}

// LLMProvider is the abstraction every chat backend implements. The
// keeper's FallbackChain holds an ordered slice of these and uses the
// first that is Available and whose Chat succeeds.
//
// Available() is a cheap health check — it must NOT make a network call
// on every invocation. Providers should gate on a cached liveness flag
// (set by a background ping) so the chain can scan quickly.
type LLMProvider interface {
	Name() string
	Chat(ctx context.Context, messages []ChatMessage) (*ChatResponse, error)
	Available() bool
}

// FallbackChain tries each provider in order until one answers. This is
// the keeper's resilience against a single LLM outage: local small
// model → groq → Nvidia → Gemini free → paid API. The chain is the
// only path the keeper uses to reach an LLM.
type FallbackChain struct {
	providers []LLMProvider
}

// NewFallbackChain builds a chain. Order matters: list providers from
// cheapest/most-available to most-expensive/least-available.
func NewFallbackChain(providers ...LLMProvider) *FallbackChain {
	return &FallbackChain{providers: providers}
}

// Chat walks the chain. A provider is skipped if Available() is false
// OR Chat returns an error. The first successful Chat response wins. If
// every provider fails, Chat returns an error describing how many were
// tried.
func (fc *FallbackChain) Chat(ctx context.Context, msgs []ChatMessage) (*ChatResponse, error) {
	if len(fc.providers) == 0 {
		return nil, errors.New("keeper: empty fallback chain (no providers configured)")
	}
	var lastErr error
	tried := 0
	for _, p := range fc.providers {
		if !p.Available() {
			continue
		}
		tried++
		resp, err := p.Chat(ctx, msgs)
		if err == nil {
			return resp, nil
		}
		lastErr = err
	}
	if lastErr != nil {
		return nil, fmt.Errorf("keeper: all %d available providers failed (last err: %w)", tried, lastErr)
	}
	return nil, fmt.Errorf("keeper: no provider available (checked %d)", len(fc.providers))
}

// MockLLMProvider is the test stand-in for a real provider. It returns
// the configured Reply (or Err) and reports Available() true unless
// explicitly disabled. It also counts Chat calls so tests can assert
// the chain visited it.
type MockLLMProvider struct {
	Reply    *ChatResponse
	Err      error
	Disabled bool
	calls    int64
}

// NewMockProvider is a convenience constructor for the common case:
// a provider that always returns the given content.
func NewMockProvider(content string) *MockLLMProvider {
	return &MockLLMProvider{Reply: &ChatResponse{Content: content, Provider: "mock"}}
}

func (m *MockLLMProvider) Name() string { return "mock" }
func (m *MockLLMProvider) Available() bool {
	return !m.Disabled
}
func (m *MockLLMProvider) Chat(ctx context.Context, msgs []ChatMessage) (*ChatResponse, error) {
	atomic.AddInt64(&m.calls, 1)
	if m.Err != nil {
		return nil, m.Err
	}
	if m.Reply == nil {
		return &ChatResponse{Content: "", Provider: "mock"}, nil
	}
	// Simulate a tiny latency so the LatencyMs field is non-zero in
	// tests that check it.
	r := *m.Reply
	if r.Provider == "" {
		r.Provider = "mock"
	}
	if r.LatencyMs == 0 {
		r.LatencyMs = 1
	}
	return &r, nil
}

// Calls returns how many times Chat was invoked. Test-only.
func (m *MockLLMProvider) Calls() int {
	return int(atomic.LoadInt64(&m.calls))
}
