package uasclient

import "strings"

// Router resolves which Gateway a chat message should be POSTed to,
// based on the target agent ID.
//
// In the single-base deployment the client has always shipped with
// (Config.GatewayURL), routing is trivial: every Send hits the one
// gateway. Multi-base deployments (H5 Shanghai + H6 Shenzhen) need a
// client-side decision instead — a message addressed to
// h6-hermes-sz-aliyun must land on the H6 gateway, not H5. The
// Gateway itself does NOT forward across bases; routing is a client
// responsibility.
//
// A nil Router (the zero value of Config.Router) means "no routing":
// Send falls back to Config.GatewayURL exactly as before, so existing
// callers see no behavior change.
type Router interface {
	// Resolve returns the Gateway URL for a given target agent ID.
	// Implementations MUST return a non-empty string for any input;
	// when no route matches, the configured Default is returned.
	Resolve(targetAgentID string) string
}

// StaticRouter is a prefix-table Router. Routes maps an agent-id
// prefix to a Gateway URL. Resolve picks the longest matching prefix
// (so "h6-hermes" wins over "h6-" for "h6-hermes-sz-aliyun") and
// falls back to Default when nothing matches.
//
// The prefix match is a plain strings.HasPrefix: agent IDs follow a
// stable dotted-prefix convention (h5-, h6-, ob-, x1-, c1-) and the
// table is operator-configured, so a substring rule would be both
// slower and more error-prone. If a future naming scheme needs
// different semantics, add a second Router implementation rather
// than overloading this one.
type StaticRouter struct {
	Default string            // fallback gateway URL when no prefix matches
	Routes  map[string]string // agent_id_prefix → gateway URL
}

// Resolve implements Router. It scans every entry in Routes and
// keeps the longest prefix that matches targetAgentID. Ties (two
// entries of equal length both matching — impossible for distinct
// prefixes, but defended against) resolve to whichever the map
// iteration happens to return last.
func (r *StaticRouter) Resolve(targetAgentID string) string {
	if r == nil || len(r.Routes) == 0 {
		return r.defaultURL()
	}
	bestLen := -1
	bestURL := ""
	for prefix, gw := range r.Routes {
		if !strings.HasPrefix(targetAgentID, prefix) {
			continue
		}
		if len(prefix) > bestLen {
			bestLen = len(prefix)
			bestURL = gw
		}
	}
	if bestLen < 0 {
		return r.defaultURL()
	}
	return bestURL
}

// defaultURL returns Default, tolerating a nil receiver so callers
// can write (&StaticRouter{}).Resolve(x) without guarding.
func (r *StaticRouter) defaultURL() string {
	if r == nil {
		return ""
	}
	return r.Default
}

// resolveGateway is the in-client helper used by Send/Reply: if a
// Router is configured, delegate to it; otherwise return the
// configured single GatewayURL. Centralizing the nil check here keeps
// the call sites in chat.go to a single line.
func (c *Client) resolveGateway(targetAgentID string) string {
	if c.cfg.Router != nil {
		return c.cfg.Router.Resolve(targetAgentID)
	}
	return c.cfg.GatewayURL
}
