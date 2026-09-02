package api

import (
	"context"
	"errors"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
	"github.com/Ripped-sys/StagePoster/backend/internal/repository"
	"github.com/Ripped-sys/StagePoster/backend/internal/service"
	"github.com/Ripped-sys/StagePoster/backend/internal/storage"
)

func (s *Server) handleAssets(
	writer http.ResponseWriter,
	request *http.Request,
) {
	switch request.Method {
	case http.MethodPost:
		s.handleAssetUpload(writer, request)

	case http.MethodGet:
		s.handleAssetList(writer, request)

	default:
		writeError(
			writer,
			http.StatusMethodNotAllowed,
			"method not allowed",
		)
	}
}

func (s *Server) handleAsset(
	writer http.ResponseWriter,
	request *http.Request,
) {
	if request.Method != http.MethodGet {
		writeError(
			writer,
			http.StatusMethodNotAllowed,
			"method not allowed",
		)
		return
	}

	path := strings.TrimPrefix(
		request.URL.Path,
		"/api/assets/",
	)

	path = strings.Trim(path, "/")

	if path == "" {
		writeError(
			writer,
			http.StatusBadRequest,
			"asset id is required",
		)
		return
	}

	if strings.HasSuffix(path, "/content") {
		assetID := strings.TrimSuffix(path, "/content")
		assetID = strings.Trim(assetID, "/")

		s.handleAssetContent(
			writer,
			request,
			assetID,
		)
		return
	}

	if strings.HasSuffix(path, "/process") {
		assetID := strings.TrimSuffix(path, "/process")
		assetID = strings.Trim(assetID, "/")

		s.handleAssetProcess(
			writer,
			request,
			assetID,
		)
		return
	}

	if strings.Contains(path, "/") {
		writeError(
			writer,
			http.StatusNotFound,
			"asset route not found",
		)
		return
	}

	s.handleAssetMetadata(writer, request, path)
}

func (s *Server) handleAssetUpload(
	writer http.ResponseWriter,
	request *http.Request,
) {
	request.Body = http.MaxBytesReader(
		writer,
		request.Body,
		25<<20,
	)

	if err := request.ParseMultipartForm(8 << 20); err != nil {
		writeError(
			writer,
			http.StatusBadRequest,
			"invalid multipart upload: "+err.Error(),
		)
		return
	}

	if request.MultipartForm != nil {
		defer request.MultipartForm.RemoveAll()
	}

	file, header, err := request.FormFile("file")
	if err != nil {
		writeError(
			writer,
			http.StatusBadRequest,
			"file field is required",
		)
		return
	}
	defer file.Close()

	kind := request.FormValue("kind")

	ctx, cancel := contextWithTimeout(
		request,
		60*time.Second,
	)
	defer cancel()

	result, err := s.assetService.Upload(
		ctx,
		kind,
		header.Filename,
		file,
	)

	switch {
	case errors.Is(err, service.ErrInvalidAssetKind):
		writeError(
			writer,
			http.StatusBadRequest,
			"kind must be person, logo, or reference",
		)
		return

	case errors.Is(err, storage.ErrAssetTooLarge):
		writeError(
			writer,
			http.StatusRequestEntityTooLarge,
			"asset exceeds the 20 MB limit",
		)
		return

	case errors.Is(err, storage.ErrUnsupportedAssetType):
		writeError(
			writer,
			http.StatusUnsupportedMediaType,
			"only PNG and JPEG assets are supported",
		)
		return

	case errors.Is(err, storage.ErrEmptyAsset):
		writeError(
			writer,
			http.StatusBadRequest,
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

	// Enqueue async processing for the uploaded asset.
	if s.assetProcessor != nil {
		go func(assetID string, assetKind string) {
			processCtx := context.Background()
			_ = s.assetProcessor.Enqueue(
				processCtx,
				assetID,
				domain.AssetKind(assetKind),
			)
		}(result.ID, kind)
	}

	writeJSON(writer, http.StatusCreated, result)
}

func (s *Server) handleAssetList(
	writer http.ResponseWriter,
	request *http.Request,
) {
	page, ok := parsePage(writer, request)
	if !ok {
		return
	}

	ctx, cancel := contextWithTimeout(
		request,
		20*time.Second,
	)
	defer cancel()

	result, err := s.assetService.List(ctx, page)
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

func (s *Server) handleAssetMetadata(
	writer http.ResponseWriter,
	request *http.Request,
	assetID string,
) {
	ctx, cancel := contextWithTimeout(
		request,
		20*time.Second,
	)
	defer cancel()

	result, err := s.assetService.Get(ctx, assetID)

	if errors.Is(err, repository.ErrNotFound) {
		writeError(
			writer,
			http.StatusNotFound,
			"asset not found",
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

func (s *Server) handleAssetContent(
	writer http.ResponseWriter,
	request *http.Request,
	assetID string,
) {
	ctx, cancel := contextWithTimeout(
		request,
		60*time.Second,
	)
	defer cancel()

	result, err := s.assetService.OpenContent(ctx, assetID)

	if errors.Is(err, repository.ErrNotFound) {
		writeError(
			writer,
			http.StatusNotFound,
			"asset not found",
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

func (s *Server) handleAssetProcess(
	writer http.ResponseWriter,
	request *http.Request,
	assetID string,
) {
	ctx, cancel := contextWithTimeout(
		request,
		20*time.Second,
	)
	defer cancel()

	result, err := s.assetService.Get(ctx, assetID)

	if errors.Is(err, repository.ErrNotFound) {
		writeError(
			writer,
			http.StatusNotFound,
			"asset not found",
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

	steps := make([]domain.ProcessingStep, 0)

	switch result.Kind {
	case domain.AssetKindLogo, domain.AssetKindPerson:
		// 这两步以前都直接复用笼统的 ProcessStatus，于是一张不透明的 JPEG
		// logo 也会显示 background_removal=completed。实际上没有接任何背景
		// 去除模型，这一步从来没跑过。
		steps = append(steps, domain.ProcessingStep{
			Name:   "background_removal",
			Status: domain.ProcessingStepStatusSkipped,
			Error:  "no background removal model is wired; upload a transparent PNG",
		}, domain.ProcessingStep{
			Name: "alpha_inspection",
			Status: cutoutStepStatus(
				result.Cutout.Status,
			),
		})

	case domain.AssetKindReference:
		steps = append(steps, domain.ProcessingStep{
			Name:   "color_analysis",
			Status: processingStepStatus(result.ProcessStatus),
		}, domain.ProcessingStep{
			Name:   "composition_analysis",
			Status: processingStepStatus(result.ProcessStatus),
		})
	}

	writeJSON(writer, http.StatusOK, map[string]any{
		"assetId":        result.ID,
		"processStatus":  result.ProcessStatus,
		"processError":   result.ProcessError,
		"processedAt":    result.ProcessedAt,
		"maskPath":       result.MaskPath,
		"cutout":         result.Cutout,
		"analysisJson":   result.AnalysisJSON,
		"dominantColors": result.DominantColors,
		"processVersion": result.ProcessVersion,
		"steps":          steps,
	})
}

func processingStepStatus(
	assetStatus domain.AssetProcessStatus,
) domain.ProcessingStepStatus {
	switch assetStatus {
	case domain.AssetProcessStatusProcessing:
		return domain.ProcessingStepStatusProcessing
	case domain.AssetProcessStatusReady:
		return domain.ProcessingStepStatusCompleted
	case domain.AssetProcessStatusFailed:
		return domain.ProcessingStepStatusFailed
	default:
		return domain.ProcessingStepStatusPending
	}
}

// cutoutStepStatus 把抠图状态映射成处理步骤状态。
// unsupported 是 skipped 而不是 completed —— 没跑过的步骤不该显示成成功。
func cutoutStepStatus(
	status domain.AssetCutoutStatus,
) domain.ProcessingStepStatus {
	switch status {
	case domain.AssetCutoutStatusReady,
		domain.AssetCutoutStatusOpaque:
		return domain.ProcessingStepStatusCompleted

	case domain.AssetCutoutStatusFailed:
		return domain.ProcessingStepStatusFailed

	// 排队中和"不会跑"必须分开：pending 的素材再查一次就有结果了。
	case domain.AssetCutoutStatusPending:
		return domain.ProcessingStepStatusPending

	default:
		return domain.ProcessingStepStatusSkipped
	}
}
