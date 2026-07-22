package benchmark

import "testing"

func TestSuiteRejectsDuplicateCases(t *testing.T) {
	item := Case{CaseID: "same", WorkloadClass: "accounting", Messages: []Message{{Role: "user", Content: "Test"}}, MaxTokens: 8}
	suite := Suite{SchemaVersion: "signalforge/model-benchmark-suite/v1", BenchmarkID: "test", Cases: []Case{item, item}}
	if suite.Validate() == nil {
		t.Fatal("expected duplicate case failure")
	}
}

func TestRepeatBlockExpandsOnlyIntoLastUserMessage(t *testing.T) {
	item := Case{
		Messages: []Message{{Role: "user", Content: "first"}, {Role: "assistant", Content: "answer"}, {Role: "user", Content: "last"}},
		Repeat:   &RepeatBlock{Text: "evidence", Count: 2},
	}
	item.expandRepeat()
	if item.Messages[0].Content != "first" || item.Messages[2].Content == "last" || item.Repeat != nil {
		t.Fatalf("unexpected expansion: %+v", item)
	}
}
