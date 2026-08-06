package uasclient

import (
	"context"
	"encoding/json"
	"fmt"
	"net/url"
	"time"

	"github.com/gorilla/websocket"
)

// wsURL builds the full WebSocket URL from a base + app_id + token.
func wsURL(gatewayURL, appID, wsToken string) string {
	base := trimRight(gatewayURL, '/')
	if len(base) >= 3 && base[len(base)-3:] == "/ws" {
		// already has /ws
	} else {
		base += "/ws"
	}
	u := base + "?app_id=" + url.QueryEscape(appID) + "&token=" + url.QueryEscape(wsToken)
	return u
}

// doHandshake blocks until the server sends server:welcome with a
// connection_id, then writes back a client.ready (or agent.ready for
// agent-mode connections). The caller passes the result through
// OnReady, which is the right hook for the reconnect→replay path.
//
// readyType must be "client.ready" or "agent.ready". The Gateway
// doesn't care which, but it stamps the value onto the connection
// record and the operator reads it later from /events/status, so we
// get it right.
func doHandshake(ctx context.Context, conn *websocket.Conn, readyType string) (connectionID string, err error) {
	deadline, ok := ctx.Deadline()
	if !ok {
		deadline = time.Now().Add(5 * time.Second)
	}
	_ = conn.SetReadDeadline(deadline)
	_, raw, err := conn.ReadMessage()
	if err != nil {
		return "", fmt.Errorf("handshake read welcome: %w", err)
	}
	_ = conn.SetReadDeadline(time.Time{})
	var welcome map[string]interface{}
	if err := json.Unmarshal(raw, &welcome); err != nil {
		return "", fmt.Errorf("handshake parse welcome: %w (raw=%q)", err, string(raw))
	}
	if welcome["type"] != "server:welcome" {
		return "", fmt.Errorf("handshake: expected server:welcome, got %v", welcome["type"])
	}
	connectionID, _ = welcome["connection_id"].(string)
	if connectionID == "" {
		return "", fmt.Errorf("handshake: server:welcome missing connection_id")
	}
	ready := map[string]interface{}{
		"type":          readyType,
		"connection_id": connectionID,
		"ts":            time.Now().UTC().Format(time.RFC3339),
	}
	if err := conn.WriteJSON(ready); err != nil {
		return "", fmt.Errorf("handshake write ready: %w", err)
	}
	return connectionID, nil
}
