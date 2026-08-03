package domain

import "time"

type AIDesignRequest struct {
	Event   EventBrief  `json:"event"`
	Visual  VisualBrief `json:"visual"`
	Message string      `json:"message"`
}

type AIMetricsResponse struct {
	LatencyMS        int64 `json:"latencyMs"`
	PromptTokens     int   `json:"promptTokens"`
	CompletionTokens int   `json:"completionTokens"`
}

type AIDesignResponse struct {
	Result  DesignAgentResult `json:"result"`
	Metrics AIMetricsResponse `json:"metrics"`
}

type PosterReviewRequest struct {
	DesignPlan *DesignPlan `json:"designPlan,omitempty"`
}

type PosterReviewRecord struct {
	ID          string `json:"reviewId"`
	PosterID    string `json:"posterId"`
	OutputID    string `json:"outputId"`
	CandidateID string `json:"candidateId,omitempty"`

	Round      int            `json:"round"`
	TotalScore Score          `json:"totalScore"`
	Decision   ReviewDecision `json:"decision"`
	Result     ReviewResult   `json:"result"`

	Model            string `json:"model"`
	PromptTokens     int    `json:"promptTokens"`
	CompletionTokens int    `json:"completionTokens"`
	LatencyMS        int64  `json:"latencyMs"`

	CreatedAt time.Time `json:"createdAt"`
}

type PosterReviewResponse struct {
	Review PosterReviewRecord `json:"review"`
}

type PosterReviewListResponse struct {
	PosterID string `json:"posterId"`

	// Items 是分页信封的统一字段名，和 /api/jobs、/api/assets 对齐。
	// CLAUDE.md §8 一直写的是 items，只有这个端点用了自己的 reviews。
	Items []PosterReviewRecord `json:"items"`

	// Reviews 是 Items 的历史别名，保留是为了不打断已经按它写的客户端。
	// 新代码请读 items。
	Reviews []PosterReviewRecord `json:"reviews"`

	ListMeta
}

// PosterMetrics 是任务级的成本汇总。AIMetricsResponse 只覆盖单次 LLM 调用，
// 跨轮次、跨阶段的总量此前没有任何结构能表达。
type PosterMetrics struct {
	// ReviewRounds 是实际跑过的复审轮数。
	ReviewRounds int `json:"reviewRounds"`

	PromptTokens     int `json:"promptTokens"`
	CompletionTokens int `json:"completionTokens"`
	TotalTokens      int `json:"totalTokens"`

	// ReviewLatencyMS 是所有复审调用的累计耗时，不含图像生成。
	ReviewLatencyMS int64 `json:"reviewLatencyMs"`

	// WallClockSeconds 是海报从创建到当前状态的墙上时间，包含 GPU 排队和
	// 图像生成 —— 这部分不体现在 token 里。
	WallClockSeconds int `json:"wallClockSeconds"`
}
