package orchestrator

import "testing"

// TestSelectHandoffTarget_PrefersLocal: given a local agent and a
// remote agent both able to handle the task, the handoff picks the
// local one (lower latency, no cross-base hop).
func TestSelectHandoffTarget_PrefersLocal(t *testing.T) {
	candidates := []handoffCandidate{
		{ID: "remote-1", PeerURL: "http://h6:8000", Online: true},
		{ID: "local-1", PeerURL: "", Online: true}, // empty PeerURL = local
	}
	got := selectHandoffTarget(candidates, "timed-out-agent")
	if got == nil || got.ID != "local-1" {
		t.Fatalf("selectHandoffTarget = %+v, want local-1", got)
	}
}

// TestSelectHandoffTarget_ExcludesTimedOutAgent: the agent that just
// timed out must never be re-selected as the handoff target — that
// would just hand the task back to the dead/slow agent.
func TestSelectHandoffTarget_ExcludesTimedOutAgent(t *testing.T) {
	candidates := []handoffCandidate{
		{ID: "timed-out-agent", PeerURL: "", Online: true},
		{ID: "local-2", PeerURL: "", Online: true},
	}
	got := selectHandoffTarget(candidates, "timed-out-agent")
	if got == nil || got.ID != "local-2" {
		t.Fatalf("selectHandoffTarget = %+v, want local-2 (timed-out excluded)", got)
	}
}

// TestSelectHandoffTarget_FallsBackToRemote: if no local agent is
// available, the handoff uses a remote agent rather than giving up.
func TestSelectHandoffTarget_FallsBackToRemote(t *testing.T) {
	candidates := []handoffCandidate{
		{ID: "remote-1", PeerURL: "http://h6:8000", Online: true},
	}
	got := selectHandoffTarget(candidates, "timed-out-agent")
	if got == nil || got.ID != "remote-1" {
		t.Fatalf("selectHandoffTarget = %+v, want remote-1 (fallback to remote)", got)
	}
}

// TestSelectHandoffTarget_RequiresOnline: offline/degraded agents are
// skipped — handing off to a known-unhealthy agent defeats the purpose.
func TestSelectHandoffTarget_RequiresOnline(t *testing.T) {
	candidates := []handoffCandidate{
		{ID: "offline-1", PeerURL: "", Online: false},
		{ID: "online-1", PeerURL: "", Online: true},
	}
	got := selectHandoffTarget(candidates, "timed-out-agent")
	if got == nil || got.ID != "online-1" {
		t.Fatalf("selectHandoffTarget = %+v, want online-1 (offline skipped)", got)
	}
}

// TestSelectHandoffTarget_NoneAvailable: when no candidate passes the
// filters (all offline, or only the timed-out agent), the function
// returns nil — the caller must then fall back to the original
// timeout_silent_resume path rather than hand off.
func TestSelectHandoffTarget_NoneAvailable(t *testing.T) {
	candidates := []handoffCandidate{
		{ID: "timed-out-agent", PeerURL: "", Online: true},
		{ID: "offline-1", PeerURL: "", Online: false},
	}
	if got := selectHandoffTarget(candidates, "timed-out-agent"); got != nil {
		t.Fatalf("selectHandoffTarget = %+v, want nil (no viable target)", got)
	}
}

// TestShouldAttemptHandoff_CapsAtOne: a task that has already been
// handed off once (handoff_count >= 1) must NOT be handed off again —
// the second failure goes straight to failed_final, no recursion.
func TestShouldAttemptHandoff(t *testing.T) {
	if !shouldAttemptHandoff(0) {
		t.Fatal("handoff_count=0 should allow handoff")
	}
	if shouldAttemptHandoff(1) {
		t.Fatal("handoff_count=1 should NOT allow handoff (caps at one, no recursion)")
	}
	if shouldAttemptHandoff(5) {
		t.Fatal("handoff_count=5 should NOT allow handoff")
	}
}
