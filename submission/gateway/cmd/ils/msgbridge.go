package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"time"
)

// createOrchestratorTask creates a task in the orchestrator for chat processing.
// Converts an inbound UAS chat message into an Orchestrator task.
func createOrchestratorTask(orchURL, token, text, from, agentID string) (string, error) {
	body, _ := json.Marshal(map[string]interface{}{
		"title":           "chat: " + truncate(text, 80),
		"description":     text,
		"task_type":       "chat",
		"target_agent_id": agentID,
		"payload": map[string]interface{}{
			"context": map[string]interface{}{
				"goal": text,
			},
		},
		"created_by": "ils-daemon",
		"priority":   80,
	})

	req, err := http.NewRequest("POST", orchURL+"/tasks", bytes.NewReader(body))
	if err != nil {
		return "", fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}

	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return "", fmt.Errorf("orchestrator unreachable: %w", err)
	}
	defer resp.Body.Close()

	respBody, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 300 {
		return "", fmt.Errorf("orchestrator %d: %s", resp.StatusCode, strings.TrimSpace(string(respBody)))
	}

	var result map[string]interface{}
	if err := json.Unmarshal(respBody, &result); err != nil {
		return "", fmt.Errorf("parse response: %w", err)
	}

	taskID, _ := result["id"].(string)
	if taskID == "" {
		// Some orchestrator responses use different key
		taskID, _ = result["task_id"].(string)
	}
	if taskID == "" {
		return "", fmt.Errorf("no task id in response: %s", string(respBody))
	}

	return taskID, nil
}

// pollOrchestratorResult polls /tasks/:id until the task completes or times out.
// Returns the task summary (result) as a string.
func pollOrchestratorResult(orchURL, token, taskID string, timeout time.Duration) string {
	client := &http.Client{Timeout: 10 * time.Second}
	deadline := time.Now().Add(timeout)
	pollInterval := 2 * time.Second

	for time.Now().Before(deadline) {
		req, err := http.NewRequest("GET", orchURL+"/tasks/"+taskID, nil)
		if err != nil {
			return fmt.Sprintf("⚠️ 轮询错误: %v", err)
		}
		if token != "" {
			req.Header.Set("Authorization", "Bearer "+token)
		}

		resp, err := client.Do(req)
		if err != nil {
			slog.Warn("poll orchestrator failed", "task", taskID[:8], "err", err)
			time.Sleep(pollInterval)
			continue
		}

		respBody, _ := io.ReadAll(resp.Body)
		resp.Body.Close()

		logLen := len(respBody)
		if logLen > 200 {
			logLen = 200
		}
		var task map[string]interface{}
		if json.Unmarshal(respBody, &task) != nil {
			time.Sleep(pollInterval)
			continue
		}

		status, _ := task["status"].(string)
		switch status {
		case "done":
			if summary, ok := task["summary"].(string); ok && summary != "" {
				return summary
			}
			return "✅ 任务完成（无摘要）"
		case "needs_review", "failed":
			summary, _ := task["summary"].(string)
			errMsg, _ := task["error_message"].(string)
			result := "⚠️ 任务需要检查"
			if summary != "" {
				result += "\n" + summary
			}
			if errMsg != "" {
				result += "\n错误: " + errMsg
			}
			return result
		case "queued", "pending", "processing", "leased", "running":
			// Still in progress, keep polling
		default:
			// Unknown status — return whatever we have
			return fmt.Sprintf("ℹ️ 任务状态: %s", status)
		}

		time.Sleep(pollInterval)
	}

	// Timeout — return partial info
	return fmt.Sprintf("⏱️ 任务超时（%s），请在 OB 中查看最新进展", timeout)
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "..."
}
