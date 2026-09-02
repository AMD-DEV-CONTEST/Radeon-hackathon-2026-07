package main

import (
	"testing"

	"github.com/rvbernucci/signalforge/internal/productscope"
)

func TestExpectedSuiteCasesSupportsDevelopmentAugmentation(t *testing.T) {
	tests := []struct {
		split string
		want  int
	}{
		{productscope.StandaloneDevelopmentSplit, 80},
		{productscope.StandaloneAugmentationSplit, 60},
		{productscope.StandaloneSealedSplit, 40},
	}
	for _, test := range tests {
		got, err := expectedSuiteCases(test.split)
		if err != nil {
			t.Fatalf("%s: %v", test.split, err)
		}
		if got != test.want {
			t.Fatalf("%s = %d cases, want %d", test.split, got, test.want)
		}
	}
	if _, err := expectedSuiteCases("unknown"); err == nil {
		t.Fatal("unknown split was accepted")
	}
}
