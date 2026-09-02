package poster

import (
	"errors"
	"fmt"
	"strings"

	"github.com/Ripped-sys/StagePoster/backend/internal/domain"
)

var ErrUnsupportedStyle = errors.New("unsupported poster style")

type Planner struct{}

func NewPlanner() *Planner {
	return &Planner{}
}

func (p *Planner) Plan(
	request domain.CreatePosterRequest,
) ([]domain.CandidateSpec, error) {
	style := strings.TrimSpace(request.Visual.Style)

	if style == "" {
		style = "metal-gothic-v1"
	}

	if style != "metal-gothic-v1" {
		return nil, fmt.Errorf(
			"%w: %s",
			ErrUnsupportedStyle,
			style,
		)
	}

	return []domain.CandidateSpec{
		{
			VariantKey:  "monumental-empty-throne",
			VariantName: "Monumental Throne",
			Motif:       "an empty monumental winged throne assembled from blackened iron, broken amplifier cabinets and cathedral stone",
			Composition: "strict central symmetry with one dominant monumental emblem",
			Camera:      "straight-on medium full shot at eye level, 50mm equivalent, natural perspective, emblem centered in the middle field",
			Materials: []string{
				"black ink engraving",
				"distressed silkscreen",
				"oxidized iron",
				"cracked cathedral stone",
			},
			Palette: []string{
				"ink black",
				"dirty ivory",
				"oxide red",
			},
			Lighting: "severe frontal contrast with a restrained eclipse glow",
		},
		{
			VariantKey:  "mechanical-wolf-reliquary",
			VariantName: "Mechanical Totem",
			Motif:       "a mechanical wolf reliquary constructed from speaker cones, chains, metal ribs and ritual audio machinery",
			Composition: "triangular altar composition with the totem rising through the central field",
			Camera:      "low-angle telephoto close crop, 85mm equivalent, compressed depth, worm's-eye view looking up at the totem",
			Materials: []string{
				"brushed metal",
				"photocopied punk texture",
				"scratched aluminium",
				"rough screen print ink",
			},
			Palette: []string{
				"charcoal black",
				"silver grey",
				"bone white",
			},
			Lighting: "hard directional side light with sharp metallic highlights",
		},
		{
			VariantKey:  "cathedral-eclipse-portal",
			VariantName: "Cathedral Eclipse",
			Motif:       "a towering black cathedral portal framing a fractured eclipse and a ritual monument made from stacked loudspeakers",
			Composition: "vertical architectural composition with deep perspective and a central eclipse",
			Camera:      "wide-angle vertical framing, 24mm equivalent, strong one-point perspective receding into the portal",
			Materials: []string{
				"weathered stone",
				"torn paper collage",
				"dry black ink",
				"distressed photocopy grain",
			},
			Palette: []string{
				"deep black",
				"smoke grey",
				"acid green accent",
			},
			Lighting: "backlit eclipse with deep architectural shadows",
		},
	}, nil
}

func (p *Planner) BuildPrompt(
	request domain.CreatePosterRequest,
	spec domain.CandidateSpec,
) string {
	// 主题只取 Visual.Theme。用 Event.Title 兜底等于把海报标题原文塞进
	// prompt——Z-Image 是能写字的模型，它会照着画出来，而标题本来是
	// composer 的活。缺主题时宁可不给，也不能拿标题顶。
	theme := strings.TrimSpace(request.Visual.Theme)

	concept := ""
	if theme != "" {
		// 不加引号。引号是“把这段字写进画面”的经典信号。
		concept = fmt.Sprintf(
			"\n\nVisual concept to illustrate: %s. Treat this concept strictly as subject matter to depict, never as text to render into the image.",
			theme,
		)
	}

	genre := strings.TrimSpace(request.Visual.MusicGenre)
	if genre == "" {
		genre = "underground heavy music"
	}

	mood := strings.Join(request.Visual.Mood, ", ")
	if mood == "" {
		mood = "dark, ritualistic, monumental"
	}

	preferredColors := strings.Join(
		request.Visual.PreferredColors,
		", ",
	)

	palette := strings.Join(spec.Palette, ", ")
	if preferredColors != "" {
		palette = preferredColors + ", informed by " + palette
	}

	materials := strings.Join(spec.Materials, ", ")

	camera := strings.TrimSpace(spec.Camera)
	if camera == "" {
		camera = "straight-on medium full shot at eye level, natural perspective"
	}

	return fmt.Sprintf(
		`A professional vertical 2:3 key visual for a %s music event.%s

Create one dominant symbolic motif: %s. Use %s. The atmosphere is %s.

The composition must keep the upper 18 percent visually quiet and low in detail, carry one powerful central key visual across the middle field, and keep the lower 22 percent equally quiet and low in detail. Both quiet bands must stay in the same color family as the artwork, carrying only soft tonal gradient — never a flat white panel, white box or blank rectangle. The central visual must remain readable from a distance and richly detailed at close range.

Camera and framing: %s.

Surface treatment and production language: %s. Color palette: %s. Lighting: %s.

The result must feel like original professional concert and festival artwork, not a movie screenshot, portrait, generic wallpaper, mockup, user interface or social-media meme.

No people, no performers, no faces, no human figures and no crowd. No readable typography, letters, numbers, Chinese characters, CJK glyphs, captions, event names, brand names, logos, signatures or watermarks. The artwork is only the background key visual. Accurate titles, logos, dates, venue details and ticket information will be added later by a deterministic layout system.`,
		genre,
		concept,
		spec.Motif,
		spec.Composition,
		mood,
		camera,
		materials,
		palette,
		spec.Lighting,
	)
}
