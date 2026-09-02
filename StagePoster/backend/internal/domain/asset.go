package domain

import "time"

type AssetKind string

const (
	AssetKindPerson    AssetKind = "person"
	AssetKindLogo      AssetKind = "logo"
	AssetKindReference AssetKind = "reference"
)

const AssetProcessVersion = "v1"

func (kind AssetKind) Valid() bool {
	switch kind {
	case AssetKindPerson,
		AssetKindLogo,
		AssetKindReference:
		return true
	default:
		return false
	}
}

type AssetProcessStatus string

const (
	AssetProcessStatusPending    AssetProcessStatus = "pending"
	AssetProcessStatusProcessing AssetProcessStatus = "processing"
	AssetProcessStatusReady      AssetProcessStatus = "ready"
	AssetProcessStatusFailed     AssetProcessStatus = "failed"
)

// AssetCutoutStatus 是抠图 / 透明化的独立状态。
//
// 以前没有这个字段：抠图成败被并进了笼统的 ProcessStatus，而"生成蒙版"这一步
// 只是把源文件复制了一份，所以 ProcessStatus=ready 的真实含义是"我们复制了文件"，
// 不是"背景已抠掉"。
type AssetCutoutStatus string

const (
	// AssetCutoutStatusUnsupported：没有接背景去除模型（rembg / matting 之类），
	// 抠图这一步根本没跑。这是当前所有 logo / person 素材的真实状态。
	AssetCutoutStatusUnsupported AssetCutoutStatus = "unsupported"

	// AssetCutoutStatusReady：素材自带可用的透明通道，合成时能正常叠加。
	AssetCutoutStatusReady AssetCutoutStatus = "ready"

	// AssetCutoutStatusOpaque：素材完全不透明。合成器只会按 alpha 叠加，
	// 不会自己抠背景，所以这种 logo 会以一个不透明矩形压在海报上。
	AssetCutoutStatusOpaque AssetCutoutStatus = "opaque"

	// AssetCutoutStatusFailed：透明度检查本身失败（解码不了等）。
	AssetCutoutStatusFailed AssetCutoutStatus = "failed"

	// AssetCutoutStatusPending：素材刚上传，透明度检查还排在异步队列里。
	//
	// 上传响应以前在这里返回空字符串 —— 既不在枚举里，也没法和 unsupported
	// 区分。而这两者含义完全相反：unsupported 是"这步不会跑"，pending 是"这步
	// 马上就跑，稍后再查会变成 ready/opaque"。
	AssetCutoutStatusPending AssetCutoutStatus = "pending"
)

// NormalizeAssetCutoutStatus 把未知值折叠成 unsupported。
//
// 空字符串来自 cutout_status 列加上之前写入的历史行，那些素材确实没跑过抠图，
// 折叠成 unsupported 是对的；pending 则必须原样保留，否则刚上传的素材会被谎报
// 成"不支持"，而它下一秒就会变成 ready。
func NormalizeAssetCutoutStatus(
	status AssetCutoutStatus,
) AssetCutoutStatus {
	switch status {
	case AssetCutoutStatusReady,
		AssetCutoutStatusOpaque,
		AssetCutoutStatusFailed,
		AssetCutoutStatusPending:
		return status

	default:
		return AssetCutoutStatusUnsupported
	}
}

// AssetCutout 是抠图相关的可观测状态。
type AssetCutout struct {
	Status AssetCutoutStatus `json:"status"`

	// HasAlpha 是实测结果：真的解码了图片并找到了非全不透明的像素。
	HasAlpha bool `json:"hasAlpha"`
}

type ProcessingStepStatus string

const (
	ProcessingStepStatusPending    ProcessingStepStatus = "pending"
	ProcessingStepStatusProcessing ProcessingStepStatus = "processing"
	ProcessingStepStatusCompleted  ProcessingStepStatus = "completed"
	ProcessingStepStatusFailed     ProcessingStepStatus = "failed"
	ProcessingStepStatusSkipped    ProcessingStepStatus = "skipped"
)

type ProcessingStep struct {
	Name        string               `json:"name"`
	Status      ProcessingStepStatus `json:"status"`
	Error       string               `json:"error,omitempty"`
	StartedAt   *time.Time           `json:"startedAt,omitempty"`
	CompletedAt *time.Time           `json:"completedAt,omitempty"`
}

type Asset struct {
	ID           string    `json:"assetId"`
	Kind         AssetKind `json:"kind"`
	OriginalName string    `json:"originalName"`
	Filename     string    `json:"filename"`
	MimeType     string    `json:"mimeType"`
	SizeBytes    int64     `json:"sizeBytes"`
	SHA256       string    `json:"sha256"`
	StoragePath  string    `json:"-"`

	Width  int `json:"width"`
	Height int `json:"height"`

	// Processing state
	ProcessStatus  AssetProcessStatus `json:"processStatus"`
	ProcessError   string             `json:"processError,omitempty"`
	ProcessedAt    *time.Time         `json:"processedAt,omitempty"`
	MaskPath       string             `json:"maskPath,omitempty"`
	AnalysisJSON   string             `json:"analysisJson,omitempty"`
	DominantColors []string           `json:"dominantColors,omitempty"`
	ProcessVersion string             `json:"processVersion,omitempty"`

	// Cutout 是抠图 / 透明化的独立状态，和笼统的 ProcessStatus 分开。
	Cutout AssetCutout `json:"cutout"`

	CreatedAt time.Time `json:"createdAt"`
}

type AssetResponse struct {
	ID           string    `json:"assetId"`
	Kind         AssetKind `json:"kind"`
	OriginalName string    `json:"originalName"`
	Filename     string    `json:"filename"`
	MimeType     string    `json:"mimeType"`
	SizeBytes    int64     `json:"sizeBytes"`
	SHA256       string    `json:"sha256"`
	ContentURL   string    `json:"contentUrl"`
	Width        int       `json:"width"`
	Height       int       `json:"height"`

	// Processing state
	ProcessStatus  AssetProcessStatus `json:"processStatus"`
	ProcessError   string             `json:"processError,omitempty"`
	ProcessedAt    *time.Time         `json:"processedAt,omitempty"`
	MaskPath       string             `json:"maskPath,omitempty"`
	AnalysisJSON   string             `json:"analysisJson,omitempty"`
	DominantColors []string           `json:"dominantColors,omitempty"`
	ProcessVersion string             `json:"processVersion,omitempty"`

	// Cutout 是抠图 / 透明化的独立状态，和笼统的 ProcessStatus 分开。
	Cutout AssetCutout `json:"cutout"`

	CreatedAt time.Time `json:"createdAt"`
}

type AssetListResponse struct {
	Items []AssetResponse `json:"items"`

	ListMeta
}
