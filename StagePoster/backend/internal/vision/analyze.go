package vision

import (
	"fmt"
	"image"
	_ "image/gif"
	_ "image/jpeg"
	_ "image/png"
	"io"
	"math"
	"os"
	"sort"

	_ "golang.org/x/image/webp"
)

// 分析网格。1024x1536 的画布切成 16x24，每格 64x64 像素 —— 比一行标题还矮，
// 足够定位安全区，又不至于让"最大空白矩形"退化成逐像素搜索。
const (
	gridColumns = 16
	gridRows    = 24
)

// 安全区的最小尺寸。比这更小的空白对叠字没有意义，返回它只会让前端把标题塞进
// 一个放不下的洞里。
const (
	minZoneColumns = 5
	minZoneRows    = 2
	maxTextZones   = 4
)

// tile 是一格的累计量。
type tile struct {
	SumR int64
	SumG int64
	SumB int64

	SumLuma   int64
	SumLumaSq int64

	SumGradient int64

	Count int64
}

func (t tile) meanGradient() float64 {
	if t.Count == 0 {
		return 0
	}

	return float64(t.SumGradient) /
		float64(t.Count)
}

func (t tile) deviation() float64 {
	if t.Count == 0 {
		return 0
	}

	mean := float64(t.SumLuma) / float64(t.Count)

	variance := float64(t.SumLumaSq)/
		float64(t.Count) -
		mean*mean

	if variance < 0 {
		variance = 0
	}

	return math.Sqrt(variance)
}

// frame 是一张图的全部网格统计，外加从本图量出的颗粒底噪。
//
// 底噪必须是逐图的：胶片颗粒和手绘噪点会把每一格的梯度都抬高，用固定阈值判
// "繁忙"时整张图都会被判成不可压字。颗粒是均匀噪声，不和文字争夺注意力；真正
// 影响可读性的是**超出本图底噪的**局部结构。
//
// 实测（本机 244 张真实候选）底噪跨度 0.00-9.63，中位 0.80 —— 也就是最重颗粒
// 的图比最干净的图高出一个数量级。改成逐图扣底噪之前，抽查的 12 张里有 6 张
// 一个安全区都返回不出来。
type frame struct {
	tiles      [gridRows][gridColumns]tile
	grainFloor float64
}

// 繁忙度两个分量的归一化除数，在真实候选图上量出来的。
//
// 单格平均梯度的中位数在各图之间落在 1.1-17，单格最大值 13-62；单格亮度标准差
// 在平滑区是个位数，遇到硬明暗分界能到 105-117（半白半黑的理论极限是 127）。
// 除数取 18 和 70，让"有细节"和"有硬边"都落在 0.5 附近而不是一上来就饱和。
const (
	gradientDivisor  = 18
	deviationDivisor = 70

	// 上报的 Grain 用这个除数压到 0..1。底噪实测最大 9.63，除以 16 之后
	// 上限约 0.60 —— 留出余量，不让最常见的重颗粒图挤在 1.0 上分不出高低。
	grainDivisor = 16
)

// complexity 把"这块底图有多繁忙"压到 0..1。
//
// 两个分量缺一不可：梯度余量抓高频细节（树叶、人脸、纹理），亮度标准差抓大块
// 的明暗跨越（一半天空一半山体，梯度很低但压字照样看不清）。只用梯度会把强烈
// 的明暗分界判成"平坦"。两项各自先夹到 0..1 再加权 —— 否则标准差那一项能到
// 1.8，把梯度的权重实际抹掉。
func (f *frame) complexity(row int, column int) float64 {
	cell := f.tiles[row][column]

	if cell.Count == 0 {
		return 0
	}

	excess := cell.meanGradient() - f.grainFloor

	if excess < 0 {
		excess = 0
	}

	gradientTerm := clamp01(excess / gradientDivisor)

	deviationTerm := clamp01(
		cell.deviation() / deviationDivisor,
	)

	return clamp01(
		0.55*gradientTerm +
			0.45*deviationTerm,
	)
}

func (f *frame) meanColor(
	row int,
	column int,
) rgb {

	return f.tiles[row][column].mean()
}

func (t tile) mean() rgb {
	if t.Count == 0 {
		return rgb{}
	}

	return rgb{
		R: uint8(t.SumR / t.Count),
		G: uint8(t.SumG / t.Count),
		B: uint8(t.SumB / t.Count),
	}
}

// complexityValues 返回全图 384 格的繁忙度，已排序。分位阈值靠它算。
func (f *frame) complexityValues() []float64 {
	values := make(
		[]float64,
		0,
		gridRows*gridColumns,
	)

	for row := 0; row < gridRows; row++ {
		for column := 0; column < gridColumns; column++ {
			values = append(
				values,
				f.complexity(row, column),
			)
		}
	}

	sort.Float64s(values)

	return values
}

func quantile(
	sorted []float64,
	percent int,
) float64 {

	if len(sorted) == 0 {
		return 0
	}

	index := percent * (len(sorted) - 1) / 100

	if index < 0 {
		index = 0
	}

	if index >= len(sorted) {
		index = len(sorted) - 1
	}

	return sorted[index]
}

func clamp01(value float64) float64 {
	if value < 0 {
		return 0
	}

	if value > 1 {
		return 1
	}

	return value
}

// AnalyzeFile 读取一张主视觉并算出全部像素可得的分析。
//
// 返回的 Source 恒为 SourcePixels —— 伪文字这一项没查，HasGeneratedText 保持
// false 只是零值，不是结论。调用方拿到 VLM 结果后用 Merge 补上。
func AnalyzeFile(path string) (Analysis, error) {
	file, err := os.Open(path)
	if err != nil {
		return Analysis{},
			fmt.Errorf(
				"open key visual for analysis: %w",
				err,
			)
	}
	defer file.Close()

	decoded, _, err := image.Decode(file)
	if err != nil {
		return Analysis{},
			fmt.Errorf(
				"decode key visual for analysis: %w",
				err,
			)
	}

	return Analyze(decoded)
}

// Analyze 是纯函数版本，测试直接构造 image.Image 调它。
func Analyze(source image.Image) (Analysis, error) {
	bounds := source.Bounds()

	width := bounds.Dx()
	height := bounds.Dy()

	if width < gridColumns ||
		height < gridRows {
		return Analysis{},
			fmt.Errorf(
				"key visual is too small to analyze: %dx%d",
				width,
				height,
			)
	}

	tiles, histogram, palettePixels := scan(
		source,
		bounds,
	)

	current := &frame{
		tiles:      tiles,
		grainFloor: grainFloor(tiles),
	}

	analysis := Analysis{
		Width:  width,
		Height: height,
		Source: SourcePixels,
	}

	palette := extractPalette(palettePixels, 5)

	analysis.Palette = make(
		[]string,
		0,
		len(palette),
	)

	for _, entry := range palette {
		analysis.Palette = append(
			analysis.Palette,
			hexOf(entry.Color),
		)
	}

	if len(analysis.Palette) > 0 {
		analysis.PrimaryColor = analysis.Palette[0]
	}

	if len(analysis.Palette) > 1 {
		analysis.SecondaryColor = analysis.Palette[1]
	}

	analysis.Brightness,
		analysis.BrightnessValue,
		analysis.Contrast,
		analysis.ContrastValue = tone(histogram)

	analysis.Grain = round3(
		clamp01(current.grainFloor / grainDivisor),
	)

	analysis.SubjectBounds = subjectBounds(current)

	analysis.TextSafeZones = textSafeZones(
		current,
		analysis.SubjectBounds,
	)

	analysis.LogoSafeZone = logoSafeZone(
		analysis.TextSafeZones,
	)

	analysis.Typography = typography(
		current,
		analysis.TextSafeZones,
		palette,
		analysis.Grain,
	)

	return analysis, nil
}

// DominantColors 返回一张图的主色，按占比降序，形如 "#1a2b3c"。
//
// 和 Analyze 共用同一套中位切分，所以候选主视觉和上传素材报出来的主色是可比的
// —— 两边各写一套量化会让"参考图主色"和"成图主色"没法放在一起看。
func DominantColors(
	source io.Reader,
	count int,
) ([]string, error) {

	decoded, _, err := image.Decode(source)
	if err != nil {
		return nil, fmt.Errorf(
			"decode image for palette: %w",
			err,
		)
	}

	bounds := decoded.Bounds()

	width := bounds.Dx()
	height := bounds.Dy()

	if width <= 0 || height <= 0 {
		return nil, fmt.Errorf(
			"image has no pixels: %dx%d",
			width,
			height,
		)
	}

	// 采样步长按图幅自适应，控制在十万样本上下。素材可能是 4000x4000 的
	// 大图，全量扫描纯属浪费。
	stride := 1

	for (width/stride)*(height/stride) > 120000 {
		stride++
	}

	pixels := make(
		[]rgb,
		0,
		(width/stride+1)*(height/stride+1),
	)

	for y := 0; y < height; y += stride {
		for x := 0; x < width; x += stride {
			r, g, b, alpha := decoded.At(
				bounds.Min.X+x,
				bounds.Min.Y+y,
			).RGBA()

			// 透明像素不参与主色。Logo 和抠好的素材大片是透明的，把它们
			// 算进去会得出一个"主色是黑"的结论 —— RGBA() 对全透明像素
			// 返回的正是 0,0,0。
			if alpha < 0x8000 {
				continue
			}

			pixels = append(
				pixels,
				rgb{
					R: uint8(r >> 8),
					G: uint8(g >> 8),
					B: uint8(b >> 8),
				},
			)
		}
	}

	palette := extractPalette(pixels, count)

	colors := make([]string, 0, len(palette))

	for _, entry := range palette {
		colors = append(
			colors,
			hexOf(entry.Color),
		)
	}

	return colors, nil
}

// scan 单遍扫描原图，同时累计网格统计、全局亮度直方图和调色板采样。
//
// 只走一遍是有意的：1024x1536 有 157 万像素，image.Image.At 是接口调用，
// 走三遍就是三倍的接口开销。
func scan(
	source image.Image,
	bounds image.Rectangle,
) ([gridRows][gridColumns]tile, [256]int, []rgb) {

	var (
		tiles     [gridRows][gridColumns]tile
		histogram [256]int
	)

	width := bounds.Dx()
	height := bounds.Dy()

	// 调色板每 4 个像素取 1 个（两个方向），约 9.8 万样本 —— 主色比例的
	// 精度远超需要，成本只有全量的 1/16。
	const paletteStride = 4

	palettePixels := make(
		[]rgb,
		0,
		(width/paletteStride+1)*
			(height/paletteStride+1),
	)

	previousRow := make([]int, width)
	currentRow := make([]int, width)

	for y := 0; y < height; y++ {
		row := y * gridRows / height

		for x := 0; x < width; x++ {
			r, g, b, _ := source.At(
				bounds.Min.X+x,
				bounds.Min.Y+y,
			).RGBA()

			pixel := rgb{
				R: uint8(r >> 8),
				G: uint8(g >> 8),
				B: uint8(b >> 8),
			}

			luma := perceivedLuminance(pixel)

			currentRow[x] = luma
			histogram[luma]++

			if x%paletteStride == 0 &&
				y%paletteStride == 0 {
				palettePixels = append(
					palettePixels,
					pixel,
				)
			}

			gradient := 0

			if x > 0 {
				gradient += absInt(
					luma - currentRow[x-1],
				)
			}

			if y > 0 {
				gradient += absInt(
					luma - previousRow[x],
				)
			}

			column := x * gridColumns / width

			cell := &tiles[row][column]

			cell.SumR += int64(pixel.R)
			cell.SumG += int64(pixel.G)
			cell.SumB += int64(pixel.B)
			cell.SumLuma += int64(luma)
			cell.SumLumaSq += int64(luma) * int64(luma)
			cell.SumGradient += int64(gradient)
			cell.Count++
		}

		previousRow, currentRow = currentRow, previousRow
	}

	return tiles, histogram, palettePixels
}

func absInt(value int) int {
	if value < 0 {
		return -value
	}

	return value
}

// tone 从亮度直方图得出明暗和对比度。
//
// 对比度取 5/95 分位的跨度而不是最大减最小：一个过曝的高光像素或一颗死黑的
// 噪点就能让极值跨度顶到 255，那样每张图都是 "high"。
func tone(
	histogram [256]int,
) (string, float64, string, float64) {

	total := 0
	weighted := 0

	for value, count := range histogram {
		total += count
		weighted += value * count
	}

	if total == 0 {
		return BrightnessBalance, 0, ContrastLow, 0
	}

	mean := float64(weighted) /
		float64(total) / 255

	low := percentile(histogram, total, 5)
	high := percentile(histogram, total, 95)

	spread := float64(high-low) / 255

	brightness := BrightnessBalance

	switch {
	case mean < 0.35:
		brightness = BrightnessDark

	case mean > 0.65:
		brightness = BrightnessLight
	}

	contrast := ContrastLow

	switch {
	case spread > 0.60:
		contrast = ContrastHigh

	case spread > 0.35:
		contrast = ContrastMedium
	}

	return brightness,
		round3(mean),
		contrast,
		round3(spread)
}

func percentile(
	histogram [256]int,
	total int,
	percent int,
) int {

	cutoff := total * percent / 100
	seen := 0

	for value := 0; value < 256; value++ {
		seen += histogram[value]

		if seen >= cutoff {
			return value
		}
	}

	return 255
}

// grainFloor 量的是"最平坦的那批格子里还剩多少高频"。
//
// 平坦区按定义不该有细节，所以那里残留的梯度就是胶片颗粒/噪点本身。直接对全图
// 取高频会把主体的纹理算进来，那测的是主体复杂度，不是颗粒。
//
// 这里按**原始梯度**排序，不按 complexity —— complexity 本身要减掉底噪，
// 用它排序就成了循环定义。
func grainFloor(
	tiles [gridRows][gridColumns]tile,
) float64 {

	gradients := make(
		[]float64,
		0,
		gridRows*gridColumns,
	)

	for row := 0; row < gridRows; row++ {
		for column := 0; column < gridColumns; column++ {
			cell := tiles[row][column]

			if cell.Count == 0 {
				continue
			}

			gradients = append(
				gradients,
				cell.meanGradient(),
			)
		}
	}

	if len(gradients) == 0 {
		return 0
	}

	sort.Float64s(gradients)

	// 最平坦的四分之一。
	sampleSize := len(gradients) / 4
	if sampleSize < 1 {
		sampleSize = 1
	}

	sum := 0.0

	for _, value := range gradients[:sampleSize] {
		sum += value
	}

	return sum / float64(sampleSize)
}
