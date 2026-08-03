package assistant

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/Ripped-sys/StagePoster/backend/internal/ai"
	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
	posterflow "github.com/Ripped-sys/StagePoster/backend/internal/poster"
	"github.com/Ripped-sys/StagePoster/backend/internal/repository"
)

var (
	ErrEmptyMessage        = errors.New("AI message is empty")
	ErrInvalidSessionState = errors.New("invalid AI session state")
	ErrInvalidAssetPurpose = errors.New("invalid AI session asset purpose")
	ErrSessionTerminal     = errors.New("AI session is terminal")
)

type Service struct {
	repository *repository.Repository
	aiService  *ai.Service
	aiRuntime  *ai.Runtime
	posterFlow *posterflow.Service
}

func NewService(
	repositoryInstance *repository.Repository,
	aiService *ai.Service,
	aiRuntime *ai.Runtime,
	posterFlow *posterflow.Service,
) *Service {
	return &Service{
		repository: repositoryInstance,
		aiService:  aiService,
		aiRuntime:  aiRuntime,
		posterFlow: posterFlow,
	}
}

func (s *Service) Create(
	ctx context.Context,
	request domain.CreateAISessionRequest,
) (domain.AISessionResponse, error) {
	sessionID, err := domain.NewID("session_")
	if err != nil {
		return domain.AISessionResponse{}, err
	}

	now := time.Now().UTC()

	session := domain.AISessionRecord{
		ID:        sessionID,
		Status:    domain.AISessionStatusCollectingBrief,
		Brief:     request.Brief,
		CreatedAt: now,
		UpdatedAt: now,
	}

	if err := s.repository.CreateAISession(
		ctx,
		session,
	); err != nil {
		return domain.AISessionResponse{}, err
	}

	if len(request.Assets) > 0 {
		return s.BindAssets(
			ctx,
			sessionID,
			request.Assets,
		)
	}

	return s.Get(ctx, sessionID)
}

func (s *Service) Get(
	ctx context.Context,
	sessionID string,
) (domain.AISessionResponse, error) {
	session, err := s.repository.GetAISession(
		ctx,
		sessionID,
	)
	if err != nil {
		return domain.AISessionResponse{}, err
	}

	var posterResult *domain.PosterResponse

	if session.PosterID != "" {
		poster, posterErr := s.posterFlow.Get(
			ctx,
			session.PosterID,
		)

		if posterErr != nil &&
			!errors.Is(
				posterErr,
				repository.ErrNotFound,
			) {
			return domain.AISessionResponse{},
				posterErr
		}

		if posterErr == nil {
			posterResult = &poster

			if session.Status !=
				domain.AISessionStatusCanceled &&
				session.Status !=
					domain.AISessionStatusCompletedWithWarnings &&
				session.Status !=
					domain.AISessionStatusNeedsUserInput {
				nextStatus := sessionStatusForPoster(
					poster.Status,
				)

				if nextStatus != "" &&
					(nextStatus != session.Status ||
						session.ErrorMessage !=
							poster.Error) {
					session.Status = nextStatus
					session.ErrorMessage =
						poster.Error

					if err := s.repository.UpdateAISession(
						ctx,
						session,
					); err != nil {
						return domain.AISessionResponse{},
							err
					}

					session, err =
						s.repository.GetAISession(
							ctx,
							sessionID,
						)
					if err != nil {
						return domain.AISessionResponse{},
							err
					}
				}
			}
		}
	}

	messages, err := s.repository.ListAIMessages(
		ctx,
		sessionID,
		50,
	)
	if err != nil {
		return domain.AISessionResponse{}, err
	}

	assets, err := s.repository.ListAISessionAssets(
		ctx,
		sessionID,
	)
	if err != nil {
		return domain.AISessionResponse{}, err
	}

	plans, err := s.repository.ListAIDesignPlans(
		ctx,
		sessionID,
	)
	if err != nil {
		return domain.AISessionResponse{}, err
	}

	var reviewSummary *domain.AIReviewSummary

	if session.PosterID != "" {
		reviews, _, reviewErr :=
			s.posterFlow.ListReviews(
				ctx,
				session.PosterID,
				domain.NormalizePage(
					domain.MaxPageLimit,
					0,
				),
			)
		if reviewErr != nil {
			return domain.AISessionResponse{},
				reviewErr
		}

		reviewSummary = buildReviewSummary(
			reviews,
			session.Status,
		)
	}

	return domain.AISessionResponse{
		SessionID: session.ID,
		Status:    session.Status,
		AvailableActions: availableActionsForSession(
			session.Status,
			posterResult,
			reviewSummary,
		),
		Brief:          session.Brief,
		MissingFields:  missingBriefFields(session.Brief),
		SelectedPlanID: session.SelectedPlanID,
		PosterID:       session.PosterID,
		Error:          session.ErrorMessage,
		ReviewSummary:  reviewSummary,
		Messages:       messages,
		Assets:         assets,
		Plans:          plans,
		Poster:         posterResult,
		CreatedAt:      session.CreatedAt,
		UpdatedAt:      session.UpdatedAt,
	}, nil
}

func (s *Service) SendMessage(
	ctx context.Context,
	sessionID string,
	content string,
) (
	domain.AIMessageResponse,
	error,
) {
	content = strings.TrimSpace(content)

	if content == "" {
		return domain.AIMessageResponse{},
			ErrEmptyMessage
	}

	session, err := s.repository.GetAISession(
		ctx,
		sessionID,
	)
	if err != nil {
		return domain.AIMessageResponse{}, err
	}

	if session.Status.Terminal() {
		return domain.AIMessageResponse{},
			ErrSessionTerminal
	}

	switch session.Status {
	case domain.AISessionStatusCollectingBrief,
		domain.AISessionStatusAwaitingPlanSelection:

	default:
		return domain.AIMessageResponse{},
			fmt.Errorf(
				"%w: cannot chat while session is %s",
				ErrInvalidSessionState,
				session.Status,
			)
	}

	userMessageID, err := domain.NewID("message_")
	if err != nil {
		return domain.AIMessageResponse{}, err
	}

	if err := s.repository.CreateAIMessage(
		ctx,
		domain.AIMessageRecord{
			ID:        userMessageID,
			SessionID: sessionID,
			Role:      domain.AIMessageRoleUser,
			Content:   content,
			CreatedAt: time.Now().UTC(),
		},
	); err != nil {
		return domain.AIMessageResponse{}, err
	}

	history, err := s.repository.ListAIMessages(
		ctx,
		sessionID,
		30,
	)
	if err != nil {
		return domain.AIMessageResponse{}, err
	}

	// 当前消息通过 latestUserMessage 单独传递，
	// 避免同一句话同时出现在 history 和 latest 中。
	if len(history) > 0 {
		last := history[len(history)-1]

		if last.Role == domain.AIMessageRoleUser &&
			last.Content == content {
			history = history[:len(history)-1]
		}
	}

	assets, err := s.repository.ListAISessionAssets(
		ctx,
		sessionID,
	)
	if err != nil {
		return domain.AIMessageResponse{}, err
	}

	release, err := s.aiRuntime.Acquire(ctx)
	if err != nil {
		return domain.AIMessageResponse{}, err
	}
	defer release()

	briefResult, metrics, err :=
		s.aiService.AssistBrief(
			ctx,
			session.Brief,
			history,
			assets,
			content,
		)
	if err != nil {
		return domain.AIMessageResponse{},
			err
	}

	session.Brief = mergeBrief(
		session.Brief,
		briefResult,
	)

	// 这一张图确实进了刚才那次 VLM 调用 —— 是整条链路里最站得住的使用证据。
	if briefResult.VisionAssetID != "" {
		if err := s.repository.MarkAISessionAssetsUsed(
			ctx,
			sessionID,
			[]string{briefResult.VisionAssetID},
			domain.AISessionAssetStageBrief,
			"作为视觉输入参与需求理解",
		); err != nil {
			return domain.AIMessageResponse{}, err
		}
	}

	session.Brief = applyAssetBindings(
		session.Brief,
		assets,
	)

	missing := missingBriefFields(session.Brief)
	reply := briefResult.Reply

	if len(missing) == 0 {
		designResult, designMetrics, err :=
			s.aiService.Plan(
				ctx,
				session.Brief.Event,
				session.Brief.Visual,
				content,
			)
		if err != nil {
			return domain.AIMessageResponse{},
				err
		}

		metrics = combineMetrics(
			metrics,
			designMetrics,
		)

		if err := s.repository.ReplaceAIDesignPlans(
			ctx,
			sessionID,
			designResult.Plans,
		); err != nil {
			return domain.AIMessageResponse{},
				err
		}

		session.Status =
			domain.AISessionStatusAwaitingPlanSelection

		if strings.TrimSpace(
			designResult.Reply,
		) != "" {
			reply = designResult.Reply
		}
	} else {
		session.Status =
			domain.AISessionStatusCollectingBrief

		// 用户修改 Brief 后重新缺字段，
		// 旧 Plan 不能继续作为有效方案。
		if err := s.repository.ReplaceAIDesignPlans(
			ctx,
			sessionID,
			nil,
		); err != nil {
			return domain.AIMessageResponse{},
				err
		}

		if reply == "" {
			reply = "还需要补充：" +
				strings.Join(missing, "、")
		}
	}

	session.ErrorMessage = ""

	if err := s.repository.UpdateAISession(
		ctx,
		session,
	); err != nil {
		return domain.AIMessageResponse{}, err
	}

	assistantMessageID, err :=
		domain.NewID("message_")
	if err != nil {
		return domain.AIMessageResponse{}, err
	}

	if err := s.repository.CreateAIMessage(
		ctx,
		domain.AIMessageRecord{
			ID:        assistantMessageID,
			SessionID: sessionID,
			Role:      domain.AIMessageRoleAssistant,
			Content:   reply,
			CreatedAt: time.Now().UTC(),
		},
	); err != nil {
		return domain.AIMessageResponse{}, err
	}

	response, err := s.Get(ctx, sessionID)
	if err != nil {
		return domain.AIMessageResponse{}, err
	}

	return domain.AIMessageResponse{
		Session: response,
		Metrics: domain.AIMetricsResponse{
			LatencyMS:        metrics.Latency.Milliseconds(),
			PromptTokens:     metrics.PromptTokens,
			CompletionTokens: metrics.CompletionTokens,
		},
	}, nil
}

func (s *Service) BindAssets(
	ctx context.Context,
	sessionID string,
	bindings []domain.BindAISessionAsset,
) (domain.AISessionResponse, error) {
	session, err := s.repository.GetAISession(
		ctx,
		sessionID,
	)
	if err != nil {
		return domain.AISessionResponse{}, err
	}

	if session.Status.Terminal() {
		return domain.AISessionResponse{},
			ErrSessionTerminal
	}

	for _, binding := range bindings {
		if !binding.Purpose.Valid() {
			return domain.AISessionResponse{},
				fmt.Errorf(
					"%w: %s",
					ErrInvalidAssetPurpose,
					binding.Purpose,
				)
		}

		asset, err := s.repository.GetAsset(
			ctx,
			binding.AssetID,
		)
		if err != nil {
			return domain.AISessionResponse{},
				err
		}

		if err := validateAssetPurpose(
			asset,
			binding.Purpose,
		); err != nil {
			return domain.AISessionResponse{},
				err
		}

		if err := s.repository.BindAISessionAsset(
			ctx,
			sessionID,
			binding.AssetID,
			binding.Purpose,
		); err != nil {
			return domain.AISessionResponse{},
				err
		}
	}

	assets, err := s.repository.ListAISessionAssets(
		ctx,
		sessionID,
	)
	if err != nil {
		return domain.AISessionResponse{}, err
	}

	session.Brief = applyAssetBindings(
		session.Brief,
		assets,
	)

	if err := s.repository.UpdateAISession(
		ctx,
		session,
	); err != nil {
		return domain.AISessionResponse{}, err
	}

	return s.Get(ctx, sessionID)
}

func (s *Service) ConfirmPlan(
	ctx context.Context,
	sessionID string,
	planID string,
) (domain.AISessionResponse, error) {
	session, err := s.repository.GetAISession(
		ctx,
		sessionID,
	)
	if err != nil {
		return domain.AISessionResponse{}, err
	}

	if session.Status.Terminal() {
		return domain.AISessionResponse{},
			ErrSessionTerminal
	}

	if session.Status !=
		domain.AISessionStatusAwaitingPlanSelection {
		return domain.AISessionResponse{},
			fmt.Errorf(
				"%w: session is %s",
				ErrInvalidSessionState,
				session.Status,
			)
	}

	planRecord, err :=
		s.repository.GetAIDesignPlan(
			ctx,
			sessionID,
			planID,
		)
	if err != nil {
		return domain.AISessionResponse{}, err
	}

	if err := s.repository.SelectAIDesignPlan(
		ctx,
		sessionID,
		planID,
	); err != nil {
		return domain.AISessionResponse{}, err
	}

	assets, err := s.repository.ListAISessionAssets(
		ctx,
		sessionID,
	)
	if err != nil {
		return domain.AISessionResponse{}, err
	}

	session.Brief = applyAssetBindings(
		session.Brief,
		assets,
	)

	session.SelectedPlanID = planID
	session.Status =
		domain.AISessionStatusGeneratingCandidates
	session.ErrorMessage = ""

	if err := s.repository.UpdateAISession(
		ctx,
		session,
	); err != nil {
		return domain.AISessionResponse{}, err
	}

	// 候选生成前明确释放 Qwen 显存。
	if err := s.aiRuntime.Suspend(ctx); err != nil {
		return s.failSession(
			ctx,
			session,
			err,
		)
	}

	poster, err :=
		s.posterFlow.CreateFromDesignPlan(
			ctx,
			domain.CreatePosterRequest{
				Event:    session.Brief.Event,
				Branding: session.Brief.Branding,
				Visual:   session.Brief.Visual,
			},
			planRecord.Plan,
		)
	if err != nil {
		return s.failSession(
			ctx,
			session,
			err,
		)
	}

	session.PosterID = poster.PosterID
	session.Status = sessionStatusForPoster(
		poster.Status,
	)

	if session.Status == "" {
		session.Status =
			domain.AISessionStatusGeneratingCandidates
	}

	if err := s.repository.UpdateAISession(
		ctx,
		session,
	); err != nil {
		return domain.AISessionResponse{}, err
	}

	messageID, err := domain.NewID("message_")
	if err == nil {
		_ = s.repository.CreateAIMessage(
			ctx,
			domain.AIMessageRecord{
				ID:        messageID,
				SessionID: sessionID,
				Role:      domain.AIMessageRoleSystem,
				Content: "已确认设计方案「" +
					planRecord.Plan.Name +
					"」，开始生成三张候选图。",
				CreatedAt: time.Now().UTC(),
			},
		)
	}

	return s.Get(ctx, sessionID)
}

func (s *Service) SelectCandidate(
	ctx context.Context,
	sessionID string,
	candidateID string,
) (domain.AISessionResponse, error) {
	sessionID = strings.TrimSpace(sessionID)
	candidateID = strings.TrimSpace(candidateID)

	if sessionID == "" || candidateID == "" {
		return domain.AISessionResponse{},
			ErrInvalidSessionState
	}

	session, err := s.repository.GetAISession(
		ctx,
		sessionID,
	)
	if err != nil {
		return domain.AISessionResponse{}, err
	}

	if session.PosterID == "" {
		return domain.AISessionResponse{},
			fmt.Errorf(
				"%w: session has no poster",
				ErrInvalidSessionState,
			)
	}

	switch session.Status {
	case domain.AISessionStatusAwaitingCandidateSelection,
		domain.AISessionStatusLooping,
		domain.AISessionStatusSucceeded:
		// 允许首次选择、合成期间重试，以及成功后的幂等重试。

	default:
		if session.Status.Terminal() {
			return domain.AISessionResponse{},
				ErrSessionTerminal
		}

		return domain.AISessionResponse{},
			fmt.Errorf(
				"%w: cannot select candidate while session is %s",
				ErrInvalidSessionState,
				session.Status,
			)
	}

	poster, err := s.posterFlow.Select(
		ctx,
		session.PosterID,
		candidateID,
	)
	if err != nil {
		return domain.AISessionResponse{}, err
	}

	nextStatus := sessionStatusForPoster(
		poster.Status,
	)
	if nextStatus == "" {
		return domain.AISessionResponse{},
			fmt.Errorf(
				"%w: unsupported poster status %s",
				ErrInvalidSessionState,
				poster.Status,
			)
	}

	session.Status = nextStatus
	session.ErrorMessage = poster.Error

	if err := s.repository.UpdateAISession(
		ctx,
		session,
	); err != nil {
		return domain.AISessionResponse{}, err
	}

	return s.Get(ctx, sessionID)
}

func (s *Service) Cancel(
	ctx context.Context,
	sessionID string,
) (domain.AISessionResponse, error) {
	session, err := s.repository.GetAISession(
		ctx,
		sessionID,
	)
	if err != nil {
		return domain.AISessionResponse{}, err
	}

	if session.Status.Terminal() {
		return s.Get(ctx, sessionID)
	}

	session.Status =
		domain.AISessionStatusCanceled
	session.ErrorMessage = ""

	if err := s.repository.UpdateAISession(
		ctx,
		session,
	); err != nil {
		return domain.AISessionResponse{}, err
	}

	return s.Get(ctx, sessionID)
}

func (s *Service) failSession(
	ctx context.Context,
	session domain.AISessionRecord,
	cause error,
) (domain.AISessionResponse, error) {
	session.Status = domain.AISessionStatusFailed
	session.ErrorMessage = cause.Error()

	_ = s.repository.UpdateAISession(
		ctx,
		session,
	)

	return domain.AISessionResponse{}, cause
}

func mergeBrief(
	current domain.AISessionBrief,
	result domain.AIBriefAgentResult,
) domain.AISessionBrief {
	mergeString(
		&current.Event.Title,
		result.Event.Title,
	)

	mergeString(
		&current.Event.Artist,
		result.Event.Artist,
	)

	mergeString(
		&current.Event.Date,
		result.Event.Date,
	)

	mergeString(
		&current.Event.Time,
		result.Event.Time,
	)

	mergeString(
		&current.Event.Venue,
		result.Event.Venue,
	)

	mergeString(
		&current.Event.PresalePrice,
		result.Event.PresalePrice,
	)

	mergeString(
		&current.Event.DoorPrice,
		result.Event.DoorPrice,
	)

	mergeString(
		&current.Visual.Style,
		result.Visual.Style,
	)

	mergeString(
		&current.Visual.Theme,
		result.Visual.Theme,
	)

	mergeString(
		&current.Visual.MusicGenre,
		result.Visual.MusicGenre,
	)

	if len(result.Visual.Mood) > 0 {
		current.Visual.Mood = append(
			[]string(nil),
			result.Visual.Mood...,
		)
	}

	if len(result.Visual.PreferredColors) > 0 {
		current.Visual.PreferredColors = append(
			[]string(nil),
			result.Visual.PreferredColors...,
		)
	}

	return current
}

func mergeString(
	target *string,
	value string,
) {
	value = strings.TrimSpace(value)

	if value != "" {
		*target = value
	}
}

func missingBriefFields(
	brief domain.AISessionBrief,
) []string {
	var missing []string

	required := []struct {
		Name  string
		Value string
	}{
		{
			Name:  "event.title",
			Value: brief.Event.Title,
		},
		{
			Name:  "event.artist",
			Value: brief.Event.Artist,
		},
		{
			Name:  "event.date",
			Value: brief.Event.Date,
		},
		{
			Name:  "event.time",
			Value: brief.Event.Time,
		},
		{
			Name:  "event.venue",
			Value: brief.Event.Venue,
		},
		{
			Name:  "visual.style",
			Value: brief.Visual.Style,
		},
		{
			Name:  "visual.theme",
			Value: brief.Visual.Theme,
		},
		{
			Name:  "visual.musicGenre",
			Value: brief.Visual.MusicGenre,
		},
	}

	for _, field := range required {
		if strings.TrimSpace(field.Value) == "" {
			missing = append(
				missing,
				field.Name,
			)
		}
	}

	if len(brief.Visual.Mood) == 0 {
		missing = append(
			missing,
			"visual.mood",
		)
	}

	return missing
}

func applyAssetBindings(
	brief domain.AISessionBrief,
	assets []domain.AISessionAssetRecord,
) domain.AISessionBrief {
	sponsorIDs := append(
		[]string(nil),
		brief.Branding.SponsorLogoAssetIDs...,
	)

	for _, asset := range assets {
		switch asset.Purpose {
		case domain.AISessionAssetPurposeArtistLogo:
			brief.Branding.ArtistLogoAssetID =
				asset.AssetID

		case domain.AISessionAssetPurposeEventLogo:
			brief.Branding.EventLogoAssetID =
				asset.AssetID

		case domain.AISessionAssetPurposeSponsorLogo:
			sponsorIDs = appendUnique(
				sponsorIDs,
				asset.AssetID,
			)
		}
	}

	brief.Branding.SponsorLogoAssetIDs =
		sponsorIDs

	return brief
}

func validateAssetPurpose(
	asset domain.Asset,
	purpose domain.AISessionAssetPurpose,
) error {
	switch purpose {
	case domain.AISessionAssetPurposePerformer:
		if asset.Kind != domain.AssetKindPerson {
			return fmt.Errorf(
				"%w: performer requires a person asset",
				ErrInvalidAssetPurpose,
			)
		}

	case domain.AISessionAssetPurposeReference:
		if asset.Kind != domain.AssetKindReference {
			return fmt.Errorf(
				"%w: reference requires a reference asset",
				ErrInvalidAssetPurpose,
			)
		}

	case domain.AISessionAssetPurposeArtistLogo,
		domain.AISessionAssetPurposeEventLogo,
		domain.AISessionAssetPurposeSponsorLogo:
		if asset.Kind != domain.AssetKindLogo {
			return fmt.Errorf(
				"%w: logo purpose requires a logo asset",
				ErrInvalidAssetPurpose,
			)
		}

	default:
		return ErrInvalidAssetPurpose
	}

	return nil
}

func appendUnique(
	values []string,
	value string,
) []string {
	for _, existing := range values {
		if existing == value {
			return values
		}
	}

	return append(values, value)
}

func combineMetrics(
	left ai.Metrics,
	right ai.Metrics,
) ai.Metrics {
	return ai.Metrics{
		PromptTokens: left.PromptTokens +
			right.PromptTokens,
		CompletionTokens: left.CompletionTokens +
			right.CompletionTokens,
		TotalTokens: left.TotalTokens +
			right.TotalTokens,
		Latency: left.Latency +
			right.Latency,
	}
}

func availableActionsForSession(
	status domain.AISessionStatus,
	poster *domain.PosterResponse,
	reviewSummary *domain.AIReviewSummary,
) []string {
	switch status {
	case domain.AISessionStatusCollectingBrief:
		return []string{
			"send_message",
			"attach_asset",
			"cancel",
		}

	case domain.AISessionStatusAwaitingPlanSelection:
		return []string{
			"send_message",
			"confirm_plan",
			"cancel",
		}

	case domain.AISessionStatusGeneratingCandidates:
		return []string{
			"refresh",
			"cancel",
		}

	case domain.AISessionStatusAwaitingCandidateSelection:
		return []string{
			"select_candidate",
			"cancel",
		}

	case domain.AISessionStatusLooping:
		return []string{
			"refresh",
			"cancel",
		}

	case domain.AISessionStatusNeedsUserInput:
		return []string{
			"send_message",
			"cancel",
		}

	case domain.AISessionStatusSucceeded:
		actions := make([]string, 0, 2)

		if reviewSummary == nil ||
			!reviewSummary.Finalized {
			actions = append(
				actions,
				"finalize",
			)
		}

		if poster != nil &&
			poster.ResultURL != "" {
			actions = append(
				actions,
				"download_final",
			)
		}

		return actions

	case domain.AISessionStatusCompletedWithWarnings:
		if poster != nil &&
			poster.ResultURL != "" {
			return []string{
				"download_final",
			}
		}

		return []string{}

	case domain.AISessionStatusFailed,
		domain.AISessionStatusCanceled:
		return []string{}

	default:
		return []string{}
	}
}

func sessionStatusForPoster(
	status domain.PosterStatus,
) domain.AISessionStatus {
	switch status {
	case domain.PosterStatusPlanning,
		domain.PosterStatusGenerating,
		domain.PosterStatusPartialReady:
		return domain.AISessionStatusGeneratingCandidates

	case domain.PosterStatusAwaitingSelection:
		return domain.AISessionStatusAwaitingCandidateSelection

	case domain.PosterStatusSelected,
		domain.PosterStatusComposing:
		return domain.AISessionStatusLooping

	case domain.PosterStatusSucceeded:
		return domain.AISessionStatusSucceeded

	case domain.PosterStatusFailed:
		return domain.AISessionStatusFailed

	default:
		return ""
	}
}
