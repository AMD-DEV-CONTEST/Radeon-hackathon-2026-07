package vision

import (
	"math"
	"sort"
)

func round3(value float64) float64 {
	return math.Round(value*1000) / 1000
}

// gridRect 是网格坐标下的矩形，右下开区间。
type gridRect struct {
	Column0 int
	Row0    int
	Column1 int
	Row1    int
}

func (g gridRect) empty() bool {
	return g.Column1 <= g.Column0 ||
		g.Row1 <= g.Row0
}

func (g gridRect) cells() int {
	if g.empty() {
		return 0
	}

	return (g.Column1 - g.Column0) *
		(g.Row1 - g.Row0)
}

// normalized 把网格矩形换成 0..1 坐标。
//
// 宽高由**两条边各自取整之后相减**得出，不是对宽度本身取整。否则相邻的两块
// 安全区会算出 0.001 的假重叠（行 10-17 和行 17-24：0.417+0.292 = 0.709 > 0.708），
// 前端只要做一次矩形相交判断就会误判成冲突。
func (g gridRect) normalized() Rect {
	x0 := round3(float64(g.Column0) / gridColumns)
	y0 := round3(float64(g.Row0) / gridRows)
	x1 := round3(float64(g.Column1) / gridColumns)
	y1 := round3(float64(g.Row1) / gridRows)

	return Rect{
		X: x0,
		Y: y0,
		W: round3(x1 - x0),
		H: round3(y1 - y0),
	}
}

// stats 返回该矩形内的平均繁忙度和平均底色。
func (g gridRect) stats(
	current *frame,
) (float64, rgb) {

	var (
		total            float64
		count            int
		sumR, sumG, sumB int64
		pixels           int64
	)

	for row := g.Row0; row < g.Row1; row++ {
		for column := g.Column0; column < g.Column1; column++ {
			total += current.complexity(row, column)
			count++

			cell := current.tiles[row][column]

			sumR += cell.SumR
			sumG += cell.SumG
			sumB += cell.SumB
			pixels += cell.Count
		}
	}

	if count == 0 || pixels == 0 {
		return 0, rgb{}
	}

	return round3(total / float64(count)),
		rgb{
			R: uint8(sumR / pixels),
			G: uint8(sumG / pixels),
			B: uint8(sumB / pixels),
		}
}

// subjectBounds 圈出主体所在的格子。
//
// 判据是"繁忙度显著高于本图平均"，而不是一个绝对阈值 —— 极简插画整张图的
// 梯度都低，绝对阈值会说它没有主体；写实照片整张图梯度都高，绝对阈值会说
// 整张都是主体。两种都错。
//
// 拿到连通块的包围盒之后必须收边。洪水填充会顺着一条细高光爬到画布角上，
// 包围盒于是覆盖大半张图 —— 而 subjectBounds 的契约是"前端文字不得覆盖"，
// 一个虚胖的框会把所有可用空间都宣布为禁区。
func subjectBounds(current *frame) []Rect {
	sorted := current.complexityValues()

	if len(sorted) == 0 {
		return []Rect{}
	}

	mean := 0.0

	for _, value := range sorted {
		mean += value
	}

	mean /= float64(len(sorted))

	variance := 0.0

	for _, value := range sorted {
		variance += (value - mean) * (value - mean)
	}

	deviation := math.Sqrt(
		variance / float64(len(sorted)),
	)

	// 全图繁忙度几乎没有起伏时（纯色背景、或者满幅均匀噪点），"主体"这个
	// 概念不成立。返回空数组，让前端知道没有需要避开的东西，而不是随便框一块。
	if deviation < 0.03 {
		return []Rect{}
	}

	threshold := mean + 0.8*deviation

	var busy [gridRows][gridColumns]bool

	for row := 0; row < gridRows; row++ {
		for column := 0; column < gridColumns; column++ {
			busy[row][column] =
				current.complexity(row, column) >= threshold
		}
	}

	components := connectedComponents(busy)

	// 面积下限 4% 的格子数，滤掉零散的高频噪点格。
	minimum := gridRows * gridColumns * 4 / 100
	if minimum < 2 {
		minimum = 2
	}

	kept := make([]gridRect, 0, len(components))

	for _, item := range components {
		if item.size < minimum {
			continue
		}

		box := tighten(current, item.box, threshold)

		// 收边之后仍然占掉大半张画布的框没有信息量 —— 它说的是"到处都别放
		// 字"，而前端无法照办。实测有一张候选的主体框正好是整幅 {0,0,1,1}，
		// 于是 384 格全部被判为禁区，安全区一块也返回不出来。
		box = capCoverage(
			current,
			box,
			gridRows*gridColumns*
				maxSubjectCoveragePercent/100,
		)

		if box.empty() {
			continue
		}

		kept = append(kept, box)
	}

	sort.Slice(
		kept,
		func(left int, right int) bool {
			if kept[left].cells() !=
				kept[right].cells() {
				return kept[left].cells() >
					kept[right].cells()
			}

			if kept[left].Row0 != kept[right].Row0 {
				return kept[left].Row0 < kept[right].Row0
			}

			return kept[left].Column0 <
				kept[right].Column0
		},
	)

	if len(kept) > 2 {
		kept = kept[:2]
	}

	// 收边之后仍然覆盖大半张画布，说明这张图没有可分辨的主体（满幅纹理）。
	// 只保留最大的那一块，剩下的空间还给文字。
	covered := 0

	for _, box := range kept {
		covered += box.cells()
	}

	if len(kept) > 1 &&
		covered*100 >= gridRows*gridColumns*60 {
		kept = kept[:1]
	}

	bounds := make([]Rect, 0, len(kept))

	for _, box := range kept {
		bounds = append(
			bounds,
			box.normalized(),
		)
	}

	return bounds
}

// tighten 从四条边往里剥，直到边线自己的平均繁忙度达到阈值。
//
// 只剥"弱边"：一条平均繁忙度低于阈值的边不属于主体，是洪水填充顺着细节爬出去
// 时捎带进来的。剥到只剩一格就停。
func tighten(
	current *frame,
	box gridRect,
	threshold float64,
) gridRect {

	lineMean := func(
		row0 int,
		column0 int,
		row1 int,
		column1 int,
	) float64 {

		total := 0.0
		count := 0

		for row := row0; row < row1; row++ {
			for column := column0; column < column1; column++ {
				total += current.complexity(row, column)
				count++
			}
		}

		if count == 0 {
			return 0
		}

		return total / float64(count)
	}

	for box.Row1-box.Row0 > 1 &&
		lineMean(
			box.Row0,
			box.Column0,
			box.Row0+1,
			box.Column1,
		) < threshold {

		box.Row0++
	}

	for box.Row1-box.Row0 > 1 &&
		lineMean(
			box.Row1-1,
			box.Column0,
			box.Row1,
			box.Column1,
		) < threshold {

		box.Row1--
	}

	for box.Column1-box.Column0 > 1 &&
		lineMean(
			box.Row0,
			box.Column0,
			box.Row1,
			box.Column0+1,
		) < threshold {

		box.Column0++
	}

	for box.Column1-box.Column0 > 1 &&
		lineMean(
			box.Row0,
			box.Column1-1,
			box.Row1,
			box.Column1,
		) < threshold {

		box.Column1--
	}

	return box
}

type component struct {
	box  gridRect
	size int
}

// 单个主体框允许占掉的画布比例上限。
const maxSubjectCoveragePercent = 55

// capCoverage 把过大的主体框贪心地剥到面积上限以内：每次比较四条边线的平均
// 繁忙度，剥掉最弱的那条。
//
// 贪心在这里是对的 —— 剥掉信息量最少的一边，剩下的就是最密的那一块核心。
// 逐边比较也保证结果确定，不依赖遍历顺序。
func capCoverage(
	current *frame,
	box gridRect,
	maxCells int,
) gridRect {

	if maxCells < 1 {
		maxCells = 1
	}

	for box.cells() > maxCells {
		if box.Row1-box.Row0 <= 1 &&
			box.Column1-box.Column0 <= 1 {
			break
		}

		type edge struct {
			mean  float64
			strip func(gridRect) gridRect
			ok    bool
		}

		lineMean := func(
			row0 int,
			column0 int,
			row1 int,
			column1 int,
		) float64 {

			total := 0.0
			count := 0

			for row := row0; row < row1; row++ {
				for column := column0; column < column1; column++ {
					total += current.complexity(row, column)
					count++
				}
			}

			if count == 0 {
				return 0
			}

			return total / float64(count)
		}

		tall := box.Row1-box.Row0 > 1
		wide := box.Column1-box.Column0 > 1

		edges := []edge{
			{
				mean: lineMean(
					box.Row0,
					box.Column0,
					box.Row0+1,
					box.Column1,
				),
				strip: func(value gridRect) gridRect {
					value.Row0++
					return value
				},
				ok: tall,
			},
			{
				mean: lineMean(
					box.Row1-1,
					box.Column0,
					box.Row1,
					box.Column1,
				),
				strip: func(value gridRect) gridRect {
					value.Row1--
					return value
				},
				ok: tall,
			},
			{
				mean: lineMean(
					box.Row0,
					box.Column0,
					box.Row1,
					box.Column0+1,
				),
				strip: func(value gridRect) gridRect {
					value.Column0++
					return value
				},
				ok: wide,
			},
			{
				mean: lineMean(
					box.Row0,
					box.Column1-1,
					box.Row1,
					box.Column1,
				),
				strip: func(value gridRect) gridRect {
					value.Column1--
					return value
				},
				ok: wide,
			},
		}

		weakest := -1

		for index, item := range edges {
			if !item.ok {
				continue
			}

			if weakest < 0 ||
				item.mean < edges[weakest].mean {
				weakest = index
			}
		}

		if weakest < 0 {
			break
		}

		box = edges[weakest].strip(box)
	}

	return box
}

// connectedComponents 是 4 连通的洪水填充，用显式栈而不是递归 —— 384 个格子
// 递归不会爆栈，但显式栈同样短，且不用去论证这件事。
func connectedComponents(
	busy [gridRows][gridColumns]bool,
) []component {

	var seen [gridRows][gridColumns]bool

	components := make([]component, 0, 8)

	type point struct {
		Column int
		Row    int
	}

	for row := 0; row < gridRows; row++ {
		for column := 0; column < gridColumns; column++ {
			if !busy[row][column] ||
				seen[row][column] {
				continue
			}

			stack := []point{
				{
					Column: column,
					Row:    row,
				},
			}

			seen[row][column] = true

			current := component{
				box: gridRect{
					Column0: column,
					Row0:    row,
					Column1: column + 1,
					Row1:    row + 1,
				},
			}

			for len(stack) > 0 {
				head := stack[len(stack)-1]
				stack = stack[:len(stack)-1]

				current.size++

				if head.Column < current.box.Column0 {
					current.box.Column0 = head.Column
				}

				if head.Column+1 > current.box.Column1 {
					current.box.Column1 = head.Column + 1
				}

				if head.Row < current.box.Row0 {
					current.box.Row0 = head.Row
				}

				if head.Row+1 > current.box.Row1 {
					current.box.Row1 = head.Row + 1
				}

				for _, offset := range [][2]int{
					{1, 0},
					{-1, 0},
					{0, 1},
					{0, -1},
				} {
					nextColumn := head.Column + offset[0]
					nextRow := head.Row + offset[1]

					if nextColumn < 0 ||
						nextColumn >= gridColumns ||
						nextRow < 0 ||
						nextRow >= gridRows {
						continue
					}

					if !busy[nextRow][nextColumn] ||
						seen[nextRow][nextColumn] {
						continue
					}

					seen[nextRow][nextColumn] = true

					stack = append(
						stack,
						point{
							Column: nextColumn,
							Row:    nextRow,
						},
					)
				}
			}

			components = append(
				components,
				current,
			)
		}
	}

	return components
}

// 安全区搜索用的分位阈值序列。
//
// 用**本图的分位**而不是固定常数，因为"干净"只有相对意义：写实夜景每一格都有
// 细节，固定阈值会一个安全区都返回不出来（实测 12 张里有 6 张如此）。分位保证
// 每张图都存在"最干净的那 30% 格子"，同时 SafeZone.Complexity 如实上报这块区域
// 到底有多干净 —— 前端据此决定加不加压暗层。
var zoneQuantiles = []int{30, 45, 60, 75}

// textSafeZones 找出可以安全压字的矩形。
//
// 反复取"当前最大的全安全矩形"再把它挖掉，而不是一次性返回所有极大矩形：
// 极大矩形集合会给出大量互相重叠的候选，前端拿到十几个重叠框没法用。
func textSafeZones(
	current *frame,
	subjects []Rect,
) []SafeZone {

	sorted := current.complexityValues()

	if len(sorted) == 0 {
		return []SafeZone{}
	}

	best := []SafeZone{}

	for _, percent := range zoneQuantiles {
		threshold := quantile(sorted, percent)

		zones := collectZones(
			current,
			subjects,
			threshold,
		)

		if len(zones) > len(best) {
			best = zones
		}

		// 拿到两块就够前端排标题和信息栏了，不必继续放宽。
		if len(best) >= 2 {
			break
		}
	}

	// 优先级：面积大、底图干净的排前面。海报惯例上标题在上、信息在下，所以
	// 同分时靠上的先给。
	sort.Slice(
		best,
		func(left int, right int) bool {
			leftScore := best[left].Area *
				(1 - best[left].Complexity)

			rightScore := best[right].Area *
				(1 - best[right].Complexity)

			if leftScore != rightScore {
				return leftScore > rightScore
			}

			return best[left].Y < best[right].Y
		},
	)

	for index := range best {
		best[index].Priority = index + 1
	}

	return best
}

func collectZones(
	current *frame,
	subjects []Rect,
	threshold float64,
) []SafeZone {

	var safe [gridRows][gridColumns]bool

	for row := 0; row < gridRows; row++ {
		for column := 0; column < gridColumns; column++ {
			if current.complexity(row, column) > threshold {
				continue
			}

			if insideAny(subjects, column, row) {
				continue
			}

			safe[row][column] = true
		}
	}

	zones := make([]SafeZone, 0, maxTextZones)

	for len(zones) < maxTextZones {
		box := largestSafeRect(
			safe,
			minZoneColumns,
			minZoneRows,
		)

		if box.empty() {
			break
		}

		complexity, background := box.stats(current)

		zone := SafeZone{
			VisualRect: box.normalized(),
			Complexity: complexity,
			Background: hexOf(background),
			Align:      alignFor(box),
		}

		zone.Area = round3(zone.VisualRect.Area())

		zones = append(zones, zone)

		for row := box.Row0; row < box.Row1; row++ {
			for column := box.Column0; column < box.Column1; column++ {
				safe[row][column] = false
			}
		}
	}

	return zones
}

func insideAny(
	subjects []Rect,
	column int,
	row int,
) bool {

	x := (float64(column) + 0.5) / gridColumns
	y := (float64(row) + 0.5) / gridRows

	for _, subject := range subjects {
		if x >= subject.X &&
			x < subject.X+subject.W &&
			y >= subject.Y &&
			y < subject.Y+subject.H {
			return true
		}
	}

	return false
}

func alignFor(box gridRect) string {
	center := (float64(box.Column0) +
		float64(box.Column1)) / 2 / gridColumns

	switch {
	case center < 0.42:
		return "left"

	case center > 0.58:
		return "right"

	default:
		return "center"
	}
}

// largestSafeRect 返回面积最大、且同时满足最小宽高的全安全矩形。
//
// 这里是穷举行区间，不是经典的"直方图 + 单调栈"。栈算法求的是**无约束**最大
// 矩形，把它的结果再拿去过最小宽高会错得很难看：一条 16x1 的窄带面积 16，
// 压过一块 5x3 的可用区（面积 15），于是栈算法交出窄带、调用方一过滤就判定
// "没有安全区"。
//
// 实测确实如此，而且症状是反直觉的：某张候选在分位 45% 时还能返回 1 块安全区，
// 放宽到 60% 和 75%（合格格子从 173 涨到 285）反而一块都返回不出来 —— 因为
// 新合格的零散格子把"最大面积矩形"变成了一条更宽更薄的带。
//
// 网格只有 16x24：276 个行区间乘 16 列，四千次布尔判断，穷举比论证栈算法在
// 带约束情形下的正确性便宜得多。
func largestSafeRect(
	safe [gridRows][gridColumns]bool,
	minColumns int,
	minRows int,
) gridRect {

	var (
		best    gridRect
		bestSum int
	)

	if minColumns < 1 {
		minColumns = 1
	}

	if minRows < 1 {
		minRows = 1
	}

	for row0 := 0; row0 < gridRows; row0++ {
		// solid[column] 表示 [row0, row1) 这段行区间里该列是否整列安全。
		var solid [gridColumns]bool

		for column := 0; column < gridColumns; column++ {
			solid[column] = true
		}

		for row1 := row0 + 1; row1 <= gridRows; row1++ {
			for column := 0; column < gridColumns; column++ {
				if !safe[row1-1][column] {
					solid[column] = false
				}
			}

			height := row1 - row0

			if height < minRows {
				continue
			}

			run := 0

			for column := 0; column <= gridColumns; column++ {
				if column < gridColumns &&
					solid[column] {
					run++
					continue
				}

				if run >= minColumns {
					if area := run * height; area > bestSum {
						bestSum = area

						best = gridRect{
							Column0: column - run,
							Row0:    row0,
							Column1: column,
							Row1:    row1,
						}
					}
				}

				run = 0
			}
		}
	}

	return best
}

// logoSafeZone 优先在画布下半部找一条干净的横带。
//
// 赞助商和主办方 logo 惯例上排在底部，把一块顶部空白当成 logo 区，前端照做
// 就会把 logo 压在标题该在的地方。找不到才退回首选文字安全区。
func logoSafeZone(zones []SafeZone) *LogoZone {
	if len(zones) == 0 {
		return nil
	}

	chosen := -1

	for index, zone := range zones {
		// 带的垂直中心落在下 35%。
		if zone.Y+zone.H/2 < 0.65 {
			continue
		}

		if chosen < 0 ||
			zone.W > zones[chosen].W ||
			(zone.W == zones[chosen].W &&
				zone.Complexity < zones[chosen].Complexity) {
			chosen = index
		}
	}

	if chosen < 0 {
		chosen = 0
	}

	zone := zones[chosen]

	// 建议高度取安全区高度的一半多一点并夹到 3%-8%：再高就压到相邻文字，
	// 再矮 logo 里的字号就糊了。宽度按常见横向锁定比 5:1 推，同时不超过
	// 安全区宽度的三分之一，好让一行放得下三个赞助商。
	suggestedHeight := clampFloat(
		zone.H*0.55,
		0.03,
		0.08,
	)

	suggestedWidth := math.Min(
		suggestedHeight*5,
		zone.W/3,
	)

	return &LogoZone{
		VisualRect:      zone.VisualRect,
		Complexity:      zone.Complexity,
		Background:      zone.Background,
		Align:           zone.Align,
		SuggestedWidth:  round3(suggestedWidth),
		SuggestedHeight: round3(suggestedHeight),
	}
}

func clampFloat(
	value float64,
	low float64,
	high float64,
) float64 {

	if value < low {
		return low
	}

	if value > high {
		return high
	}

	return value
}

// typography 把首选安全区的底色和繁忙度翻译成字体建议。
//
// Family 不在这里定 —— 衬线/无衬线/手写是风格判断，像素统计给不出来，留给 VLM。
func typography(
	current *frame,
	zones []SafeZone,
	palette []paletteEntry,
	grainValue float64,
) Typography {

	box := gridRect{
		Column0: 0,
		Row0:    0,
		Column1: gridColumns,
		Row1:    gridRows,
	}

	aspect := float64(gridColumns) / gridRows

	if len(zones) > 0 {
		zone := zones[0]

		box = gridRect{
			Column0: int(math.Round(zone.X * gridColumns)),
			Row0:    int(math.Round(zone.Y * gridRows)),
			Column1: int(math.Round((zone.X + zone.W) * gridColumns)),
			Row1:    int(math.Round((zone.Y + zone.H) * gridRows)),
		}

		if zone.H > 0 {
			aspect = zone.W / zone.H
		}
	}

	complexity, background := box.stats(current)

	fill, stroke, accent, ratio := pickTextColors(
		background,
		palette,
	)

	// 底图越乱，字越要重才压得住。500..900，按百取整。
	weight := int(
		math.Round((500+complexity*400)/100),
	) * 100

	if weight < 400 {
		weight = 400
	}

	if weight > 900 {
		weight = 900
	}

	width := "normal"

	switch {
	case aspect < 1.2:
		width = "condensed"

	case aspect > 3:
		width = "extended"
	}

	// 描边宽度是相对字号的比例，不是像素 —— 前端的渲染尺寸后端并不知道。
	strokeWidth := 0.0

	switch {
	case ratio < 4.5:
		strokeWidth = 0.06

	case ratio < 7:
		strokeWidth = 0.03
	}

	return Typography{
		Weight:        weight,
		Width:         width,
		FillColor:     hexOf(fill),
		StrokeColor:   hexOf(stroke),
		AccentColor:   hexOf(accent),
		StrokeWidth:   strokeWidth,
		Shadow:        ratio < 4.5 || complexity > 0.5,
		Distress:      grainValue,
		ContrastRatio: round3(ratio),
	}
}
