package api

import (
	"crypto/subtle"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/ai"
	aisession "github.com/Ripped-sys/StagePoster/backend/internal/assistant"
	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
	posterflow "github.com/Ripped-sys/StagePoster/backend/internal/poster"
	"github.com/Ripped-sys/StagePoster/backend/internal/repository"
	"github.com/Ripped-sys/StagePoster/backend/internal/service"
	"github.com/Ripped-sys/StagePoster/backend/internal/storage"
)

type Server struct {
	service      *service.PosterService
	assetService *service.AssetService
	posterFlow   *posterflow.Service

	aiSessionService *aisession.Service

	aiClient  *ai.Client
	aiService *ai.Service
	aiRuntime *ai.Runtime
	aiURL     string
	aiModel   string

	apiToken        string
	corsOrigin      string
	assetProcessor  *service.AssetProcessor
	healthCollector *service.HealthCollector
}

func NewServer(
	posterService *service.PosterService,
	assetService *service.AssetService,
	posterFlow *posterflow.Service,
	apiToken string,
	corsOrigin string,
) *Server {
	if corsOrigin == "" {
		corsOrigin = "*"
	}

	return &Server{
		service:      posterService,
		assetService: assetService,
		posterFlow:   posterFlow,
		apiToken:     apiToken,
		corsOrigin:   corsOrigin,
	}
}

func (s *Server) WithAssetProcessor(
	processor *service.AssetProcessor,
) *Server {
	s.assetProcessor = processor
	return s
}

func (s *Server) WithHealthCollector(
	collector *service.HealthCollector,
) *Server {
	s.healthCollector = collector
	return s
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("/health", s.handleHealth)
	mux.HandleFunc(
		"/api/ai/design",
		s.handleAIDesign,
	)

	mux.HandleFunc(
		"/api/system/dependencies",
		s.handleDependencies,
	)
	mux.HandleFunc(
		"/api/ai/sessions",
		s.handleAISessions,
	)
	mux.HandleFunc(
		"/api/ai/sessions/",
		s.handleAISessionRoute,
	)

	mux.HandleFunc("/api/generate", s.handleGenerate)
	mux.HandleFunc("/api/posters", s.handlePosters)
	mux.HandleFunc("/api/posters/", s.handlePosterRoute)
	mux.HandleFunc("/api/assets", s.handleAssets)
	mux.HandleFunc("/api/assets/", s.handleAsset)
	mux.HandleFunc("/api/jobs", s.handleJobList)
	mux.HandleFunc("/api/jobs/", s.handleJobs)

	return s.cors(s.auth(mux))
}

func (s *Server) handleHealth(
	writer http.ResponseWriter,
	request *http.Request,
) {
	if request.Method != http.MethodGet {
		writeError(writer, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	ctx, cancel := contextWithTimeout(request, 10*time.Second)
	defer cancel()

	if err := s.service.Health(ctx); err != nil {
		writeJSON(
			writer,
			http.StatusServiceUnavailable,
			map[string]any{
				"status": "degraded",
				"error":  err.Error(),
			},
		)
		return
	}

	if s.healthCollector != nil {
		info := s.healthCollector.Collect(ctx)
		info.TokenRequired = s.apiToken != ""
		writeJSON(writer, http.StatusOK, info)
		return
	}

	writeJSON(
		writer,
		http.StatusOK,
		map[string]any{
			"status":        "ok",
			"comfy":         "connected",
			"database":      "connected",
			"bindings":      s.service.Bindings(),
			"tokenRequired": s.apiToken != "",
		},
	)
}

func (s *Server) handleGenerate(
	writer http.ResponseWriter,
	request *http.Request,
) {
	if request.Method != http.MethodPost {
		writeError(writer, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	request.Body = http.MaxBytesReader(
		writer,
		request.Body,
		1024*1024,
	)

	var payload domain.GenerateRequest

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

	ctx, cancel := contextWithTimeout(request, 70*time.Second)
	defer cancel()

	result, err := s.service.Generate(ctx, payload)
	if errors.Is(err, service.ErrPromptRequired) {
		writeError(writer, http.StatusBadRequest, err.Error())
		return
	}

	// 参考图素材不存在是调用方的问题，不是上游故障 —— 以前落到下面的
	// 兜底分支返回 502，看起来像 ComfyUI 挂了。
	if errors.Is(err, repository.ErrNotFound) {
		writeError(
			writer,
			http.StatusNotFound,
			"reference asset not found",
		)
		return
	}

	// 这套部署没装 ControlNet 权重却收到参考图：明确拒绝，不要静默丢掉参考图
	// 然后返回一张跟它无关的图。
	if errors.Is(err, service.ErrReferenceControlUnavailable) {
		writeError(
			writer,
			http.StatusConflict,
			err.Error(),
		)
		return
	}

	if err != nil {
		writeError(writer, http.StatusBadGateway, err.Error())
		return
	}

	writeJSON(writer, http.StatusAccepted, result)
}

func (s *Server) handleJobList(
	writer http.ResponseWriter,
	request *http.Request,
) {
	if request.Method != http.MethodGet {
		writeError(writer, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	page, ok := parsePage(writer, request)
	if !ok {
		return
	}

	ctx, cancel := contextWithTimeout(request, 20*time.Second)
	defer cancel()

	result, err := s.service.ListJobs(ctx, page)
	if err != nil {
		writeInternalError(writer, request, err)
		return
	}

	writeJSON(writer, http.StatusOK, result)
}

func (s *Server) handleJobs(
	writer http.ResponseWriter,
	request *http.Request,
) {
	if request.Method != http.MethodGet {
		writeError(writer, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	path := strings.TrimPrefix(
		request.URL.Path,
		"/api/jobs/",
	)
	path = strings.Trim(path, "/")

	if path == "" {
		writeError(writer, http.StatusBadRequest, "job id is required")
		return
	}

	if strings.HasSuffix(path, "/result") {
		jobID := strings.TrimSuffix(path, "/result")
		jobID = strings.Trim(jobID, "/")

		s.handleResult(writer, request, jobID)
		return
	}

	s.handleStatus(writer, request, path)
}

func (s *Server) handleStatus(
	writer http.ResponseWriter,
	request *http.Request,
	jobID string,
) {
	ctx, cancel := contextWithTimeout(request, 30*time.Second)
	defer cancel()

	result, err := s.service.Status(ctx, jobID)
	if errors.Is(err, repository.ErrNotFound) {
		writeError(writer, http.StatusNotFound, "job not found")
		return
	}

	if err != nil {
		writeError(writer, http.StatusBadGateway, err.Error())
		return
	}

	writeJSON(writer, http.StatusOK, result)
}

func (s *Server) handleResult(
	writer http.ResponseWriter,
	request *http.Request,
	jobID string,
) {
	ctx, cancel := contextWithTimeout(request, 60*time.Second)
	defer cancel()

	result, err := s.service.OpenResult(ctx, jobID)

	switch {
	case errors.Is(err, repository.ErrNotFound):
		writeError(writer, http.StatusNotFound, "job not found")
		return

	case errors.Is(err, service.ErrResultNotReady):
		writeError(writer, http.StatusConflict, err.Error())
		return

	case errors.Is(err, service.ErrGenerationFailed):
		writeError(writer, http.StatusConflict, err.Error())
		return

	// 记录存在但文件没了，对客户端等价于不存在。
	case errors.Is(err, storage.ErrOutputMissing):
		writeError(writer, http.StatusNotFound, "job result not found")
		return

	case err != nil:
		writeInternalError(writer, request, err)
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

func (s *Server) auth(next http.Handler) http.Handler {
	return http.HandlerFunc(
		func(writer http.ResponseWriter, request *http.Request) {
			if s.apiToken == "" ||
				!strings.HasPrefix(request.URL.Path, "/api/") {
				next.ServeHTTP(writer, request)
				return
			}

			token := request.Header.Get("X-Poster-Token")

			if token == "" {
				authorization := request.Header.Get("Authorization")
				token = strings.TrimPrefix(
					authorization,
					"Bearer ",
				)
			}

			if token == "" {
				token = request.URL.Query().Get("token")
			}

			valid := subtle.ConstantTimeCompare(
				[]byte(token),
				[]byte(s.apiToken),
			) == 1

			if !valid {
				writeError(writer, http.StatusUnauthorized, "unauthorized")
				return
			}

			next.ServeHTTP(writer, request)
		},
	)
}

func (s *Server) cors(next http.Handler) http.Handler {
	return http.HandlerFunc(
		func(writer http.ResponseWriter, request *http.Request) {
			writer.Header().Set(
				"Access-Control-Allow-Origin",
				s.corsOrigin,
			)

			writer.Header().Set(
				"Access-Control-Allow-Headers",
				"Content-Type, Authorization, X-Poster-Token",
			)

			writer.Header().Set(
				"Access-Control-Allow-Methods",
				"GET, POST, OPTIONS",
			)

			if request.Method == http.MethodOptions {
				writer.WriteHeader(http.StatusNoContent)
				return
			}

			next.ServeHTTP(writer, request)
		},
	)
}

func writeJSON(
	writer http.ResponseWriter,
	status int,
	value any,
) {
	writer.Header().Set(
		"Content-Type",
		"application/json; charset=utf-8",
	)

	writer.WriteHeader(status)
	_ = json.NewEncoder(writer).Encode(value)
}

func writeError(
	writer http.ResponseWriter,
	status int,
	message string,
) {
	writeJSON(
		writer,
		status,
		map[string]any{
			"error": message,
		},
	)
}

// writeInternalError 把真实错误写日志，只给客户端一句通用说明。
// 500 分支以前统一回显 err.Error()，而文件打开失败的错误里带着服务器绝对
// 路径，等于把存储布局送给了任何一个调用方。
func writeInternalError(
	writer http.ResponseWriter,
	request *http.Request,
	err error,
) {
	log.Printf(
		"%s %s failed: %v",
		request.Method,
		request.URL.Path,
		err,
	)

	writeError(
		writer,
		http.StatusInternalServerError,
		"internal server error",
	)
}
