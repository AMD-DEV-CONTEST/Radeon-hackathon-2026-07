package api

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
	posterflow "github.com/Ripped-sys/StagePoster/backend/internal/poster"
	"github.com/Ripped-sys/StagePoster/backend/internal/repository"
	"github.com/Ripped-sys/StagePoster/backend/internal/service"
)

func (s *Server) handlePosters(
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

	request.Body = http.MaxBytesReader(
		writer,
		request.Body,
		1024*1024,
	)

	var payload domain.CreatePosterRequest

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
		90*time.Second,
	)
	defer cancel()

	result, err := s.posterFlow.Create(
		ctx,
		payload,
	)

	switch {
	case errors.Is(
		err,
		posterflow.ErrInvalidPosterBrief,
	):
		writeError(
			writer,
			http.StatusBadRequest,
			err.Error(),
		)
		return

	case errors.Is(
		err,
		posterflow.ErrUnsupportedStyle,
	):
		writeError(
			writer,
			http.StatusBadRequest,
			err.Error(),
		)
		return

	// visual.referenceAssetId 指向不存在的素材：调用方的问题，不是 500。
	case errors.Is(err, repository.ErrNotFound):
		writeError(
			writer,
			http.StatusNotFound,
			"reference asset not found",
		)
		return

	// 带了参考图但这套部署没装 ControlNet 权重。明确拒绝，不静默降级。
	case errors.Is(
		err,
		service.ErrReferenceControlUnavailable,
	):
		writeError(
			writer,
			http.StatusConflict,
			err.Error(),
		)
		return

	case err != nil:
		writeInternalError(
			writer,
			request,
			err,
		)
		return
	}

	writeJSON(
		writer,
		http.StatusAccepted,
		result,
	)
}

func (s *Server) handlePosterRoute(
	writer http.ResponseWriter,
	request *http.Request,
) {
	path := strings.TrimPrefix(
		request.URL.Path,
		"/api/posters/",
	)

	segments := strings.Split(
		strings.Trim(path, "/"),
		"/",
	)

	if len(segments) == 0 ||
		segments[0] == "" {
		writeError(
			writer,
			http.StatusBadRequest,
			"poster id is required",
		)
		return
	}

	posterID := segments[0]

	switch {
	case len(segments) == 1 &&
		request.Method == http.MethodGet:
		s.handlePosterGet(
			writer,
			request,
			posterID,
		)

	case len(segments) == 2 &&
		segments[1] == "result" &&
		request.Method == http.MethodGet:
		s.handlePosterResult(
			writer,
			request,
			posterID,
		)

	case len(segments) == 2 &&
		segments[1] == "thumbnail" &&
		request.Method == http.MethodGet:
		s.handlePosterThumbnail(
			writer,
			request,
			posterID,
		)

	case len(segments) == 2 &&
		segments[1] == "select" &&
		request.Method == http.MethodPost:
		s.handlePosterSelect(
			writer,
			request,
			posterID,
		)

	case len(segments) == 4 &&
		segments[1] == "candidates" &&
		segments[3] == "image" &&
		request.Method == http.MethodGet:
		s.handleCandidateImage(
			writer,
			request,
			posterID,
			segments[2],
		)
	case len(segments) == 2 &&
		segments[1] == "review" &&
		request.Method == http.MethodPost:

		s.handlePosterReview(
			writer,
			request,
			posterID,
		)

	case len(segments) == 2 &&
		segments[1] == "reviews" &&
		request.Method == http.MethodGet:

		s.handlePosterReviews(
			writer,
			request,
			posterID,
		)

	case len(segments) == 2 &&
		segments[1] == "timeline" &&
		request.Method == http.MethodGet:

		s.handlePosterTimeline(
			writer,
			request,
			posterID,
		)

	case len(segments) == 2 &&
		segments[1] == "cancel" &&
		request.Method == http.MethodPost:

		s.handlePosterCancel(
			writer,
			request,
			posterID,
		)

	case len(segments) == 4 &&
		segments[1] == "candidates" &&
		segments[3] == "retry" &&
		request.Method == http.MethodPost:

		s.handleCandidateRetry(
			writer,
			request,
			posterID,
			segments[2],
		)

	default:
		writeError(
			writer,
			http.StatusNotFound,
			"poster route not found",
		)
	}
}

func (s *Server) handlePosterGet(
	writer http.ResponseWriter,
	request *http.Request,
	posterID string,
) {
	ctx, cancel := contextWithTimeout(
		request,
		60*time.Second,
	)
	defer cancel()

	result, err := s.posterFlow.Get(
		ctx,
		posterID,
	)

	if errors.Is(err, repository.ErrNotFound) {
		writeError(
			writer,
			http.StatusNotFound,
			"poster not found",
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

func (s *Server) handlePosterSelect(
	writer http.ResponseWriter,
	request *http.Request,
	posterID string,
) {
	var payload domain.SelectCandidateRequest

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

	result, err := s.posterFlow.Select(
		ctx,
		posterID,
		payload.CandidateID,
	)

	switch {
	case errors.Is(err, repository.ErrNotFound):
		writeError(
			writer,
			http.StatusNotFound,
			"poster or candidate not found",
		)
		return

	case errors.Is(
		err,
		posterflow.ErrCandidateNotReady,
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

	writeJSON(writer, http.StatusOK, result)
}

func (s *Server) handleCandidateImage(
	writer http.ResponseWriter,
	request *http.Request,
	posterID string,
	candidateID string,
) {
	ctx, cancel := contextWithTimeout(
		request,
		60*time.Second,
	)
	defer cancel()

	result, err := s.posterFlow.OpenCandidate(
		ctx,
		posterID,
		candidateID,
	)

	switch {
	case errors.Is(err, repository.ErrNotFound):
		writeError(
			writer,
			http.StatusNotFound,
			"candidate not found",
		)
		return

	case errors.Is(
		err,
		posterflow.ErrCandidateNotReady,
	):
		writeError(
			writer,
			http.StatusConflict,
			err.Error(),
		)
		return

	case err != nil:
		writeInternalError(
			writer,
			request,
			err,
		)
		return
	}

	defer result.Body.Close()

	if result.ContentType != "" {
		writer.Header().Set(
			"Content-Type",
			result.ContentType,
		)
	}

	writer.Header().Set(
		"Cache-Control",
		"private, max-age=3600",
	)

	writer.WriteHeader(http.StatusOK)
	_, _ = io.Copy(writer, result.Body)
}

func (s *Server) handlePosterResult(
	writer http.ResponseWriter,
	request *http.Request,
	posterID string,
) {
	s.servePosterFile(
		writer,
		request,
		posterID,
		s.posterFlow.OpenFinalResult,
		"poster result not found",
	)
}

func (s *Server) handlePosterThumbnail(
	writer http.ResponseWriter,
	request *http.Request,
	posterID string,
) {
	s.servePosterFile(
		writer,
		request,
		posterID,
		s.posterFlow.OpenThumbnail,
		"poster thumbnail not found",
	)
}

func (s *Server) servePosterFile(
	writer http.ResponseWriter,
	request *http.Request,
	posterID string,
	open func(
		context.Context,
		string,
	) (posterflow.ComposedFile, error),
	notFoundMessage string,
) {
	ctx, cancel := contextWithTimeout(
		request,
		60*time.Second,
	)
	defer cancel()

	result, err := open(
		ctx,
		posterID,
	)

	switch {
	case errors.Is(
		err,
		posterflow.ErrResultNotReady,
	):
		writeError(
			writer,
			http.StatusConflict,
			err.Error(),
		)
		return

	case errors.Is(err, repository.ErrNotFound):
		writeError(
			writer,
			http.StatusNotFound,
			notFoundMessage,
		)
		return

	// 记录还在但磁盘上的文件没了。对客户端来说和记录不存在是一回事，都是 404。
	case errors.Is(err, posterflow.ErrOutputMissing):
		writeError(
			writer,
			http.StatusNotFound,
			notFoundMessage,
		)
		return

	case err != nil:
		writeInternalError(
			writer,
			request,
			err,
		)
		return
	}

	defer result.Body.Close()

	writer.Header().Set(
		"Content-Type",
		result.ContentType,
	)
	writer.Header().Set(
		"Cache-Control",
		"private, max-age=3600",
	)

	writer.WriteHeader(http.StatusOK)
	_, _ = io.Copy(writer, result.Body)
}

func (s *Server) handlePosterCancel(
	writer http.ResponseWriter,
	request *http.Request,
	posterID string,
) {
	ctx, cancel := contextWithTimeout(
		request,
		30*time.Second,
	)
	defer cancel()

	err := s.posterFlow.Cancel(ctx, posterID)

	switch {
	case errors.Is(err, repository.ErrNotFound):
		writeError(
			writer,
			http.StatusNotFound,
			"poster not found",
		)
		return

	case err != nil:
		writeInternalError(
			writer,
			request,
			err,
		)
		return
	}

	// Cancel 对 succeeded / failed / canceled 是无操作的，所以不能写死
	// "canceled"——那会让一张已经成功的海报在响应里显示成已取消。
	status := domain.PosterStatusCanceled

	if response, err := s.posterFlow.Get(
		ctx,
		posterID,
	); err == nil {
		status = response.Status
	}

	writeJSON(writer, http.StatusOK, map[string]any{
		"posterId": posterID,
		"status":   status,
	})
}

func (s *Server) handleCandidateRetry(
	writer http.ResponseWriter,
	request *http.Request,
	posterID string,
	candidateID string,
) {
	ctx, cancel := contextWithTimeout(
		request,
		60*time.Second,
	)
	defer cancel()

	result, err := s.posterFlow.RetryCandidate(
		ctx,
		posterID,
		candidateID,
	)

	switch {
	case errors.Is(err, repository.ErrNotFound):
		writeError(
			writer,
			http.StatusNotFound,
			"poster or candidate not found",
		)
		return

	case errors.Is(err, posterflow.ErrCandidateNotReady):
		writeError(
			writer,
			http.StatusConflict,
			err.Error(),
		)
		return

	case errors.Is(err, posterflow.ErrPosterNotSelectable):
		writeError(
			writer,
			http.StatusConflict,
			err.Error(),
		)
		return

	case err != nil:
		writeInternalError(
			writer,
			request,
			err,
		)
		return
	}

	writeJSON(writer, http.StatusOK, result)
}
