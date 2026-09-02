package domain

import "time"

type PosterStatus string

const (
	PosterStatusPlanning          PosterStatus = "planning_candidates"
	PosterStatusGenerating        PosterStatus = "generating_candidates"
	PosterStatusValidating        PosterStatus = "validating_candidates"
	PosterStatusPartialReady      PosterStatus = "partial_ready"
	PosterStatusAwaitingSelection PosterStatus = "awaiting_selection"
	PosterStatusSelected          PosterStatus = "selected"
	PosterStatusComposing         PosterStatus = "composing"
	PosterStatusSucceeded         PosterStatus = "succeeded"
	PosterStatusFailed            PosterStatus = "failed"
	PosterStatusCanceled          PosterStatus = "canceled"
)

type CandidateStatus string

const (
	CandidateStatusGenerating CandidateStatus = "generating"
	CandidateStatusValidating CandidateStatus = "validating"
	CandidateStatusRetrying   CandidateStatus = "retrying"
	CandidateStatusReady      CandidateStatus = "ready"
	CandidateStatusFailed     CandidateStatus = "failed"
)

type EventBrief struct {
	Title        string `json:"title"`
	Artist       string `json:"artist,omitempty"`
	Date         string `json:"date"`
	Time         string `json:"time"`
	Venue        string `json:"venue"`
	PresalePrice string `json:"presalePrice,omitempty"`
	DoorPrice    string `json:"doorPrice,omitempty"`
}

type BrandingBrief struct {
	ArtistLogoAssetID   string   `json:"artistLogoAssetId,omitempty"`
	EventLogoAssetID    string   `json:"eventLogoAssetId,omitempty"`
	SponsorLogoAssetIDs []string `json:"sponsorLogoAssetIds,omitempty"`
}

type VisualBrief struct {
	Style           string   `json:"style"`
	Theme           string   `json:"theme"`
	MusicGenre      string   `json:"musicGenre,omitempty"`
	Mood            []string `json:"mood,omitempty"`
	PreferredColors []string `json:"preferredColors,omitempty"`

	// ReferenceAssetID 指向一张已上传的参考图（kind=reference）。
	//
	// 装了 Z-Image ControlNet 权重时，它会经 Canny 边缘图真正参与采样；
	// 否则只作为视觉输入进需求理解那次 VLM 调用。查
	// GET /api/system/dependencies 的 capabilities.referenceImageConditioning
	// 能知道当前是哪种。
	ReferenceAssetID string `json:"referenceAssetId,omitempty"`

	// ControlStrength 是参考图的控制强度，0–1，省略取默认 0.55。
	ControlStrength float64 `json:"controlStrength,omitempty"`
}

type CreatePosterRequest struct {
	Event    EventBrief    `json:"event"`
	Branding BrandingBrief `json:"branding"`
	Visual   VisualBrief   `json:"visual"`
}

type GoalContract struct {
	Width               int  `json:"width"`
	Height              int  `json:"height"`
	AllowPeople         bool `json:"allowPeople"`
	AllowReadableText   bool `json:"allowReadableText"`
	RequireCentralMotif bool `json:"requireCentralMotif"`
	MaxAttempts         int  `json:"maxAttempts"`
}

type PersonIdentityControl struct {
	Similarity  float64 `json:"similarity"`  // 0-1, IP-Adapter similarity
	MaskBlur    int     `json:"maskBlur"`    // IP-Adapter mask blur radius
	FaceRestore bool    `json:"faceRestore"` // 是否启用人脸修复
}

type StyleReferenceControl struct {
	Strength        float64  `json:"strength"`        // ControlNet strength (0-1)
	ColorConstraint []string `json:"colorConstraint"` // 颜色约束
	CompositionRef  bool     `json:"compositionRef"`  // 构图参考
	MaterialRef     []string `json:"materialRef"`     // 材质参考
}

type GenerationControl struct {
	PersonIdentity *PersonIdentityControl `json:"personIdentity,omitempty"`
	StyleReference *StyleReferenceControl `json:"styleReference,omitempty"`
}

type CandidateSpec struct {
	VariantKey  string   `json:"variantKey"`
	VariantName string   `json:"variantName"`
	Motif       string   `json:"motif"`
	Composition string   `json:"composition"`
	Camera      string   `json:"camera,omitempty"`
	Materials   []string `json:"materials"`
	Palette     []string `json:"palette"`
	Lighting    string   `json:"lighting"`
}

type PosterRecord struct {
	ID                  string       `json:"posterId"`
	Status              PosterStatus `json:"status"`
	StyleKey            string       `json:"styleKey"`
	EventJSON           string       `json:"-"`
	BrandingJSON        string       `json:"-"`
	VisualJSON          string       `json:"-"`
	GoalJSON            string       `json:"-"`
	SelectedCandidateID string       `json:"selectedCandidateId,omitempty"`
	ErrorMessage        string       `json:"error,omitempty"`
	CreatedAt           time.Time    `json:"createdAt"`
	UpdatedAt           time.Time    `json:"updatedAt"`
	CompletedAt         *time.Time   `json:"completedAt,omitempty"`
}

type CandidateRecord struct {
	ID             string          `json:"candidateId"`
	PosterID       string          `json:"posterId"`
	JobID          string          `json:"jobId"`
	VariantIndex   int             `json:"variantIndex"`
	VariantKey     string          `json:"variantKey"`
	VariantName    string          `json:"variantName"`
	SpecJSON       string          `json:"-"`
	CompiledPrompt string          `json:"-"`
	Seed           int64           `json:"seed"`
	Attempt        int             `json:"attempt"`
	Status         CandidateStatus `json:"status"`
	Passed         bool            `json:"passed"`
	Selected       bool            `json:"selected"`
	ErrorMessage   string          `json:"error,omitempty"`
	CreatedAt      time.Time       `json:"createdAt"`
	UpdatedAt      time.Time       `json:"updatedAt"`
}

type CandidateResponse struct {
	CandidateID string          `json:"candidateId"`
	VariantKey  string          `json:"variantKey"`
	VariantName string          `json:"variantName"`
	Status      CandidateStatus `json:"status"`
	Attempt     int             `json:"attempt"`
	Selected    bool            `json:"selected"`
	ImageURL    string          `json:"imageUrl,omitempty"`
	Spec        *CandidateSpec  `json:"spec,omitempty"`
	Seed        int64           `json:"seed,omitempty"`
	Error       string          `json:"error,omitempty"`
}

type PosterResponse struct {
	PosterID            string              `json:"posterId"`
	Status              PosterStatus        `json:"status"`
	SelectedCandidateID string              `json:"selectedCandidateId,omitempty"`
	ResultURL           string              `json:"resultUrl,omitempty"`
	ThumbnailURL        string              `json:"thumbnailUrl,omitempty"`
	Candidates          []CandidateResponse `json:"candidates"`
	Progress            PosterProgress      `json:"progress"`
	Error               string              `json:"error,omitempty"`
	CreatedAt           time.Time           `json:"createdAt"`
	UpdatedAt           time.Time           `json:"updatedAt"`
}

// PosterProgress 以前只有候选图的 completed / total 两个计数，而这个计数只在
// 候选生成阶段动 —— composing、validating、以及整个复审循环期间它完全冻住，
// 客户端看不出还要等多久，也不知道当前卡在哪一步。
type PosterProgress struct {
	Completed int `json:"completed"`
	Total     int `json:"total"`

	// Stage 是当前所处的粗粒度阶段，由状态派生，便于前端显示文案。
	Stage string `json:"stage"`

	// Percent 是整条流水线的推进比例（0-100），不只是候选生成那一段。
	Percent int `json:"percent"`

	// ElapsedSeconds 自任务创建起的实际耗时。
	ElapsedSeconds int `json:"elapsedSeconds"`

	// EtaSeconds 是剩余时间估计，取自历史上已成功海报的中位总耗时。
	// 没有足够历史样本时省略 —— 编一个数字比不给更糟。
	EtaSeconds *int `json:"etaSeconds,omitempty"`
}

// Terminal 表示海报流程已经结束，不会再推进。
func (status PosterStatus) Terminal() bool {
	switch status {
	case PosterStatusSucceeded,
		PosterStatusFailed,
		PosterStatusCanceled:
		return true

	default:
		return false
	}
}

// posterStageWeights 是各状态对应的整体完成度。数字是按实测流水线耗时排的
// 粗略刻度，不是精确测量；用途只是让进度条单调前进。
var posterStageWeights = map[PosterStatus]int{
	PosterStatusPlanning:          5,
	PosterStatusGenerating:        20,
	PosterStatusValidating:        55,
	PosterStatusPartialReady:      60,
	PosterStatusAwaitingSelection: 65,
	PosterStatusSelected:          70,
	PosterStatusComposing:         80,
	PosterStatusSucceeded:         100,
	PosterStatusFailed:            100,
	PosterStatusCanceled:          100,
}

// StageProgress 返回某个状态对应的整体完成度。
func StageProgress(
	status PosterStatus,
) int {
	if weight, ok := posterStageWeights[status]; ok {
		return weight
	}

	return 0
}

type SelectCandidateRequest struct {
	CandidateID string `json:"candidateId"`
}
