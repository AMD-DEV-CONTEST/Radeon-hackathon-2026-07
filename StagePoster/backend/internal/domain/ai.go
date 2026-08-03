package domain

import (
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
)

type Score int

func (s Score) Int() int {
	return int(s)
}

func (s *Score) UnmarshalJSON(
	data []byte,
) error {

	raw :=
		strings.TrimSpace(
			string(data),
		)

	var value float64

	// 数字
	if err := json.Unmarshal(
		data,
		&value,
	); err != nil {

		// 字符串数字
		parsed, err :=
			strconv.ParseFloat(
				strings.Trim(
					raw,
					"\"",
				),
				64,
			)

		if err != nil {
			return fmt.Errorf(
				"invalid score %s",
				raw,
			)
		}

		value = parsed
	}

	// 模型习惯输出 0-10
	// 自动转百分制
	if value > 0 &&
		value <= 10 {

		value *= 10
	}

	*s =
		Score(
			int(value + 0.5),
		)

	return nil
}

type ReviewDecision string

const (
	ReviewDecisionAccept       ReviewDecision = "ACCEPT"
	ReviewDecisionRecompose    ReviewDecision = "RECOMPOSE"
	ReviewDecisionRegenerate   ReviewDecision = "REGENERATE"
	ReviewDecisionRewriteBrief ReviewDecision = "REWRITE_BRIEF"
)

// ReviewAcceptScore 是接受阈值。以前 review.go 的判断和 service.go 的提示词里
// 各写了一遍字面量 82，改一处忘一处就会让服务端的裁决和模型被告知的规则对不上。
const ReviewAcceptScore = 82

// ReviewPixelDefectScore：visualQuality 低于此值说明瑕疵在生成的像素里，
// 重排版救不了 —— 合成器只能挪标题、改信息栏，动不了主视觉本身。
//
// 六个分项评分此前完全不参与决策，只有 totalScore 被比较。而 visualQuality
// 恰好就是"瑕疵是否已经烤进图里"的直接信号，把它接进裁决能解决模型给
// RECOMPOSE、重排若干轮仍救不回来、最后撞上轮数上限的情况。
const ReviewPixelDefectScore = 60

// ReviewIssueLayer 是 issues[].layer 的取值。提示词一直要求模型填这个字段，
// 但服务端解析完就扔了，路由全靠自由文本关键词匹配 —— 于是一条 composition
// 层的问题只要描述里出现"水印"就会被误判成需要重新生成。
type ReviewIssueLayer = string

const (
	ReviewIssueLayerGeneration  ReviewIssueLayer = "generation"
	ReviewIssueLayerComposition ReviewIssueLayer = "composition"
	ReviewIssueLayerBrief       ReviewIssueLayer = "brief"
)

func (d ReviewDecision) Valid() bool {
	switch d {
	case ReviewDecisionAccept,
		ReviewDecisionRecompose,
		ReviewDecisionRegenerate,
		ReviewDecisionRewriteBrief:
		return true
	default:
		return false
	}
}

type ReviewFailure struct {
	Code        string `json:"code"`
	Description string `json:"description"`
}

type ReviewIssue struct {
	Code     string `json:"code"`
	Severity string `json:"severity"`
	Layer    string `json:"layer"`

	Description string `json:"description"`
	Suggestion  string `json:"suggestion"`
}

type ReviewScores struct {
	RequirementAlignment Score `json:"requirementAlignment"`

	Composition Score `json:"composition"`

	Typography Score `json:"typography"`

	Readability Score `json:"readability"`

	VisualQuality Score `json:"visualQuality"`

	BrandConsistency Score `json:"brandConsistency"`
}

type ReviewNextInstruction struct {
	PromptAdditions StringList `json:"promptAdditions"`

	NegativePromptAdditions StringList `json:"negativePromptAdditions"`

	ComposerTemplate string `json:"composerTemplate"`
}

type ReviewResult struct {
	TotalScore Score `json:"totalScore"`

	Scores ReviewScores `json:"scores"`

	HardFailures []ReviewFailure `json:"hardFailures"`

	Issues []ReviewIssue `json:"issues"`

	Decision ReviewDecision `json:"decision"`

	NextInstruction ReviewNextInstruction `json:"nextInstruction"`
}
