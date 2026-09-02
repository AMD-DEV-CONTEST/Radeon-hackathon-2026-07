package vision

import (
	"bytes"
	"image"
	"image/color"
	"image/png"
	"testing"
)

// lcg 是个定死的线性同余发生器。测试要造"有噪点的区域"，但又必须每次跑出同一
// 张图 —— 用 math/rand 的全局源会让失败无法复现。
type lcg struct {
	state uint32
}

func (l *lcg) next() uint32 {
	l.state = l.state*1664525 + 1013904223
	return l.state
}

func (l *lcg) spread(amplitude int) int {
	return int(l.next()>>24)%(2*amplitude+1) - amplitude
}

func solidImage(
	width int,
	height int,
	fill color.RGBA,
) *image.RGBA {

	canvas := image.NewRGBA(
		image.Rect(0, 0, width, height),
	)

	for y := 0; y < height; y++ {
		for x := 0; x < width; x++ {
			canvas.SetRGBA(x, y, fill)
		}
	}

	return canvas
}

// noisyRect 在画布上糊一块高频噪声，用来扮演"主体"。
func noisyRect(
	canvas *image.RGBA,
	area image.Rectangle,
	base color.RGBA,
	amplitude int,
) {

	source := &lcg{state: 0x5eed}

	for y := area.Min.Y; y < area.Max.Y; y++ {
		for x := area.Min.X; x < area.Max.X; x++ {
			canvas.SetRGBA(
				x,
				y,
				color.RGBA{
					R: clampByte(int(base.R) + source.spread(amplitude)),
					G: clampByte(int(base.G) + source.spread(amplitude)),
					B: clampByte(int(base.B) + source.spread(amplitude)),
					A: 0xff,
				},
			)
		}
	}
}

func clampByte(value int) uint8 {
	if value < 0 {
		return 0
	}

	if value > 255 {
		return 255
	}

	return uint8(value)
}

func TestAnalyzeRejectsTinyImages(t *testing.T) {
	t.Parallel()

	_, err := Analyze(
		solidImage(
			4,
			4,
			color.RGBA{A: 0xff},
		),
	)

	if err == nil {
		t.Fatal(
			"expected an error for an image smaller than the analysis grid",
		)
	}
}

// 纯色图没有主体。返回一个"主体"框等于告诉前端有东西要避开，而实际上没有。
func TestSolidImageHasNoSubject(t *testing.T) {
	t.Parallel()

	analysis, err := Analyze(
		solidImage(
			256,
			384,
			color.RGBA{R: 0x20, G: 0x30, B: 0x40, A: 0xff},
		),
	)
	if err != nil {
		t.Fatal(err)
	}

	if len(analysis.SubjectBounds) != 0 {
		t.Fatalf(
			"solid image reported %d subject bounds: %v",
			len(analysis.SubjectBounds),
			analysis.SubjectBounds,
		)
	}

	if analysis.Contrast != ContrastLow {
		t.Fatalf(
			"contrast = %q, want %q",
			analysis.Contrast,
			ContrastLow,
		)
	}
}

func TestSubjectBoundsTrackTheNoisyRegion(t *testing.T) {
	t.Parallel()

	canvas := solidImage(
		256,
		384,
		color.RGBA{R: 0x18, G: 0x18, B: 0x1c, A: 0xff},
	)

	// 中间偏下的一块，占画布宽的一半、高的四分之一。
	noisyRect(
		canvas,
		image.Rect(64, 192, 192, 288),
		color.RGBA{R: 0x90, G: 0x80, B: 0x70, A: 0xff},
		70,
	)

	analysis, err := Analyze(canvas)
	if err != nil {
		t.Fatal(err)
	}

	if len(analysis.SubjectBounds) == 0 {
		t.Fatal(
			"a high-frequency block should be detected as a subject",
		)
	}

	subject := analysis.SubjectBounds[0]

	// 允许一格的误差（1/16 宽、1/24 高），网格量化决定了不可能精确。
	if subject.X > 0.30 ||
		subject.X+subject.W < 0.70 {
		t.Fatalf(
			"subject does not span the noisy block horizontally: %+v",
			subject,
		)
	}

	if subject.Y > 0.55 ||
		subject.Y+subject.H < 0.70 {
		t.Fatalf(
			"subject does not span the noisy block vertically: %+v",
			subject,
		)
	}
}

// 这条是整套分析对前端的核心承诺：安全区不许压在主体上。
func TestSafeZonesAvoidSubjects(t *testing.T) {
	t.Parallel()

	canvas := solidImage(
		256,
		384,
		color.RGBA{R: 0x10, G: 0x14, B: 0x20, A: 0xff},
	)

	noisyRect(
		canvas,
		image.Rect(48, 128, 208, 320),
		color.RGBA{R: 0xa0, G: 0x60, B: 0x40, A: 0xff},
		80,
	)

	analysis, err := Analyze(canvas)
	if err != nil {
		t.Fatal(err)
	}

	if len(analysis.TextSafeZones) == 0 {
		t.Fatal("expected at least one text safe zone")
	}

	for _, zone := range analysis.TextSafeZones {
		for _, subject := range analysis.SubjectBounds {
			if overlaps(zone.VisualRect, subject) {
				t.Fatalf(
					"safe zone %+v overlaps subject %+v",
					zone.VisualRect,
					subject,
				)
			}
		}
	}
}

// overlaps 判断两个归一化矩形是否真的相交。
//
// 必须留 epsilon。安全区靠"格子中心归属"互斥，所以相邻的两块会共享一条边，
// 而 X+W 在二进制浮点里算不出和邻块 X 完全相等的值（0.083+0.125 得到的是
// 0.20800000000000002，不是 0.208）。用严格小于号会把 244 张图里 3 张的相邻
// 边判成重叠 —— 那是浮点表示的产物，不是版式冲突。
const overlapEpsilon = 1e-6

func overlaps(left Rect, right Rect) bool {
	return left.X < right.X+right.W-overlapEpsilon &&
		right.X < left.X+left.W-overlapEpsilon &&
		left.Y < right.Y+right.H-overlapEpsilon &&
		right.Y < left.Y+left.H-overlapEpsilon
}

func TestSafeZonesDoNotOverlapEachOther(t *testing.T) {
	t.Parallel()

	canvas := solidImage(
		256,
		384,
		color.RGBA{R: 0x22, G: 0x22, B: 0x28, A: 0xff},
	)

	noisyRect(
		canvas,
		image.Rect(80, 160, 176, 256),
		color.RGBA{R: 0xd0, G: 0xc0, B: 0x30, A: 0xff},
		90,
	)

	analysis, err := Analyze(canvas)
	if err != nil {
		t.Fatal(err)
	}

	zones := analysis.TextSafeZones

	for i := 0; i < len(zones); i++ {
		for j := i + 1; j < len(zones); j++ {
			if overlaps(zones[i].VisualRect, zones[j].VisualRect) {
				t.Fatalf(
					"zones %d and %d overlap: %+v vs %+v",
					i,
					j,
					zones[i].VisualRect,
					zones[j].VisualRect,
				)
			}
		}
	}

	for index, zone := range zones {
		if zone.Priority != index+1 {
			t.Fatalf(
				"zone %d has priority %d",
				index,
				zone.Priority,
			)
		}

		if zone.X < 0 || zone.Y < 0 ||
			zone.X+zone.W > 1.0001 ||
			zone.Y+zone.H > 1.0001 {
			t.Fatalf(
				"zone %d is out of the normalized canvas: %+v",
				index,
				zone.VisualRect,
			)
		}
	}
}

// 这份分析要写进数据库并被前端缓存，所以同一张图必须永远得出同一个结果。
// 中位切分没有随机性，但 map 迭代有 —— 这条测试盯的是后者。
func TestAnalyzeIsDeterministic(t *testing.T) {
	t.Parallel()

	canvas := solidImage(
		256,
		384,
		color.RGBA{R: 0x30, G: 0x40, B: 0x50, A: 0xff},
	)

	noisyRect(
		canvas,
		image.Rect(32, 64, 224, 200),
		color.RGBA{R: 0xb0, G: 0x40, B: 0x90, A: 0xff},
		75,
	)

	first, err := Analyze(canvas)
	if err != nil {
		t.Fatal(err)
	}

	for attempt := 0; attempt < 5; attempt++ {
		again, err := Analyze(canvas)
		if err != nil {
			t.Fatal(err)
		}

		if len(again.Palette) != len(first.Palette) {
			t.Fatalf(
				"palette length changed: %d then %d",
				len(first.Palette),
				len(again.Palette),
			)
		}

		for index := range first.Palette {
			if first.Palette[index] !=
				again.Palette[index] {
				t.Fatalf(
					"palette entry %d changed: %s then %s",
					index,
					first.Palette[index],
					again.Palette[index],
				)
			}
		}

		if len(again.TextSafeZones) !=
			len(first.TextSafeZones) {
			t.Fatalf(
				"zone count changed: %d then %d",
				len(first.TextSafeZones),
				len(again.TextSafeZones),
			)
		}

		if again.Typography != first.Typography {
			t.Fatalf(
				"typography changed: %+v then %+v",
				first.Typography,
				again.Typography,
			)
		}
	}
}

// largestSafeRect 曾经用"直方图 + 单调栈"求无约束最大矩形，再由调用方过滤
// 最小宽高。这个用例就是那个组合失败的最小形状：一条 8x1 的带（面积 8）压过
// 一块 4x2 的可用区（面积 8，同分但满足约束），栈算法交出窄带，调用方一过滤
// 就报告"没有安全区"。
func TestLargestSafeRectRespectsMinimumDimensions(t *testing.T) {
	t.Parallel()

	var safe [gridRows][gridColumns]bool

	// 第 0 行整行安全 —— 很宽，但只有一行高。
	for column := 0; column < gridColumns; column++ {
		safe[0][column] = true
	}

	// 第 5-7 行的 0-4 列安全 —— 5 宽 3 高，满足 5x2 的下限。
	for row := 5; row < 8; row++ {
		for column := 0; column < 5; column++ {
			safe[row][column] = true
		}
	}

	box := largestSafeRect(safe, 5, 2)

	if box.empty() {
		t.Fatal(
			"a qualifying 5x3 block exists but nothing was returned",
		)
	}

	if box.Row1-box.Row0 < 2 {
		t.Fatalf(
			"returned a single-row band despite minRows=2: %+v",
			box,
		)
	}

	if box.Row0 != 5 ||
		box.Row1 != 8 ||
		box.Column0 != 0 ||
		box.Column1 != 5 {
		t.Fatalf(
			"expected the 5x3 block at rows 5-8, got %+v",
			box,
		)
	}
}

func TestLargestSafeRectEmptyGrid(t *testing.T) {
	t.Parallel()

	var safe [gridRows][gridColumns]bool

	if box := largestSafeRect(
		safe,
		5,
		2,
	); !box.empty() {
		t.Fatalf(
			"expected an empty rect, got %+v",
			box,
		)
	}
}

// 一个覆盖整幅画布的主体框等于"哪里都别放字"，前端无法照办。实测确实出现过
// {0,0,1,1}，于是 384 格全部成为禁区、安全区一块也返回不出来。
func TestCapCoverageShrinksAFullCanvasBox(t *testing.T) {
	t.Parallel()

	canvas := solidImage(
		256,
		384,
		color.RGBA{R: 0x40, G: 0x40, B: 0x40, A: 0xff},
	)

	noisyRect(
		canvas,
		image.Rect(0, 0, 256, 384),
		color.RGBA{R: 0x80, G: 0x80, B: 0x80, A: 0xff},
		60,
	)

	// 左上角额外加一块更强的噪声，给贪心一个明确的"最密核心"。
	noisyRect(
		canvas,
		image.Rect(0, 0, 96, 96),
		color.RGBA{R: 0x90, G: 0x50, B: 0x30, A: 0xff},
		110,
	)

	analysis, err := Analyze(canvas)
	if err != nil {
		t.Fatal(err)
	}

	limit := float64(maxSubjectCoveragePercent) / 100

	for _, subject := range analysis.SubjectBounds {
		if subject.Area() > limit+0.02 {
			t.Fatalf(
				"subject covers %.3f of the canvas, above the %.2f cap: %+v",
				subject.Area(),
				limit,
				subject,
			)
		}
	}
}

func TestPickTextColorsPrefersReadableFill(t *testing.T) {
	t.Parallel()

	white := rgb{R: 0xff, G: 0xff, B: 0xff}

	fill, _, _, ratio := pickTextColors(
		white,
		[]paletteEntry{
			{
				Color:  rgb{R: 0xee, G: 0xee, B: 0xee},
				Weight: 0.9,
			},
		},
	)

	// 调色板里只有一个几乎和白底一样的颜色。硬从调色板里挑就是给前端一个
	// 读不清的建议，所以必须退到近黑。
	if relativeLuminance(fill) > 0.2 {
		t.Fatalf(
			"fill %s is too light for a white background",
			hexOf(fill),
		)
	}

	if ratio < 4.5 {
		t.Fatalf(
			"contrast ratio %.2f is below the WCAG AA threshold",
			ratio,
		)
	}
}

func TestContrastRatioIsSymmetricAndBounded(t *testing.T) {
	t.Parallel()

	black := rgb{}
	white := rgb{R: 0xff, G: 0xff, B: 0xff}

	forward := contrastRatio(black, white)
	backward := contrastRatio(white, black)

	if forward != backward {
		t.Fatalf(
			"contrast ratio is not symmetric: %.4f vs %.4f",
			forward,
			backward,
		)
	}

	// 黑白是理论上限 21:1。
	if forward < 20.9 || forward > 21.1 {
		t.Fatalf(
			"black on white should be 21:1, got %.4f",
			forward,
		)
	}

	if same := contrastRatio(
		white,
		white,
	); same != 1 {
		t.Fatalf(
			"identical colors should be 1:1, got %.4f",
			same,
		)
	}
}

func TestExtractPaletteFindsBothColors(t *testing.T) {
	t.Parallel()

	pixels := make([]rgb, 0, 200)

	for index := 0; index < 150; index++ {
		pixels = append(
			pixels,
			rgb{R: 0x10, G: 0x20, B: 0x30},
		)
	}

	for index := 0; index < 50; index++ {
		pixels = append(
			pixels,
			rgb{R: 0xe0, G: 0xd0, B: 0x40},
		)
	}

	palette := extractPalette(pixels, 4)

	if len(palette) < 2 {
		t.Fatalf(
			"expected at least 2 clusters, got %d",
			len(palette),
		)
	}

	// 占比大的那个必须排在前面。
	if palette[0].Weight < palette[1].Weight {
		t.Fatalf(
			"palette is not sorted by weight: %+v",
			palette,
		)
	}

	if perceivedLuminance(palette[0].Color) >
		perceivedLuminance(palette[1].Color) {
		t.Fatalf(
			"the dominant cluster should be the dark one: %s then %s",
			hexOf(palette[0].Color),
			hexOf(palette[1].Color),
		)
	}
}

func TestExtractPaletteHandlesEmptyInput(t *testing.T) {
	t.Parallel()

	if palette := extractPalette(
		nil,
		4,
	); len(palette) != 0 {
		t.Fatalf(
			"expected no clusters, got %d",
			len(palette),
		)
	}
}

// Source 必须如实说明伪文字这项查过没有。把"没查过"当成"没有伪文字"是这套
// 接口最容易犯的错，所以零值和结论必须能区分。
func TestMergeMarksTheVLMSource(t *testing.T) {
	t.Parallel()

	analysis := Analysis{Source: SourcePixels}

	if analysis.Source != SourcePixels {
		t.Fatalf(
			"source = %q",
			analysis.Source,
		)
	}

	analysis.Merge(
		Inspection{
			Texture: "hand_drawn_grain",
			Style:   "vintage_print",
			Family:  "expressive_serif",
			HasText: true,
			Text:    []string{"AUGSST"},
		},
	)

	if analysis.Source != SourcePixelsVLM {
		t.Fatalf(
			"source after merge = %q, want %q",
			analysis.Source,
			SourcePixelsVLM,
		)
	}

	if !analysis.HasGeneratedText {
		t.Fatal("merge dropped the pseudo-text verdict")
	}

	if analysis.Typography.Family != "expressive_serif" {
		t.Fatalf(
			"family = %q",
			analysis.Typography.Family,
		)
	}
}

// VLM 认不出字体族时不该把像素层已有的值抹成空串。
func TestMergeKeepsFamilyWhenInspectionOmitsIt(t *testing.T) {
	t.Parallel()

	analysis := Analysis{
		Source: SourcePixels,
		Typography: Typography{
			Family: "geometric_sans",
		},
	}

	analysis.Merge(Inspection{Texture: "photographic"})

	if analysis.Typography.Family != "geometric_sans" {
		t.Fatalf(
			"family = %q, want it preserved",
			analysis.Typography.Family,
		)
	}
}

func TestQuantileClampsOutOfRangeInput(t *testing.T) {
	t.Parallel()

	sorted := []float64{0.1, 0.2, 0.3, 0.4}

	if value := quantile(sorted, 0); value != 0.1 {
		t.Fatalf("quantile 0 = %v", value)
	}

	if value := quantile(sorted, 100); value != 0.4 {
		t.Fatalf("quantile 100 = %v", value)
	}

	if value := quantile(nil, 50); value != 0 {
		t.Fatalf("quantile of nil = %v", value)
	}
}

// 透明像素必须被排除。Logo 和抠好的素材大片透明，而 color.RGBA() 对全透明像素
// 返回 0,0,0 —— 算进去就会得出"这个 logo 的主色是黑色"。
func TestDominantColorsIgnoresTransparentPixels(t *testing.T) {
	t.Parallel()

	canvas := image.NewRGBA(
		image.Rect(0, 0, 64, 64),
	)

	// 左侧全透明，右侧不透明的橙色。
	for y := 0; y < 64; y++ {
		for x := 0; x < 32; x++ {
			canvas.SetRGBA(
				x,
				y,
				color.RGBA{},
			)
		}

		for x := 32; x < 64; x++ {
			canvas.SetRGBA(
				x,
				y,
				color.RGBA{R: 0xe8, G: 0x7a, B: 0x1e, A: 0xff},
			)
		}
	}

	var buffer bytes.Buffer

	if err := png.Encode(
		&buffer,
		canvas,
	); err != nil {
		t.Fatal(err)
	}

	colors, err := DominantColors(&buffer, 4)
	if err != nil {
		t.Fatal(err)
	}

	if len(colors) == 0 {
		t.Fatal("expected at least one dominant color")
	}

	if colors[0] != "#e87a1e" {
		t.Fatalf(
			"dominant color = %s, want the opaque orange",
			colors[0],
		)
	}
}

func TestDominantColorsRejectsUndecodableInput(t *testing.T) {
	t.Parallel()

	if _, err := DominantColors(
		bytes.NewReader([]byte("not an image")),
		4,
	); err == nil {
		t.Fatal("expected a decode error")
	}
}

func TestLogoZonePrefersTheLowerHalf(t *testing.T) {
	t.Parallel()

	zones := []SafeZone{
		{
			VisualRect: Rect{X: 0, Y: 0.02, W: 1, H: 0.12},
			Complexity: 0.05,
			Align:      "center",
		},
		{
			VisualRect: Rect{X: 0, Y: 0.82, W: 0.8, H: 0.10},
			Complexity: 0.09,
			Align:      "center",
		},
	}

	zone := logoSafeZone(zones)

	if zone == nil {
		t.Fatal("expected a logo zone")
	}

	// 顶部那块更宽也更干净，但 logo 惯例在底部；选顶部会把 logo 压到标题位。
	if zone.Y < 0.5 {
		t.Fatalf(
			"logo zone landed in the top half: %+v",
			zone.VisualRect,
		)
	}

	if zone.SuggestedHeight <= 0 ||
		zone.SuggestedHeight > zone.H {
		t.Fatalf(
			"suggested height %.3f does not fit the zone height %.3f",
			zone.SuggestedHeight,
			zone.H,
		)
	}

	if zone.SuggestedWidth <= 0 ||
		zone.SuggestedWidth > zone.W {
		t.Fatalf(
			"suggested width %.3f does not fit the zone width %.3f",
			zone.SuggestedWidth,
			zone.W,
		)
	}
}

func TestLogoZoneFallsBackToTheBestZone(t *testing.T) {
	t.Parallel()

	zones := []SafeZone{
		{
			VisualRect: Rect{X: 0, Y: 0.02, W: 1, H: 0.12},
			Complexity: 0.05,
			Align:      "center",
		},
	}

	zone := logoSafeZone(zones)

	if zone == nil {
		t.Fatal(
			"with no lower-half zone the best zone should still be offered",
		)
	}

	if zone.Y != 0.02 {
		t.Fatalf(
			"expected the fallback zone, got %+v",
			zone.VisualRect,
		)
	}

	if logoSafeZone(nil) != nil {
		t.Fatal(
			"no zones at all must yield no logo zone",
		)
	}
}
