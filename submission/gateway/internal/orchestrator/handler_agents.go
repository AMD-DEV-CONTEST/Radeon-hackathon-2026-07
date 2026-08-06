package orchestrator

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"time"
)

// AgentRegisterRequest is the body for POST /agents/register.
type AgentRegisterRequest struct {
	Name           string                 `json:"name"`
	AgentType      string                 `json:"agent_type"`
	HostID         string                 `json:"host_id"`
	OS             string                 `json:"os,omitempty"`
	Shell          string                 `json:"shell,omitempty"`
	BindingStatus  string                 `json:"binding_status,omitempty"` // ready | degraded | failed
	Capabilities   map[string]interface{} `json:"capabilities,omitempty"`
	MaxConcurrency int                    `json:"max_concurrency"`
}

// AgentRegisterResponse is returned after successful registration.
type AgentRegisterResponse struct {
	ID             string `json:"id"`
	AgentID        string `json:"agent_id"` // compatibility with Node.js agents
	Name           string `json:"name"`
	HostID         string `json:"host_id"`
	Status         string `json:"status"`
	IsNew          bool   `json:"is_new"`
	OnboardTaskID  string `json:"onboard_task_id,omitempty"`
}

// AgentRegister handles POST /agents/register — upsert agent + onboarding task.
func AgentRegister(w http.ResponseWriter, r *http.Request) {
	if pool == nil {
		http.Error(w, `{"error":"db not initialized"}`, http.StatusServiceUnavailable)
		return
	}

	var req AgentRegisterRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid request body"}`, http.StatusBadRequest)
		return
	}
	if req.Name == "" || req.AgentType == "" || req.HostID == "" {
		http.Error(w, `{"error":"name, agent_type, host_id are required"}`, http.StatusBadRequest)
		return
	}
	if req.MaxConcurrency <= 0 {
		req.MaxConcurrency = 1
	}
	capsJSON, err := json.Marshal(req.Capabilities)
	if err != nil {
		http.Error(w, `{"error":"invalid capabilities"}`, http.StatusBadRequest)
		return
	}
	if len(capsJSON) == 0 || string(capsJSON) == "null" {
		capsJSON = []byte("{}")
	}

	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()

	now := time.Now().UTC()

	// Check if agent with same name+host_id already exists
	var existingID string
	err = pool.QueryRow(ctx,
		`SELECT id FROM agents WHERE name = $1 AND host_id = $2`,
		req.Name, req.HostID,
	).Scan(&existingID)

	var agentID string
	var isNew bool

	if err == nil {
		// Agent exists → update capabilities and heartbeat
		agentID = existingID
		isNew = false
		_, err = pool.Exec(ctx,
			`UPDATE agents SET
				agent_type = $1, os = $2, shell = $3,
				binding_status = $4,
				capabilities = $5, max_concurrency = $6,
				status = 'online', last_heartbeat_at = $7, updated_at = $7
			 WHERE id = $8`,
			req.AgentType, req.OS, req.Shell, req.BindingStatus, capsJSON, req.MaxConcurrency, now, agentID,
		)
		if err != nil {
			slog.Error("agent register update", "agent", agentID, "err", err)
			http.Error(w, `{"error":"db update failed"}`, http.StatusInternalServerError)
			return
		}
	} else {
		// Agent does not exist → insert
		isNew = true
		err = pool.QueryRow(ctx,
			`INSERT INTO agents (id, name, agent_type, host_id, os, shell, binding_status, capabilities, max_concurrency, status, last_heartbeat_at, created_at, updated_at)
			 VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, $7, $8, 'online', $9, $9, $9)
			 RETURNING id`,
			req.Name, req.AgentType, req.HostID, req.OS, req.Shell, req.BindingStatus, capsJSON, req.MaxConcurrency, now,
		).Scan(&agentID)
		if err != nil {
			slog.Error("agent register insert", "err", err)
			http.Error(w, fmt.Sprintf(`{"error":"db insert failed: %s"}`, err.Error()), http.StatusInternalServerError)
			return
		}
	}

	slog.Info("agent register", "id", agentID, "name", req.Name, "host", req.HostID, "is_new", isNew)

	resp := AgentRegisterResponse{
		ID:      agentID,
		AgentID: agentID,
		Name:    req.Name,
		HostID:  req.HostID,
		Status:  "online",
		IsNew:   isNew,
	}

	// ── 暗线-3：新 agent 创建入职任务 ─────────────────────────────
	if isNew {
		onboardPayload, _ := json.Marshal(map[string]interface{}{
			"instruction": "欢迎加入 UAS！请阅读员工手册和席位制度，了解系统工作方式。回复「已阅」完成入职。",
			"handoff":     map[string]interface{}{"schema": "1.0"},
		})

		onboardDesc := `# UnionAgents 员工手册 v1.0

> 联署人：TCC × 老何 | 2026-06-07 | 全员生效

## 一、身份
你是 UnionAgents 多 Agent 协作框架中的一名 Worker。
- 你的职责：接收任务 → 执行任务 → 交付结果
- 你不是：决策者、架构师、项目经理

## 二、任务执行铁律（ILS 五条军规）
| # | 规则 |
| 1 | 先召回相似案例 |
| 2 | 结构化输出必须用户确认 |
| 3 | 单任务 ≤ 1 小时，超时拆分 |
| 4 | 需决策时暂停，提交 needs_user_insight |
| 5 | 完成必须沉淀案例 |

## 三、完整工作流
接单 → 租约 → 读上下文 → 召回案例 → 执行 → 自检 → 验收 → 提交 handoff → 释放租约

## 四、安全约束
- 所有文件操作在 workspace 目录内
- 禁用：rm -rf /、git push --force、DROP TABLE、chmod 777、curl | bash

## 五、禁止事项
跳过 ILS 门控、伪造验收、接不属于自己的任务、替用户做架构决策

## 六、异常与恢复
API Key 失效 → blocked_auth | 网络中断 → 重试3次 | 任务超时 → partial handoff

## 七、席位
当前席位：C1/R2/R4/O4/R5。详情见 docs/席位制度-v1.0.md`

		var onboardTaskID string
		err = pool.QueryRow(ctx,
			`INSERT INTO tasks (title, description, task_type, status, priority,
				max_attempts, created_by, target_agent_id, payload, created_at, updated_at)
			 VALUES ($1, $2, 'coding', 'queued', 100,
			 	1, 'system', $3, $4, $5, $5)
			 RETURNING id`,
			"入职：欢迎加入 UAS — 请阅读员工手册",
			onboardDesc,
			agentID, onboardPayload, now,
		).Scan(&onboardTaskID)
		if err != nil {
			slog.Error("agent register onboard task create", "err", err)
		} else {
			resp.OnboardTaskID = onboardTaskID
			slog.Info("agent register onboard task created", "task_id", onboardTaskID, "agent", agentID)
		}
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	writeJSON(w, resp)
}
// AgentList handles GET /agents — returns all agents with heartbeat status.
//
// Query param ?scope=all|local (default local) controls whether remote
// (peer-discovered) agents are included. scope=local is backward-compatible:
// the response shape is unchanged. scope=all adds "remote" and
// "peers_healthy" fields describing the cross-base view.
func AgentList(w http.ResponseWriter, r *http.Request) {
	if pool == nil {
		http.Error(w, `{"error":"db not initialized"}`, http.StatusServiceUnavailable)
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
	defer cancel()

	rows, err := pool.Query(ctx,
		`SELECT id, name, agent_type, host_id, os, shell, binding_status, status, max_concurrency,
		 last_heartbeat_at, created_at, updated_at
		 FROM agents ORDER BY name`)
	if err != nil {
		slog.Error("agent list query", "err", err)
		http.Error(w, `{"error":"db error"}`, http.StatusInternalServerError)
		return
	}
	defer rows.Close()

	type AgentSummary struct {
		ID              string    `json:"id"`
		Name            string    `json:"name"`
		AgentType       string    `json:"agent_type"`
		HostID          string    `json:"host_id"`
		OS              string    `json:"os"`
		Shell           string    `json:"shell"`
		BindingStatus   string    `json:"binding_status"`
		Status          string    `json:"status"`
		MaxConcurrency  int       `json:"max_concurrency"`
		LastHeartbeatAt time.Time `json:"last_heartbeat_at"`
		HeartbeatAgo    string    `json:"heartbeat_ago"`
		CreatedAt       time.Time `json:"created_at"`
		UpdatedAt       time.Time `json:"updated_at"`
	}

	agents := make([]AgentSummary, 0)
	now := time.Now().UTC()

	for rows.Next() {
		var a AgentSummary
		if err := rows.Scan(&a.ID, &a.Name, &a.AgentType, &a.HostID, &a.OS, &a.Shell,
			&a.BindingStatus, &a.Status, &a.MaxConcurrency, &a.LastHeartbeatAt, &a.CreatedAt, &a.UpdatedAt); err != nil {
			continue
		}
		a.HeartbeatAgo = now.Sub(a.LastHeartbeatAt).Truncate(time.Second).String()
		agents = append(agents, a)
	}

	resp := map[string]interface{}{
		"agents": agents,
		"count":  len(agents),
	}

	// scope=all merges in the peer-discovered remote view. We only add
	// fields when explicitly requested, so existing callers see no shape
	// change in the default (local) path.
	if r.URL.Query().Get("scope") == "all" {
		resp["remote"] = globalPeerCache.allRemote(now)
		resp["peers_healthy"] = globalPeerCache.peersHealthy(now)
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

// AgentDiscover handles GET /agents/discover — returns agents aggregated
// by agent_type across local + remote (peer-discovered) bases, plus a
// per-base capacity summary. This is the input the 2.5 handoff
// evaluator uses to answer "who else can take this task?".
//
// Unlike /agents?scope=all (which returns flat lists), discover groups
// by capability so a caller can ask "give me every online worker across
// all bases" in one field rather than filtering client-side.
func AgentDiscover(w http.ResponseWriter, r *http.Request) {
	if pool == nil {
		http.Error(w, `{"error":"db not initialized"}`, http.StatusServiceUnavailable)
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
	defer cancel()

	// Local agents, online only — discover is for "who can take work now".
	rows, err := pool.Query(ctx,
		`SELECT id, name, agent_type, host_id, status, max_concurrency
		 FROM agents WHERE status = 'online' ORDER BY agent_type, name`)
	if err != nil {
		slog.Error("agent discover query", "err", err)
		http.Error(w, `{"error":"db error"}`, http.StatusInternalServerError)
		return
	}
	defer rows.Close()

	now := time.Now().UTC()
	// byType[agent_type] = list of agents (local first, then remote).
	byType := map[string][]map[string]interface{}{}
	// byBase[peer_url | "local"] = count of online agents.
	byBase := map[string]int{}

	for rows.Next() {
		var id, name, agentType, hostID, status string
		var maxConc int
		if err := rows.Scan(&id, &name, &agentType, &hostID, &status, &maxConc); err != nil {
			continue
		}
		byType[agentType] = append(byType[agentType], map[string]interface{}{
			"id": id, "name": name, "host_id": hostID,
			"base": "local", "max_concurrency": maxConc,
		})
		byBase["local"]++
	}

	for _, pa := range globalPeerCache.allRemote(now) {
		if pa.Status != "online" {
			continue
		}
		byType[pa.AgentType] = append(byType[pa.AgentType], map[string]interface{}{
			"id": pa.ID, "name": pa.Name, "host_id": pa.HostID,
			"base": pa.PeerURL, "max_concurrency": pa.MaxConcurrency,
		})
		byBase[pa.PeerURL]++
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"by_type":  byType,
		"by_base":  byBase,
		"scanned_at": now.Format(time.RFC3339),
	})
}

// AgentGet handles GET /agents/{agentID} — returns single agent with recent tasks.
func AgentGet(w http.ResponseWriter, r *http.Request) {
	if pool == nil {
		http.Error(w, `{"error":"db not initialized"}`, http.StatusServiceUnavailable)
		return
	}

	agentID := r.PathValue("agentID")
	if agentID == "" {
		http.Error(w, `{"error":"agentID required"}`, http.StatusBadRequest)
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()

	type AgentDetail struct {
		ID              string                 `json:"id"`
		Name            string                 `json:"name"`
		AgentType       string                 `json:"agent_type"`
		HostID          string                 `json:"host_id"`
		OS              string                 `json:"os"`
		Shell           string                 `json:"shell"`
		BindingStatus   string                 `json:"binding_status"`
		Status          string                 `json:"status"`
		Capabilities    map[string]interface{} `json:"capabilities"`
		MaxConcurrency  int                    `json:"max_concurrency"`
		LastHeartbeatAt time.Time              `json:"last_heartbeat_at"`
		HeartbeatAgo    string                 `json:"heartbeat_ago"`
		CreatedAt       time.Time              `json:"created_at"`
	}

	var a AgentDetail
	var capsJSON []byte
	err := pool.QueryRow(ctx,
		`SELECT id, name, agent_type, host_id, os, shell, binding_status, status,
		 capabilities, max_concurrency, last_heartbeat_at, created_at
		 FROM agents WHERE id = $1`, agentID,
	).Scan(&a.ID, &a.Name, &a.AgentType, &a.HostID, &a.OS, &a.Shell,
		&a.BindingStatus, &a.Status, &capsJSON, &a.MaxConcurrency, &a.LastHeartbeatAt, &a.CreatedAt)
	if err != nil {
		http.Error(w, `{"error":"agent not found"}`, http.StatusNotFound)
		return
	}
	json.Unmarshal(capsJSON, &a.Capabilities)
	a.HeartbeatAgo = time.Now().UTC().Sub(a.LastHeartbeatAt).Truncate(time.Second).String()

	// Recent tasks for this agent
	taskRows, err := pool.Query(ctx,
		`SELECT id, title, status, created_at
		 FROM tasks WHERE target_agent_id = $1
		 ORDER BY created_at DESC LIMIT 10`, agentID)
	tasks := make([]map[string]interface{}, 0)
	if err == nil {
		defer taskRows.Close()
		for taskRows.Next() {
			var id, title, status string
			var ca time.Time
			taskRows.Scan(&id, &title, &status, &ca)
			tasks = append(tasks, map[string]interface{}{
				"id": id, "title": title, "status": status, "created_at": ca,
			})
		}
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"agent": a,
		"recent_tasks": tasks,
	})
}
