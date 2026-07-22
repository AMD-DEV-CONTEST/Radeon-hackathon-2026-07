package workspace

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

func TestFixtureServerSustainsExpectedDemoReadLoad(t *testing.T) {
	server, err := NewServer(ServerConfig{
		Mode:        ModeFixture,
		FixturePath: filepath.Join("..", "..", "fixtures", "workspace", "golden-case.json"),
		EventDelay:  0,
		RunTimeout:  time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}
	httpServer := httptest.NewServer(server.Handler())
	defer httpServer.Close()

	paths := []string{"/api/v1/health", "/api/v1/config", "/api/v1/cases/golden"}
	const requests = 96
	started := time.Now()
	errors := make(chan error, requests)
	var wait sync.WaitGroup
	for index := 0; index < requests; index++ {
		wait.Add(1)
		go func(path string) {
			defer wait.Done()
			response, requestErr := http.Get(httpServer.URL + path)
			if requestErr != nil {
				errors <- requestErr
				return
			}
			defer response.Body.Close()
			if response.StatusCode != http.StatusOK {
				errors <- fmt.Errorf("%s returned %s", path, response.Status)
			}
		}(paths[index%len(paths)])
	}
	wait.Wait()
	close(errors)
	for err := range errors {
		t.Fatal(err)
	}
	if elapsed := time.Since(started); elapsed > 5*time.Second {
		t.Fatalf("fixture demo read load took %s", elapsed)
	}
}
