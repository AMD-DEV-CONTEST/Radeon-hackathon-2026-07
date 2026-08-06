package orchestrator

import (
	"bufio"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"strings"
)

const configFilePath = "/etc/unionagents/orchestrator.env"

// ConfigFeishuWebhookGet handles GET /config/feishu-webhook
func ConfigFeishuWebhookGet(w http.ResponseWriter, r *http.Request) {
	url := os.Getenv("FEISHU_WEBHOOK_URL")
	configured := url != ""

	writeJSON(w, map[string]interface{}{
		"feishu_webhook_url": url,
		"configured":         configured,
	})
}

// ConfigFeishuWebhookPut handles PUT /config/feishu-webhook
func ConfigFeishuWebhookPut(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPut {
		http.Error(w, `{"error":"method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	var req struct {
		URL string `json:"url"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid request body"}`, http.StatusBadRequest)
		return
	}

	// Update env file
	if err := updateEnvFile(configFilePath, "FEISHU_WEBHOOK_URL", req.URL); err != nil {
		slog.Error("config feishu webhook update file", "err", err)
		http.Error(w, fmt.Sprintf(`{"error":"%s"}`, err.Error()), http.StatusInternalServerError)
		return
	}

	slog.Info("config feishu webhook updated", "url", req.URL)

	writeJSON(w, map[string]interface{}{
		"status": "ok",
		"message": "Feishu webhook URL updated. Restart orchestrator to apply.",
		"restart_required": true,
	})
}

// updateEnvFile reads an env file, sets or replaces a key=value line, and writes it back.
func updateEnvFile(path, key, value string) error {
	f, err := os.Open(path)
	if err != nil {
		if os.IsNotExist(err) {
			// Create new file
			return os.WriteFile(path, []byte(fmt.Sprintf("%s=%s\n", key, value)), 0644)
		}
		return fmt.Errorf("open config: %w", err)
	}
	defer f.Close()

	var lines []string
	found := false
	prefix := key + "="
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := scanner.Text()
		if strings.HasPrefix(line, prefix) || strings.HasPrefix(line, "#"+prefix) {
			if value != "" {
				lines = append(lines, prefix+value)
			}
			// If value is empty, skip the line (remove it)
			found = true
		} else {
			lines = append(lines, line)
		}
	}
	if err := scanner.Err(); err != nil {
		return fmt.Errorf("scan config: %w", err)
	}

	if !found && value != "" {
		lines = append(lines, prefix+value)
	}

	return os.WriteFile(path, []byte(strings.Join(lines, "\n")+"\n"), 0644)
}
