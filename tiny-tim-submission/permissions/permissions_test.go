package permissions

import "testing"

func TestPolicyAllowPasses(t *testing.T) {
	p := DefaultPolicy(nil)
	if err := p.Check(LocalFiles, "read a file"); err != nil {
		t.Fatalf("expected LocalFiles (Allow) to pass, got: %v", err)
	}
}

func TestPolicyDenyBlocks(t *testing.T) {
	p := DefaultPolicy(nil)
	if err := p.Check(ShellExecution, "run a shell command"); err == nil {
		t.Fatal("expected ShellExecution (Deny) to be blocked, got nil error")
	}
}

func TestPolicyAskWithConfirmTruePasses(t *testing.T) {
	p := DefaultPolicy(func(action string) bool { return true })
	if err := p.Check(WriteCorpus, "write a verified claim"); err != nil {
		t.Fatalf("expected WriteCorpus (Ask, confirmed true) to pass, got: %v", err)
	}
}

func TestPolicyAskWithConfirmFalseBlocks(t *testing.T) {
	p := DefaultPolicy(func(action string) bool { return false })
	if err := p.Check(WriteCorpus, "write a verified claim"); err == nil {
		t.Fatal("expected WriteCorpus (Ask, declined) to be blocked, got nil error")
	}
}

func TestPolicyAskWithNoConfirmFuncBlocks(t *testing.T) {
	p := DefaultPolicy(nil)
	if err := p.Check(WriteCorpus, "write a verified claim"); err == nil {
		t.Fatal("expected WriteCorpus (Ask, no confirm func configured) to be blocked, got nil error")
	}
}

func TestPolicyUnknownCategoryDefaultsToDeny(t *testing.T) {
	p := DefaultPolicy(func(action string) bool { return true })
	if err := p.Check(Category("some_unrecognized_category"), "do something unknown"); err == nil {
		t.Fatal("expected an unrecognized category to default-deny, got nil error")
	}
}
