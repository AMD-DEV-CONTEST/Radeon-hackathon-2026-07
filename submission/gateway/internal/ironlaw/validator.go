package ironlaw

import (
	"encoding/json"
	"regexp"
	"strings"
)

var gateExemptTaskTypes = map[string]bool{
	"review":     true,
	"audit":      true,
	"research":   true,
	"analysis":   true,
	"read_only":  true,
	"planning":   true,
	"discussion": true,
	"deployment": true,
	"chat":       true, // OB chat:send → orchestrator HTTP fallback
}

func checkRule1ContextRequired(task map[string]interface{}) *RuleViolation {
	payload, _ := task["payload"].(map[string]interface{})
	if payload == nil {
		return &RuleViolation{
			Rule:        1,
			Message:     "任务缺少 context.goal 字段。必须先调用 /iron-law/context 组装上下文再发布任务。",
			AutoFixable: false,
		}
	}
	ctx, _ := payload["context"].(map[string]interface{})
	if ctx == nil {
		return &RuleViolation{
			Rule:        1,
			Message:     "任务缺少 context.goal 字段。必须先调用 /iron-law/context 组装上下文再发布任务。",
			AutoFixable: false,
		}
	}
	goal, _ := ctx["goal"].(string)
	if goal == "" {
		return &RuleViolation{
			Rule:        1,
			Message:     "任务缺少 context.goal 字段。必须先调用 /iron-law/context 组装上下文再发布任务。",
			AutoFixable: false,
		}
	}
	return nil
}

func checkRule3TaskGranularity(title, description string, estimatedHours *float64) *RuleViolation {
	if estimatedHours != nil && *estimatedHours > 1.0 {
		return &RuleViolation{
			Rule:        3,
			Message:     "任务 '" + title + "' 估时超过 1 小时上限，必须拆分为更小的子任务。",
			AutoFixable: true,
		}
	}

	connectors := []string{"然后", "接着", "再然后", "之后再", "完成后再", "并且还要"}
	count := 0
	for _, c := range connectors {
		count += strings.Count(description, c)
	}
	if count >= 3 {
		return &RuleViolation{
			Rule:        3,
			Message:     "任务描述包含多个串行步骤连接词，疑似大任务，建议拆分。",
			AutoFixable: true,
		}
	}
	return nil
}

func checkRule2OwnershipLock(task map[string]interface{}) *RuleViolation {
	caps, _ := task["required_capabilities"].(map[string]interface{})
	if caps == nil || len(caps) == 0 {
		return &RuleViolation{
			Rule:        2,
			Message:     "任务缺少 required_capabilities，无法确定 agent 归属，可能导致执行冲突。请指定至少一个 capability 标签。",
			AutoFixable: true,
		}
	}
	return nil
}

var reRule4Destructive = regexp.MustCompile(`(?i)(删|drop|truncate|clear|wipe|purge)`)

func checkRule4ScopeLock(task map[string]interface{}) *RuleViolation {
	desc := stringField(task, "description")
	descLower := strings.ToLower(desc)

	dbKeywords := []string{"数据库", "database", "db", "表", "table", "collection", "索引", "index"}
	hasDBRef := false
	for _, kw := range dbKeywords {
		if strings.Contains(descLower, kw) {
			hasDBRef = true
			break
		}
	}

	if hasDBRef && reRule4Destructive.MatchString(desc) {
		payload, _ := task["payload"].(map[string]interface{})
		if payload != nil {
			if bc, ok := payload["backup_confirmed"]; ok {
				if confirmed, ok := bc.(bool); ok && confirmed {
					return nil
				}
			}
		}
		return &RuleViolation{
			Rule:        4,
			Message:     "疑似数据库破坏性操作，必须在 payload 中设置 backup_confirmed: true 并确认备份已完成。",
			AutoFixable: false,
		}
	}
	return nil
}

func checkRule5AcceptanceRequired(task map[string]interface{}) *RuleViolation {
	ac, _ := task["acceptance_check"].(map[string]interface{})
	if ac == nil {
		title, _ := task["title"].(string)
		return &RuleViolation{
			Rule:        5,
			Message:     "任务 '" + title + "' 缺少 acceptance_check，完成后无法验收。",
			AutoFixable: false,
		}
	}

	acType, _ := ac["type"].(string)
	caps, _ := task["required_capabilities"].(map[string]interface{})
	agentType := ""
	if caps != nil {
		if at, ok := caps["agent_type"].(string); ok {
			agentType = at
		}
	}

	if acType == "command" {
		cmdRaw, _ := ac["command"].([]interface{})
		var cmdParts []string
		for _, c := range cmdRaw {
			if s, ok := c.(string); ok {
				cmdParts = append(cmdParts, s)
			}
		}
		cmdStr := strings.Join(cmdParts, " ")

		forbiddenCombos := map[string]string{
			"pnpm build": "pnpm build 不适合验收 Python 服务",
			"npm build":  "npm build 不适合验收 Python/后端服务",
		}

		for pattern, reason := range forbiddenCombos {
			if strings.Contains(cmdStr, pattern) && !strings.Contains(agentType, "node") && !strings.Contains(agentType, "codex") {
				return &RuleViolation{
					Rule:        5,
					Message:     "acceptance_check 类型错误：" + reason,
					AutoFixable: true,
				}
			}
		}
	}
	return nil
}

// ValidateTaskBeforeDispatch performs full validation of a task before it enters the orchestrator queue.
// Returns warnings (non-blocking); returns a *RuleViolation error to reject the task.
func ValidateTaskBeforeDispatch(task map[string]interface{}) (warnings []string, err error) {
	payload, _ := task["payload"].(map[string]interface{})
	if payload == nil {
		payload = make(map[string]interface{})
	}

	taskType := strings.ToLower(stringField(task, "task_type"))

	if gateExemptTaskTypes[taskType] {
		title := stringField(task, "title")
		desc := stringField(task, "description")
		var estHours *float64
		if eh, ok := payload["estimated_hours"].(float64); ok {
			estHours = &eh
		}
		if v := checkRule3TaskGranularity(title, desc, estHours); v != nil {
			if v.AutoFixable {
				warnings = append(warnings, v.Error())
			} else {
				return warnings, v
			}
		}
		return warnings, nil
	}

	if v := checkRule1ContextRequired(task); v != nil {
		return warnings, v
	}

	if v := checkRule2OwnershipLock(task); v != nil {
		if v.AutoFixable {
			warnings = append(warnings, v.Error())
		}
	}

	if v := checkRule4ScopeLock(task); v != nil {
		return warnings, v
	}

	title := stringField(task, "title")
	desc := stringField(task, "description")
	var estHours *float64
	if eh, ok := payload["estimated_hours"].(float64); ok {
		estHours = &eh
	}
	if v := checkRule3TaskGranularity(title, desc, estHours); v != nil {
		if v.AutoFixable {
			warnings = append(warnings, v.Error())
		} else {
			return warnings, v
		}
	}

	if v := checkRule5AcceptanceRequired(task); v != nil {
		if v.AutoFixable {
			warnings = append(warnings, v.Error())
		} else {
			return warnings, v
		}
	}

	return warnings, nil
}

func stringField(m map[string]interface{}, key string) string {
	v, _ := m[key].(string)
	return v
}

// ToJSON marshals a task dict for use in tests and APIs.
func ToJSON(task map[string]interface{}) string {
	b, _ := json.Marshal(task)
	return string(b)
}

// ParseTask parses a JSON task dict string into a map.
func ParseTask(raw string) (map[string]interface{}, error) {
	var m map[string]interface{}
	if err := json.Unmarshal([]byte(raw), &m); err != nil {
		return nil, err
	}
	return m, nil
}
