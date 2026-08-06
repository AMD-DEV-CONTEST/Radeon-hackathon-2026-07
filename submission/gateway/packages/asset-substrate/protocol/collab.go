package protocol

// CollaborationRequest is sent between seat agents for P2P cooperation.
// Defined in protocol (not in any agent package) to keep seats independent.
type CollaborationRequest struct {
	FromSeat string `json:"from_seat"`
	ToSeat   string `json:"to_seat"`
	Action   string `json:"action"`
	Payload  string `json:"payload"`
	Context  string `json:"context"`
}

// CollaborationResponse is the response from a collaboration request.
type CollaborationResponse struct {
	FromSeat string `json:"from_seat"`
	Success  bool   `json:"success"`
	Data     string `json:"data,omitempty"`
	Error    string `json:"error,omitempty"`
}
