package comfy

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestClientFreeMemory(t *testing.T) {
	t.Parallel()

	server := httptest.NewServer(
		http.HandlerFunc(
			func(
				writer http.ResponseWriter,
				request *http.Request,
			) {
				if request.Method != http.MethodPost {
					t.Fatalf(
						"method = %s, want POST",
						request.Method,
					)
				}

				if request.URL.Path != "/free" {
					t.Fatalf(
						"path = %s, want /free",
						request.URL.Path,
					)
				}

				var payload map[string]bool

				if err := json.NewDecoder(
					request.Body,
				).Decode(&payload); err != nil {
					t.Fatalf(
						"decode payload: %v",
						err,
					)
				}

				if !payload["unload_models"] {
					t.Fatal(
						"unload_models is false",
					)
				}

				if !payload["free_memory"] {
					t.Fatal(
						"free_memory is false",
					)
				}

				writer.WriteHeader(http.StatusOK)
			},
		),
	)
	defer server.Close()

	client := NewClient(server.URL)

	if err := client.FreeMemory(
		context.Background(),
	); err != nil {
		t.Fatalf(
			"FreeMemory error: %v",
			err,
		)
	}
}

func TestClientFreeMemoryRejectsFailure(t *testing.T) {
	t.Parallel()

	server := httptest.NewServer(
		http.HandlerFunc(
			func(
				writer http.ResponseWriter,
				request *http.Request,
			) {
				http.Error(
					writer,
					"allocator busy",
					http.StatusInternalServerError,
				)
			},
		),
	)
	defer server.Close()

	client := NewClient(server.URL)

	if err := client.FreeMemory(
		context.Background(),
	); err == nil {
		t.Fatal(
			"FreeMemory returned nil for HTTP 500",
		)
	}
}
