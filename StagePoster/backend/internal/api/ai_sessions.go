package api

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"time"

	aisession "github.com/Ripped-sys/StagePoster/backend/internal/assistant"
	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
	"github.com/Ripped-sys/StagePoster/backend/internal/repository"
)

func (s *Server) handleAISessions(
	writer http.ResponseWriter,
	request *http.Request,
) {
	if request.Method != http.MethodPost {
		writeError(
			writer,
			http.StatusMethodNotAllowed,
			"method not allowed",
		)
		return
	}

	if !s.aiSessionsReady() {
		writeError(
			writer,
			http.StatusServiceUnavailable,
			"AI session service is not configured",
		)
		return
	}

	request.Body = http.MaxBytesReader(
		writer,
		request.Body,
		1024*1024,
	)

	var payload domain.CreateAISessionRequest

	decoder := json.NewDecoder(request.Body)
	decoder.DisallowUnknownFields()

	if err := decoder.Decode(&payload); err != nil &&
		!errors.Is(err, io.EOF) {
		writeError(
			writer,
			http.StatusBadRequest,
			"invalid JSON: "+err.Error(),
		)
		return
	}

	ctx, cancel := contextWithTimeout(
		request,
		30*time.Second,
	)
	defer cancel()

	result, err := s.aiSessionService.Create(
		ctx,
		payload,
	)
	if err != nil {
		writeInternalError(
			writer,
			request,
			err,
		)
		return
	}

	writeJSON(
		writer,
		http.StatusCreated,
		result,
	)
}

func (s *Server) handleAISessionRoute(
	writer http.ResponseWriter,
	request *http.Request,
) {
	if !s.aiSessionsReady() {
		writeError(
			writer,
			http.StatusServiceUnavailable,
			"AI session service is not configured",
		)
		return
	}

	path := strings.TrimPrefix(
		request.URL.Path,
		"/api/ai/sessions/",
	)

	path = strings.Trim(path, "/")

	if path == "" {
		writeError(
			writer,
			http.StatusBadRequest,
			"session id is required",
		)
		return
	}

	segments := strings.Split(path, "/")
	sessionID := segments[0]

	switch {
	case len(segments) == 1 &&
		request.Method == http.MethodGet:

		s.handleGetAISession(
			writer,
			request,
			sessionID,
		)

	case len(segments) == 2 &&
		segments[1] == "messages" &&
		request.Method == http.MethodPost:

		s.handleAIMessage(
			writer,
			request,
			sessionID,
		)

	case len(segments) == 2 &&
		segments[1] == "assets" &&
		request.Method == http.MethodPost:

		s.handleBindAISessionAssets(
			writer,
			request,
			sessionID,
		)

	case len(segments) == 2 &&
		segments[1] == "cancel" &&
		request.Method == http.MethodPost:

		s.handleCancelAISession(
			writer,
			request,
			sessionID,
		)

	case len(segments) == 2 &&
		segments[1] == "finalize" &&
		request.Method == http.MethodPost:

		s.handleFinalizeAISession(
			writer,
			request,
			sessionID,
		)

	case len(segments) == 4 &&
		segments[1] == "plans" &&
		segments[3] == "confirm" &&
		request.Method == http.MethodPost:

		s.handleConfirmAIPlan(
			writer,
			request,
			sessionID,
			segments[2],
		)

	case len(segments) == 4 &&
		segments[1] == "candidates" &&
		segments[3] == "select" &&
		request.Method == http.MethodPost:

		s.handleSelectAICandidate(
			writer,
			request,
			sessionID,
			segments[2],
		)

	default:
		writeError(
			writer,
			http.StatusNotFound,
			"AI session route not found",
		)
	}
}

func (s *Server) handleFinalizeAISession(
	writer http.ResponseWriter,
	request *http.Request,
	sessionID string,
) {
	ctx, cancel := contextWithTimeout(
		request,
		12*time.Minute,
	)
	defer cancel()

	result, err := s.aiSessionService.Finalize(
		ctx,
		sessionID,
	)

	switch {
	case errors.Is(err, repository.ErrNotFound):
		writeError(
			writer,
			http.StatusNotFound,
			"AI session, poster, or design plan not found",
		)
		return

	case errors.Is(
		err,
		aisession.ErrFinalizeNotReady,
	),
		errors.Is(
			err,
			aisession.ErrInvalidSessionState,
		),
		errors.Is(
			err,
			aisession.ErrSessionTerminal,
		):
		writeError(
			writer,
			http.StatusConflict,
			err.Error(),
		)
		return

	case err != nil:
		writeError(
			writer,
			http.StatusBadGateway,
			err.Error(),
		)
		return
	}

	writeJSON(
		writer,
		http.StatusOK,
		result,
	)
}

func (s *Server) handleSelectAICandidate(
	writer http.ResponseWriter,
	request *http.Request,
	sessionID string,
	candidateID string,
) {
	ctx, cancel := contextWithTimeout(
		request,
		2*time.Minute,
	)
	defer cancel()

	result, err :=
		s.aiSessionService.SelectCandidate(
			ctx,
			sessionID,
			candidateID,
		)

	switch {
	case errors.Is(err, repository.ErrNotFound):
		writeError(
			writer,
			http.StatusNotFound,
			"AI session, poster, or candidate not found",
		)
		return

	case errors.Is(
		err,
		aisession.ErrInvalidSessionState,
	),
		errors.Is(
			err,
			aisession.ErrSessionTerminal,
		):

		writeError(
			writer,
			http.StatusConflict,
			err.Error(),
		)
		return

	case err != nil:
		writeError(
			writer,
			http.StatusConflict,
			err.Error(),
		)
		return
	}

	writeJSON(
		writer,
		http.StatusOK,
		result,
	)
}

func (s *Server) handleGetAISession(
	writer http.ResponseWriter,
	request *http.Request,
	sessionID string,
) {
	ctx, cancel := contextWithTimeout(
		request,
		60*time.Second,
	)
	defer cancel()

	result, err := s.aiSessionService.Get(
		ctx,
		sessionID,
	)

	if errors.Is(err, repository.ErrNotFound) {
		writeError(
			writer,
			http.StatusNotFound,
			"AI session not found",
		)
		return
	}

	if err != nil {
		writeInternalError(
			writer,
			request,
			err,
		)
		return
	}

	writeJSON(writer, http.StatusOK, result)
}

func (s *Server) handleAIMessage(
	writer http.ResponseWriter,
	request *http.Request,
	sessionID string,
) {
	request.Body = http.MaxBytesReader(
		writer,
		request.Body,
		1024*1024,
	)

	var payload domain.SendAIMessageRequest

	decoder := json.NewDecoder(request.Body)
	decoder.DisallowUnknownFields()

	if err := decoder.Decode(&payload); err != nil {
		writeError(
			writer,
			http.StatusBadRequest,
			"invalid JSON: "+err.Error(),
		)
		return
	}

	ctx, cancel := contextWithTimeout(
		request,
		8*time.Minute,
	)
	defer cancel()

	result, err := s.aiSessionService.SendMessage(
		ctx,
		sessionID,
		payload.Content,
	)

	switch {
	case errors.Is(err, repository.ErrNotFound):
		writeError(
			writer,
			http.StatusNotFound,
			"AI session not found",
		)

	case errors.Is(err, aisession.ErrEmptyMessage):
		writeError(
			writer,
			http.StatusBadRequest,
			err.Error(),
		)

	case errors.Is(
		err,
		aisession.ErrInvalidSessionState,
	),
		errors.Is(
			err,
			aisession.ErrSessionTerminal,
		):

		writeError(
			writer,
			http.StatusConflict,
			err.Error(),
		)

	case err != nil:
		writeError(
			writer,
			http.StatusBadGateway,
			err.Error(),
		)

	default:
		writeJSON(
			writer,
			http.StatusOK,
			result,
		)
	}
}

func (s *Server) handleBindAISessionAssets(
	writer http.ResponseWriter,
	request *http.Request,
	sessionID string,
) {
	request.Body = http.MaxBytesReader(
		writer,
		request.Body,
		1024*1024,
	)

	var payload domain.BindAISessionAssetsRequest

	decoder := json.NewDecoder(request.Body)
	decoder.DisallowUnknownFields()

	if err := decoder.Decode(&payload); err != nil {
		writeError(
			writer,
			http.StatusBadRequest,
			"invalid JSON: "+err.Error(),
		)
		return
	}

	ctx, cancel := contextWithTimeout(
		request,
		30*time.Second,
	)
	defer cancel()

	result, err := s.aiSessionService.BindAssets(
		ctx,
		sessionID,
		payload.Assets,
	)

	switch {
	case errors.Is(err, repository.ErrNotFound):
		writeError(
			writer,
			http.StatusNotFound,
			"session or asset not found",
		)

	case errors.Is(
		err,
		aisession.ErrInvalidAssetPurpose,
	):
		writeError(
			writer,
			http.StatusBadRequest,
			err.Error(),
		)

	case errors.Is(
		err,
		aisession.ErrSessionTerminal,
	):
		writeError(
			writer,
			http.StatusConflict,
			err.Error(),
		)

	case err != nil:
		writeInternalError(
			writer,
			request,
			err,
		)

	default:
		writeJSON(
			writer,
			http.StatusOK,
			result,
		)
	}
}

func (s *Server) handleConfirmAIPlan(
	writer http.ResponseWriter,
	request *http.Request,
	sessionID string,
	planID string,
) {
	ctx, cancel := contextWithTimeout(
		request,
		3*time.Minute,
	)
	defer cancel()

	result, err := s.aiSessionService.ConfirmPlan(
		ctx,
		sessionID,
		planID,
	)

	switch {
	case errors.Is(err, repository.ErrNotFound):
		writeError(
			writer,
			http.StatusNotFound,
			"session or plan not found",
		)

	case errors.Is(
		err,
		aisession.ErrInvalidSessionState,
	),
		errors.Is(
			err,
			aisession.ErrSessionTerminal,
		):

		writeError(
			writer,
			http.StatusConflict,
			err.Error(),
		)

	case err != nil:
		writeError(
			writer,
			http.StatusBadGateway,
			err.Error(),
		)

	default:
		writeJSON(
			writer,
			http.StatusAccepted,
			result,
		)
	}
}

func (s *Server) handleCancelAISession(
	writer http.ResponseWriter,
	request *http.Request,
	sessionID string,
) {
	ctx, cancel := contextWithTimeout(
		request,
		30*time.Second,
	)
	defer cancel()

	result, err := s.aiSessionService.Cancel(
		ctx,
		sessionID,
	)

	if errors.Is(err, repository.ErrNotFound) {
		writeError(
			writer,
			http.StatusNotFound,
			"AI session not found",
		)
		return
	}

	if err != nil {
		writeInternalError(
			writer,
			request,
			err,
		)
		return
	}

	writeJSON(writer, http.StatusOK, result)
}

func (s *Server) aiSessionsReady() bool {
	return s.aiSessionService != nil &&
		s.aiReady()
}
