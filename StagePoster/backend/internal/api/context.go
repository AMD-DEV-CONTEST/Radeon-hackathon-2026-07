package api

import (
	"context"
	"net/http"
	"time"
)

func contextWithTimeout(
	request *http.Request,
	timeout time.Duration,
) (context.Context, context.CancelFunc) {
	return context.WithTimeout(
		request.Context(),
		timeout,
	)
}
