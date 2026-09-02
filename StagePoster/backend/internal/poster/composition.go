package poster

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"log"
	"os"
	"strings"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

var ErrResultNotReady = errors.New(
	"poster result is not ready",
)

// ErrOutputMissing 表示 poster_outputs 里有记录，但磁盘上的文件不在了。
// 以前这里直接把 *fs.PathError 包出去，处理器落到默认分支返回 500，并把
// 服务器绝对路径原样写进响应体。对客户端来说文件没了就是 404，路径不该外泄。
var ErrOutputMissing = errors.New(
	"poster output file is missing",
)

type CompositionEngine interface {
	Compose(
		context.Context,
		domain.ComposeInput,
	) (domain.ComposeResult, error)
}

type ComposedFile struct {
	Body        *os.File
	ContentType string
	Filename    string
}

func (s *Service) reconcileComposition(
	ctx context.Context,
	posterRecord domain.PosterRecord,
) error {
	return s.composePoster(
		ctx,
		posterRecord,
		domain.CompositionAdjustments{},
		"",
	)
}

func (s *Service) composePoster(
	ctx context.Context,
	posterRecord domain.PosterRecord,
	adjustments domain.CompositionAdjustments,
	keyVisualOverride string,
) error {
	candidate, err := s.repository.GetSelectedCandidate(
		ctx,
		posterRecord.ID,
	)
	if err != nil {
		return s.failComposition(
			ctx,
			posterRecord.ID,
			fmt.Errorf(
				"resolve selected candidate: %w",
				err,
			),
		)
	}

	if candidate.Status != domain.CandidateStatusReady ||
		!candidate.Passed {
		return s.failComposition(
			ctx,
			posterRecord.ID,
			ErrCandidateNotReady,
		)
	}

	if posterRecord.Status == domain.PosterStatusSelected {
		if err := s.repository.UpdatePosterStatus(
			ctx,
			posterRecord.ID,
			domain.PosterStatusComposing,
			"",
		); err != nil {
			return err
		}
	}

	keyVisualPath := strings.TrimSpace(
		keyVisualOverride,
	)

	if keyVisualPath == "" {
		keyVisual, outputErr :=
			s.repository.GetOutput(
				ctx,
				candidate.JobID,
				"poster",
			)
		if outputErr != nil {
			return s.failComposition(
				ctx,
				posterRecord.ID,
				fmt.Errorf(
					"resolve candidate output: %w",
					outputErr,
				),
			)
		}

		keyVisualPath = keyVisual.StoragePath
	}

	var event domain.EventBrief
	if err := json.Unmarshal(
		[]byte(posterRecord.EventJSON),
		&event,
	); err != nil {
		return s.failComposition(
			ctx,
			posterRecord.ID,
			fmt.Errorf(
				"decode event brief: %w",
				err,
			),
		)
	}

	var branding domain.BrandingBrief
	if err := json.Unmarshal(
		[]byte(posterRecord.BrandingJSON),
		&branding,
	); err != nil {
		return s.failComposition(
			ctx,
			posterRecord.ID,
			fmt.Errorf(
				"decode branding brief: %w",
				err,
			),
		)
	}

	artistLogo, err := s.resolveCompositionAsset(
		ctx,
		branding.ArtistLogoAssetID,
	)
	if err != nil {
		return s.failComposition(
			ctx,
			posterRecord.ID,
			fmt.Errorf(
				"resolve artist logo: %w",
				err,
			),
		)
	}

	eventLogo, err := s.resolveCompositionAsset(
		ctx,
		branding.EventLogoAssetID,
	)
	if err != nil {
		return s.failComposition(
			ctx,
			posterRecord.ID,
			fmt.Errorf(
				"resolve event logo: %w",
				err,
			),
		)
	}

	sponsors := make(
		[]domain.CompositionAsset,
		0,
		len(branding.SponsorLogoAssetIDs),
	)

	for _, sponsorID := range branding.SponsorLogoAssetIDs {
		sponsor, err := s.resolveCompositionAsset(
			ctx,
			sponsorID,
		)
		if err != nil {
			return s.failComposition(
				ctx,
				posterRecord.ID,
				fmt.Errorf(
					"resolve sponsor logo %s: %w",
					sponsorID,
					err,
				),
			)
		}

		sponsors = append(sponsors, sponsor)
	}

	result, err := s.composer.Compose(
		ctx,
		domain.ComposeInput{
			PosterID:      posterRecord.ID,
			CandidateID:   candidate.ID,
			Width:         1024,
			Height:        1536,
			KeyVisualPath: keyVisualPath,
			Event:         event,
			Adjustments:   adjustments,
			ArtistLogo:    artistLogo,
			EventLogo:     eventLogo,
			Sponsors:      sponsors,
		},
	)
	if err != nil {
		return s.failComposition(
			ctx,
			posterRecord.ID,
			err,
		)
	}

	now := time.Now().UTC()

	// 使用证据来自合成器真正画上去的素材，不是"我们传了哪些素材"。
	// StoragePath 为空的素材会被静默跳过，两者并不等价。
	if err := s.repository.RecordComposedAssetUsage(
		ctx,
		posterRecord.ID,
		result.UsedAssetIDs,
	); err != nil {
		// 证据落库失败不该毁掉一张已经合成好的海报。
		log.Printf(
			"poster %s: record asset usage: %v",
			posterRecord.ID,
			err,
		)
	}

	finalID, err := domain.NewID("poster_output_")
	if err != nil {
		return err
	}

	thumbnailID, err := domain.NewID("poster_output_")
	if err != nil {
		return err
	}

	if err := s.repository.UpsertPosterOutput(
		ctx,
		domain.PosterOutput{
			ID:          finalID,
			PosterID:    posterRecord.ID,
			CandidateID: candidate.ID,
			Kind:        domain.PosterOutputKindFinal,
			Filename:    "final-poster.png",
			MimeType:    "image/png",
			StoragePath: result.FinalPath,
			Width:       result.Width,
			Height:      result.Height,
			CreatedAt:   now,
		},
	); err != nil {
		return s.failComposition(
			ctx,
			posterRecord.ID,
			err,
		)
	}

	if err := s.repository.UpsertPosterOutput(
		ctx,
		domain.PosterOutput{
			ID:          thumbnailID,
			PosterID:    posterRecord.ID,
			CandidateID: candidate.ID,
			Kind:        domain.PosterOutputKindThumbnail,
			Filename:    "thumbnail.png",
			MimeType:    "image/png",
			StoragePath: result.ThumbnailPath,
			Width:       result.ThumbnailWidth,
			Height:      result.ThumbnailHeight,
			CreatedAt:   now,
		},
	); err != nil {
		return s.failComposition(
			ctx,
			posterRecord.ID,
			err,
		)
	}

	return s.repository.CompletePoster(
		ctx,
		posterRecord.ID,
	)
}

func (s *Service) resolveCompositionAsset(
	ctx context.Context,
	assetID string,
) (domain.CompositionAsset, error) {
	if assetID == "" {
		return domain.CompositionAsset{}, nil
	}

	return s.repository.GetCompositionAsset(
		ctx,
		assetID,
	)
}

func (s *Service) failComposition(
	ctx context.Context,
	posterID string,
	cause error,
) error {
	if updateErr := s.repository.UpdatePosterStatus(
		ctx,
		posterID,
		domain.PosterStatusFailed,
		cause.Error(),
	); updateErr != nil {
		return errors.Join(cause, updateErr)
	}

	return nil
}

func (s *Service) OpenFinalResult(
	ctx context.Context,
	posterID string,
) (ComposedFile, error) {
	return s.openOutput(
		ctx,
		posterID,
		domain.PosterOutputKindFinal,
	)
}

// OpenThumbnail 服务 PosterResponse 里那个 thumbnailUrl。合成阶段一直在写
// 缩略图文件和 poster_outputs 记录，只是从来没有路由把它读出来。
func (s *Service) OpenThumbnail(
	ctx context.Context,
	posterID string,
) (ComposedFile, error) {
	return s.openOutput(
		ctx,
		posterID,
		domain.PosterOutputKindThumbnail,
	)
}

func (s *Service) openOutput(
	ctx context.Context,
	posterID string,
	kind string,
) (ComposedFile, error) {
	posterRecord, err := s.repository.GetPoster(
		ctx,
		posterID,
	)
	if err != nil {
		return ComposedFile{}, err
	}

	if posterRecord.Status != domain.PosterStatusSucceeded {
		return ComposedFile{}, ErrResultNotReady
	}

	output, err := s.repository.GetPosterOutput(
		ctx,
		posterID,
		kind,
	)
	if err != nil {
		return ComposedFile{}, err
	}

	file, err := os.Open(output.StoragePath)
	if err != nil {
		// 路径只进日志，不进响应体。
		log.Printf(
			"poster %s output %s unreadable: %v",
			posterID,
			kind,
			err,
		)

		if errors.Is(err, fs.ErrNotExist) {
			return ComposedFile{}, ErrOutputMissing
		}

		return ComposedFile{},
			errors.New("poster output is unreadable")
	}

	return ComposedFile{
		Body:        file,
		ContentType: output.MimeType,
		Filename:    output.Filename,
	}, nil
}
