package decision

import (
	"testing"
)

// ── Text Scanner Tests ──────────────────────────────────────────────

func TestScannerAll10Phrasings(t *testing.T) {
	s := NewScanner()

	tests := []struct {
		phrase   string
		category string
		text     string
	}{
		{"必须", "obligation", "用户必须提供密码才能登录。"},
		{"应该", "urgency", "你应该考虑这个选项。"},
		{"立即", "urgency", "请立即停止操作。"},
		{"禁止", "prohibition", "禁止在系统上运行未授权的软件。"},
		{"不准", "prohibition", "不准私自修改配置。"},
		{"务必", "obligation", "请务必在截止日期前提交。"},
		{"强制", "obligation", "系统将强制更新到最新版本。"},
		{"确保", "obligation", "请确保所有测试通过。"},
		{"不得", "prohibition", "任何人不得删除系统日志。"},
		{"严禁", "prohibition", "严禁在生产环境直接调试。"},
	}

	for _, tt := range tests {
		t.Run(tt.phrase, func(t *testing.T) {
			results := s.Scan(tt.text)
			if len(results) == 0 {
				t.Fatalf("expected to find '%s' in '%s'", tt.phrase, tt.text)
			}

			found := false
			for _, r := range results {
				if r.Phrase == tt.phrase {
					found = true
					if r.Category != tt.category {
						t.Errorf("phrase %s: expected category %s, got %s", tt.phrase, tt.category, r.Category)
					}
					if r.Sentence == "" {
						t.Error("sentence context should not be empty")
					}
					break
				}
			}
			if !found {
				t.Errorf("phrase '%s' not found in scan results", tt.phrase)
			}
		})
	}
}

func TestScannerMultipleMatches(t *testing.T) {
	s := NewScanner()
	text := "用户必须提供密码。请确保密码强度足够。禁止使用常见密码。务必定期更换。"

	results := s.Scan(text)
	if len(results) < 4 {
		t.Errorf("expected at least 4 directive matches, got %d", len(results))
	}

	// All must be found
	phrases := []string{"必须", "确保", "禁止", "务必"}
	for _, p := range phrases {
		found := false
		for _, r := range results {
			if r.Phrase == p {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("phrase '%s' not found", p)
		}
	}
}

func TestScannerNoDirectives(t *testing.T) {
	s := NewScanner()
	text := "今天天气很好。我们去公园散步吧。晚饭想吃什么？"
	results := s.Scan(text)
	if len(results) != 0 {
		t.Errorf("expected 0 matches in neutral text, got %d", len(results))
	}
}

func TestScannerWithDirectiveInLongText(t *testing.T) {
	s := NewScanner()
	text := "这是一段很长的文本，其中包含了一些日常描述。" +
		"根据系统安全策略，任何人不得在未授权的情况下访问敏感数据。" +
		"此外，所有操作都应该记录在审计日志中。" +
		"系统管理员必须定期检查日志。" +
		"如果发现异常，请立即上报。"

	results := s.Scan(text)
	if len(results) < 4 {
		t.Errorf("expected at least 4 directive matches, got %d", len(results))
	}

	// Check sentence extraction has context
	for _, r := range results {
		if len(r.Sentence) < 5 {
			t.Errorf("sentence too short for phrase '%s': '%s'", r.Phrase, r.Sentence)
		}
	}
}

func TestScannerAllRulesCoverage(t *testing.T) {
	s := NewScanner()
	rules := s.ScanAllRules()

	total := 0
	for _, phrases := range rules {
		total += len(phrases)
	}
	if total != 10 {
		t.Errorf("expected 10 total directive rules, got %d", total)
	}

	// Verify all 10 phrases are covered
	allPhrases := make(map[string]bool)
	for _, phrases := range rules {
		for _, p := range phrases {
			allPhrases[p] = true
		}
	}
	expected := []string{"必须", "应该", "立即", "禁止", "不准", "务必", "强制", "确保", "不得", "严禁"}
	for _, p := range expected {
		if !allPhrases[p] {
			t.Errorf("phrase '%s' missing from rules", p)
		}
	}
}

// ── Evidence Collector Tests ────────────────────────────────────────

func TestEvidenceCollector(t *testing.T) {
	ec := NewEvidenceCollector()
	if ec.HasDirectives() {
		t.Error("new collector should not have directives")
	}

	ec.Add("source-1", "必须", "必须提供密码", "warning")
	ec.Add("source-2", "禁止", "禁止访问", "critical")

	if !ec.HasDirectives() {
		t.Error("collector should have directives after adding")
	}

	pointers := ec.Pointers()
	if len(pointers) != 2 {
		t.Fatalf("expected 2 pointers, got %d", len(pointers))
	}

	if pointers[0].Source != "source-1" {
		t.Errorf("expected source-1, got %s", pointers[0].Source)
	}
	if pointers[1].Severity != "critical" {
		t.Errorf("expected severity critical, got %s", pointers[1].Severity)
	}
}

// ── Decision Engine Tests ──────────────────────────────────────────

func TestProcessDecision(t *testing.T) {
	scanner := NewScanner()
	collector := NewEvidenceCollector()

	text := "系统管理员必须定期检查日志。禁止删除审计记录。发现异常请立即上报。"

	output := ProcessDecision(text, scanner, collector)
	if output == nil {
		t.Fatal("ProcessDecision returned nil")
	}

	if output.Decision != "analysis_complete" {
		t.Errorf("expected decision 'analysis_complete', got '%s'", output.Decision)
	}

	if len(output.DirectivesFound) < 3 {
		t.Errorf("expected at least 3 directives, got %d", len(output.DirectivesFound))
	}

	if len(output.EvidencePointers) < 3 {
		t.Errorf("expected at least 3 evidence pointers, got %d", len(output.EvidencePointers))
	}

	// Verify evidence has severity based on category
	for _, ep := range output.EvidencePointers {
		if ep.Severity == "" {
			t.Error("evidence pointer should have severity")
		}
	}
}

// ── Mock LLM Tests ─────────────────────────────────────────────────

func TestMockLLMClient(t *testing.T) {
	mock := NewMockLLMClient("This is a mock response.")

	resp, err := mock.Complete(&LLMRequest{Prompt: "test", MaxTokens: 100})
	if err != nil {
		t.Fatalf("mock Complete: %v", err)
	}
	if resp.Text != "This is a mock response." {
		t.Errorf("expected mock response, got '%s'", resp.Text)
	}
	if resp.Model != "mock" {
		t.Errorf("expected model 'mock', got '%s'", resp.Model)
	}
}

// ── Extract Sentence Tests ─────────────────────────────────────────

func TestExtractSentence(t *testing.T) {
	tests := []struct {
		name string
		text string
		pos  int
		want string
	}{
		{"simple", "Hello world. Must do this.", 12, "Hello world."},
		{"chinese", "你好。必须这样做。完毕。", 9, "必须这样做。"},
		{"at start", "必须马上处理。然后继续。", 0, "必须马上处理。"},
		{"with newline", "line1\n必须继续\nline3", 8, "必须继续"},
		{"empty", "", 0, ""},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := extractSentence(tt.text, tt.pos)
			if got == "" && tt.want != "" {
				t.Errorf("got empty, want '%s'", tt.want)
			}
		})
	}
}
