package api

import (
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/ai"
)

type AIConfig struct {
	Client  *ai.Client
	Service *ai.Service
	Runtime *ai.Runtime

	URL   string
	Model string
}

func NewAIConfigFromEnv() AIConfig {
	vlmURL := envOrDefault(
		"VLM_URL",
		"http://127.0.0.1:8001",
	)

	apiKey := envOrDefault(
		"VLM_API_KEY",
		"stageposter-vlm-local",
	)

	model := envOrDefault(
		"VLM_MODEL",
		"stageposter-vlm",
	)

	timeout := 4 * time.Minute

	if rawTimeout := strings.TrimSpace(
		os.Getenv("VLM_REQUEST_TIMEOUT"),
	); rawTimeout != "" {
		if parsed, err := time.ParseDuration(
			rawTimeout,
		); err == nil {
			timeout = parsed
		}
	}

	autoSleep := true

	if raw := strings.TrimSpace(
		os.Getenv("VLM_AUTO_SLEEP"),
	); raw != "" {
		if parsed, err := strconv.ParseBool(raw); err == nil {
			autoSleep = parsed
		}
	}

	client := ai.NewClient(
		vlmURL,
		apiKey,
		model,
		timeout,
	)

	service := ai.NewService(client)

	return AIConfig{
		Client:  client,
		Service: service,
		Runtime: ai.NewRuntime(
			client,
			autoSleep,
		),
		URL:   vlmURL,
		Model: model,
	}
}

func (s *Server) WithAI(
	config AIConfig,
) *Server {
	s.aiClient = config.Client
	s.aiService = config.Service
	s.aiRuntime = config.Runtime
	s.aiURL = config.URL
	s.aiModel = config.Model

	return s
}

func envOrDefault(
	key string,
	fallback string,
) string {
	value := strings.TrimSpace(
		os.Getenv(key),
	)

	if value == "" {
		return fallback
	}

	return value
}
