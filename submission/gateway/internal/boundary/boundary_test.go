package boundary

import "testing"

func TestSnapshotKeepsExternalReferencesOutOfUASChain(t *testing.T) {
	snap := NewSnapshot("test-component", "test role")

	for _, node := range snap.UASChain {
		if node.Name == "Lark CLI / Feishu Cloud" || node.Name == "Feishu Cloud" || node.Name == "Lark CLI" {
			t.Fatalf("external reference leaked into uas_chain: %+v", node)
		}
	}

	foundReferenceOnly := false
	for _, ref := range snap.ExternalReferences {
		if ref.Name == "Lark CLI / Feishu Cloud" {
			foundReferenceOnly = true
			if ref.Relation != "reference_only" {
				t.Fatalf("external reference relation = %q, want reference_only", ref.Relation)
			}
		}
	}
	if !foundReferenceOnly {
		t.Fatal("missing Lark CLI / Feishu Cloud reference_only entry")
	}
}

func TestSnapshotForbidsFeishuMappings(t *testing.T) {
	snap := NewSnapshot("test-component", "test role")
	required := []string{
		"Feishu Cloud -> Hermes Gateway -> UAS Gateway",
		"JD-ECS receives Feishu Cloud events",
		"UAS maps Feishu event_id/message_id/chat_id/open_id",
		"Lark CLI event bus == ils daemon",
	}

	for _, want := range required {
		found := false
		for _, got := range snap.ForbiddenMappings {
			if got == want {
				found = true
				break
			}
		}
		if !found {
			t.Fatalf("missing forbidden mapping %q", want)
		}
	}
}
