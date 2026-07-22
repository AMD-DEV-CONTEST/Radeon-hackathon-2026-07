package fred

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/macro"
)

const DefaultBaseURL = "https://api.stlouisfed.org"

type Client struct {
	baseURL *url.URL
	apiKey  string
	http    *http.Client
	clock   func() time.Time
}

type Snapshot struct {
	SourceURI    string              `json:"source_uri"`
	Content      []byte              `json:"-"`
	ContentSHA   string              `json:"content_sha256"`
	RetrievedAt  time.Time           `json:"retrieved_at"`
	Observations []macro.Observation `json:"observations"`
}

type response struct {
	Units        string `json:"units"`
	Observations []struct {
		RealtimeStart string `json:"realtime_start"`
		RealtimeEnd   string `json:"realtime_end"`
		Date          string `json:"date"`
		Value         string `json:"value"`
	} `json:"observations"`
}

func NewClient(baseURL, apiKey string, httpClient *http.Client) (*Client, error) {
	if baseURL == "" {
		baseURL = DefaultBaseURL
	}
	parsed, err := url.Parse(baseURL)
	if err != nil || parsed.Scheme == "" || parsed.Host == "" {
		return nil, errors.New("valid FRED base URL is required")
	}
	if parsed.Scheme != "https" && parsed.Hostname() != "localhost" && parsed.Hostname() != "127.0.0.1" {
		return nil, errors.New("FRED base URL must use HTTPS")
	}
	if strings.TrimSpace(apiKey) == "" {
		return nil, errors.New("FRED API key is required at runtime")
	}
	if httpClient == nil {
		httpClient = &http.Client{Timeout: 30 * time.Second}
	}
	return &Client{baseURL: parsed, apiKey: apiKey, http: httpClient, clock: time.Now}, nil
}

func (client *Client) Observations(ctx context.Context, seriesID string, start, end, vintage time.Time) ([]macro.Observation, error) {
	snapshot, err := client.Snapshot(ctx, seriesID, start, end, vintage)
	return snapshot.Observations, err
}

func (client *Client) Snapshot(ctx context.Context, seriesID string, start, end, vintage time.Time) (Snapshot, error) {
	seriesID = strings.TrimSpace(seriesID)
	if seriesID == "" || start.IsZero() || end.IsZero() || vintage.IsZero() || end.Before(start) {
		return Snapshot{}, errors.New("series, date range, and vintage are required")
	}
	endpoint := client.baseURL.ResolveReference(&url.URL{Path: "/fred/series/observations"})
	query := endpoint.Query()
	query.Set("series_id", seriesID)
	query.Set("api_key", client.apiKey)
	query.Set("file_type", "json")
	query.Set("observation_start", start.Format("2006-01-02"))
	query.Set("observation_end", end.Format("2006-01-02"))
	query.Set("realtime_start", vintage.Format("2006-01-02"))
	query.Set("realtime_end", vintage.Format("2006-01-02"))
	endpoint.RawQuery = query.Encode()
	request, _ := http.NewRequestWithContext(ctx, http.MethodGet, endpoint.String(), nil)
	responseValue, err := client.http.Do(request)
	if err != nil {
		return Snapshot{}, err
	}
	defer responseValue.Body.Close()
	if responseValue.StatusCode != http.StatusOK {
		return Snapshot{}, fmt.Errorf("FRED returned %s", responseValue.Status)
	}
	content, err := io.ReadAll(io.LimitReader(responseValue.Body, 16<<20))
	if err != nil {
		return Snapshot{}, err
	}
	var payload response
	if err := json.Unmarshal(content, &payload); err != nil {
		return Snapshot{}, err
	}
	digest := sha256.Sum256(content)
	retrieved := client.clock().UTC()
	sourceURI := endpoint.String()
	redacted := endpoint.Query()
	redacted.Set("api_key", "REDACTED")
	endpoint.RawQuery = redacted.Encode()
	sourceURI = endpoint.String()
	result := make([]macro.Observation, 0, len(payload.Observations))
	for _, item := range payload.Observations {
		if item.Value == "." {
			continue
		}
		observationDate, dateErr := time.Parse("2006-01-02", item.Date)
		realtimeStart, startErr := time.Parse("2006-01-02", item.RealtimeStart)
		realtimeEnd, endErr := time.Parse("2006-01-02", item.RealtimeEnd)
		if dateErr != nil || startErr != nil || endErr != nil {
			return Snapshot{}, errors.New("FRED returned invalid temporal metadata")
		}
		observation := macro.Observation{
			SeriesID: seriesID, ObservationDate: observationDate.UTC(), Value: item.Value,
			Unit: payload.Units, RealtimeStart: realtimeStart.UTC(), RealtimeEnd: realtimeEnd.UTC(),
			AvailableAt: realtimeStart.UTC(), RetrievedAt: retrieved, SourceURI: sourceURI,
			SourceSHA256: hex.EncodeToString(digest[:]),
		}
		if err := macro.ValidateObservation(observation); err != nil {
			return Snapshot{}, err
		}
		result = append(result, observation)
	}
	return Snapshot{
		SourceURI: sourceURI, Content: content, ContentSHA: hex.EncodeToString(digest[:]),
		RetrievedAt: retrieved, Observations: result,
	}, nil
}
