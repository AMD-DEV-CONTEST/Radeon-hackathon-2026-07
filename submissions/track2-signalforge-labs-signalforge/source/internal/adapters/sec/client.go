package sec

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/rvbernucci/signalforge/internal/data"
)

const (
	DefaultBaseURL = "https://data.sec.gov"
	maxBodyBytes   = 32 << 20
)

type RawDocument struct {
	SourceURI   string    `json:"source_uri"`
	Content     []byte    `json:"content"`
	ContentSHA  string    `json:"content_sha256"`
	RetrievedAt time.Time `json:"retrieved_at"`
}

type Client struct {
	baseURL    *url.URL
	archiveURL *url.URL
	userAgent  string
	http       *http.Client
	interval   time.Duration
	clock      func() time.Time

	mu       sync.Mutex
	lastCall time.Time
}

func NewClient(baseURL, userAgent string, httpClient *http.Client) (*Client, error) {
	if strings.TrimSpace(baseURL) == "" {
		baseURL = DefaultBaseURL
	}
	parsed, err := url.Parse(baseURL)
	if err != nil || parsed.Scheme == "" || parsed.Host == "" {
		return nil, errors.New("valid SEC base URL is required")
	}
	if parsed.Scheme != "https" && parsed.Hostname() != "127.0.0.1" && parsed.Hostname() != "localhost" {
		return nil, errors.New("SEC base URL must use HTTPS")
	}
	archiveURL := parsed
	if parsed.Hostname() == "data.sec.gov" {
		archiveURL, _ = url.Parse("https://www.sec.gov")
	}
	if strings.TrimSpace(userAgent) == "" {
		return nil, errors.New("descriptive SEC user agent is required")
	}
	if httpClient == nil {
		httpClient = &http.Client{Timeout: 30 * time.Second}
	}
	return &Client{
		baseURL: parsed, archiveURL: archiveURL, userAgent: userAgent, http: httpClient,
		interval: 200 * time.Millisecond, clock: time.Now,
	}, nil
}

func (client *Client) CompanySubmissions(ctx context.Context, cik string) (RawDocument, error) {
	canonical, err := data.CanonicalCIK(cik)
	if err != nil {
		return RawDocument{}, err
	}
	return client.get(ctx, "/submissions/CIK"+canonical+".json")
}

func (client *Client) CompanyFacts(ctx context.Context, cik string) (RawDocument, error) {
	canonical, err := data.CanonicalCIK(cik)
	if err != nil {
		return RawDocument{}, err
	}
	return client.get(ctx, "/api/xbrl/companyfacts/CIK"+canonical+".json")
}

func (client *Client) HistoricalSubmissions(ctx context.Context, filename string) (RawDocument, error) {
	filename = strings.TrimSpace(filename)
	if filename == "" || strings.Contains(filename, "/") || strings.Contains(filename, "\\") || !strings.HasSuffix(filename, ".json") {
		return RawDocument{}, errors.New("valid SEC historical submissions filename is required")
	}
	return client.get(ctx, "/submissions/"+filename)
}

func (client *Client) FilingDocument(ctx context.Context, cik, accession, primaryDocument string) (RawDocument, error) {
	canonical, err := data.CanonicalCIK(cik)
	if err != nil {
		return RawDocument{}, err
	}
	if !validAccession(accession) {
		return RawDocument{}, errors.New("canonical SEC accession is required")
	}
	primaryDocument = strings.TrimSpace(primaryDocument)
	if primaryDocument == "" || strings.Contains(primaryDocument, "/") || strings.Contains(primaryDocument, "\\") {
		return RawDocument{}, errors.New("safe primary document filename is required")
	}
	path := fmt.Sprintf("/Archives/edgar/data/%s/%s/%s", strings.TrimLeft(canonical, "0"), strings.ReplaceAll(accession, "-", ""), primaryDocument)
	return client.getFrom(ctx, client.archiveURL, path, "text/html,application/xhtml+xml,text/plain")
}

func (client *Client) get(ctx context.Context, path string) (RawDocument, error) {
	return client.getFrom(ctx, client.baseURL, path, "application/json")
}

func (client *Client) getFrom(ctx context.Context, base *url.URL, path, accept string) (RawDocument, error) {
	if err := client.wait(ctx); err != nil {
		return RawDocument{}, err
	}
	endpoint := base.ResolveReference(&url.URL{Path: path})
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint.String(), nil)
	if err != nil {
		return RawDocument{}, err
	}
	request.Header.Set("User-Agent", client.userAgent)
	request.Header.Set("Accept", accept)
	request.Header.Set("Accept-Encoding", "identity")

	response, err := client.http.Do(request)
	if err != nil {
		return RawDocument{}, fmt.Errorf("SEC request: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, 4096))
		return RawDocument{}, fmt.Errorf("SEC request returned %s", response.Status)
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, maxBodyBytes+1))
	if err != nil {
		return RawDocument{}, fmt.Errorf("read SEC response: %w", err)
	}
	if len(body) > maxBodyBytes {
		return RawDocument{}, errors.New("SEC response exceeds safety limit")
	}
	digest := sha256.Sum256(body)
	return RawDocument{
		SourceURI: endpoint.String(), Content: body, ContentSHA: hex.EncodeToString(digest[:]),
		RetrievedAt: client.clock().UTC(),
	}, nil
}

func validAccession(value string) bool {
	if len(value) != 20 || value[10] != '-' || value[13] != '-' {
		return false
	}
	for index, character := range value {
		if index == 10 || index == 13 {
			continue
		}
		if character < '0' || character > '9' {
			return false
		}
	}
	return true
}

func (client *Client) wait(ctx context.Context) error {
	client.mu.Lock()
	defer client.mu.Unlock()
	now := client.clock()
	wait := client.lastCall.Add(client.interval).Sub(now)
	if wait > 0 {
		timer := time.NewTimer(wait)
		defer timer.Stop()
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-timer.C:
		}
	}
	client.lastCall = client.clock()
	return nil
}
