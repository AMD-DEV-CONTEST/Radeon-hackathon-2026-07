package orchestrator

import (
	"testing"
	"time"
)

// TestShouldPromoteKeeperToWorker: the promote condition requires ALL
// three signals at once — every worker running (满载), a high-priority
// task waiting past the threshold, and an idle keeper available. Any
// one missing → no promotion.
func TestShouldPromoteKeeperToWorker(t *testing.T) {
	threshold := 2 * time.Minute
	cases := []struct {
		name string
		sig  phaseChangeSignals
		want bool
	}{
		{
			name: "all_conditions_met",
			sig: phaseChangeSignals{
				AllWorkersRunning:      true,
				HighPriorityWaitingFor: 3 * time.Minute,
				IdleKeeperAvailable:    true,
				OnlineKeeperExists:     true, // keeper exists but is the idle one
			},
			want: true,
		},
		{
			name: "not_full_load",
			sig: phaseChangeSignals{
				AllWorkersRunning:      false,
				HighPriorityWaitingFor: 3 * time.Minute,
				IdleKeeperAvailable:    true,
			},
			want: false,
		},
		{
			name: "no_high_priority_waiting",
			sig: phaseChangeSignals{
				AllWorkersRunning:      true,
				HighPriorityWaitingFor: 30 * time.Second, // under threshold
				IdleKeeperAvailable:    true,
			},
			want: false,
		},
		{
			name: "no_idle_keeper",
			sig: phaseChangeSignals{
				AllWorkersRunning:      true,
				HighPriorityWaitingFor: 3 * time.Minute,
				IdleKeeperAvailable:    false,
			},
			want: false,
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := shouldPromoteKeeperToWorker(c.sig, threshold)
			if got != c.want {
				t.Fatalf("shouldPromoteKeeperToWorker = %v, want %v", got, c.want)
			}
		})
	}
}

// TestShouldDemoteWorkerToKeeper: demote fires when there is NO online
// keeper (the role is vacant) AND an idle worker exists to fill it.
// An idle worker is one with no running task for a while.
func TestShouldDemoteWorkerToKeeper(t *testing.T) {
	idleThreshold := 5 * time.Minute
	cases := []struct {
		name string
		sig  phaseChangeSignals
		want bool
	}{
		{
			name: "no_keeper_and_idle_worker",
			sig: phaseChangeSignals{
				OnlineKeeperExists:  false,
				IdleWorkerAvailable: true,
				IdleWorkerIdleFor:   6 * time.Minute,
			},
			want: true,
		},
		{
			name: "keeper_still_online",
			sig: phaseChangeSignals{
				OnlineKeeperExists:  true,
				IdleWorkerAvailable: true,
				IdleWorkerIdleFor:   6 * time.Minute,
			},
			want: false,
		},
		{
			name: "no_idle_worker",
			sig: phaseChangeSignals{
				OnlineKeeperExists:  false,
				IdleWorkerAvailable: false,
				IdleWorkerIdleFor:   0,
			},
			want: false,
		},
		{
			name: "worker_not_idle_long_enough",
			sig: phaseChangeSignals{
				OnlineKeeperExists:  false,
				IdleWorkerAvailable: true,
				IdleWorkerIdleFor:   2 * time.Minute, // under 5m threshold
			},
			want: false,
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := shouldDemoteWorkerToKeeper(c.sig, idleThreshold)
			if got != c.want {
				t.Fatalf("shouldDemoteWorkerToKeeper = %v, want %v", got, c.want)
			}
		})
	}
}

// TestShouldApplyPending: a pending role change is eligible to apply
// only when pending_until is set (non-zero) and the current time is
// past it.
func TestShouldApplyPending(t *testing.T) {
	now := time.Now()
	cases := []struct {
		name        string
		pendingUntil time.Time
		want        bool
	}{
		{"past_grace", now.Add(-10 * time.Second), true},
		{"future_still_waiting", now.Add(30 * time.Second), false},
		{"never_set", time.Time{}, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := shouldApplyPending(c.pendingUntil, now)
			if got != c.want {
				t.Fatalf("shouldApplyPending = %v, want %v", got, c.want)
			}
		})
	}
}
