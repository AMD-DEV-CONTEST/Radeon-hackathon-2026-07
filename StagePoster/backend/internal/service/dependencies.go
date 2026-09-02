package service

import "context"

func (s *PosterService) DatabaseHealth(
	ctx context.Context,
) error {
	return s.repository.Ping(ctx)
}

func (s *PosterService) ComfyHealth(
	ctx context.Context,
) error {
	return s.client.Health(ctx)
}
