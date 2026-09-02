package permissions

import "testing"

func TestReadOnlyModelAndExplicitUserMutationPolicy(t *testing.T) {
	for _, operation := range []Operation{SourceRead, Compute} {
		if err := Authorize(AuthorityModel, operation); err != nil {
			t.Fatalf("model %s: %v", operation, err)
		}
	}
	for _, operation := range []Operation{CaseRead, CaseSave, CaseExport, CaseDelete, ExternalWrite} {
		if err := Authorize(AuthorityModel, operation); err == nil {
			t.Fatalf("model unexpectedly authorized for %s", operation)
		}
	}
	for _, operation := range []Operation{CaseRead, CaseSave, CaseExport, CaseDelete} {
		if err := Authorize(AuthorityUser, operation); err != nil {
			t.Fatalf("user %s: %v", operation, err)
		}
	}
	if err := Authorize(AuthorityUser, ExternalWrite); err == nil {
		t.Fatal("external writes must remain unavailable in the bounded product")
	}
}
