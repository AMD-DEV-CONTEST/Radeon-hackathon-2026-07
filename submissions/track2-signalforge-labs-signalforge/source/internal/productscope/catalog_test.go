package productscope

import (
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
)

func TestTechnology20CatalogMatchesEntityAuthority(t *testing.T) {
	if err := ValidateCatalog(); err != nil {
		t.Fatal(err)
	}
	if len(Companies()) != 20 {
		t.Fatal("technology catalog does not contain twenty companies")
	}
}

func TestInitialPeerLanesRemainDisabledUntilEvaluation(t *testing.T) {
	asOf := time.Date(2026, 7, 24, 12, 0, 0, 0, time.UTC)
	lanes, err := InitialPeerLanes(asOf, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
	if err != nil {
		t.Fatal(err)
	}
	if len(lanes) != 5 {
		t.Fatalf("expected five peer lanes, found %d", len(lanes))
	}
	for _, lane := range lanes {
		if lane.Enabled {
			t.Fatalf("unevaluated lane %q was enabled", lane.LaneID)
		}
		if err := contracts.ValidatePeerLane(lane); err != nil {
			t.Fatalf("lane %q is invalid: %v", lane.LaneID, err)
		}
	}
}
