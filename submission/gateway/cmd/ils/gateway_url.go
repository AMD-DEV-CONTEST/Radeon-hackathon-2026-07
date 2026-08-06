package main

import "strings"

// gatewayHTTPBase converts a ws:// Gateway URL to its http://
// counterpart and trims any trailing /ws path. Kept in the ils
// command package because doctor.go, status.go, and event.go all
// need a one-shot HTTP base for /health, /events/status, and
// /boundary calls without the overhead of a uasclient.Client.
//
// For URL→WS conversion (which IS what uasclient does internally)
// use uasclient.New(). For URL→HTTP+trims (which doctor/status
// use), use this function.
func gatewayHTTPBase(gatewayURL string) string {
	base := gatewayURL
	if strings.HasPrefix(base, "ws://") {
		base = "http://" + strings.TrimPrefix(base, "ws://")
	} else if strings.HasPrefix(base, "wss://") {
		base = "https://" + strings.TrimPrefix(base, "wss://")
	}
	// Trim trailing /ws so a caller passing a full WS URL still
	// gets a clean HTTP base.
	if strings.HasSuffix(base, "/ws") {
		base = strings.TrimSuffix(base, "/ws")
	}
	return strings.TrimRight(base, "/")
}
