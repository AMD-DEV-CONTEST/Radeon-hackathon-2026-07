package domain

import (
	"strings"
	"time"
)

const (
	PosterOutputKindFinal     = "final_poster"
	PosterOutputKindThumbnail = "thumbnail"
)

type CompositionAsset struct {
	ID          string
	MimeType    string
	StoragePath string
	Width       int
	Height      int
}

type CompositionAdjustments struct {
	Template         string
	TitleOffsetRatio float64
	PanelTopRatio    float64
	PanelTheme       string
}

// NormalizeCompositionAdjustments 把模板默认值填进零值字段，并把结果夹到合法区间。
//
// 这段逻辑原先私有在 composer 包里。移到 domain 是因为调用方需要知道某个模板的
// **生效值**才能在它之上做增量调整：审查循环原先直接把 TitleOffsetRatio 设成
// 0.055、PanelTopRatio 设成 0.81，而这恰好就是 cinematic_center 的默认值，
// 于是"调整"之后重排出来的是同一张图。零值在这里表示"用模板默认"，不是"设为 0"，
// 不先解析默认值就无法判断一次调整到底改了什么。
func NormalizeCompositionAdjustments(
	adjustments CompositionAdjustments,
) CompositionAdjustments {

	switch strings.ToLower(
		strings.TrimSpace(adjustments.Template),
	) {
	case "editorial_top":
		if adjustments.TitleOffsetRatio == 0 {
			adjustments.TitleOffsetRatio = 0.035
		}

		if adjustments.PanelTopRatio == 0 {
			adjustments.PanelTopRatio = 0.80
		}

	case "cinematic_center":
		if adjustments.TitleOffsetRatio == 0 {
			adjustments.TitleOffsetRatio = 0.055
		}

		if adjustments.PanelTopRatio == 0 {
			adjustments.PanelTopRatio = 0.81
		}

		if strings.TrimSpace(
			adjustments.PanelTheme,
		) == "" {
			adjustments.PanelTheme = "dark"
		}

	case "gothic_frame":
		if adjustments.TitleOffsetRatio == 0 {
			adjustments.TitleOffsetRatio = 0.045
		}

		if adjustments.PanelTopRatio == 0 {
			adjustments.PanelTopRatio = 0.82
		}

		if strings.TrimSpace(
			adjustments.PanelTheme,
		) == "" {
			adjustments.PanelTheme = "dark"
		}
	}

	if adjustments.PanelTopRatio == 0 {
		adjustments.PanelTopRatio = 0.77
	}

	if adjustments.PanelTopRatio < CompositionPanelTopMin {
		adjustments.PanelTopRatio = CompositionPanelTopMin
	}

	if adjustments.PanelTopRatio > CompositionPanelTopMax {
		adjustments.PanelTopRatio = CompositionPanelTopMax
	}

	if adjustments.TitleOffsetRatio < 0 {
		adjustments.TitleOffsetRatio = 0
	}

	if adjustments.TitleOffsetRatio > CompositionTitleOffsetMax {
		adjustments.TitleOffsetRatio = CompositionTitleOffsetMax
	}

	switch strings.ToLower(
		strings.TrimSpace(adjustments.PanelTheme),
	) {
	case "dark":
		adjustments.PanelTheme = "dark"

	default:
		adjustments.PanelTheme = "light"
	}

	return adjustments
}

// 版式参数的合法区间。审查循环靠"递增后是否仍等于原值"判断是否已经顶到边界，
// 所以这几个数必须是单一来源，不能在 composer 和 poster 里各写一份。
const (
	CompositionPanelTopMin    = 0.70
	CompositionPanelTopMax    = 0.86
	CompositionTitleOffsetMax = 0.12
)

type ComposeInput struct {
	PosterID    string
	CandidateID string

	Width  int
	Height int

	KeyVisualPath string

	Event       EventBrief
	Adjustments CompositionAdjustments

	ArtistLogo CompositionAsset
	EventLogo  CompositionAsset
	Sponsors   []CompositionAsset
}

type ComposeResult struct {
	FinalPath     string
	ThumbnailPath string

	Width           int
	Height          int
	ThumbnailWidth  int
	ThumbnailHeight int

	// UsedAssetIDs 是真正画进画布的素材 ID。ai_session_assets.actually_used
	// 之前恒为 false，对确实用过的素材主动断言"没用过"；证据只能由合成器给出，
	// 因为只有它知道哪个素材因为 StoragePath 为空被跳过了。
	UsedAssetIDs []string
}

type PosterOutput struct {
	ID          string
	PosterID    string
	CandidateID string

	Kind        string
	Filename    string
	MimeType    string
	StoragePath string

	Width  int
	Height int

	CreatedAt time.Time
}
