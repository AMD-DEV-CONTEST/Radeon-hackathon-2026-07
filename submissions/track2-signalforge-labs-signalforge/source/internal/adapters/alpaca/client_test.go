package alpaca

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/market"
)

func TestBarsUseHeadersAndPreserveEntitlement(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/v2/stocks/MSFT/bars" || request.URL.Query().Get("feed") != "iex" {
			t.Errorf("unexpected request %s", request.URL.String())
		}
		if request.Header.Get("APCA-API-KEY-ID") != "key-id" || request.Header.Get("APCA-API-SECRET-KEY") != "secret" {
			t.Error("credentials were not sent in headers")
		}
		_, _ = response.Write([]byte(`{"bars":[{"t":"2025-01-02T05:00:00Z","o":420.1,"h":425.2,"l":419.8,"c":424.5,"v":1000,"n":50,"vw":423.7}],"next_page_token":null}`))
	}))
	defer server.Close()
	client, err := NewClient(server.URL, "key-id", "secret", server.Client())
	if err != nil {
		t.Fatal(err)
	}
	client.clock = func() time.Time { return time.Date(2025, 1, 4, 0, 0, 0, 0, time.UTC) }
	bars, err := client.Bars(context.Background(), market.Query{
		Symbol: "msft", Start: time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC),
		End: time.Date(2025, 1, 3, 0, 0, 0, 0, time.UTC), Timeframe: "1Day",
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(bars) != 1 || bars[0].Close != "424.5" || bars[0].Entitlement != "iex" || !bars[0].AvailableAt.Equal(bars[0].RetrievedAt) {
		t.Fatalf("unexpected bars: %#v", bars)
	}
}

func TestClientRequiresRuntimeCredentials(t *testing.T) {
	if _, err := NewClient(DefaultBaseURL, "", "", nil); err == nil {
		t.Fatal("missing credentials must fail")
	}
}
