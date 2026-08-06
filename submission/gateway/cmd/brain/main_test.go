package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/konspace/unionagents-go/internal/uasclient"
)

func resetConvState() {
	stateMu.Lock()
	defer stateMu.Unlock()
	convMap = make(map[string]*convState)
}

func TestCallLLM_RequestShapeAndParse(t *testing.T) {
	var got llmRequest
	var hdr http.Header
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hdr = r.Header.Clone()
		body, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(body, &got)
		w.WriteHeader(200)
		_, _ = w.Write([]byte(`{
			"content":[{"type":"text","text":"hello"}],
			"stop_reason":"end_turn",
			"usage":{"input_tokens":7,"output_tokens":2}
		}`))
	}))
	defer s.Close()

	hc := s.Client()
	text, inTok, outTok, err := callLLM(
		context.Background(), hc,
		s.URL, "sk-test", "deepseek-v4-flash",
		"sys", "ping?", 200, 0.5,
	)
	if err != nil {
		t.Fatal(err)
	}
	if text != "hello" {
		t.Errorf("text: %q", text)
	}
	if inTok != 7 || outTok != 2 {
		t.Errorf("usage: %d/%d", inTok, outTok)
	}
	if got.Model != "deepseek-v4-flash" || got.MaxTokens != 200 || got.System != "sys" {
		t.Errorf("req: %+v", got)
	}
	if len(got.Messages) != 1 || got.Messages[0].Content != "ping?" {
		t.Errorf("messages: %+v", got.Messages)
	}
	if hdr.Get("Authorization") != "Bearer sk-test" {
		t.Errorf("auth header: %q", hdr.Get("Authorization"))
	}
	if hdr.Get("x-api-key") != "" {
		t.Errorf("x-api-key must NOT be sent (DeepSeek rejects it): %q", hdr.Get("x-api-key"))
	}
}

func TestCallLLM_HTTPErrorReturned(t *testing.T) {
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(401)
		_, _ = w.Write([]byte(`{"error":"unauth"}`))
	}))
	defer s.Close()
	_, _, _, err := callLLM(context.Background(), s.Client(), s.URL, "bad", "m", "sys", "ping", 100, 0.5)
	if err == nil {
		t.Fatal("expected error on 401")
	}
}

func TestHandleEvent_FullChainAndAntiLoop(t *testing.T) {
	llmServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"content":[{"type":"text","text":"reply"}],"stop_reason":"end_turn","usage":{"input_tokens":3,"output_tokens":1}}`))
	}))
	defer llmServer.Close()

	cfg := runtimeConfig{
		AgentID: "cc-c1-brain", AgentName: "C1",
		LLMBaseURL: llmServer.URL, LLMAPIKey: "sk", LLMModel: "m",
		MaxTokens: 100, Temperature: 0.5,
	}

	var mu sync.Mutex
	var sent []uasclient.Outgoing
	send := func(_ context.Context, msg uasclient.Outgoing) (*uasclient.SendResult, error) {
		mu.Lock()
		sent = append(sent, msg)
		mu.Unlock()
		return &uasclient.SendResult{Status: "accepted", DeliveredToConnections: 1}, nil
	}

	hc := &http.Client{}

	handleEvent(context.Background(), hc, send, cfg, uasclient.Event{
		Type: "chat", ConvID: "cv-1", FromAgentID: "reasonix-r3-aws", Text: "ping?",
	})
	handleEvent(context.Background(), hc, send, cfg, uasclient.Event{
		Type: "chat", ConvID: "cv-1", FromAgentID: "cc-c1-brain", Text: "echo",
	})
	handleEvent(context.Background(), hc, send, cfg, uasclient.Event{
		Type: "chat", ConvID: "", FromAgentID: "r3", Text: "x",
	})

	if len(sent) != 1 {
		t.Fatalf("expected exactly 1 send, got %d", len(sent))
	}
	got := sent[0]
	if got.TargetAgentID != "reasonix-r3-aws" || got.Text != "reply" || got.ConvID != "cv-1" {
		t.Errorf("send shape: %+v", got)
	}
	if got.FromAgentID != "cc-c1-brain" || got.From != "C1" {
		t.Errorf("identity: %+v", got)
	}
}

func TestHandleEvent_LLMFailureSwallowedNoSend(t *testing.T) {
	llmServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(500)
	}))
	defer llmServer.Close()
	cfg := runtimeConfig{
		AgentID: "cc-c1-brain", AgentName: "C1",
		LLMBaseURL: llmServer.URL, LLMAPIKey: "sk", LLMModel: "m",
		MaxTokens: 50, Temperature: 0.5,
	}
	var called bool
	send := func(_ context.Context, _ uasclient.Outgoing) (*uasclient.SendResult, error) {
		called = true
		return &uasclient.SendResult{}, nil
	}
	handleEvent(context.Background(), &http.Client{}, send, cfg, uasclient.Event{
		Type: "chat", ConvID: "cv-1", FromAgentID: "r3", Text: "hi",
	})
	if called {
		t.Fatal("must not send when LLM fails")
	}
}

func TestGuardrail_TurnLimitBlocksExcess(t *testing.T) {
	resetConvState()
	llmServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"content":[{"type":"text","text":"ok"}],"stop_reason":"end_turn","usage":{"input_tokens":1,"output_tokens":1}}`))
	}))
	defer llmServer.Close()

	cfg := runtimeConfig{
		AgentID: "cc-c1-brain", AgentName: "C1",
		LLMBaseURL: llmServer.URL, LLMAPIKey: "sk", LLMModel: "m",
		MaxTokens: 100, Temperature: 0.5,
		Guardrails: guardrailConfig{MaxTurnsPerConv: 2},
	}

	var sent int
	send := func(_ context.Context, _ uasclient.Outgoing) (*uasclient.SendResult, error) {
		sent++
		return &uasclient.SendResult{DeliveredToConnections: 1}, nil
	}

	handleEvent(context.Background(), &http.Client{}, send, cfg, uasclient.Event{
		Type: "chat", ConvID: "cv-limit", FromAgentID: "r3", Text: "m1",
	})
	handleEvent(context.Background(), &http.Client{}, send, cfg, uasclient.Event{
		Type: "chat", ConvID: "cv-limit", FromAgentID: "r3", Text: "m2",
	})
	handleEvent(context.Background(), &http.Client{}, send, cfg, uasclient.Event{
		Type: "chat", ConvID: "cv-limit", FromAgentID: "r3", Text: "m3",
	})

	if sent != 2 {
		t.Errorf("expected 2 replies (turn limit), got %d", sent)
	}
}

func TestGuardrail_PeerNotAllowedBlocksReply(t *testing.T) {
	resetConvState()
	llmServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"content":[{"type":"text","text":"ok"}],"stop_reason":"end_turn","usage":{"input_tokens":1,"output_tokens":1}}`))
	}))
	defer llmServer.Close()

	cfg := runtimeConfig{
		AgentID: "cc-c1-brain", AgentName: "C1",
		LLMBaseURL: llmServer.URL, LLMAPIKey: "sk", LLMModel: "m",
		MaxTokens: 100, Temperature: 0.5,
		Guardrails: guardrailConfig{AllowedPeers: map[string]bool{"trusted-r3": true}},
	}

	var called bool
	send := func(_ context.Context, _ uasclient.Outgoing) (*uasclient.SendResult, error) {
		called = true
		return &uasclient.SendResult{}, nil
	}

	handleEvent(context.Background(), &http.Client{}, send, cfg, uasclient.Event{
		Type: "chat", ConvID: "cv-peer", FromAgentID: "evil-r5", Text: "hack",
	})
	if called {
		t.Error("must not reply to unallowed peer")
	}

	handleEvent(context.Background(), &http.Client{}, send, cfg, uasclient.Event{
		Type: "chat", ConvID: "cv-peer", FromAgentID: "trusted-r3", Text: "hi",
	})
	if !called {
		t.Error("must reply to allowed peer")
	}
}

func TestGuardrail_CooldownPreventsBurstReplies(t *testing.T) {
	resetConvState()
	llmServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"content":[{"type":"text","text":"ok"}],"stop_reason":"end_turn","usage":{"input_tokens":1,"output_tokens":1}}`))
	}))
	defer llmServer.Close()

	cfg := runtimeConfig{
		AgentID: "cc-c1-brain", AgentName: "C1",
		LLMBaseURL: llmServer.URL, LLMAPIKey: "sk", LLMModel: "m",
		MaxTokens: 100, Temperature: 0.5,
		Guardrails: guardrailConfig{ReplyCooldown: 200 * time.Millisecond},
	}

	var sent int
	send := func(_ context.Context, _ uasclient.Outgoing) (*uasclient.SendResult, error) {
		sent++
		return &uasclient.SendResult{DeliveredToConnections: 1}, nil
	}

	handleEvent(context.Background(), &http.Client{}, send, cfg, uasclient.Event{
		Type: "chat", ConvID: "cv-cool", FromAgentID: "r3", Text: "m1",
	})
	handleEvent(context.Background(), &http.Client{}, send, cfg, uasclient.Event{
		Type: "chat", ConvID: "cv-cool", FromAgentID: "r3", Text: "m2",
	})

	if sent != 1 {
		t.Errorf("expected 1 reply during cooldown, got %d", sent)
	}

	time.Sleep(250 * time.Millisecond)
	handleEvent(context.Background(), &http.Client{}, send, cfg, uasclient.Event{
		Type: "chat", ConvID: "cv-cool", FromAgentID: "r3", Text: "m3",
	})

	if sent != 2 {
		t.Errorf("expected 2nd reply after cooldown, got %d", sent)
	}
}

func TestGuardrail_TokenLimitBlocksExcess(t *testing.T) {
	resetConvState()
	llmServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"content":[{"type":"text","text":"ok"}],"stop_reason":"end_turn","usage":{"input_tokens":50,"output_tokens":50}}`))
	}))
	defer llmServer.Close()

	cfg := runtimeConfig{
		AgentID: "cc-c1-brain", AgentName: "C1",
		LLMBaseURL: llmServer.URL, LLMAPIKey: "sk", LLMModel: "m",
		MaxTokens: 100, Temperature: 0.5,
		Guardrails: guardrailConfig{MaxTokensPerConv: 100}, // exactly 100 = 50+50
	}

	var sent int
	send := func(_ context.Context, _ uasclient.Outgoing) (*uasclient.SendResult, error) {
		sent++
		return &uasclient.SendResult{DeliveredToConnections: 1}, nil
	}

	handleEvent(context.Background(), &http.Client{}, send, cfg, uasclient.Event{
		Type: "chat", ConvID: "cv-tok", FromAgentID: "r3", Text: "m1",
	})
	handleEvent(context.Background(), &http.Client{}, send, cfg, uasclient.Event{
		Type: "chat", ConvID: "cv-tok", FromAgentID: "r3", Text: "m2",
	})

	if sent != 1 {
		t.Errorf("expected 1 reply (total 100 tok hits limit), got %d", sent)
	}
}

func TestGuardrail_WallTimeLimitBlocksAfterTimeout(t *testing.T) {
	resetConvState()
	llmServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"content":[{"type":"text","text":"ok"}],"stop_reason":"end_turn","usage":{"input_tokens":1,"output_tokens":1}}`))
	}))
	defer llmServer.Close()

	cfg := runtimeConfig{
		AgentID: "cc-c1-brain", AgentName: "C1",
		LLMBaseURL: llmServer.URL, LLMAPIKey: "sk", LLMModel: "m",
		MaxTokens: 100, Temperature: 0.5,
		Guardrails: guardrailConfig{MaxWallTimePerConv: 100 * time.Millisecond},
	}

	var sent int
	send := func(_ context.Context, _ uasclient.Outgoing) (*uasclient.SendResult, error) {
		sent++
		return &uasclient.SendResult{DeliveredToConnections: 1}, nil
	}

	handleEvent(context.Background(), &http.Client{}, send, cfg, uasclient.Event{
		Type: "chat", ConvID: "cv-wall", FromAgentID: "r3", Text: "m1",
	})
	time.Sleep(150 * time.Millisecond)
	handleEvent(context.Background(), &http.Client{}, send, cfg, uasclient.Event{
		Type: "chat", ConvID: "cv-wall", FromAgentID: "r3", Text: "m2",
	})

	if sent != 1 {
		t.Errorf("expected 1 reply before wall time expires, got %d", sent)
	}
}
