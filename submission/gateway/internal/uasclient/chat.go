package uasclient

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"time"

	"github.com/gorilla/websocket"
)

// Send posts a chat message via HTTP /chat and returns the
// Gateway's structured response. This is the one-shot path used
// by both standalone CLI use and by Request (which calls Send
// first and then waits for the matching reply on the WS).
func (c *Client) Send(ctx context.Context, msg Outgoing) (*SendResult, error) {
	body, _ := json.Marshal(msg)
	gw := c.resolveGateway(msg.TargetAgentID)
	req, err := http.NewRequestWithContext(ctx, "POST", HTTPBase(gw)+"/chat", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	out, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("/chat: read body: %w", err)
	}
	if resp.StatusCode >= 300 {
		return nil, fmt.Errorf("/chat HTTP %d: %s", resp.StatusCode, string(out))
	}
	var sr SendResult
	if err := json.Unmarshal(out, &sr); err != nil {
		return nil, fmt.Errorf("/chat: invalid JSON: %w (body=%q)", err, string(out))
	}
	return &sr, nil
}

// Request sends a chat message and blocks until a matching reply
// arrives on the WS read loop, or the timeout fires, or ctx is
// cancelled. The match rule is: conv_id matches AND (from_agent_id
// OR from) matches the target we sent to. This mirrors the legacy
// ils chat request behavior.
func (c *Client) Request(ctx context.Context, msg Outgoing, timeout time.Duration) (Event, error) {
	if msg.ConvID == "" {
		msg.ConvID = fmt.Sprintf("a2a_%d", time.Now().UnixNano())
	}
	// Use a one-shot channel; the OnEvent hook will deliver the
	// reply into it when the matching event arrives. We preserve
	// the caller's OnEvent so a stream consumer still gets every
	// event, including the matching reply.
	type replyResult struct {
		evt Event
	}
	ch := make(chan replyResult, 1)

	prev := c.cfg.OnEvent
	c.cfg.OnEvent = func(ctx context.Context, e Event) error {
		if isReplyFor(e, msg) {
			select {
			case ch <- replyResult{evt: e}:
			default:
			}
		}
		if prev != nil {
			return prev(ctx, e)
		}
		return nil
	}
	defer func() {
		c.cfg.OnEvent = prev
	}()

	if c.currentConn() == nil {
		return Event{}, errNotReady
	}

	sr, err := c.Send(ctx, msg)
	if err != nil {
		return Event{}, err
	}
	if !sr.TargetConnected {
		return Event{}, fmt.Errorf("target %s not connected", msg.TargetAgentID)
	}

	tctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	select {
	case <-tctx.Done():
		return Event{}, tctx.Err()
	case r := <-ch:
		return r.evt, nil
	}
}

// Reply sends a chat reply tied to a previously-received event
// via its event_id. The Gateway correlates requests and replies
// through conv_id; we also stamp the inbound event_id into the
// X-Event-Id header for forward-compat logging on the Gateway
// side. eventID may be empty if the caller has no correlation
// token (e.g. test scaffolding).
func (c *Client) Reply(ctx context.Context, eventID string, msg Outgoing) error {
	if msg.ConvID == "" {
		return fmt.Errorf("Reply: msg.ConvID is required (carried from the inbound event)")
	}
	body, _ := json.Marshal(msg)
	gw := c.resolveGateway(msg.TargetAgentID)
	req, err := http.NewRequestWithContext(ctx, "POST", HTTPBase(gw)+"/chat", bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if eventID != "" {
		req.Header.Set("X-Event-Id", eventID)
	}
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		out, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("/chat HTTP %d: %s", resp.StatusCode, string(out))
	}
	return nil
}

// isReplyFor decides whether e is the matching reply for an A2A
// request. Mirrors the legacy isA2AReply rule from chat.go:241:
//
//	event type == "chat"
//	conv_id matches (or, for legacy frames, conversation_id matches)
//	from matches the target we sent to (either by agent_id or by
//	display name)
//	if the reply has target_agent_id set, it must be us
func isReplyFor(e Event, sent Outgoing) bool {
	if e.Type != "chat" {
		return false
	}
	convID := e.ConvID
	if convID == "" {
		if cid, ok := e.Raw["conversation_id"].(string); ok {
			convID = cid
		}
	}
	if convID != sent.ConvID {
		return false
	}
	fromMatches := e.FromAgentID == sent.TargetAgentID || e.From == sent.TargetAgentID
	if !fromMatches {
		return false
	}
	if e.TargetAgentID != "" && sent.FromAgentID != "" && e.TargetAgentID != sent.FromAgentID {
		return false
	}
	return true
}

// urlValues is a tiny helper used by dedupe.go and here.
func urlValues(p map[string]string) url.Values {
	v := url.Values{}
	for k, val := range p {
		v.Set(k, val)
	}
	return v
}

// connOrError returns the live connection or errNotReady. Used by
// callers (and the OnEvent override path in Request) that want
// to fail fast when Connect wasn't started.
func (c *Client) connOrError() (*websocket.Conn, error) {
	conn := c.currentConn()
	if conn == nil {
		return nil, errNotReady
	}
	return conn, nil
}
