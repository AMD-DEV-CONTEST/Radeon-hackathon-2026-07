package ai

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

const briefSystemPrompt = `You are StagePoster's conversational creative director.

Your task is to extract and continuously update a structured music-event poster brief from the conversation and attached asset metadata.

Return exactly one valid JSON object.
Do not use Markdown.
Do not use code fences.

Rules:
- Reply in Chinese.
- Preserve existing factual values unless the user explicitly changes them.
- Never invent event dates, times, venues, artists or ticket prices.
- Creative fields such as style, theme and mood may be inferred from the user's creative description.
- Assets are already bound by the backend. Use their metadata and the attached image to understand creative intent.
- Do not generate design plans in this step.
- Empty or unknown fields must be returned as empty strings or empty arrays.

Return exactly this schema:
{
  "reply": "Chinese conversational response",
  "event": {
    "title": "",
    "artist": "",
    "date": "",
    "time": "",
    "venue": "",
    "presalePrice": "",
    "doorPrice": ""
  },
  "visual": {
    "style": "",
    "theme": "",
    "musicGenre": "",
    "mood": [],
    "preferredColors": []
  }
}`

func (service *Service) AssistBrief(
	ctx context.Context,
	current domain.AISessionBrief,
	messages []domain.AIMessageRecord,
	assets []domain.AISessionAssetRecord,
	latestUserMessage string,
) (
	domain.AIBriefAgentResult,
	Metrics,
	error,
) {
	type assetMetadata struct {
		AssetID      string                       `json:"assetId"`
		Purpose      domain.AISessionAssetPurpose `json:"purpose"`
		Kind         domain.AssetKind             `json:"kind"`
		OriginalName string                       `json:"originalName"`
		MimeType     string                       `json:"mimeType"`
		Width        int                          `json:"width"`
		Height       int                          `json:"height"`
	}

	assetItems := make(
		[]assetMetadata,
		0,
		len(assets),
	)

	for _, asset := range assets {
		assetItems = append(
			assetItems,
			assetMetadata{
				AssetID:      asset.AssetID,
				Purpose:      asset.Purpose,
				Kind:         asset.Kind,
				OriginalName: asset.OriginalName,
				MimeType:     asset.MimeType,
				Width:        asset.Width,
				Height:       asset.Height,
			},
		)
	}

	input := struct {
		Current           domain.AISessionBrief    `json:"currentBrief"`
		Conversation      []domain.AIMessageRecord `json:"conversation"`
		Assets            []assetMetadata          `json:"assets"`
		LatestUserMessage string                   `json:"latestUserMessage"`
	}{
		Current:      current,
		Conversation: messages,
		Assets:       assetItems,
		LatestUserMessage: strings.TrimSpace(
			latestUserMessage,
		),
	}

	encoded, err := json.Marshal(input)
	if err != nil {
		return domain.AIBriefAgentResult{},
			Metrics{},
			fmt.Errorf(
				"encode AI brief request: %w",
				err,
			)
	}

	content := []map[string]any{
		{
			"type": "text",
			"text": string(encoded),
		},
	}

	// 当前 vLLM 配置限制每次请求最多一张图片。
	// 所有 Asset 都会通过 metadata 提供给模型，
	// 视觉输入优先选择 performer，其次 reference，再其次其他图片。
	visionAsset, hasVisionAsset := selectBriefVisionAsset(
		assets,
	)

	if hasVisionAsset {
		imageURL, err := imageDataURL(
			visionAsset.StoragePath,
		)
		if err != nil {
			return domain.AIBriefAgentResult{},
				Metrics{},
				fmt.Errorf(
					"encode brief asset image: %w",
					err,
				)
		}

		content = append(
			content,
			map[string]any{
				"type": "image_url",
				"image_url": map[string]string{
					"url": imageURL,
				},
			},
		)
	}

	var result domain.AIBriefAgentResult

	metrics, err := service.client.CompleteJSON(
		ctx,
		[]Message{
			{
				Role:    "system",
				Content: briefSystemPrompt,
			},
			{
				Role:    "user",
				Content: content,
			},
		},
		CompletionOptions{
			Temperature: 0.2,
			MaxTokens:   900,
		},
		&result,
	)
	if err != nil {
		return domain.AIBriefAgentResult{},
			metrics,
			err
	}

	result.Reply = strings.TrimSpace(result.Reply)

	if result.Reply == "" {
		result.Reply = "已更新海报需求。"
	}

	// 记下真正附上去的那张图，让调用方能落使用证据。
	if hasVisionAsset {
		result.VisionAssetID = visionAsset.AssetID
	}

	return result, metrics, nil
}

// selectBriefVisionAsset 返回真正会被附到 VLM 请求上的那个素材。
// 以前只返回路径，调用方拿不到 assetID，于是"这张图确实参与了需求理解"
// 这条唯一站得住的使用证据被丢掉了。
func selectBriefVisionAsset(
	assets []domain.AISessionAssetRecord,
) (domain.AISessionAssetRecord, bool) {
	priorities := []domain.AISessionAssetPurpose{
		domain.AISessionAssetPurposePerformer,
		domain.AISessionAssetPurposeReference,
		domain.AISessionAssetPurposeEventLogo,
		domain.AISessionAssetPurposeArtistLogo,
		domain.AISessionAssetPurposeSponsorLogo,
	}

	for _, purpose := range priorities {
		for _, asset := range assets {
			if asset.Purpose == purpose &&
				strings.HasPrefix(
					asset.MimeType,
					"image/",
				) {
				return asset, true
			}
		}
	}

	return domain.AISessionAssetRecord{}, false
}
