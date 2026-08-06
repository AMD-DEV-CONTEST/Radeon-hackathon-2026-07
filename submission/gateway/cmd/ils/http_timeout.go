package main

import (
	"net/http"
	"os"
	"strconv"
	"time"
)

func ilsHTTPTimeout() time.Duration {
	return envSeconds("ILS_HTTP_TIMEOUT_SECONDS", 30) * time.Second
}

func ilsShortHTTPTimeout() time.Duration {
	return envSeconds("ILS_SHORT_HTTP_TIMEOUT_SECONDS", 10) * time.Second
}

func ilsHTTPClient() *http.Client {
	return &http.Client{Timeout: ilsHTTPTimeout()}
}

func ilsShortHTTPClient() *http.Client {
	return &http.Client{Timeout: ilsShortHTTPTimeout()}
}

func envSeconds(key string, fallback int) time.Duration {
	raw := os.Getenv(key)
	if raw == "" {
		return time.Duration(fallback)
	}
	n, err := strconv.Atoi(raw)
	if err != nil || n <= 0 {
		return time.Duration(fallback)
	}
	return time.Duration(n)
}
