package boundary

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

type CombinedStatus struct {
	Status               string      `json:"status"`
	GatewayURL           string      `json:"gateway_url"`
	OrchestratorURL      string      `json:"orchestrator_url"`
	GatewayBoundary      interface{} `json:"gateway_boundary"`
	OrchestratorBoundary interface{} `json:"orchestrator_boundary"`
	GatewayOK            bool        `json:"-"`
	OrchestratorOK       bool        `json:"-"`
}

func FetchCombinedStatus(ctx context.Context, gatewayURL, orchestratorURL string) CombinedStatus {
	gatewayBoundary, gatewayOK := GetJSON(ctx, GatewayHTTPBase(gatewayURL)+"/boundary")
	orchestratorBoundary, orchestratorOK := GetJSON(ctx, strings.TrimRight(orchestratorURL, "/")+"/boundary")
	return CombinedStatus{
		Status:               OKStatus(gatewayOK && orchestratorOK),
		GatewayURL:           gatewayURL,
		OrchestratorURL:      orchestratorURL,
		GatewayBoundary:      gatewayBoundary,
		OrchestratorBoundary: orchestratorBoundary,
		GatewayOK:            gatewayOK,
		OrchestratorOK:       orchestratorOK,
	}
}

func GetJSON(ctx context.Context, url string) (interface{}, bool) {
	client := &http.Client{Timeout: 5 * time.Second}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return err.Error(), false
	}
	resp, err := client.Do(req)
	if err != nil {
		return err.Error(), false
	}
	defer resp.Body.Close()
	out, err := io.ReadAll(resp.Body)
	if err != nil {
		return err.Error(), false
	}
	if resp.StatusCode >= 300 {
		return fmt.Sprintf("HTTP %d: %s", resp.StatusCode, string(out)), false
	}
	var decoded interface{}
	if err := json.Unmarshal(out, &decoded); err != nil {
		return string(out), true
	}
	return decoded, true
}

func GatewayHTTPBase(gatewayURL string) string {
	base := strings.Replace(gatewayURL, "ws://", "http://", 1)
	base = strings.Replace(base, "wss://", "https://", 1)
	if idx := strings.Index(base, "/ws"); idx > 0 {
		base = base[:idx]
	}
	return strings.TrimRight(base, "/")
}

func OKStatus(ok bool) string {
	if ok {
		return "ok"
	}
	return "fail"
}

func FormatCombinedStatus(status CombinedStatus, jsonOutput bool) (string, error) {
	if jsonOutput {
		out, err := json.MarshalIndent(status, "", "  ")
		if err != nil {
			return "", err
		}
		return string(out), nil
	}
	return fmt.Sprintf(`status: %s
gateway_url: %s
gateway_boundary: %s
orchestrator_url: %s
orchestrator_boundary: %s`, status.Status, status.GatewayURL, OKStatus(status.GatewayOK), status.OrchestratorURL, OKStatus(status.OrchestratorOK)), nil
}
