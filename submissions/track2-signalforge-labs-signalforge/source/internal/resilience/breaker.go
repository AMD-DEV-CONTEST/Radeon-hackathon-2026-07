package resilience

import (
	"sync"
	"time"
)

type Breaker struct {
	mu        sync.Mutex
	threshold int
	cooldown  time.Duration
	failures  int
	openUntil time.Time
}

func NewBreaker(threshold int, cooldown time.Duration) *Breaker {
	if threshold < 1 {
		threshold = 3
	}
	if cooldown <= 0 {
		cooldown = 30 * time.Second
	}
	return &Breaker{threshold: threshold, cooldown: cooldown}
}

func (breaker *Breaker) Allow(now time.Time) bool {
	breaker.mu.Lock()
	defer breaker.mu.Unlock()
	if breaker.openUntil.IsZero() || !now.Before(breaker.openUntil) {
		if !breaker.openUntil.IsZero() {
			breaker.failures = 0
			breaker.openUntil = time.Time{}
		}
		return true
	}
	return false
}

func (breaker *Breaker) Success() {
	breaker.mu.Lock()
	breaker.failures = 0
	breaker.openUntil = time.Time{}
	breaker.mu.Unlock()
}

func (breaker *Breaker) Failure(now time.Time) {
	breaker.mu.Lock()
	defer breaker.mu.Unlock()
	breaker.failures++
	if breaker.failures >= breaker.threshold {
		breaker.openUntil = now.Add(breaker.cooldown)
	}
}
