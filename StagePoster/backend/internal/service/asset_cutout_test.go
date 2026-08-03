package service

import (
	"bytes"
	"image"
	"image/color"
	"image/jpeg"
	"image/png"
	"os"
	"path/filepath"
	"testing"
)

func writeImage(
	t *testing.T,
	name string,
	img image.Image,
	asJPEG bool,
) string {
	t.Helper()

	path := filepath.Join(t.TempDir(), name)

	var buffer bytes.Buffer

	if asJPEG {
		if err := jpeg.Encode(&buffer, img, nil); err != nil {
			t.Fatalf("encode jpeg: %v", err)
		}
	} else {
		if err := png.Encode(&buffer, img); err != nil {
			t.Fatalf("encode png: %v", err)
		}
	}

	if err := os.WriteFile(
		path,
		buffer.Bytes(),
		0o600,
	); err != nil {
		t.Fatalf("write image: %v", err)
	}

	return path
}

// 透明 PNG 的 logo 能正常叠加。
func TestImageHasAlphaTransparentPNG(
	t *testing.T,
) {
	t.Parallel()

	img := image.NewNRGBA(
		image.Rect(0, 0, 8, 8),
	)

	img.Set(0, 0, color.NRGBA{
		R: 255,
		A: 0,
	})

	path := writeImage(t, "logo.png", img, false)

	hasAlpha, err := imageHasAlpha(path)
	if err != nil {
		t.Fatalf("inspect alpha: %v", err)
	}

	if !hasAlpha {
		t.Fatal("transparent PNG reported as opaque")
	}
}

// 不透明的 JPEG logo 会以矩形压在海报上 —— 合成器不会自己抠背景。
// 这件事必须能被检出来，否则调用方无从得知。
func TestImageHasAlphaOpaqueJPEG(
	t *testing.T,
) {
	t.Parallel()

	img := image.NewRGBA(
		image.Rect(0, 0, 8, 8),
	)

	for y := 0; y < 8; y++ {
		for x := 0; x < 8; x++ {
			img.Set(x, y, color.RGBA{
				R: 10,
				G: 20,
				B: 30,
				A: 255,
			})
		}
	}

	path := writeImage(t, "logo.jpg", img, true)

	hasAlpha, err := imageHasAlpha(path)
	if err != nil {
		t.Fatalf("inspect alpha: %v", err)
	}

	if hasAlpha {
		t.Fatal("opaque JPEG reported as transparent")
	}
}

// 解不开的文件要报错，不能静默当成不透明。
func TestImageHasAlphaRejectsNonImage(
	t *testing.T,
) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), "junk.png")

	if err := os.WriteFile(
		path,
		[]byte("not an image"),
		0o600,
	); err != nil {
		t.Fatalf("write junk: %v", err)
	}

	if _, err := imageHasAlpha(path); err == nil {
		t.Fatal("expected decode error")
	}
}
