package modelapi

import (
	"errors"
	"fmt"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

const (
	ProviderRadeonVLLM = "radeon-vllm"

	envEnabled     = "SIGNALFORGE_SPECIALIST_API_ENABLED"
	envProvider    = "SIGNALFORGE_SPECIALIST_API_PROVIDER"
	envBaseURL     = "SIGNALFORGE_SPECIALIST_API_BASE_URL"
	envAPIKey      = "SIGNALFORGE_SPECIALIST_API_KEY"
	envAPIKeyFile  = "SIGNALFORGE_SPECIALIST_API_KEY_FILE"
	envTextModel   = "SIGNALFORGE_SPECIALIST_TEXT_MODEL"
	envVisionModel = "SIGNALFORGE_SPECIALIST_VISION_MODEL"
	envTimeout     = "SIGNALFORGE_SPECIALIST_API_TIMEOUT"
)

type Config struct {
	Enabled     bool
	Provider    string
	BaseURL     string
	APIKey      string
	TextModel   string
	VisionModel string
	Timeout     time.Duration
}

func LoadFromEnv() (Config, error) {
	enabled, err := parseEnabled(os.Getenv(envEnabled))
	if err != nil {
		return Config{}, err
	}
	if !enabled {
		return Config{}, nil
	}

	key, err := loadSecret(os.Getenv(envAPIKey), os.Getenv(envAPIKeyFile))
	if err != nil {
		return Config{}, err
	}
	timeout := 90 * time.Second
	if raw := strings.TrimSpace(os.Getenv(envTimeout)); raw != "" {
		timeout, err = time.ParseDuration(raw)
		if err != nil || timeout <= 0 {
			return Config{}, fmt.Errorf("%s must be a positive duration", envTimeout)
		}
	}
	config := Config{
		Enabled: true, Provider: strings.TrimSpace(os.Getenv(envProvider)),
		BaseURL: strings.TrimRight(strings.TrimSpace(os.Getenv(envBaseURL)), "/"),
		APIKey:  key, TextModel: strings.TrimSpace(os.Getenv(envTextModel)),
		VisionModel: strings.TrimSpace(os.Getenv(envVisionModel)), Timeout: timeout,
	}
	if config.Provider == "" {
		config.Provider = ProviderRadeonVLLM
	}
	if err := config.Validate(); err != nil {
		return Config{}, err
	}
	return config, nil
}

func (config Config) Validate() error {
	if !config.Enabled {
		return nil
	}
	if config.Provider != ProviderRadeonVLLM {
		return fmt.Errorf("unsupported specialist API provider %q", config.Provider)
	}
	if config.BaseURL == "" || config.APIKey == "" || config.TextModel == "" {
		return errors.New("enabled specialist API requires base URL, API key, and text model")
	}
	parsed, err := url.Parse(config.BaseURL)
	if err != nil || parsed.Hostname() == "" {
		return errors.New("specialist API base URL is invalid")
	}
	if parsed.Scheme != "https" && !isLoopback(parsed.Hostname()) {
		return errors.New("external specialist API base URL must use HTTPS")
	}
	if config.Timeout <= 0 {
		return errors.New("specialist API timeout must be positive")
	}
	return nil
}

func parseEnabled(raw string) (bool, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return false, nil
	}
	value, err := strconv.ParseBool(raw)
	if err != nil {
		return false, fmt.Errorf("%s must be true or false", envEnabled)
	}
	return value, nil
}

func loadSecret(value, path string) (string, error) {
	value, path = strings.TrimSpace(value), strings.TrimSpace(path)
	if value != "" && path != "" {
		return "", fmt.Errorf("set only one of %s or %s", envAPIKey, envAPIKeyFile)
	}
	if path == "" {
		if value == "" {
			return "", errors.New("specialist API key is required")
		}
		return value, nil
	}
	clean := filepath.Clean(path)
	payload, err := os.ReadFile(clean)
	if err != nil {
		return "", fmt.Errorf("read specialist API key file: %w", err)
	}
	key := strings.TrimSpace(string(payload))
	if key == "" {
		return "", errors.New("specialist API key file is empty")
	}
	return key, nil
}

func isLoopback(host string) bool {
	if strings.EqualFold(host, "localhost") {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}
