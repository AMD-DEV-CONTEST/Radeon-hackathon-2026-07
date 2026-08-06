package orchestrator

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"time"
)

// FeishuWebhookURL returns the configured webhook URL.
// Set FEISHU_WEBHOOK_URL env var. If empty, alerts are logged only.
func FeishuWebhookURL() string {
	return os.Getenv("FEISHU_WEBHOOK_URL")
}

// AlertLevel matches event levels.
type AlertLevel string

const (
	AlertInfo  AlertLevel = "info"
	AlertWarn  AlertLevel = "warn"
	AlertError AlertLevel = "error"
)

// AlertPayload is the message body pushed to Feishu.
type AlertPayload struct {
	Title    string     `json:"title"`
	Content  string     `json:"content"`
	Level    AlertLevel `json:"level"`
	Source   string     `json:"source"`
	Detail   any        `json:"detail,omitempty"`
	Time     string     `json:"time"`
}

// SendAlert pushes an alert to Feishu webhook (if configured).
// Blocks at most 3 seconds. Logs if webhook is unavailable.
func SendAlert(ctx context.Context, p AlertPayload) {
	if p.Time == "" {
		p.Time = time.Now().UTC().Format(time.RFC3339)
	}
	if p.Source == "" {
		p.Source = "unionagents-orchestrator"
	}

	webhookURL := FeishuWebhookURL()
	if webhookURL == "" {
		slog.Info("alert (no webhook configured)", "title", p.Title, "level", p.Level)
		return
	}

	// Build Feishu card message format
	titleColor := map[AlertLevel]string{
		AlertInfo:  "blue",
		AlertWarn:  "yellow",
		AlertError: "red",
	}[p.Level]
	if titleColor == "" {
		titleColor = "blue"
	}

	detailStr := ""
	if p.Detail != nil {
		if b, err := json.MarshalIndent(p.Detail, "", "  "); err == nil {
			detailStr = string(b)
		}
	}

	msg := map[string]any{
		"msg_type": "interactive",
		"card": map[string]any{
			"header": map[string]any{
				"title": map[string]any{
					"tag":     "plain_text",
					"content": fmt.Sprintf("[%s] %s", p.Level, p.Title),
				},
				"template": titleColor,
			},
			"elements": []map[string]any{
				{
					"tag":     "markdown",
					"content": fmt.Sprintf("**来源**: %s\n**时间**: %s\n\n%s\n\n%s", p.Source, p.Time, p.Content, detailStr),
				},
			},
		},
	}

	body, err := json.Marshal(msg)
	if err != nil {
		slog.Error("alert marshal failed", "err", err)
		return
	}

	reqCtx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(reqCtx, http.MethodPost, webhookURL, bytes.NewReader(body))
	if err != nil {
		slog.Error("alert http request failed", "err", err)
		return
	}
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 3 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		slog.Warn("alert webhook post failed", "err", err)
		return
	}
	resp.Body.Close()

	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		slog.Info("alert sent", "title", p.Title, "level", p.Level)
	} else {
		slog.Warn("alert webhook non-2xx", "status", resp.StatusCode)
	}
}

// // ── Convenience helpers ──────────────────────────────────────────────

// AlertAgentStatus sends an alert when agent health state changes.
func AlertAgentStatus(agentID, agentName, oldState, newState, reason string) {
	level := AlertWarn
	if newState == "dead" || newState == "unhealthy" {
		level = AlertError
	} else if newState == "healthy" {
		level = AlertInfo
	}

	SendAlert(context.Background(), AlertPayload{
		Title:   fmt.Sprintf("Agent 状态变更: %s", agentName),
		Content: fmt.Sprintf("**%s** 健康状态变化\n\n`%s` → `%s`\n\n原因: %s", agentName, oldState, newState, reason),
		Level:   level,
		Detail: map[string]any{
			"agent_id":   agentID,
			"agent_name": agentName,
			"old_state":  oldState,
			"new_state":  newState,
			"reason":     reason,
		},
	})
}

// AlertCircuitBreaker sends an alert when circuit breaker opens.
func AlertCircuitBreaker(agentID, agentName string, consecFails, totalFails int) {
	SendAlert(context.Background(), AlertPayload{
		Title:   fmt.Sprintf("熔断触发: %s", agentName),
		Content: fmt.Sprintf("**%s** 连续失败 %d 次，熔断器打开\n\n暂停派单 5 分钟\n累计失败: %d 次", agentName, consecFails, totalFails),
		Level:   AlertError,
		Detail: map[string]any{
			"agent_id":             agentID,
			"agent_name":           agentName,
			"consecutive_failures": consecFails,
			"total_failures":       totalFails,
		},
	})
}

// AlertAgentDisabled sends an alert when agent is auto-disabled.
func AlertAgentDisabled(agentID, agentName string, totalFails int) {
	SendAlert(context.Background(), AlertPayload{
		Title:   fmt.Sprintf("Agent 自动禁用: %s", agentName),
		Content: fmt.Sprintf("**%s** 累计失败 %d 次，已达上限\n\n已自动禁用，需人工介入", agentName, totalFails),
		Level:   AlertError,
		Detail: map[string]any{
			"agent_id":     agentID,
			"agent_name":   agentName,
			"total_failures": totalFails,
		},
	})
}

// AlertTaskDeadAgentReclaim sends an alert when tasks are reclaimed from a dead agent.
func AlertTaskDeadAgentReclaim(agentID, agentName string, taskCount int) {
	SendAlert(context.Background(), AlertPayload{
		Title:   fmt.Sprintf("Dead Agent 任务回收: %s", agentName),
		Content: fmt.Sprintf("**%s** 已死亡，回收 %d 个任务重新入队", agentName, taskCount),
		Level:   AlertWarn,
		Detail: map[string]any{
			"agent_id":   agentID,
			"agent_name": agentName,
			"task_count": taskCount,
		},
	})
}
