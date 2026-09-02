// Package vision 从候选主视觉里量出前端叠字需要的事实。
//
// 这里只做能从像素里算出来的部分：主色、明暗、对比度、颗粒、主体占位、文字
// 安全区、Logo 安全区，以及由这些推出的推荐字色/描边/字重。全部是确定性计算，
// 同一张图永远得到同一份结果，也不需要 GPU。
//
// 剩下三件事像素算不出来 —— 纹理归类、视觉风格、以及"图里有没有模型伪文字"。
// 那三个字段留给 VLM 填（internal/ai.Service.InspectKeyVisual），填不上就保持
// 空值。Source 字段如实标注这份分析来自哪一层，所以前端能分辨"没有伪文字"和
// "没查过伪文字"—— 把后者当成前者是这套接口最容易犯的错。
//
// 本机没有可用的 OCR：项目刻意不引入 CGO（modernc.org/sqlite 就是为此选的），
// 而 gosseract/tesseract 绑定都要 CGO，外网又不通。所以"检查安全区里有没有伪
// 文字"这件事由视觉模型承担，不是由像素规则承担。
package vision

import "github.com/Ripped-sys/StagePoster/backend/internal/domain"

// 分析结果的形状由 domain 拥有（和 AssetCutout、ReviewResult 一样），这里用
// 类型别名把它们拉进来，好让算法代码不必到处写 domain. 前缀。别名不是新类型，
// vision.Analysis 和 domain.VisualAnalysis 是同一个类型。
type (
	Rect       = domain.VisualRect
	SafeZone   = domain.TextSafeZone
	LogoZone   = domain.LogoSafeZone
	Typography = domain.TypographyProfile
	Analysis   = domain.VisualAnalysis
	Inspection = domain.VisualInspection
)

const (
	SourcePixels    = domain.VisualSourcePixels
	SourcePixelsVLM = domain.VisualSourcePixelsVLM

	ContrastLow    = domain.VisualContrastLow
	ContrastMedium = domain.VisualContrastMedium
	ContrastHigh   = domain.VisualContrastHigh

	BrightnessDark    = domain.VisualBrightnessDark
	BrightnessBalance = domain.VisualBrightnessBalanced
	BrightnessLight   = domain.VisualBrightnessLight
)
