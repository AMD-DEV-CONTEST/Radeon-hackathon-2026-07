package ironlaw

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"regexp"
	"strconv"
	"strings"
	"time"
)

var ragBaseURL = env("RAG_BASE_URL", "http://127.0.0.1:8010")
var defaultTopK = envInt("ILS_DEFAULT_TOP_K", 5)
var minSimilarity = envFloat("ILS_MIN_SIMILARITY", 0.3)

var (
	reVaguePronounsZH = regexp.MustCompile(
		`(那个|这个|它|他|她|那里|这里|上次|之前|刚才|前几天|` +
			`那个服务|那个文件|那个端口|那个配置|那个脚本|那个项目)`,
	)
	reVaguePronounsEN = regexp.MustCompile(
		`(?i)\b(it|that|this|those|these|there|the service|the file|` +
			`the port|the config|the script|last time|before)\b`,
	)
	reHighRiskKeywords = regexp.MustCompile(
		`(?i)(删|删除|rm|drop|truncate|format|格式化|` +
			`改端口|换端口|关服务|停服务|kill|重启|` +
			`改密码|重置|清空|wipe|purge|` +
			`改权限|chmod 777|chown)`,
	)
	reCompoundConnectors = regexp.MustCompile(
		`(然后|接着|并且|同时|另外|还有|此外|再加上|顺便|以及|完成.*再)`,
	)

	// ILS-R013: ops/maintenance keywords — these tasks should not enter the agent queue
	reOpsMaintenance = regexp.MustCompile(
		`(?i)(systemctl|journalctl|crontab|logrotate|` +
			`磁盘清理|日志清理|重启服务|定时任务配置|运维|` +
			`disk clean|log rotation|service restart|` +
			`nginx reload|ssl cert|证书续期|firewall rule|防火墙规则)`,
	)

	// ILS-R008: execution task keywords — warn if targeting reasoning-only agent
	reExecutionTask = regexp.MustCompile(
		`(?i)(go build|cargo build|npm (install|build|run)|yarn build|` +
			`make (all|install|deploy)|编译|构建二进制|打包二进制)`,
	)

	// ILS-R014: permanent failure indicators — in task text these hint at auth issues
	rePermanentFailureHint = regexp.MustCompile(
		`(?i)(403|unauthorized|api key|access token|subscription expired|` +
			`authentication failed|invalid token|ANTHROPIC_API_KEY)`,
	)
)

type noTargetPattern struct {
	re     *regexp.Regexp
	reason string
}

var noTargetPatterns = []noTargetPattern{
	{regexp.MustCompile(`^(帮我看|帮我查|帮我改|帮我修|帮我弄|帮我搞|帮我把|帮我装|帮我配)`), "缺少操作目标"},
	{regexp.MustCompile(`^(看一下|查一下|改一下|修一下|弄一下)`), "缺少操作目标"},
	{regexp.MustCompile(`^(怎么样|好不好|行不行|可不可以)$`), "无上下文评价"},
}

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func envInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

func envFloat(key string, def float64) float64 {
	if v := os.Getenv(key); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			return f
		}
	}
	return def
}

func DetectAmbiguity(rawText string) []AmbiguityFlag {
	var flags []AmbiguityFlag

	zhMatches := reVaguePronounsZH.FindAllString(rawText, -1)
	if len(zhMatches) > 0 {
		flags = append(flags, AmbiguityFlag{
			Type:       "vague_reference",
			Span:       strings.Join(zhMatches, ", "),
			Suggestion: fmt.Sprintf("文本中含指代词 '%s'，建议确认具体指代对象。可列出候选：最近改过的文件/服务/端口。", zhMatches[0]),
		})
	}

	enMatches := reVaguePronounsEN.FindAllString(rawText, -1)
	if len(enMatches) > 0 && len(zhMatches) == 0 {
		take := enMatches
		if len(take) > 3 {
			take = take[:3]
		}
		flags = append(flags, AmbiguityFlag{
			Type:       "vague_reference",
			Span:       strings.Join(take, ", "),
			Suggestion: fmt.Sprintf("含英文指代词 '%s'，建议确认具体对象。", enMatches[0]),
		})
	}

	trimmed := strings.TrimSpace(rawText)
	for _, p := range noTargetPatterns {
		if p.re.MatchString(trimmed) && len([]rune(trimmed)) < 15 {
			flags = append(flags, AmbiguityFlag{
				Type:       "missing_target",
				Span:       truncateRunes(trimmed, 50),
				Suggestion: fmt.Sprintf("%s。建议询问操作的具体目标（文件/服务/端口/项目）。", p.reason),
			})
			break
		}
	}

	compoundMatches := reCompoundConnectors.FindAllString(rawText, -1)
	if len(compoundMatches) >= 2 {
		flags = append(flags, AmbiguityFlag{
			Type:       "compound_request",
			Span:       strings.Join(compoundMatches, ", "),
			Suggestion: fmt.Sprintf("含 %d 个串联连接词，可能是多步骤复合需求。建议拆分为独立子任务，逐个确认后执行。", len(compoundMatches)),
		})
	}

	riskMatches := reHighRiskKeywords.FindAllString(rawText, -1)
	if len(riskMatches) > 0 {
		take := riskMatches
		if len(take) > 5 {
			take = take[:5]
		}
		flags = append(flags, AmbiguityFlag{
			Type:       "high_risk",
			Span:       strings.Join(take, ", "),
			Suggestion: fmt.Sprintf("含高风险操作词 '%s'。建议执行前确认范围、先备份、输出 dry-run 计划。", riskMatches[0]),
		})
	}

	// ILS-R013: ops/maintenance task — should not enter agent queue (CM-UAS-015)
	if opsMatches := reOpsMaintenance.FindAllString(rawText, -1); len(opsMatches) > 0 {
		flags = append(flags, AmbiguityFlag{
			Type: "ops_maintenance",
			Span: strings.Join(opsMatches[:min(len(opsMatches), 3)], ", "),
			Suggestion: fmt.Sprintf(
				"[ILS-R013] 检测到运维/维护关键词 '%s'。此类任务不走 Agent 队列，"+
					"请改用 SSH 直连 / systemd / Makefile target。"+
					"Agent 队列仅用于代码和推理任务。", opsMatches[0]),
		})
	}

	// ILS-R008: execution task keywords — may need execution agent, not reasoning agent (CM-UAS-008)
	if execMatches := reExecutionTask.FindAllString(rawText, -1); len(execMatches) > 0 {
		flags = append(flags, AmbiguityFlag{
			Type: "execution_task",
			Span: strings.Join(execMatches[:min(len(execMatches), 3)], ", "),
			Suggestion: fmt.Sprintf(
				"[ILS-R008] 任务含编译/构建关键词 '%s'，需要执行型 Agent (SCC/cc_worker)，"+
					"不能派给推理型 Agent (O4)。确认 target_agent_id 指向有 shell 执行能力的 Agent。",
				execMatches[0]),
		})
	}

	// ILS-R014: auth/API credential hint in task text (CM-UAS-010)
	if authMatches := rePermanentFailureHint.FindAllString(rawText, -1); len(authMatches) > 0 {
		flags = append(flags, AmbiguityFlag{
			Type: "permanent_failure_risk",
			Span: strings.Join(authMatches[:min(len(authMatches), 2)], ", "),
			Suggestion: fmt.Sprintf(
				"[ILS-R014] 任务描述含凭证/鉴权关键词 '%s'。"+
					"403/鉴权失败属于永久错误，重试无效。执行前确认 API key/subscription 有效。",
				authMatches[0]),
		})
	}

	return flags
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func SearchSimilarCases(rawText string, topK int) []SimilarCase {
	if topK <= 0 {
		topK = defaultTopK
	}

	if ragSearchFunc != nil {
		results, err := ragSearchFunc(rawText, topK)
		if err != nil {
			slog.Warn("pre-intake RAG search failed", "err", err)
			return nil
		}
		cases := make([]SimilarCase, 0, len(results))
		for _, r := range results {
			cases = append(cases, SimilarCase{
				CaseID:     r.Case.CaseID,
				Title:      r.Case.Title,
				Similarity: r.Similarity,
				Category:   r.Case.Category,
				Summary:    extractLesson(r.Case.Content),
			})
		}
		return cases
	}

	payload := map[string]interface{}{
		"query":          rawText,
		"top_k":          topK,
		"min_similarity": minSimilarity,
	}
	body, _ := json.Marshal(payload)

	url := ragBaseURL + "/cases/search"
	req, err := http.NewRequest("POST", url, bytes.NewReader(body))
	if err != nil {
		slog.Warn("pre-intake RAG: build request failed", "err", err)
		return nil
	}
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 8 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		slog.Warn("pre-intake RAG search failed", "err", err)
		return nil
	}
	defer resp.Body.Close()

	var result struct {
		Results []ragResult `json:"results"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		slog.Warn("pre-intake RAG: decode failed", "err", err)
		return nil
	}

	cases := make([]SimilarCase, 0, len(result.Results))
	for _, r := range result.Results {
		cases = append(cases, SimilarCase{
			CaseID:     r.Case.CaseID,
			Title:      r.Case.Title,
			Similarity: r.Similarity,
			Category:   r.Case.Category,
			Summary:    extractLesson(r.Case.Content),
		})
	}
	return cases
}

func extractLesson(c struct {
	WhatWorked       string `json:"what_worked"`
	AcceptanceResult string `json:"acceptance_result"`
	Goal             string `json:"goal"`
}) string {
	var parts []string
	if c.WhatWorked != "" {
		s := c.WhatWorked
		if len([]rune(s)) > 120 {
			s = string([]rune(s)[:120])
		}
		parts = append(parts, "✓ "+s)
	}
	if c.AcceptanceResult == "fail" {
		parts = append(parts, "✗ 验收失败")
	}
	if c.Goal != "" && len([]rune(c.Goal)) < 100 {
		parts = append(parts, "目标: "+c.Goal)
	}
	return strings.Join(parts, " | ")
}

func AssessRisk(rawText string, cases []SimilarCase, flags []AmbiguityFlag) (level string, reasons []string) {
	score := 0

	if reHighRiskKeywords.MatchString(rawText) {
		score += 3
		reasons = append(reasons, "含高风险操作关键词")
	}

	failedCount := 0
	for _, c := range cases {
		if strings.Contains(c.Summary, "失败") || strings.Contains(strings.ToLower(c.Summary), "fail") {
			failedCount++
		}
	}
	if failedCount >= 2 {
		score += 2
		reasons = append(reasons, fmt.Sprintf("有 %d 个相似案例曾失败", failedCount))
	}

	vagueCount := 0
	for _, f := range flags {
		if f.Type == "vague_reference" {
			vagueCount++
		}
	}
	if vagueCount >= 1 {
		score++
		reasons = append(reasons, fmt.Sprintf("存在 %d 处指代歧义", vagueCount))
	}

	compoundCount := 0
	for _, f := range flags {
		if f.Type == "compound_request" {
			compoundCount++
		}
	}
	if compoundCount >= 1 {
		score++
		reasons = append(reasons, "检测到复合需求，可能需要拆分")
	}

	switch {
	case score >= 4:
		return "high", reasons
	case score >= 2:
		return "medium", reasons
	default:
		return "low", reasons
	}
}

func BuildGuidance(rawText string, cases []SimilarCase, flags []AmbiguityFlag, riskLevel string, riskReasons []string, isCompound bool) string {
	var lines []string
	lines = append(lines, "[ILS PRE-INTAKE — 铁律前置增强上下文]")

	if len(cases) > 0 {
		lines = append(lines, "\n📚 相似历史案例（用户原文匹配）：")
		max := len(cases)
		if max > 5 {
			max = 5
		}
		for i := 0; i < max; i++ {
			c := cases[i]
			lines = append(lines, fmt.Sprintf("  %d. [%s] %s (相似度 %.3f)", i+1, c.Category, c.Title, c.Similarity))
			if c.Summary != "" {
				s := c.Summary
				if len([]rune(s)) > 150 {
					s = string([]rune(s)[:150])
				}
				lines = append(lines, "     "+s)
			}
		}
	}

	if len(flags) > 0 {
		lines = append(lines, "\n⚠️ 歧义检测：")
		for _, f := range flags {
			lines = append(lines, fmt.Sprintf("  • [%s] %s", f.Type, f.Span))
			lines = append(lines, "    → "+f.Suggestion)
		}
	}

	if riskLevel != "low" {
		lines = append(lines, fmt.Sprintf("\n🔴 风险等级: %s", strings.ToUpper(riskLevel)))
		for _, r := range riskReasons {
			lines = append(lines, "  • "+r)
		}
	}

	if isCompound {
		lines = append(lines, "\n🔗 检测到复合需求，建议拆分确认后逐个执行。")
	}

	lines = append(lines, "\n💡 Hermes 行为指引：")
	hasAmbiguity := len(flags) > 0
	if hasAmbiguity {
		lines = append(lines, "  1. 先向用户确认歧义点，不要猜测")
		lines = append(lines, "  2. 列出候选目标让用户选择")
	}
	if riskLevel == "high" {
		lines = append(lines, "  3. 高风险操作：先出 dry-run 计划，用户确认后再执行")
		lines = append(lines, "  4. 执行前确认备份状态")
	}
	if len(cases) > 0 {
		lines = append(lines, "  5. 参考相似案例的教训，主动提醒用户可能的风险")
	}
	if !hasAmbiguity && riskLevel == "low" {
		lines = append(lines, "  • 无歧义、低风险，可直接执行, 但注意边界")
	}

	lines = append(lines, "\n[/ILS PRE-INTAKE]")
	lines = append(lines, "\n---\n用户消息:\n"+rawText)

	return strings.Join(lines, "\n")
}

func Enrich(rawText, userID, project string) EnrichmentPacket {
	t0 := timenow()

	flags := DetectAmbiguity(rawText)

	cases := SearchSimilarCases(rawText, defaultTopK)

	riskLevel, riskReasons := AssessRisk(rawText, cases, flags)

	compoundParts := reCompoundConnectors.FindAllString(rawText, -1)
	isCompound := len(compoundParts) >= 2

	guidance := BuildGuidance(rawText, cases, flags, riskLevel, riskReasons, isCompound)

	elapsed := float64(timenow().Sub(t0).Microseconds()) / 1000.0

	packet := EnrichmentPacket{
		RawText:        rawText,
		UserID:         userID,
		EnrichedAt:     timenow().UTC().Format(time.RFC3339),
		SimilarCases:   cases,
		PriorFailures:  nil,
		AmbiguityFlags: flags,
		RiskLevel:      riskLevel,
		RiskReasons:    riskReasons,
		IsCompound:     isCompound,
		CompoundParts:  compoundParts,
		HermesGuidance: guidance,
		Project:        project,
		ProcessingMs:   elapsed,
	}

	slog.Info("pre_intake enriched", "risk", riskLevel, "ambiguities", len(flags), "similar", len(cases), "compound", isCompound, "ms", elapsed)

	return packet
}

func truncateRunes(s string, max int) string {
	runes := []rune(s)
	if len(runes) <= max {
		return s
	}
	return string(runes[:max])
}
