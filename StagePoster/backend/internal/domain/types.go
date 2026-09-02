package domain

import "time"

type GenerateRequest struct {
	Prompt         string `json:"prompt"`
	NegativePrompt string `json:"negativePrompt,omitempty"`
	Seed           *int64 `json:"seed,omitempty"`

	// ReferenceAssetID 是一张已上传素材的 ID，用作构图参考。
	//
	// 它以前对出图毫无影响 —— 工作流只绑 prompt / negative / seed，参考图只作为
	// 视觉输入进了需求理解那次 VLM 调用。现在它经 Canny 边缘图接进 Z-Image 的
	// ControlNet，真的参与采样。
	ReferenceAssetID string `json:"referenceAssetId,omitempty"`

	// ControlStrength 是参考图的控制强度，0–1。
	// 省略时用 DefaultReferenceControlStrength。
	//
	// 越接近 1 越严格照搬参考图的构图，越接近 0 参考图的影响越轻微。
	ControlStrength float64 `json:"controlStrength,omitempty"`
}

// 参考图控制强度的取值范围与默认值。
//
// 实测 0.75 会把参考图的构图几乎 1:1 复刻出来（圆环、竖柱、横条全部照搬），
// 对"照这个版式来"是想要的，对"只要这个调性"就太强了。默认取中间偏低一档。
const (
	MinReferenceControlStrength     = 0.05
	MaxReferenceControlStrength     = 1.0
	DefaultReferenceControlStrength = 0.55
)

// NormalizeControlStrength 把强度收进合法区间；0 取默认值。
func NormalizeControlStrength(
	strength float64,
) float64 {
	if strength <= 0 {
		return DefaultReferenceControlStrength
	}

	if strength < MinReferenceControlStrength {
		return MinReferenceControlStrength
	}

	if strength > MaxReferenceControlStrength {
		return MaxReferenceControlStrength
	}

	return strength
}

type GenerateResponse struct {
	JobID    string    `json:"jobId"`
	PromptID string    `json:"promptId"`
	Status   JobStatus `json:"status"`
	Seed     int64     `json:"seed"`
}

type ImageMeta struct {
	Filename  string `json:"filename"`
	Subfolder string `json:"subfolder"`
	Type      string `json:"type"`
}

type JobResponse struct {
	JobID           string     `json:"jobId"`
	PromptID        string     `json:"promptId,omitempty"`
	Status          JobStatus  `json:"status"`
	Prompt          string     `json:"prompt"`
	NegativePrompt  string     `json:"negativePrompt,omitempty"`
	Seed            int64      `json:"seed"`
	WorkflowKey     string     `json:"workflowKey"`
	WorkflowVersion string     `json:"workflowVersion"`
	Image           *ImageMeta `json:"image,omitempty"`
	ResultURL       string     `json:"resultUrl,omitempty"`
	Error           string     `json:"error,omitempty"`
	CreatedAt       time.Time  `json:"createdAt"`
	StartedAt       *time.Time `json:"startedAt,omitempty"`
	CompletedAt     *time.Time `json:"completedAt,omitempty"`
	UpdatedAt       time.Time  `json:"updatedAt"`
}

type JobListResponse struct {
	Items []JobResponse `json:"items"`

	ListMeta
}
