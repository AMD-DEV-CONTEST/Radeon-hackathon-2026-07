package main

import "fmt"

// fromIdentity is the resolved sender identity for `ils chat send`.
type fromIdentity struct {
	fromAgentID string
	from        string
}

// resolveFromProfile resolves the sender for chat send. Precedence:
//  1. explicitAgentID (from --from-agent-id) wins — no profile lookup.
//  2. fromProfile (from --from-profile) loads the profile; its agent_id
//     becomes fromAgentID. from is set to the profile's display name
//     (or a default) unless explicitly overridden.
//  3. Neither set → returns zero values; caller applies existing defaults
//     (AGENT_ID env, hostname-ils-cli).
//
// This preserves the legacy --from-agent-id path byte-for-byte; the
// --from-profile flag is purely additive identity resolution.
func resolveFromProfile(fromProfile, explicitAgentID, explicitFrom string) (fromIdentity, error) {
	if explicitAgentID != "" {
		return fromIdentity{fromAgentID: explicitAgentID, from: explicitFrom}, nil
	}
	if fromProfile == "" {
		return fromIdentity{}, nil
	}
	p, err := profileGet(fromProfile)
	if err != nil {
		return fromIdentity{}, fmt.Errorf("--from-profile %q: %w", fromProfile, err)
	}
	from := explicitFrom
	if from == "" {
		from = "ils-profile-" + p.Name
	}
	return fromIdentity{fromAgentID: p.AgentID, from: from}, nil
}
