package lifememory

import (
	"testing"
)

func fixtureNodes() []*MemoryNode {
	return []*MemoryNode{
		{ID: "mem-001", Title: "Wedding Anniversary", Content: "June 22", Tags: []string{"anniversary", "family", "important"}},
		{ID: "mem-002", Title: "Birthday", Content: "Alice's birthday is March 15", Tags: []string{"birthday", "family", "important"}},
		{ID: "mem-003", Title: "Dog's Name", Content: "Our dog is named Max", Tags: []string{"pet", "family"}},
		{ID: "mem-004", Title: "Home Address", Content: "123 Main St", Tags: []string{"home", "important"}},
		{ID: "mem-005", Title: "Work Email", Content: "alice@company.com", Tags: []string{"work", "contact"}},
		{ID: "mem-006", Title: "Passport Number", Content: "AB123456", Tags: []string{"document", "important", "travel"}},
		{ID: "mem-007", Title: "Insurance Policy", Content: "Policy #XYZ-789", Tags: []string{"insurance", "document", "important"}},
		{ID: "mem-008", Title: "Favorite Restaurant", Content: "The Italian Place", Tags: []string{"food", "favorite"}},
		{ID: "mem-009", Title: "Gym Membership", Content: "Monthly pass at FitClub", Tags: []string{"health", "membership"}},
		{ID: "mem-010", Title: "Car License Plate", Content: "ABC-1234", Tags: []string{"vehicle", "document"}},
	}
}

func TestInsertAndGetByID(t *testing.T) {
	s := NewMemStore()
	node := &MemoryNode{ID: "mem-001", Title: "Test", Content: "Test content", Tags: []string{"test"}}

	if err := s.Insert(node); err != nil {
		t.Fatalf("Insert: %v", err)
	}

	got, err := s.GetByID("mem-001")
	if err != nil {
		t.Fatalf("GetByID: %v", err)
	}
	if got.Title != "Test" {
		t.Errorf("title: got %s, want Test", got.Title)
	}
	if got.CreatedAt.IsZero() {
		t.Error("CreatedAt should be set")
	}

	_, err = s.GetByID("nonexistent")
	if err != ErrNodeNotFound {
		t.Errorf("expected ErrNodeNotFound, got %v", err)
	}
}

func TestInsertWithoutID(t *testing.T) {
	s := NewMemStore()
	err := s.Insert(&MemoryNode{Title: "No ID", Content: "test", Tags: []string{"test"}})
	if err == nil {
		t.Error("expected error for empty ID")
	}
}

func TestInsert10FixturesAndQueryByTag(t *testing.T) {
	s := NewMemStore()
	nodes := fixtureNodes()

	for _, n := range nodes {
		if err := s.Insert(n); err != nil {
			t.Fatalf("Insert %s: %v", n.ID, err)
		}
	}

	// Verify count
	count, err := s.Count()
	if err != nil {
		t.Fatalf("Count: %v", err)
	}
	if count != 10 {
		t.Errorf("expected 10 nodes, got %d", count)
	}

	// Query by single tag: "important"
	important, err := s.QueryByTag("important")
	if err != nil {
		t.Fatalf("QueryByTag(important): %v", err)
	}
	if len(important) != 5 {
		t.Errorf("expected 5 nodes with tag 'important', got %d", len(important))
	}

	// Verify all returned nodes have the tag
	for _, n := range important {
		if !hasTag(n.Tags, "important") {
			t.Errorf("node %s should have tag 'important', got %v", n.ID, n.Tags)
		}
	}

	// Query by tag: "family"
	family, err := s.QueryByTag("family")
	if err != nil {
		t.Fatalf("QueryByTag(family): %v", err)
	}
	if len(family) != 3 {
		t.Errorf("expected 3 nodes with tag 'family', got %d", len(family))
	}

	// Query by tag: "document"
	doc, err := s.QueryByTag("document")
	if err != nil {
		t.Fatalf("QueryByTag(document): %v", err)
	}
	if len(doc) != 3 {
		t.Errorf("expected 3 nodes with tag 'document', got %d", len(doc))
	}

	// Query by nonexistent tag
	empty, err := s.QueryByTag("nonexistent")
	if err != nil {
		t.Fatalf("QueryByTag(nonexistent): %v", err)
	}
	if len(empty) != 0 {
		t.Errorf("expected 0 nodes, got %d", len(empty))
	}
}

func TestQueryByTagsANDLogic(t *testing.T) {
	s := NewMemStore()
	for _, n := range fixtureNodes() {
		if err := s.Insert(n); err != nil {
			t.Fatalf("Insert %s: %v", n.ID, err)
		}
	}

	// AND query: nodes with BOTH "family" AND "important"
	result, err := s.QueryByTags([]string{"family", "important"})
	if err != nil {
		t.Fatalf("QueryByTags: %v", err)
	}
	// mem-001 (anniversary) and mem-002 (birthday) have both
	if len(result) != 2 {
		t.Errorf("expected 2 nodes with family+important, got %d", len(result))
	}
	for _, n := range result {
		if n.ID != "mem-001" && n.ID != "mem-002" {
			t.Errorf("unexpected node in result: %s", n.ID)
		}
	}

	// AND query: "family" + "pet" -> only mem-003
	result2, err := s.QueryByTags([]string{"family", "pet"})
	if err != nil {
		t.Fatalf("QueryByTags: %v", err)
	}
	if len(result2) != 1 || result2[0].ID != "mem-003" {
		t.Errorf("expected 1 node (mem-003), got %d", len(result2))
	}

	// Three-tag AND: "important" + "document" + "insurance" -> mem-007
	result3, err := s.QueryByTags([]string{"important", "document", "insurance"})
	if err != nil {
		t.Fatalf("QueryByTags: %v", err)
	}
	if len(result3) != 1 || result3[0].ID != "mem-007" {
		t.Errorf("expected 1 node (mem-007), got %d", len(result3))
	}
}

func TestDelete(t *testing.T) {
	s := NewMemStore()
	s.Insert(&MemoryNode{ID: "del-001", Title: "To Delete", Content: "bye", Tags: []string{"temp"}})

	// Verify it exists
	count, _ := s.Count()
	if count != 1 {
		t.Fatalf("expected 1 before delete, got %d", count)
	}

	// Delete
	if err := s.Delete("del-001"); err != nil {
		t.Fatalf("Delete: %v", err)
	}

	// Verify gone
	_, err := s.GetByID("del-001")
	if err != ErrNodeNotFound {
		t.Errorf("expected ErrNodeNotFound after delete")
	}

	count, _ = s.Count()
	if count != 0 {
		t.Errorf("expected 0 after delete, got %d", count)
	}

	// Delete nonexistent
	err = s.Delete("nonexistent")
	if err != ErrNodeNotFound {
		t.Errorf("expected ErrNodeNotFound for nonexistent delete")
	}
}

func TestEmptyStore(t *testing.T) {
	s := NewMemStore()
	count, _ := s.Count()
	if count != 0 {
		t.Errorf("expected empty store, got %d", count)
	}

	nodes, err := s.QueryByTag("anything")
	if err != nil {
		t.Fatalf("QueryByTag on empty: %v", err)
	}
	if len(nodes) != 0 {
		t.Errorf("expected 0 from empty query, got %d", len(nodes))
	}
}

func TestNodeWithMultipleTags(t *testing.T) {
	s := NewMemStore()
	s.Insert(&MemoryNode{ID: "multi", Title: "Many Tags", Content: "test", Tags: []string{"a", "b", "c", "d", "e"}})

	for _, tag := range []string{"a", "b", "c", "d", "e"} {
		nodes, err := s.QueryByTag(tag)
		if err != nil {
			t.Fatalf("QueryByTag(%s): %v", tag, err)
		}
		if len(nodes) != 1 {
			t.Errorf("expected 1 node for tag %s, got %d", tag, len(nodes))
		}
	}

	// AND query with all 5 tags
	nodes, err := s.QueryByTags([]string{"a", "b", "c", "d", "e"})
	if err != nil {
		t.Fatalf("QueryByTags: %v", err)
	}
	if len(nodes) != 1 {
		t.Errorf("expected 1 node matching all 5 tags, got %d", len(nodes))
	}
}
