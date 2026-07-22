package alpaca

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

	"github.com/rvbernucci/signalforge/internal/market"
)

const DefaultBaseURL = "https://data.alpaca.markets"

type Client struct {
	baseURL *url.URL
	keyID   string
	secret  string
	http    *http.Client
	clock   func() time.Time
}

type Snapshot struct {
	SourceURI   string    `json:"source_uri"`
	Content     []byte    `json:"-"`
	ContentSHA  string    `json:"content_sha256"`
	RetrievedAt time.Time `json:"retrieved_at"`
}

type response struct {
	Bars []struct {
		Timestamp time.Time   `json:"t"`
		Open      json.Number `json:"o"`
		High      json.Number `json:"h"`
		Low       json.Number `json:"l"`
		Close     json.Number `json:"c"`
		Volume    json.Number `json:"v"`
		Trades    int64       `json:"n"`
		VWAP      json.Number `json:"vw"`
	} `json:"bars"`
	NextPageToken string `json:"next_page_token"`
}

func NewClient(baseURL, keyID, secret string, httpClient *http.Client) (*Client, error) {
	if baseURL == "" {
		baseURL = DefaultBaseURL
	}
	parsed, err := url.Parse(baseURL)
	if err != nil || parsed.Scheme == "" || parsed.Host == "" {
		return nil, errors.New("valid Alpaca base URL is required")
	}
	if parsed.Scheme != "https" && parsed.Hostname() != "localhost" && parsed.Hostname() != "127.0.0.1" {
		return nil, errors.New("Alpaca base URL must use HTTPS")
	}
	if strings.TrimSpace(keyID) == "" || strings.TrimSpace(secret) == "" {
		return nil, errors.New("Alpaca credentials are required at runtime")
	}
	if httpClient == nil {
		httpClient = &http.Client{Timeout: 30 * time.Second}
	}
	return &Client{baseURL: parsed, keyID: keyID, secret: secret, http: httpClient, clock: time.Now}, nil
}

func (client *Client) Bars(ctx context.Context, query market.Query) ([]market.Bar, error) {
	bars, _, err := client.BarsWithSnapshots(ctx, query)
	return bars, err
}

func (client *Client) BarsWithSnapshots(ctx context.Context, query market.Query) ([]market.Bar, []Snapshot, error) {
	query.Symbol = strings.ToUpper(strings.TrimSpace(query.Symbol))
	if err := market.ValidateQuery(query); err != nil {
		return nil, nil, err
	}
	var result []market.Bar
	var snapshots []Snapshot
	token := ""
	for page := 0; page < 100; page++ {
		bars, next, snapshot, err := client.page(ctx, query, token)
		if err != nil {
			return nil, nil, err
		}
		result = append(result, bars...)
		snapshots = append(snapshots, snapshot)
		if next == "" {
			return result, snapshots, nil
		}
		token = next
	}
	return nil, nil, errors.New("Alpaca pagination exceeded safety limit")
}

func (client *Client) page(ctx context.Context, query market.Query, token string) ([]market.Bar, string, Snapshot, error) {
	endpoint := client.baseURL.ResolveReference(&url.URL{Path: "/v2/stocks/" + url.PathEscape(strings.ToUpper(query.Symbol)) + "/bars"})
	values := endpoint.Query()
	values.Set("start", query.Start.UTC().Format(time.RFC3339))
	values.Set("end", query.End.UTC().Format(time.RFC3339))
	values.Set("timeframe", query.Timeframe)
	values.Set("adjustment", "all")
	values.Set("feed", "iex")
	values.Set("limit", "10000")
	if token != "" {
		values.Set("page_token", token)
	}
	endpoint.RawQuery = values.Encode()
	request, _ := http.NewRequestWithContext(ctx, http.MethodGet, endpoint.String(), nil)
	request.Header.Set("APCA-API-KEY-ID", client.keyID)
	request.Header.Set("APCA-API-SECRET-KEY", client.secret)
	responseValue, err := client.http.Do(request)
	if err != nil {
		return nil, "", Snapshot{}, err
	}
	defer responseValue.Body.Close()
	if responseValue.StatusCode != http.StatusOK {
		return nil, "", Snapshot{}, fmt.Errorf("Alpaca returned %s", responseValue.Status)
	}
	content, err := io.ReadAll(io.LimitReader(responseValue.Body, 32<<20))
	if err != nil {
		return nil, "", Snapshot{}, err
	}
	decoder := json.NewDecoder(strings.NewReader(string(content)))
	decoder.UseNumber()
	var payload response
	if err := decoder.Decode(&payload); err != nil {
		return nil, "", Snapshot{}, err
	}
	digest := sha256.Sum256(content)
	retrieved := client.clock().UTC()
	result := make([]market.Bar, 0, len(payload.Bars))
	for _, item := range payload.Bars {
		bar := market.Bar{
			Provider: "alpaca", Symbol: strings.ToUpper(query.Symbol), Timestamp: item.Timestamp.UTC(),
			Open: item.Open.String(), High: item.High.String(), Low: item.Low.String(), Close: item.Close.String(),
			Volume: item.Volume.String(), TradeCount: item.Trades, VWAP: item.VWAP.String(),
			Currency: "USD", Venue: "US consolidated via IEX entitlement", Entitlement: "iex",
			Adjustment: "all", AvailableAt: retrieved, RetrievedAt: retrieved,
			SourceURI: endpoint.String(), SourceSHA256: hex.EncodeToString(digest[:]),
		}
		if err := market.ValidateBar(bar); err != nil {
			return nil, "", Snapshot{}, err
		}
		result = append(result, bar)
	}
	return result, payload.NextPageToken, Snapshot{
		SourceURI: endpoint.String(), Content: content, ContentSHA: hex.EncodeToString(digest[:]), RetrievedAt: retrieved,
	}, nil
}
