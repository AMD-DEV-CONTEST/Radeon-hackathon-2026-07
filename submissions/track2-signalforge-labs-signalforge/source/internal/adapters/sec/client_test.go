package sec

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestCompanySubmissionsUsesCanonicalPathAndRequiredHeaders(t *testing.T) {
	payload := []byte(`{"cik":"0000789019","name":"Microsoft Corporation"}`)
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/submissions/CIK0000789019.json" {
			t.Errorf("unexpected path %q", request.URL.Path)
		}
		if request.Header.Get("User-Agent") != "SignalForge test contact@example.com" {
			t.Errorf("missing descriptive user agent")
		}
		if request.Header.Get("Accept") != "application/json" {
			t.Errorf("missing JSON accept header")
		}
		_, _ = response.Write(payload)
	}))
	defer server.Close()

	client, err := NewClient(server.URL, "SignalForge test contact@example.com", server.Client())
	if err != nil {
		t.Fatalf("new client: %v", err)
	}
	client.interval = 0
	document, err := client.CompanySubmissions(context.Background(), "789019")
	if err != nil {
		t.Fatalf("company submissions: %v", err)
	}
	digest := sha256.Sum256(payload)
	if document.ContentSHA != hex.EncodeToString(digest[:]) {
		t.Fatalf("unexpected content hash %q", document.ContentSHA)
	}
	if document.RetrievedAt.IsZero() {
		t.Fatal("retrieval time is required")
	}
}

func TestClientRejectsMissingIdentityAndInsecureRemoteBaseURL(t *testing.T) {
	if _, err := NewClient(DefaultBaseURL, "", nil); err == nil {
		t.Fatal("missing user agent must be rejected")
	}
	if _, err := NewClient("http://example.com", "SignalForge contact@example.com", nil); err == nil {
		t.Fatal("insecure remote endpoint must be rejected")
	}
}

func TestCompanyFactsRejectsInvalidCIKBeforeNetwork(t *testing.T) {
	client, err := NewClient(DefaultBaseURL, "SignalForge contact@example.com", &http.Client{Timeout: time.Second})
	if err != nil {
		t.Fatalf("new client: %v", err)
	}
	if _, err := client.CompanyFacts(context.Background(), "not-a-cik"); err == nil {
		t.Fatal("invalid CIK must fail before request")
	}
}

func TestNonSuccessStatusDoesNotReturnDocument(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, _ *http.Request) {
		http.Error(response, "busy", http.StatusServiceUnavailable)
	}))
	defer server.Close()
	client, _ := NewClient(server.URL, "SignalForge test contact@example.com", server.Client())
	client.interval = 0
	if _, err := client.CompanyFacts(context.Background(), "1045810"); err == nil {
		t.Fatal("non-success response must fail closed")
	}
}

func TestHistoricalSubmissionsRejectsPathTraversal(t *testing.T) {
	client, err := NewClient(DefaultBaseURL, "SignalForge contact@example.com", &http.Client{Timeout: time.Second})
	if err != nil {
		t.Fatal(err)
	}
	for _, filename := range []string{"", "../secret.json", "nested/file.json", "not-json.txt"} {
		if _, err := client.HistoricalSubmissions(context.Background(), filename); err == nil {
			t.Fatalf("unsafe filename %q must fail", filename)
		}
	}
}
