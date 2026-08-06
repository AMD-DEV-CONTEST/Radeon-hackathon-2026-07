package uasclient

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
)

// errUnauthorized is returned by register* when the Gateway
// answers 401. The reconnect loop watches for this to trigger
// a re-registration step (the prior app_id has been invalidated
// by a Gateway restart).
var errUnauthorized = errors.New("gateway returned 401: re-registration required")

// httpBase converts a ws(s):// base into its http(s):// counterpart
// and trims any trailing /ws path. The Gateway exposes chat, auth,
// register, replay, status on plain HTTP(S); only the long-lived
// stream itself rides WebSocket.
//
// Exported because command-level helper code (e.g. cmd/ils/doctor
// and cmd/ils/status) needs the same conversion without having to
// spin up a uasclient.Client for a one-shot HTTP GET.
func HTTPBase(gatewayURL string) string {
	base := gatewayURL
	if len(base) > 5 && base[:5] == "ws://" {
		base = "http://" + base[5:]
	} else if len(base) > 6 && base[:6] == "wss://" {
		base = "https://" + base[6:]
	}
	for i := 0; i < len(base)-3; i++ {
		if base[i] == '/' && base[i+1] == 'w' && base[i+2] == 's' && (base[i+3] == '/' || base[i+3] == 0) {
			return trimRight(base[:i], '/')
		}
	}
	return trimRight(base, '/')
}

func trimRight(s string, cut byte) string {
	for len(s) > 0 && s[len(s)-1] == cut {
		s = s[:len(s)-1]
	}
	return s
}

// Login posts to /auth/login and returns a bearer token. The
// current Gateway treats AUTH_ENABLED=0 as "no login needed" and
// returns a generated token; the agent path is the only place
// that actually enforces a password check. We keep the same
// behavior: if password is empty, we still POST to /auth/login
// with empty creds and accept whatever the Gateway returns.
//
// Exported for cmd/ils/doctor (which exercises the login path
// without wanting to set up a long-lived Client).
func Login(ctx context.Context, hc *http.Client, gatewayURL, username, password string) (string, error) {
	body, _ := json.Marshal(map[string]string{
		"username": username,
		"password": password,
	})
	req, err := http.NewRequestWithContext(ctx, "POST", HTTPBase(gatewayURL)+"/auth/login", bytes.NewReader(body))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := hc.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	out, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 300 {
		return "", fmt.Errorf("/auth/login HTTP %d: %s", resp.StatusCode, string(out))
	}
	var result struct {
		Token string `json:"token"`
	}
	if err := json.Unmarshal(out, &result); err != nil {
		return "", fmt.Errorf("/auth/login: invalid JSON: %w (body=%q)", err, string(out))
	}
	return result.Token, nil
}

// RegisterAgent posts to /register/agent and returns app_id + ws
// token. agentType is normalized server-side via the gateway's
// own rules; we pass it through untouched.
//
// Exported for the same reason as Login.
func RegisterAgent(ctx context.Context, hc *http.Client, gatewayURL, bearer, agentID, agentName, agentType, version string) (appID, wsToken string, err error) {
	body, _ := json.Marshal(map[string]interface{}{
		"type":       "agent",
		"agent_type": agentType,
		"agent_id":   agentID,
		"agent_name": agentName,
		"version":    version,
	})
	req, err := http.NewRequestWithContext(ctx, "POST", HTTPBase(gatewayURL)+"/register/agent", bytes.NewReader(body))
	if err != nil {
		return "", "", err
	}
	req.Header.Set("Content-Type", "application/json")
	if bearer != "" {
		req.Header.Set("Authorization", "Bearer "+bearer)
	}
	resp, err := hc.Do(req)
	if err != nil {
		return "", "", err
	}
	defer resp.Body.Close()
	out, _ := io.ReadAll(resp.Body)
	if resp.StatusCode == 401 {
		return "", "", ErrUnauthorized
	}
	if resp.StatusCode >= 300 {
		return "", "", fmt.Errorf("/register/agent HTTP %d: %s", resp.StatusCode, string(out))
	}
	var result map[string]interface{}
	if err := json.Unmarshal(out, &result); err != nil {
		return "", "", fmt.Errorf("/register/agent: invalid JSON: %w (body=%q)", err, string(out))
	}
	appID, _ = result["app_id"].(string)
	wsToken, _ = result["token"].(string)
	if appID == "" || wsToken == "" {
		return "", "", fmt.Errorf("/register/agent: missing app_id/token: %v", result)
	}
	return appID, wsToken, nil
}

// RegisterClient posts to /register/client and returns app_id +
// ws token. Client registration is auth-free on the Gateway today
// (no bearer required), so we send no Authorization header.
//
// Exported for cmd/ils/doctor.
func RegisterClient(ctx context.Context, hc *http.Client, gatewayURL, name, version, agentID string) (appID, wsToken string, err error) {
	body, _ := json.Marshal(map[string]interface{}{
		"type":     "client",
		"name":     name,
		"agent_id": agentID,
		"version":  version,
	})
	req, err := http.NewRequestWithContext(ctx, "POST", HTTPBase(gatewayURL)+"/register/client", bytes.NewReader(body))
	if err != nil {
		return "", "", err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := hc.Do(req)
	if err != nil {
		return "", "", err
	}
	defer resp.Body.Close()
	out, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 300 {
		return "", "", fmt.Errorf("/register/client HTTP %d: %s", resp.StatusCode, string(out))
	}
	var result map[string]interface{}
	if err := json.Unmarshal(out, &result); err != nil {
		return "", "", fmt.Errorf("/register/client: invalid JSON: %w (body=%q)", err, string(out))
	}
	appID, _ = result["app_id"].(string)
	wsToken, _ = result["token"].(string)
	if appID == "" || wsToken == "" {
		return "", "", fmt.Errorf("/register/client: missing app_id/token: %v", result)
	}
	return appID, wsToken, nil
}

// ErrUnauthorized is returned by RegisterAgent when the Gateway
// answers 401. Exported so callers (cmd/ils/doctor) can match on
// it without re-defining the sentinel.
var ErrUnauthorized = errors.New("gateway returned 401: re-registration required")
