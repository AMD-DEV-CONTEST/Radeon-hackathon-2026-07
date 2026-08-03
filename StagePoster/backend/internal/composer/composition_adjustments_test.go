package composer

import (
	"testing"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

func TestNormalizeCompositionAdjustments(
	t *testing.T,
) {
	t.Parallel()

	adjustments := normalizeCompositionAdjustments(
		domain.CompositionAdjustments{
			Template: "cinematic_center",
		},
	)

	if adjustments.TitleOffsetRatio == 0 {
		t.Fatal("title offset was not applied")
	}

	if adjustments.PanelTopRatio < 0.80 {
		t.Fatalf(
			"panel top = %f",
			adjustments.PanelTopRatio,
		)
	}

	if adjustments.PanelTheme != "dark" {
		t.Fatalf(
			"panel theme = %q",
			adjustments.PanelTheme,
		)
	}
}
