package main

import "testing"

func TestSplitValuesCanonicalizesSymbols(t *testing.T) {
	values := splitValues("msft,NVDA,MSFT")
	if len(values) != 2 || values[0] != "MSFT" || values[1] != "NVDA" {
		t.Fatalf("unexpected values %#v", values)
	}
}
