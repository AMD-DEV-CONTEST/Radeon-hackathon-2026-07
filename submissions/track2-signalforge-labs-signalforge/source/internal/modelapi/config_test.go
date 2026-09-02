package modelapi

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestLoadFromEnvIsDisabledByDefault(t *testing.T) {
	clearEnvironment(t)
	config, err := LoadFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	if config.Enabled {
		t.Fatal("specialist API must be opt-in")
	}
}

func TestLoadFromEnvReadsMountedSecretFile(t *testing.T) {
	clearEnvironment(t)
	secretPath := filepath.Join(t.TempDir(), "api-key")
	if err := os.WriteFile(secretPath, []byte("mounted-secret\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv(envEnabled, "true")
	t.Setenv(envBaseURL, "https://radeon.example/api/v1")
	t.Setenv(envAPIKeyFile, secretPath)
	t.Setenv(envTextModel, "DeepSeek-V4-Flash")
	t.Setenv(envVisionModel, "Qwen3.6-35B-A3B")
	t.Setenv(envTimeout, "45s")

	config, err := LoadFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	if !config.Enabled || config.Provider != ProviderRadeonVLLM ||
		config.APIKey != "mounted-secret" || config.Timeout != 45*time.Second {
		t.Fatalf("unexpected config: %+v", config)
	}
}

func TestLoadFromEnvRejectsSecretAmbiguityAndInsecureRemoteURL(t *testing.T) {
	clearEnvironment(t)
	secretPath := filepath.Join(t.TempDir(), "api-key")
	if err := os.WriteFile(secretPath, []byte("mounted-secret"), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv(envEnabled, "true")
	t.Setenv(envBaseURL, "https://radeon.example/api/v1")
	t.Setenv(envAPIKey, "environment-secret")
	t.Setenv(envAPIKeyFile, secretPath)
	t.Setenv(envTextModel, "DeepSeek-V4-Flash")
	if _, err := LoadFromEnv(); err == nil {
		t.Fatal("ambiguous secrets must fail")
	}

	t.Setenv(envAPIKeyFile, "")
	t.Setenv(envBaseURL, "http://radeon.example/api/v1")
	if _, err := LoadFromEnv(); err == nil {
		t.Fatal("external plaintext endpoint must fail")
	}
}

func clearEnvironment(t *testing.T) {
	t.Helper()
	for _, key := range []string{
		envEnabled, envProvider, envBaseURL, envAPIKey, envAPIKeyFile,
		envTextModel, envVisionModel, envTimeout,
	} {
		t.Setenv(key, "")
	}
}
