package main

import "testing"

func TestParseCIKsCanonicalizesAndDeduplicates(t *testing.T) {
	got, err := parseCIKs("789019,0001045810,0000789019")
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if len(got) != 2 || got[0] != "0000789019" || got[1] != "0001045810" {
		t.Fatalf("unexpected CIKs: %#v", got)
	}
}

func TestParseCIKsRejectsEmptyAndInvalidValues(t *testing.T) {
	if _, err := parseCIKs(""); err == nil {
		t.Fatal("empty CIK list must fail")
	}
	if _, err := parseCIKs("789019,invalid"); err == nil {
		t.Fatal("invalid CIK must fail")
	}
}
