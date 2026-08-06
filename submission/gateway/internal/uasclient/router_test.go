package uasclient

import "testing"

// TestStaticRouter_Resolve covers the four Resolve rules required by
// Task 1.4: exact match, prefix match, longest-prefix-wins, and
// default fallback when nothing matches.
func TestStaticRouter_Resolve(t *testing.T) {
	const (
		h5 = "ws://h5-gateway:8001"
		h6 = "ws://h6-gateway:8001"
	)
	r := &StaticRouter{
		Default: h5,
		Routes: map[string]string{
			"h6-":        h6,
			"h6-hermes":  h6 + "/hermes", // longer prefix, distinct URL to prove selection
			"h5-hermes":  h5 + "/hermes",
		},
	}

	cases := []struct {
		name string
		in   string
		want string
	}{
		// 1. exact-ish: a known full agent id falls under its prefix.
		{"exact_agent_id_h6", "h6-hermes-sz-aliyun", h6 + "/hermes"},
		// 2. prefix only: h6-foo (no h6-hermes match) → h6 base.
		{"prefix_h6_only", "h6-worker-01", h6},
		// 3. longest prefix wins: h6-hermes-* beats h6-.
		{"longest_prefix_wins", "h6-hermes-sz-aliyun", h6 + "/hermes"},
		// 4. no match → default.
		{"no_match_default", "ob-main", h5},
		// 4b. empty target → default.
		{"empty_target_default", "", h5},
		// 5. h5 prefix routes to h5/hermes.
		{"h5_prefix", "h5-hermes-aws-hk", h5 + "/hermes"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := r.Resolve(tc.in)
			if got != tc.want {
				t.Fatalf("Resolve(%q) = %q, want %q", tc.in, got, tc.want)
			}
		})
	}
}

// TestStaticRouter_EmptyRoutesFallsBackToDefault: with no Routes
// entries at all, every input must return Default. Guards against a
// nil-map panic and against accidentally treating empty as "match".
func TestStaticRouter_EmptyRoutesFallsBackToDefault(t *testing.T) {
	r := &StaticRouter{Default: "ws://default:8001", Routes: nil}
	if got := r.Resolve("h6-hermes-sz-aliyun"); got != "ws://default:8001" {
		t.Fatalf("nil Routes: got %q, want default", got)
	}
}

// TestClient_ResolveGateway_NilRouter: when Config.Router is nil,
// the client must fall back to Config.GatewayURL for every target —
// i.e. behavior is unchanged from the pre-router single-gateway world.
func TestClient_ResolveGateway_NilRouter(t *testing.T) {
	c := &Client{cfg: Config{GatewayURL: "ws://single-gw:8001"}}
	cases := []string{"h6-hermes-sz-aliyun", "ob-main", "x1", ""}
	for _, target := range cases {
		if got := c.resolveGateway(target); got != "ws://single-gw:8001" {
			t.Fatalf("resolveGateway(%q) with nil Router = %q, want cfg.GatewayURL", target, got)
		}
	}
}

// TestClient_ResolveGateway_WithRouter: when a Router is configured,
// resolveGateway delegates to it for the given target.
func TestClient_ResolveGateway_WithRouter(t *testing.T) {
	c := &Client{cfg: Config{
		GatewayURL: "ws://default-gw:8001",
		Router: &StaticRouter{
			Default: "ws://default-gw:8001",
			Routes:  map[string]string{"h6-": "ws://h6-gw:8001"},
		},
	}}
	if got := c.resolveGateway("h6-hermes-sz-aliyun"); got != "ws://h6-gw:8001" {
		t.Fatalf("got %q, want h6-gw", got)
	}
	if got := c.resolveGateway("ob-main"); got != "ws://default-gw:8001" {
		t.Fatalf("got %q, want default-gw", got)
	}
}
