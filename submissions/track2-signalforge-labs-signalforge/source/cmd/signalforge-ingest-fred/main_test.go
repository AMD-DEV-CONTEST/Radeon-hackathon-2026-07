package main

import "testing"

func TestSplitValuesDeduplicatesSeries(t *testing.T) {
	values := splitValues("DFF,DGS10,DFF")
	if len(values) != 2 || values[0] != "DFF" || values[1] != "DGS10" {
		t.Fatalf("unexpected values %#v", values)
	}
}
