package worker

import (
	"context"
	"errors"
	"log"
	"time"

	posterflow "github.com/Ripped-sys/StagePoster/backend/internal/poster"
)

type PosterReconciler struct {
	service  *posterflow.Service
	interval time.Duration
	logger   *log.Logger
}

func NewPosterReconciler(
	service *posterflow.Service,
	interval time.Duration,
	logger *log.Logger,
) *PosterReconciler {
	if interval <= 0 {
		interval = 2 * time.Second
	}

	if logger == nil {
		logger = log.Default()
	}

	return &PosterReconciler{
		service:  service,
		interval: interval,
		logger:   logger,
	}
}

func (r *PosterReconciler) Run(
	ctx context.Context,
) {
	defer func() {
		if rec := recover(); rec != nil {
			r.logger.Printf(
				"POSTER RECONCILER PANIC (will not restart): %v",
				rec,
			)
		}
	}()

	r.runOnce(ctx)

	ticker := time.NewTicker(r.interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return

		case <-ticker.C:
			func() {
				defer func() {
					if rec := recover(); rec != nil {
						r.logger.Printf(
							"POSTER RECONCILER TICK PANIC: %v",
							rec,
						)
					}
				}()
				r.runOnce(ctx)
			}()
		}
	}
}

func (r *PosterReconciler) runOnce(
	parent context.Context,
) {
	ctx, cancel := context.WithTimeout(
		parent,
		90*time.Second,
	)
	defer cancel()

	err := r.service.ReconcileActive(ctx, 50)
	if err == nil {
		return
	}

	if errors.Is(err, context.Canceled) {
		return
	}

	r.logger.Printf(
		"poster reconciliation warning: %v",
		err,
	)
}
