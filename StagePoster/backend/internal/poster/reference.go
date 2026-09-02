package poster

import (
	"encoding/json"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

// applyReferenceControl 把视觉简报里的参考图设置搬进生成请求。
//
// 三条生成路径（首次候选、按设计方案生成、复审后重生成）都得带上它，否则
// 重生成的那张会悄悄丢掉参考图，同一张海报的候选之间构图依据就不一致了。
func applyReferenceControl(
	request domain.GenerateRequest,
	visual domain.VisualBrief,
) domain.GenerateRequest {
	request.ReferenceAssetID = visual.ReferenceAssetID
	request.ControlStrength = visual.ControlStrength

	return request
}

// visualBriefFrom 从海报记录里解出视觉简报。
//
// 解不出来时返回零值而不是报错：复审后重生成不该因为读不出参考图设置而整个失败，
// 退化成"没有参考图"是安全的。
func visualBriefFrom(
	posterRecord domain.PosterRecord,
) domain.VisualBrief {
	var visual domain.VisualBrief

	if err := json.Unmarshal(
		[]byte(posterRecord.VisualJSON),
		&visual,
	); err != nil {
		return domain.VisualBrief{}
	}

	return visual
}
