package fred

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestObservationsPreserveVintageAndRedactKey(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/fred/series/observations" || request.URL.Query().Get("series_id") != "DFF" {
			t.Errorf("unexpected request %s", request.URL.String())
		}
		if request.URL.Query().Get("api_key") != "test-secret" {
			t.Error("runtime key missing")
		}
		_, _ = response.Write([]byte(`{"units":"lin","observations":[{"realtime_start":"2025-01-02","realtime_end":"2025-01-02","date":"2025-01-01","value":"4.33"},{"realtime_start":"2025-01-02","realtime_end":"2025-01-02","date":"2025-01-02","value":"."}]}`))
	}))
	defer server.Close()
	client, err := NewClient(server.URL, "test-secret", server.Client())
	if err != nil {
		t.Fatal(err)
	}
	client.clock = func() time.Time { return time.Date(2025, 1, 3, 0, 0, 0, 0, time.UTC) }
	values, err := client.Observations(context.Background(), "DFF", time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC), time.Date(2025, 1, 2, 0, 0, 0, 0, time.UTC), time.Date(2025, 1, 2, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	if len(values) != 1 || values[0].Value != "4.33" || strings.Contains(values[0].SourceURI, "test-secret") {
		t.Fatalf("unexpected observations: %#v", values)
	}
}

func TestClientRequiresKeyAndHTTPS(t *testing.T) {
	if _, err := NewClient(DefaultBaseURL, "", nil); err == nil {
		t.Fatal("missing key must fail")
	}
	if _, err := NewClient("http://example.com", "key", nil); err == nil {
		t.Fatal("insecure remote URL must fail")
	}
}
