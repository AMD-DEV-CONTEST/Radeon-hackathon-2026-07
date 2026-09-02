package ai

import (
	"context"
	"fmt"
	"log"
	"strings"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

// 纹理 / 风格 / 字体族的闭集。
//
// 词表必须**提示词和服务端同时收口**，只收一边等于没收。视觉审查那边的
// issue.Code 就是只在提示词里给了两个示例值、服务端不校验，结果线上 94 条
// issue 里 53 条的取值落不到任何处理分支。这里从第一天就把两边都关上。
//
// 认不出来的取值归一化成空串，**绝不硬塞进某个合法值** —— 前端拿到空串知道
// "模型没给出判断"，拿到一个猜的值却会当成事实去选字体。
var (
	inspectionTextures = map[string]struct{}{
		"photographic":     {},
		"film_grain":       {},
		"hand_drawn_grain": {},
		"painterly":        {},
		"vector_flat":      {},
		"halftone_print":   {},
		"glitch_digital":   {},
		"smooth_gradient":  {},
	}

	inspectionStyles = map[string]struct{}{
		"vintage_print":     {},
		"modern_minimal":    {},
		"brutalist":         {},
		"psychedelic":       {},
		"cyberpunk":         {},
		"gothic":            {},
		"collage":           {},
		"documentary_photo": {},
		"illustrative":      {},
	}

	inspectionFamilies = map[string]struct{}{
		"expressive_serif": {},
		"geometric_sans":   {},
		"humanist_sans":    {},
		"condensed_sans":   {},
		"script":           {},
		"display_slab":     {},
	}
)

const inspectKeyVisualSystemPrompt = `You inspect a generated key visual for a music event poster.

The image is supposed to be BACKGROUND ART ONLY. All real text (event title, artist
names, date, venue, ticket info) and all logos are composited afterwards by a
deterministic renderer. Therefore ANY glyph-like mark in the image is a defect,
including marks that only look like writing.

Report these things and nothing else:

1. hasGeneratedText - true if the image contains letters, digits, Chinese
   characters, pseudo-letterforms, gibberish typography, a signature, a
   watermark, a wordmark, a barcode or a QR code. Look at signage, banners,
   clothing, posters-within-the-poster, and the bottom strip, which is where
   these most often appear. When you are unsure whether a mark is a glyph or
   just texture, answer true - a false "clean" verdict ships a broken poster,
   while a false alarm only costs one regeneration.
2. generatedText - the marks you found, transcribed as best you can. Empty
   array when hasGeneratedText is false.
3. texture - the dominant surface quality.
4. style - the overall visual idiom.
5. family - the type family that would sit best on this artwork.

Allowed texture values:
photographic, film_grain, hand_drawn_grain, painterly, vector_flat,
halftone_print, glitch_digital, smooth_gradient

Allowed style values:
vintage_print, modern_minimal, brutalist, psychedelic, cyberpunk, gothic,
collage, documentary_photo, illustrative

Allowed family values:
expressive_serif, geometric_sans, humanist_sans, condensed_sans, script,
display_slab

Use exactly one value from each list. If none of the listed values fits, return
an empty string for that field rather than inventing a new one.

Reply with a single JSON object and no prose:

{
  "hasGeneratedText": false,
  "generatedText": [],
  "texture": "film_grain",
  "style": "vintage_print",
  "family": "expressive_serif"
}`

// InspectKeyVisual 让视觉模型回答像素统计答不出的三件事，外加"图里有没有
// 伪文字"。
//
// 伪文字这一项由视觉模型承担而不是 OCR：项目刻意不引入 CGO，而所有 tesseract
// 绑定都要 CGO，外网也不通。用视觉模型是唯一可行的方案，不是偷懒的替代品 ——
// 而且它还能认出 OCR 认不出的东西：OCR 只找可识别字符，这里要找的恰恰是
// "看起来像字但不是任何语言"的那种笔画。
//
// 调用方必须自己先拿到 aiRuntime 的 GPU 许可 —— Acquire 会卸载 ComfyUI 模型，
// 由这里偷偷 Acquire 会在候选还在生成时把 ComfyUI 踢出显存。
func (service *Service) InspectKeyVisual(
	ctx context.Context,
	imagePath string,
) (
	domain.VisualInspection,
	Metrics,
	error,
) {

	imageURL, err := imageDataURL(imagePath)
	if err != nil {
		return domain.VisualInspection{},
			Metrics{},
			err
	}

	content := []map[string]any{
		{
			"type": "text",
			"text": "Inspect this key visual.",
		},
		{
			"type": "image_url",
			"image_url": map[string]string{
				"url": imageURL,
			},
		},
	}

	var result domain.VisualInspection

	metrics, err := service.client.CompleteJSON(
		ctx,
		[]Message{
			{
				Role:    "system",
				Content: inspectKeyVisualSystemPrompt,
			},
			{
				Role:    "user",
				Content: content,
			},
		},
		CompletionOptions{
			Temperature: 0.1,
			MaxTokens:   400,
		},
		&result,
	)
	if err != nil {
		return domain.VisualInspection{},
			metrics,
			fmt.Errorf(
				"inspect key visual: %w",
				err,
			)
	}

	NormalizeInspection(&result)

	return result, metrics, nil
}

// GatedInspector 把 InspectKeyVisual 包上 GPU 许可，供 poster 流程使用。
//
// 一次 Acquire 检查完所有图再释放。Acquire 会卸载 ComfyUI 模型（main.go 里
// 挂的 beforeAcquire），逐张拿许可就是逐张卸载/加载，三张候选要多付两轮。
type GatedInspector struct {
	runtime *Runtime
	service *Service
}

func NewGatedInspector(
	runtime *Runtime,
	service *Service,
) *GatedInspector {

	return &GatedInspector{
		runtime: runtime,
		service: service,
	}
}

// InspectKeyVisuals 检查多张主视觉。
//
// 单张失败不进结果 map 也不中断其余的：一张图解码失败没理由让另外两张也失去
// 伪文字检查。只有拿不到 GPU 许可才整体返回错误 —— 那时一张都做不了。
func (g *GatedInspector) InspectKeyVisuals(
	ctx context.Context,
	paths []string,
) (map[string]domain.VisualInspection, error) {

	if len(paths) == 0 {
		return map[string]domain.VisualInspection{}, nil
	}

	release, err := g.runtime.Acquire(ctx)
	if err != nil {
		return nil, fmt.Errorf(
			"acquire VLM for key visual inspection: %w",
			err,
		)
	}
	defer release()

	results := make(
		map[string]domain.VisualInspection,
		len(paths),
	)

	for _, path := range paths {
		inspection, _, err := g.service.InspectKeyVisual(
			ctx,
			path,
		)
		if err != nil {
			log.Printf(
				"inspect key visual %s: %v",
				path,
				err,
			)

			continue
		}

		results[path] = inspection
	}

	return results, nil
}

// NormalizeInspection 把模型的自由发挥折叠回闭集。
func NormalizeInspection(
	result *domain.VisualInspection,
) {

	result.Texture = canonicalInspectionValue(
		result.Texture,
		inspectionTextures,
	)

	result.Style = canonicalInspectionValue(
		result.Style,
		inspectionStyles,
	)

	result.Family = canonicalInspectionValue(
		result.Family,
		inspectionFamilies,
	)

	cleaned := make([]string, 0, len(result.Text))

	for _, value := range result.Text {
		value = strings.TrimSpace(value)

		if value == "" {
			continue
		}

		cleaned = append(cleaned, value)
	}

	result.Text = cleaned

	// 模型报了具体的伪文字内容，却把布尔位留成 false —— 以内容为准。
	// 反过来不成立：说了 true 但列不出内容是合理的（一团糊掉的笔画本来就
	// 转录不出来），那种情况必须保留 true。
	if len(result.Text) > 0 {
		result.HasText = true
	}
}

// canonicalInspectionValue 归一化单个取值：统一小写、把空格和连字符换成下划线，
// 再查闭集。查不到返回空串。
func canonicalInspectionValue(
	value string,
	allowed map[string]struct{},
) string {

	normalized := strings.ToLower(
		strings.TrimSpace(value),
	)

	normalized = strings.ReplaceAll(
		normalized,
		"-",
		"_",
	)

	normalized = strings.ReplaceAll(
		normalized,
		" ",
		"_",
	)

	if _, ok := allowed[normalized]; ok {
		return normalized
	}

	return ""
}
