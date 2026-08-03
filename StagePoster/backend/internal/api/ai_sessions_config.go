package api

import aisession "github.com/Ripped-sys/StagePoster/backend/internal/assistant"

func (s *Server) WithAISessions(
	service *aisession.Service,
) *Server {
	s.aiSessionService = service
	return s
}
