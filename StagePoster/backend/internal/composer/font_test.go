package composer

import (
	"os"
	"strings"
	"testing"

	"golang.org/x/image/font/gofont/goregular"
)

const notoSansCJKRegular = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

func TestLoadFontBuiltinFallback(
	t *testing.T,
) {
	t.Parallel()

	parsed, err := loadFont("", goregular.TTF)
	if err != nil {
		t.Fatalf("builtin fallback failed: %v", err)
	}

	if parsed == nil {
		t.Fatal("builtin fallback returned nil font")
	}
}

// 内置 Go 字体没有任何 CJK 字形。这个断言保证探针本身是有效的：
// 如果哪天它对 goregular 也返回“字形齐全”，说明探针失灵了。
func TestBuiltinFontHasNoCJKGlyph(
	t *testing.T,
) {
	t.Parallel()

	parsed, err := parseFontData(goregular.TTF)
	if err != nil {
		t.Fatalf("parse builtin font: %v", err)
	}

	missing, err := missingCJKRune(parsed)
	if err != nil {
		t.Fatalf("probe builtin font: %v", err)
	}

	if missing == 0 {
		t.Fatal("builtin Go font unexpectedly reports full CJK coverage")
	}
}

func TestLoadFontNotoCJKCollection(
	t *testing.T,
) {
	t.Parallel()

	if _, err := os.Stat(
		notoSansCJKRegular,
	); err != nil {
		t.Skipf(
			"%s not installed",
			notoSansCJKRegular,
		)
	}

	parsed, err := loadFont(
		notoSansCJKRegular,
		goregular.TTF,
	)
	if err != nil {
		t.Fatalf("load Noto CJK collection: %v", err)
	}

	missing, err := missingCJKRune(parsed)
	if err != nil {
		t.Fatalf("probe Noto CJK: %v", err)
	}

	if missing != 0 {
		t.Fatalf(
			"Noto CJK reports missing glyph %q",
			missing,
		)
	}
}

func TestLoadFontMissingPathFails(
	t *testing.T,
) {
	t.Parallel()

	_, err := loadFont(
		"/nonexistent/font.ttf",
		goregular.TTF,
	)
	if err == nil {
		t.Fatal("expected an error for a missing font path")
	}

	if !strings.Contains(err.Error(), "read font") {
		t.Fatalf("unexpected error: %v", err)
	}
}

// 显式配置了一个没有中文字形的字体时必须报错，而不是静默渲染成豆腐块。
func TestLoadFontRejectsNonCJKConfiguredFont(
	t *testing.T,
) {
	t.Parallel()

	path := t.TempDir() + "/latin-only.ttf"

	if err := os.WriteFile(
		path,
		goregular.TTF,
		0o600,
	); err != nil {
		t.Fatalf("write temp font: %v", err)
	}

	_, err := loadFont(path, goregular.TTF)
	if err == nil {
		t.Fatal("expected a CJK coverage error")
	}

	if !strings.Contains(err.Error(), "no glyph for") {
		t.Fatalf("unexpected error: %v", err)
	}
}
