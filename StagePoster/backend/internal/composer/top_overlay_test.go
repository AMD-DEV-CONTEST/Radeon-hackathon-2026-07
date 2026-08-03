package composer

import (
	"image"
	"image/color"
	"testing"
)

func fillCanvas(
	width int,
	height int,
	shade uint8,
) *image.NRGBA {
	canvas := image.NewNRGBA(
		image.Rect(0, 0, width, height),
	)

	for y := 0; y < height; y++ {
		for x := 0; x < width; x++ {
			canvas.SetNRGBA(
				x,
				y,
				color.NRGBA{
					R: shade,
					G: shade,
					B: shade,
					A: 255,
				},
			)
		}
	}

	return canvas
}

func bandLuminanceAfterOverlay(
	t *testing.T,
	shade uint8,
	offsetRatio float64,
) float64 {
	t.Helper()

	canvas := fillCanvas(1024, 1536, shade)

	band := titleBandRect(
		canvas.Bounds(),
		offsetRatio,
	)

	composer := &Composer{}
	composer.drawTopOverlay(canvas, band)

	return brightLuminance(canvas, band)
}

// 底图本来就暗时，压暗形状必须和改造前完全一样——纯线性渐变、峰值 190。
// 这条是防回归的：不能为了救亮图把已经好看的深色海报改暗。
func TestTopOverlayUnchangedOnDarkKeyVisual(
	t *testing.T,
) {
	t.Parallel()

	canvas := fillCanvas(1024, 1536, 20)

	shape := planTopOverlay(
		canvas,
		titleBandRect(canvas.Bounds(), 0),
	)

	if shape.HoldUntil != 0 {
		t.Fatalf(
			"dark key visual should keep the pure linear ramp, got holdUntil=%d",
			shape.HoldUntil,
		)
	}

	if shape.PeakAlpha != titleScrimBaseAlpha {
		t.Fatalf(
			"peak alpha = %v, want %v",
			shape.PeakAlpha,
			titleScrimBaseAlpha,
		)
	}

	height := canvas.Bounds().Dy()

	if want := int(float64(height) * 0.24); shape.Height != want {
		t.Fatalf(
			"height = %d, want %d",
			shape.Height,
			want,
		)
	}
}

// 过曝天空是真实失效场景：cathedral-eclipse-portal 顶部接近纯白，
// 固定渐变到标题盒子底边已经衰减到压不住了。
func TestTopOverlayDarkensPaleKeyVisual(
	t *testing.T,
) {
	t.Parallel()

	for _, shade := range []uint8{
		200,
		235,
		255,
	} {
		got := bandLuminanceAfterOverlay(t, shade, 0)

		if got > titleScrimTargetLuminance {
			t.Fatalf(
				"shade %d: band luminance after overlay = %v, want <= %v",
				shade,
				got,
				titleScrimTargetLuminance,
			)
		}
	}
}

// TitleOffsetRatio 上限是 0.12，此时标题盒子会伸到画布 30% 处，
// 原来那条 24% 高的渐变根本盖不住它。
func TestTopOverlayCoversOffsetTitleBand(
	t *testing.T,
) {
	t.Parallel()

	canvas := fillCanvas(1024, 1536, 240)

	band := titleBandRect(canvas.Bounds(), 0.12)

	shape := planTopOverlay(canvas, band)

	if shape.Height < band.Max.Y {
		t.Fatalf(
			"overlay height %d does not cover title band bottom %d",
			shape.Height,
			band.Max.Y,
		)
	}

	if got := bandLuminanceAfterOverlay(
		t,
		240,
		0.12,
	); got > titleScrimTargetLuminance {
		t.Fatalf(
			"offset title band luminance = %v, want <= %v",
			got,
			titleScrimTargetLuminance,
		)
	}
}

// 均值会被暗部拉低，所以必须用高分位。半黑半白的条带上，
// 用均值算出来的压暗量救不了压在白色那半边的字。
func TestBrightLuminanceIgnoresDarkMajority(
	t *testing.T,
) {
	t.Parallel()

	canvas := fillCanvas(1024, 400, 0)

	for y := 0; y < 400; y++ {
		for x := 800; x < 1024; x++ {
			canvas.SetNRGBA(
				x,
				y,
				color.NRGBA{
					R: 250,
					G: 250,
					B: 250,
					A: 255,
				},
			)
		}
	}

	if got := brightLuminance(
		canvas,
		canvas.Bounds(),
	); got < 200 {
		t.Fatalf(
			"bright luminance = %v, a mean-based metric would report near 0",
			got,
		)
	}
}

func TestBrightLuminanceEmptyBand(
	t *testing.T,
) {
	t.Parallel()

	canvas := fillCanvas(64, 64, 200)

	if got := brightLuminance(
		canvas,
		image.Rect(500, 500, 600, 600),
	); got != 0 {
		t.Fatalf(
			"off-canvas band should report 0, got %v",
			got,
		)
	}
}
