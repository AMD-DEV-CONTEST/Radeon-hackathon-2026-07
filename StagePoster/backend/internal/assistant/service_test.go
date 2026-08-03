package assistant

import (
	"testing"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

func TestMissingBriefFields(
	t *testing.T,
) {
	brief := domain.AISessionBrief{
		Event: domain.EventBrief{
			Title:  "Abyssal Kingdom",
			Artist: "Maverick",
			Date:   "2026-08-21",
			Time:   "20:00",
			Venue:  "Void Arena",
		},
		Visual: domain.VisualBrief{
			Style:      "dark fantasy editorial",
			Theme:      "abyssal gothic kingdom",
			MusicGenre: "gothic metal",
			Mood: []string{
				"epic",
			},
		},
	}

	missing := missingBriefFields(brief)

	if len(missing) != 0 {
		t.Fatalf(
			"expected complete brief, got %v",
			missing,
		)
	}
}

func TestMergeBriefPreservesKnownValues(
	t *testing.T,
) {
	current := domain.AISessionBrief{
		Event: domain.EventBrief{
			Title: "Existing Title",
			Date:  "2026-08-21",
		},
	}

	result := domain.AIBriefAgentResult{
		Event: domain.EventBrief{
			Artist: "Maverick",
			Venue:  "Void Arena",
		},
		Visual: domain.VisualBrief{
			Style:      "dark fantasy editorial",
			Theme:      "abyssal kingdom",
			MusicGenre: "gothic metal",
			Mood: []string{
				"epic",
				"mysterious",
			},
		},
	}

	merged := mergeBrief(current, result)

	if merged.Event.Title != "Existing Title" {
		t.Fatalf(
			"title was overwritten: %q",
			merged.Event.Title,
		)
	}

	if merged.Event.Artist != "Maverick" {
		t.Fatalf(
			"artist was not merged: %q",
			merged.Event.Artist,
		)
	}

	if merged.Visual.Theme != "abyssal kingdom" {
		t.Fatalf(
			"theme was not merged: %q",
			merged.Visual.Theme,
		)
	}
}

func TestApplyAssetBindings(
	t *testing.T,
) {
	brief := domain.AISessionBrief{}

	assets := []domain.AISessionAssetRecord{
		{
			AssetID: "asset_artist",
			Purpose: domain.AISessionAssetPurposeArtistLogo,
		},
		{
			AssetID: "asset_event",
			Purpose: domain.AISessionAssetPurposeEventLogo,
		},
		{
			AssetID: "asset_sponsor",
			Purpose: domain.AISessionAssetPurposeSponsorLogo,
		},
	}

	result := applyAssetBindings(
		brief,
		assets,
	)

	if result.Branding.ArtistLogoAssetID !=
		"asset_artist" {
		t.Fatal("artist logo was not bound")
	}

	if result.Branding.EventLogoAssetID !=
		"asset_event" {
		t.Fatal("event logo was not bound")
	}

	if len(
		result.Branding.SponsorLogoAssetIDs,
	) != 1 {
		t.Fatal("sponsor logo was not bound")
	}
}
