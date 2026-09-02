package resilience

import (
	"testing"
	"time"
)

func TestBreakerOpensResetsAndRecovers(t *testing.T) {
	now := time.Date(2026, 7, 22, 10, 0, 0, 0, time.UTC)
	breaker := NewBreaker(3, 30*time.Second)
	for index := 0; index < 2; index++ {
		breaker.Failure(now)
		if !breaker.Allow(now) {
			t.Fatalf("opened after %d failures", index+1)
		}
	}
	breaker.Failure(now)
	if breaker.Allow(now) {
		t.Fatal("breaker should be open")
	}
	if !breaker.Allow(now.Add(31 * time.Second)) {
		t.Fatal("breaker did not recover after cooldown")
	}
	breaker.Failure(now)
	breaker.Success()
	if !breaker.Allow(now) {
		t.Fatal("success did not reset breaker")
	}
}
