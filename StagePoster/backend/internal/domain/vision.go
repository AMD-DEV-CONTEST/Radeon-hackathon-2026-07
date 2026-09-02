package domain

// 主视觉视觉分析。算法在 internal/vision，类型放在这里 —— 和 AssetCutout、
// ReviewResult、ComposeResult 一样，凡是要出现在 HTTP 响应里的形状都由 domain
// 拥有，这样 api / repository / poster 都不必导入算法包。

// VisualRect 是归一化坐标（0..1），相对画布左上角。前端直接乘自己的渲染尺寸
// 即可，不需要知道后端画布是 1024x1536。
type VisualRect struct {
	X float64 `json:"x"`
	Y float64 `json:"y"`
	W float64 `json:"w"`
	H float64 `json:"h"`
}

func (r VisualRect) Area() float64 {
	if r.W <= 0 || r.H <= 0 {
		return 0
	}

	return r.W * r.H
}

// TextSafeZone 是一块可以安全压字的区域。
//
// Complexity 是该区域的背景繁忙度（0..1）：0 是纯色平面，1 是高频细节。前端
// 拿它决定要不要加描边或压暗层。Priority 从 1 开始，1 最推荐。
type TextSafeZone struct {
	VisualRect

	Area       float64 `json:"area"`
	Complexity float64 `json:"complexity"`
	Align      string  `json:"align"`
	Priority   int     `json:"priority"`

	// Background 是该区域的平均底色，前端要自算对比度时用得上。
	Background string `json:"background"`
}

// LogoSafeZone 除了区域本身还给出建议尺寸。
//
// SuggestedWidth/Height 是**单个** logo 的归一化上限，已经按区域高度和常见
// 横向锁定比留了余量 —— 直接铺满安全区会顶到边。
type LogoSafeZone struct {
	VisualRect

	Complexity      float64 `json:"complexity"`
	Background      string  `json:"background"`
	SuggestedWidth  float64 `json:"suggestedWidth"`
	SuggestedHeight float64 `json:"suggestedHeight"`
	Align           string  `json:"align"`
}

// TypographyProfile 是字体建议。
//
// Family 只能由 VLM 给（衬线/无衬线/手写是风格判断，不是像素统计），像素层
// 填不了就留空。其余字段都是算出来的：Weight 和描边跟着首选安全区的繁忙度走，
// FillColor 按 WCAG 对比度在候选字色里挑最高的那个。
type TypographyProfile struct {
	Family string `json:"family"`
	Weight int    `json:"weight"`
	Width  string `json:"width"`

	FillColor   string `json:"fillColor"`
	StrokeColor string `json:"strokeColor"`
	AccentColor string `json:"accentColor"`

	// StrokeWidth 是相对字号的比例，不是像素 —— 后端并不知道前端的渲染尺寸。
	StrokeWidth float64 `json:"strokeWidth"`
	Shadow      bool    `json:"shadow"`
	Distress    float64 `json:"distress"`

	// ContrastRatio 是 FillColor 相对首选安全区底色的 WCAG 对比度（1..21）。
	// 低于 4.5 时 Shadow 会被置真 —— 把判据一起给出来，前端不必复算。
	ContrastRatio float64 `json:"contrastRatio"`
}

// 分析来源。前端靠这个区分"查过且没有伪文字"和"根本没查"。
const (
	VisualSourcePixels    = "pixels"
	VisualSourcePixelsVLM = "pixels+vlm"
)

// 对比度与明暗的分级取值。
const (
	VisualContrastLow    = "low"
	VisualContrastMedium = "medium"
	VisualContrastHigh   = "high"

	VisualBrightnessDark     = "dark"
	VisualBrightnessBalanced = "balanced"
	VisualBrightnessLight    = "light"
)

// VisualAnalysis 是单张候选图的完整视觉分析，直接序列化成候选 JSON 的
// visualAnalysis 字段。
type VisualAnalysis struct {
	Width  int `json:"width"`
	Height int `json:"height"`

	Palette        []string `json:"palette"`
	PrimaryColor   string   `json:"primaryColor"`
	SecondaryColor string   `json:"secondaryColor"`

	Contrast      string  `json:"contrast"`
	ContrastValue float64 `json:"contrastValue"`

	Brightness      string  `json:"brightness"`
	BrightnessValue float64 `json:"brightnessValue"`

	Grain float64 `json:"grain"`

	// Texture 和 Style 由 VLM 填，像素层留空。
	Texture string `json:"texture"`
	Style   string `json:"style"`

	Typography TypographyProfile `json:"typographyProfile"`

	SubjectBounds []VisualRect   `json:"subjectBounds"`
	TextSafeZones []TextSafeZone `json:"textSafeZones"`
	LogoSafeZone  *LogoSafeZone  `json:"logoSafeZone"`

	// HasGeneratedText 只有 Source 为 pixels+vlm 时才有意义。Source 仍是
	// pixels 时它恒为 false，那是零值而不是结论。
	HasGeneratedText bool     `json:"hasGeneratedText"`
	GeneratedText    []string `json:"generatedText,omitempty"`

	Source string `json:"source"`
}

// VisualInspection 是 VLM 那一层能补上的字段。像素分析先跑，拿到 Inspection
// 再合并，所以 VLM 不可用时接口仍然返回一份完整的、诚实标注了来源的分析。
type VisualInspection struct {
	Texture string   `json:"texture"`
	Style   string   `json:"style"`
	Family  string   `json:"family"`
	HasText bool     `json:"hasGeneratedText"`
	Text    []string `json:"generatedText"`
}

// Merge 把 VLM 的判断并进像素分析。
func (a *VisualAnalysis) Merge(
	inspection VisualInspection,
) {

	a.Texture = inspection.Texture
	a.Style = inspection.Style

	// VLM 认不出字体族时不要把像素层已有的值抹成空串。
	if inspection.Family != "" {
		a.Typography.Family = inspection.Family
	}

	a.HasGeneratedText = inspection.HasText
	a.GeneratedText = inspection.Text
	a.Source = VisualSourcePixelsVLM
}
