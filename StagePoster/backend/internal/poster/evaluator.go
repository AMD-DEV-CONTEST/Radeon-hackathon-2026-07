package poster

import (
	"errors"
	"fmt"
	"image"
	_ "image/gif"
	_ "image/jpeg"
	_ "image/png"
	"os"
	"strings"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

var ErrCandidateRejected = errors.New("candidate rejected")

type Evaluator struct{}

func NewEvaluator() *Evaluator {
	return &Evaluator{}
}

func (e *Evaluator) Evaluate(
	output domain.Output,
	goal domain.GoalContract,
) error {
	if output.StoragePath == "" {
		return fmt.Errorf(
			"%w: output storage path is empty",
			ErrCandidateRejected,
		)
	}

	if !strings.HasPrefix(output.MimeType, "image/") {
		return fmt.Errorf(
			"%w: output MIME type is %s",
			ErrCandidateRejected,
			output.MimeType,
		)
	}

	info, err := os.Stat(output.StoragePath)
	if err != nil {
		return fmt.Errorf(
			"%w: inspect output file: %v",
			ErrCandidateRejected,
			err,
		)
	}

	if info.Size() < 32*1024 {
		return fmt.Errorf(
			"%w: output file is suspiciously small",
			ErrCandidateRejected,
		)
	}

	file, err := os.Open(output.StoragePath)
	if err != nil {
		return fmt.Errorf(
			"%w: open output file: %v",
			ErrCandidateRejected,
			err,
		)
	}
	defer file.Close()

	config, _, err := image.DecodeConfig(file)
	if err != nil {
		return fmt.Errorf(
			"%w: decode output image: %v",
			ErrCandidateRejected,
			err,
		)
	}

	if config.Width != goal.Width ||
		config.Height != goal.Height {
		return fmt.Errorf(
			"%w: expected %dx%d, received %dx%d",
			ErrCandidateRejected,
			goal.Width,
			goal.Height,
			config.Width,
			config.Height,
		)
	}

	return nil
}
