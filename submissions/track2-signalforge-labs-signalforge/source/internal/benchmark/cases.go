package benchmark

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"
)

type Message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type Tool struct {
	Type     string       `json:"type"`
	Function ToolFunction `json:"function"`
}

type ToolFunction struct {
	Name        string         `json:"name"`
	Description string         `json:"description"`
	Parameters  map[string]any `json:"parameters"`
}

type RepeatBlock struct {
	Text  string `json:"text"`
	Count int    `json:"count"`
}

type Case struct {
	CaseID                string         `json:"case_id"`
	WorkloadClass         string         `json:"workload_class"`
	Messages              []Message      `json:"messages"`
	MaxTokens             int            `json:"max_tokens"`
	Temperature           float64        `json:"temperature"`
	RequiredTerms         []string       `json:"required_terms,omitempty"`
	ForbiddenTerms        []string       `json:"forbidden_terms,omitempty"`
	Tools                 []Tool         `json:"tools,omitempty"`
	RequiredTool          string         `json:"required_tool,omitempty"`
	RequiredToolArguments map[string]any `json:"required_tool_arguments,omitempty"`
	ResponseFormat        map[string]any `json:"response_format,omitempty"`
	RequireJSON           bool           `json:"require_json,omitempty"`
	Repeat                *RepeatBlock   `json:"repeat,omitempty"`
}

type Suite struct {
	SchemaVersion string `json:"schema_version"`
	BenchmarkID   string `json:"benchmark_id"`
	Cases         []Case `json:"cases"`
}

func LoadSuite(path string) (Suite, error) {
	payload, err := os.ReadFile(path)
	if err != nil {
		return Suite{}, fmt.Errorf("read benchmark suite: %w", err)
	}
	var suite Suite
	if err := json.Unmarshal(payload, &suite); err != nil {
		return Suite{}, fmt.Errorf("decode benchmark suite: %w", err)
	}
	if err := suite.Validate(); err != nil {
		return Suite{}, err
	}
	for index := range suite.Cases {
		suite.Cases[index].expandRepeat()
	}
	return suite, nil
}

func (suite Suite) Validate() error {
	if suite.SchemaVersion != "signalforge/model-benchmark-suite/v1" || suite.BenchmarkID == "" || len(suite.Cases) == 0 {
		return errors.New("benchmark suite is incomplete")
	}
	seen := map[string]bool{}
	for _, item := range suite.Cases {
		if item.CaseID == "" || item.WorkloadClass == "" || len(item.Messages) == 0 || item.MaxTokens < 1 {
			return fmt.Errorf("benchmark case %q is incomplete", item.CaseID)
		}
		if seen[item.CaseID] {
			return fmt.Errorf("duplicate benchmark case %q", item.CaseID)
		}
		seen[item.CaseID] = true
		for _, message := range item.Messages {
			if (message.Role != "system" && message.Role != "user" && message.Role != "assistant") || strings.TrimSpace(message.Content) == "" {
				return fmt.Errorf("benchmark case %q has an invalid message", item.CaseID)
			}
		}
		if item.Repeat != nil && (item.Repeat.Count < 1 || strings.TrimSpace(item.Repeat.Text) == "") {
			return fmt.Errorf("benchmark case %q has an invalid repeat block", item.CaseID)
		}
		if len(item.RequiredToolArguments) > 0 && item.RequiredTool == "" {
			return fmt.Errorf("benchmark case %q requires arguments without a tool", item.CaseID)
		}
	}
	return nil
}

func (item *Case) expandRepeat() {
	if item.Repeat == nil {
		return
	}
	for index := len(item.Messages) - 1; index >= 0; index-- {
		if item.Messages[index].Role == "user" {
			item.Messages[index].Content += "\n\nRESEARCH PACKET:\n" + strings.Repeat(item.Repeat.Text+"\n", item.Repeat.Count)
			break
		}
	}
	item.Repeat = nil
}
