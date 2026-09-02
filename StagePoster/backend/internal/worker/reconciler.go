package worker

import (
	"context"
	"errors"
	"log"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/service"
)

type Reconciler struct {
	service  *service.PosterService
	interval time.Duration
	logger   *log.Logger
}

func NewReconciler(
	posterService *service.PosterService,
	interval time.Duration,
	logger *log.Logger,
) *Reconciler {
	if interval <= 0 {
		interval = 2 * time.Second
	}

	if logger == nil {
		logger = log.Default()
	}

	return &Reconciler{
		service:  posterService,
		interval: interval,
		logger:   logger,
	}
}

func (r *Reconciler) Run(ctx context.Context) {
	defer func() {
		if rec := recover(); rec != nil {
			r.logger.Printf(
				"RECONCILER PANIC (will not restart): %v",
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
							"RECONCILER TICK PANIC: %v",
							rec,
						)
					}
				}()
				r.runOnce(ctx)
			}()
		}
	}
}

func (r *Reconciler) runOnce(parent context.Context) {
	ctx, cancel := context.WithTimeout(
		parent,
		90*time.Second,
	)
	defer cancel()

	err := r.service.ReconcileActiveJobs(ctx, 50)
	if err == nil {
		return
	}

	if errors.Is(err, context.Canceled) {
		return
	}

	r.logger.Printf("job reconciliation warning: %v", err)
}
