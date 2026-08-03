package vision

import (
	"fmt"
	"math"
	"sort"
)

// rgb 是分析用的像素表示。全部计算都在 8 位空间做，避免在 uint32 和 uint8
// 之间来回换算时出现两套亮度定义。
type rgb struct {
	R uint8
	G uint8
	B uint8
}

func hexOf(color rgb) string {
	return fmt.Sprintf(
		"#%02x%02x%02x",
		color.R,
		color.G,
		color.B,
	)
}

// perceivedLuminance 是 ITU-R BT.601 的整数近似，和 composer.brightLuminance
// 用的是同一组系数。返回 0..255，用于明暗分级和直方图。
func perceivedLuminance(color rgb) int {
	return (299*int(color.R) +
		587*int(color.G) +
		114*int(color.B)) / 1000
}

// relativeLuminance 是 WCAG 2.1 的相对亮度，走 sRGB 逆伽马。
// 这个和 perceivedLuminance 是两件不同的事：分级用后者（便宜、和合成器一致），
// 算对比度必须用前者，否则挑出来的字色在深色底上看着够、实际不够。
func relativeLuminance(color rgb) float64 {
	channel := func(value uint8) float64 {
		normalized := float64(value) / 255

		if normalized <= 0.03928 {
			return normalized / 12.92
		}

		return math.Pow(
			(normalized+0.055)/1.055,
			2.4,
		)
	}

	return 0.2126*channel(color.R) +
		0.7152*channel(color.G) +
		0.0722*channel(color.B)
}

// contrastRatio 返回 WCAG 对比度，范围 1..21。
func contrastRatio(left rgb, right rgb) float64 {
	lighter := relativeLuminance(left)
	darker := relativeLuminance(right)

	if darker > lighter {
		lighter, darker = darker, lighter
	}

	return (lighter + 0.05) / (darker + 0.05)
}

// chroma 是 HSV 意义上的饱和幅度（0..255）。挑强调色时用它，而不是饱和度比值
// —— 比值会把接近黑的暗色也判成高饱和。
func chroma(color rgb) int {
	high := int(color.R)
	low := int(color.R)

	for _, value := range []int{
		int(color.G),
		int(color.B),
	} {
		if value > high {
			high = value
		}

		if value < low {
			low = value
		}
	}

	return high - low
}

// paletteEntry 是一个色簇。Weight 是该簇占的像素比例，调用方靠它区分主色和
// 只占百分之一的点缀色。
type paletteEntry struct {
	Color  rgb
	Weight float64
}

// extractPalette 用中位切分（median cut）取主色。
//
// 选它而不是 k-means 是因为确定性：k-means 要挑初始质心，同一张图两次跑可能
// 给出不同顺序的主色，而这份分析要写进数据库并被前端缓存，抖动是 bug。
// 中位切分没有随机性。
func extractPalette(
	pixels []rgb,
	count int,
) []paletteEntry {

	if len(pixels) == 0 || count <= 0 {
		return nil
	}

	// 先按 5 位量化合并近似色，切分时才不会被传感器噪点带偏。累计的是原始
	// 像素值，所以最终报出来的颜色不受量化影响。
	buckets := make(map[rgb]*sample, len(pixels)/4)

	for _, pixel := range pixels {
		key := rgb{
			R: pixel.R & 0xf8,
			G: pixel.G & 0xf8,
			B: pixel.B & 0xf8,
		}

		entry, ok := buckets[key]
		if !ok {
			entry = &sample{Color: key}
			buckets[key] = entry
		}

		entry.SumR += int64(pixel.R)
		entry.SumG += int64(pixel.G)
		entry.SumB += int64(pixel.B)
		entry.Count++
	}

	samples := make([]sample, 0, len(buckets))

	for _, entry := range buckets {
		samples = append(samples, *entry)
	}

	// map 迭代顺序随机，先定序，否则切分结果不可复现。
	sort.Slice(
		samples,
		func(left int, right int) bool {
			if samples[left].Count !=
				samples[right].Count {
				return samples[left].Count >
					samples[right].Count
			}

			return luminanceKey(samples[left].Color) <
				luminanceKey(samples[right].Color)
		},
	)

	boxes := [][]sample{samples}

	for len(boxes) < count {
		target := -1
		widest := 0

		for index, box := range boxes {
			if len(box) < 2 {
				continue
			}

			if spread := channelSpread(box); spread > widest {
				widest = spread
				target = index
			}
		}

		if target < 0 {
			break
		}

		box := boxes[target]
		axis := widestChannel(box)

		sort.Slice(
			box,
			func(left int, right int) bool {
				if channelOf(box[left].Color, axis) !=
					channelOf(box[right].Color, axis) {
					return channelOf(box[left].Color, axis) <
						channelOf(box[right].Color, axis)
				}

				return luminanceKey(box[left].Color) <
					luminanceKey(box[right].Color)
			},
		)

		// 按像素数的中位切，不是按元素个数 —— 否则一大片背景色会和一个
		// 噪点色平分秋色。
		total := 0
		for _, entry := range box {
			total += entry.Count
		}

		half := total / 2
		seen := 0
		split := 1

		for index, entry := range box {
			seen += entry.Count

			if seen >= half {
				split = index + 1
				break
			}
		}

		if split >= len(box) {
			split = len(box) - 1
		}

		if split < 1 {
			split = 1
		}

		boxes[target] = box[:split]
		boxes = append(
			boxes,
			box[split:],
		)
	}

	entries := make([]paletteEntry, 0, len(boxes))
	grand := float64(len(pixels))

	for _, box := range boxes {
		if len(box) == 0 {
			continue
		}

		var (
			sumR, sumG, sumB int64
			weight           int
		)

		for _, entry := range box {
			sumR += entry.SumR
			sumG += entry.SumG
			sumB += entry.SumB
			weight += entry.Count
		}

		if weight == 0 {
			continue
		}

		entries = append(
			entries,
			paletteEntry{
				Color: rgb{
					R: uint8(sumR / int64(weight)),
					G: uint8(sumG / int64(weight)),
					B: uint8(sumB / int64(weight)),
				},
				Weight: float64(weight) / grand,
			},
		)
	}

	sort.Slice(
		entries,
		func(left int, right int) bool {
			if entries[left].Weight !=
				entries[right].Weight {
				return entries[left].Weight >
					entries[right].Weight
			}

			return luminanceKey(entries[left].Color) <
				luminanceKey(entries[right].Color)
		},
	)

	return entries
}

func luminanceKey(color rgb) int {
	return int(color.R)<<16 |
		int(color.G)<<8 |
		int(color.B)
}

func channelOf(color rgb, axis int) int {
	switch axis {
	case 0:
		return int(color.R)

	case 1:
		return int(color.G)

	default:
		return int(color.B)
	}
}

func widestChannel(box []sample) int {
	_, axis := spreadAndAxis(box)
	return axis
}

func channelSpread(box []sample) int {
	spread, _ := spreadAndAxis(box)
	return spread
}

// sample 是一个量化色格。
//
// Color 是量化后的键，只用来决定切分轴；Sum* 累计的是**原始**像素值。
// 两者分开是必要的：靠量化键求平均会让上报的主色永远落在 8 的倍数上，
// 一个 #e87a1e 的橙色会变成 #e87818 —— 前端拿这个色去描边就和图上的颜色差一档。
type sample struct {
	Color rgb

	SumR  int64
	SumG  int64
	SumB  int64
	Count int
}

func spreadAndAxis(box []sample) (int, int) {
	if len(box) == 0 {
		return 0, 0
	}

	low := [3]int{255, 255, 255}
	high := [3]int{0, 0, 0}

	for _, entry := range box {
		for axis := 0; axis < 3; axis++ {
			value := channelOf(entry.Color, axis)

			if value < low[axis] {
				low[axis] = value
			}

			if value > high[axis] {
				high[axis] = value
			}
		}
	}

	widest := 0
	axis := 0

	for index := 0; index < 3; index++ {
		if spread := high[index] - low[index]; spread > widest {
			widest = spread
			axis = index
		}
	}

	return widest, axis
}

// pickTextColors 在给定底色上挑字色、描边色和强调色。
//
// 候选字色刻意包含近黑和近白：调色板里可能一个颜色都撑不到 4.5 的对比度，
// 这时候硬从调色板里选是在给前端一个读不清的建议。
func pickTextColors(
	background rgb,
	palette []paletteEntry,
) (fill rgb, stroke rgb, accent rgb, ratio float64) {

	candidates := []rgb{
		{R: 0x0a, G: 0x0a, B: 0x0a},
		{R: 0xf5, G: 0xf5, B: 0xf5},
	}

	for _, entry := range palette {
		candidates = append(
			candidates,
			entry.Color,
		)
	}

	fill = candidates[0]
	ratio = contrastRatio(fill, background)

	for _, candidate := range candidates[1:] {
		if value := contrastRatio(
			candidate,
			background,
		); value > ratio {
			fill = candidate
			ratio = value
		}
	}

	// 强调色取调色板里最鲜艳、且和字色区分得开的那个。区分不开就退回字色，
	// 不编一个新颜色出来。
	accent = fill
	best := -1

	for _, entry := range palette {
		if contrastRatio(
			entry.Color,
			fill,
		) < 1.6 {
			continue
		}

		if value := chroma(entry.Color); value > best {
			best = value
			accent = entry.Color
		}
	}

	// 描边的作用是把字从底图里托出来，所以取和字色对比最大的那个方向：
	// 深字配浅描边，浅字配深描边。
	if relativeLuminance(fill) < 0.5 {
		stroke = rgb{R: 0xf5, G: 0xf5, B: 0xf5}
	} else {
		stroke = rgb{R: 0x0a, G: 0x0a, B: 0x0a}
	}

	if best >= 0 &&
		contrastRatio(accent, fill) >= 3 {
		stroke = accent
	}

	return fill, stroke, accent, ratio
}
