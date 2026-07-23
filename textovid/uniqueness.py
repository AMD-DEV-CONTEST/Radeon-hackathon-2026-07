"""
Textovid — Uniqueness Engine v2
Guarantees every generated comic is structurally and narratively distinct.
Expanded libraries for maximum variety in hackathon submissions.
"""

import random
import hashlib
from typing import Optional

# ── Plot Structure Library ──────────────────────────────────────────────
PLOT_STRUCTURES = [
    "Hero's Journey", "Reverse Chronology",
    "Frame Narrative (story within a story)",
    "Rashomon (multiple perspectives)", "Linear Three-Act",
    "Non-Linear Montage", "Epistolary (letters / journal entries)",
    "In Medias Res (start in the middle)",
    "Circular (ends where it begins, but changed)",
    "Parallel Storylines that converge",
    "Flashback-Heavy", "Unreliable Narrator",
    "Countdown / Ticking Clock", "Bait-and-Switch (false protagonist)",
    "Two-Timeline Split (past and present intercut)",
    "Escalating Stakes (each panel raises the tension)",
    "Ensemble Cast (multiple POV characters)",
    "The Long Con (plan revealed at the end)",
    "Chase Structure (relentless forward momentum)",
]

# ── Character Building Blocks ───────────────────────────────────────────
CHARACTER_ARCHETYPES = [
    "Reluctant Hero", "Trickster Mentor", "Cursed Scholar",
    "Rogue with a Heart of Gold", "AI Awakening", "Last of Their Kind",
    "Time-Displaced Warrior", "Gifted Child", "Fallen Noble",
    "Street-Level Detective", "Mad Scientist with Good Intentions",
    "Exiled Royalty", "Ghost Bound to the Living",
    "Soldier Who Refuses to Fight", "Archivist of Forbidden Knowledge",
    "Shape-Shifter with Identity Crisis", "Retired God",
    "Pacifist in a War Zone", "Engineer of Impossible Things",
]

CHARACTER_TRAITS = [
    "has a prosthetic arm that occasionally glitches",
    "can hear the emotions of inanimate objects",
    "is terrified of silence",
    "collects forgotten memories in glass jars",
    "was raised by a collective consciousness",
    "speaks only in metaphors",
    "has a photographic memory but can't forget trauma",
    "can taste lies",
    "is slowly becoming transparent",
    "carries a map to a place that doesn't exist yet",
    "dreams in reverse chronological order",
    "has a shadow that acts independently",
    "was once a villain who lost their memory",
    "communicates through music instead of words",
    "ages one year every time they use their power",
    "can see 5 seconds into the future, always",
    "is made of starlight compressed into human form",
    "has a tattoo that changes based on their emotional state",
    "cannot tell a lie but is forced to keep secrets",
    "leaves flowers growing wherever they walk",
    "sneezes small storms when nervous",
    "can read the history of any object by touching it",
    "has a mechanical heart powered by music",
    "only exists between sunset and sunrise",
    "bleeds ink instead of blood",
    "has wings that are invisible to everyone except children",
    "remembers every version of the timeline they've lived through",
    "can fold space like origami, but only paper-thin sheets",
    "has a voice that causes plants to grow or wilt",
]

# ── World-Building Elements ─────────────────────────────────────────────
SETTINGS = [
    "a city built inside the ribcage of a colossal fossil",
    "an underground ocean lit by bioluminescent jellyfish",
    "a floating marketplace above the clouds",
    "a forest where every tree is actually a sleeping person",
    "a library that contains books written by future civilizations",
    "a volcano that erupts with liquid crystal instead of lava",
    "a space station orbiting a dying star",
    "a village that resets every dawn — nobody remembers yesterday",
    "a desert where the sand is made of ground-up hourglasses",
    "a tower that extends through multiple dimensions",
    "an abandoned amusement park haunted by nostalgic AI",
    "a garden where plants grow overnight into architecture",
    "a frozen ocean with cities preserved beneath the ice",
    "a mountain range that is actually the spine of a buried god",
    "a subway network connecting parallel universes",
    "a cathedral made of frozen lightning",
    "a bazaar that sells bottled emotions",
    "an archipelago floating on a sea of liquid memories",
    "a prison with no walls, only an ever-shrinking sky",
    "a clockwork city that winds down every century",
    "a canyon where echoes become real after seven repetitions",
    "an island that migrates across the ocean following the moon",
    "a kingdom inside a snow globe the size of a continent",
    "a market where currency is traded memories",
    "a labyrinth that rearranges itself based on the walker's fears",
    "a reef made of sunken spaceships slowly becoming coral",
    "a village on the back of a turtle that only stops walking to sleep",
]

# ── Art-Style Modifier Keywords ─────────────────────────────────────────
STYLE_PROMPTS = {
    "Manga (Japanese comic)":            "manga style, black and white with screentones, dynamic action lines, expressive characters, Japanese comic art, ink wash, speed lines",
    "Western Comic (Marvel/DC style)":   "western comic book style, bold ink lines, vibrant colors, dramatic shading, superhero art, cel-shaded, dynamic poses, dramatic perspective",
    "Watercolor Illustration":           "watercolor illustration, soft washes, delicate color blending, painterly textures, ethereal atmosphere, visible brush strokes",
    "Pixel Art":                         "pixel art, 16-bit game aesthetic, limited color palette, crisp edges, retro gaming art style, dithering",
    "Film Noir":                         "film noir style, high contrast black and white, dramatic shadows, venetian blind lighting, detective aesthetic, fog",
    "Chibi / Kawaii":                    "chibi style, kawaii, cute exaggerated proportions, big sparkly eyes, pastel colors, adorable, round shapes",
    "Hyperrealistic Digital Art":        "hyperrealistic digital painting, photorealistic, intricate detail, cinematic lighting, concept art quality, 8k render",
    "Art Nouveau":                       "art nouveau style, flowing organic lines, ornate borders, Alphonse Mucha inspired, decorative patterns, botanical motifs",
    "Woodblock Print (Ukiyo-e)":         "Japanese ukiyo-e woodblock print style, flat colors, bold outlines, traditional composition, wave patterns, earth tones",
    "Pop Art":                           "pop art style, Andy Warhol inspired, bold primary colors, halftone dots, comic book Ben-Day dots, screen print aesthetic",
    "Grisaille (Monochrome)":            "grisaille monochrome painting, shades of grey, classical oil painting technique, dramatic chiaroscuro, renaissance style",
}

# ── Narrative Twist Library ─────────────────────────────────────────────
TWIST_TYPES = [
    "The mentor has been the villain all along",
    "The world they've been saving doesn't actually exist",
    "The protagonist and antagonist are the same person from different timelines",
    "The quest object was inside them the whole time",
    "Everyone they saved was already dead — they were freeing ghosts",
    "The 'monster' was trying to protect something precious",
    "Their power comes at a cost someone else is paying",
    "They're not the chosen one — they were a backup plan that got activated by mistake",
    "The enemy they've been fighting is future versions of themselves",
    "The entire adventure was a test, and they just passed",
    "The world resets, but this time they remember everything",
    "The side character was the real hero all along",
    "The protagonist was dead from the very first panel",
    "What they thought was reality was actually someone else's dream",
    "The prize they sought was a lie — but what they found instead was real",
    "Time moves backwards for the antagonist",
    "The artifact they carry is slowly rewriting their personality",
    "They've already won — the comic shows the aftermath of victory",
    "The villain's motivation was identical to the hero's",
    "The comic itself is a spell that traps the reader",
]


# ════════════════════════════════════════════════════════════════════════
#   PUBLIC FUNCTIONS
# ════════════════════════════════════════════════════════════════════════

def generate_unique_premise(
    genre: Optional[str] = None,
    sub_genre: Optional[str] = None,
    theme: Optional[str] = None,
    mood: Optional[str] = None,
) -> dict:
    """
    Build a one-of-a-kind creative premise by randomising
    plot structure, characters, setting mashup, and optional twist.
    """
    g = genre or random.choice(["Sci-Fi", "Fantasy", "Horror", "Mystery", "Drama",
                                 "Superhero", "Thriller", "Comedy", "Romance", "Slice-of-Life"])

    # ── Plot structure ──────────────────────────────────────────────────
    plot_structure = random.choice(PLOT_STRUCTURES)

    # ── Protagonist ─────────────────────────────────────────────────────
    archetype = random.choice(CHARACTER_ARCHETYPES)
    traits = random.sample(CHARACTER_TRAITS, k=2)

    # ── Setting mashup ──────────────────────────────────────────────────
    sA = random.choice(SETTINGS)
    sB = random.choice([s for s in SETTINGS if s != sA])
    setting = f"{sA}, intertwined with {sB}"

    # ── Optional twist ──────────────────────────────────────────────────
    has_twist = random.random() < 0.75
    twist = random.choice(TWIST_TYPES) if has_twist else None

    # ── Panel count per page (varies for visual dynamism) ───────────────
    panels_per_page_options = [3, 4, 4, 5, 6]
    panels_per_page = random.choice(panels_per_page_options)

    # ── Content fingerprint ────────────────────────────────────────────
    fp_raw = f"{g}|{plot_structure}|{archetype}|{sA}|{sB}|{traits}"
    fingerprint = hashlib.sha256(fp_raw.encode()).hexdigest()[:16]

    return {
        "genre": g,
        "sub_genre": sub_genre,
        "theme": theme,
        "mood": mood,
        "plot_structure": plot_structure,
        "protagonist": {
            "archetype": archetype,
            "traits": traits,
        },
        "setting": setting,
        "has_twist": has_twist,
        "twist": twist,
        "panels_per_page": panels_per_page,
        "fingerprint": fingerprint,
    }


def get_art_style_prompt(style_name: str) -> str:
    """Return the image-prompt keywords for a chosen art style."""
    return STYLE_PROMPTS.get(style_name, STYLE_PROMPTS["Western Comic (Marvel/DC style)"])


def randomize_panel_layout(num_panels: int) -> list:
    """
    Return a grid specification: list of rows, each row is a list of
    float column-weights that sum to 1.0.
    Uses non-uniform layouts for visual dynamism.
    """
    if num_panels <= 2:
        return [[1.0]] * num_panels
    if num_panels == 3:
        choice = random.choice(["wide_top", "wide_bottom", "equal"])
        if choice == "wide_top":
            return [[1.0], [0.5, 0.5]]
        if choice == "wide_bottom":
            return [[0.5, 0.5], [1.0]]
        return [[0.34, 0.33, 0.33]]
    if num_panels == 4:
        choice = random.choice(["grid", "feature_top", "feature_bottom", "cinematic"])
        if choice == "grid":
            return [[0.5, 0.5], [0.5, 0.5]]
        if choice == "feature_top":
            return [[1.0], [0.34, 0.33, 0.33]]
        if choice == "feature_bottom":
            return [[0.34, 0.33, 0.33], [1.0]]
        # cinematic: 2 panels stacked left, 2 stacked right
        return [[0.6, 0.4], [0.6, 0.4]]
    if num_panels == 5:
        return [[0.34, 0.33, 0.33], [0.55, 0.45]]
    if num_panels == 6:
        choice = random.choice(["grid33", "grid23", "grid32"])
        if choice == "grid33":
            return [[0.34, 0.33, 0.33], [0.34, 0.33, 0.33]]
        if choice == "grid23":
            return [[0.34, 0.33, 0.33], [0.5, 0.5]]
        return [[0.5, 0.5], [0.34, 0.33, 0.33]]
    # Generic grid for larger counts
    cols = min(num_panels, 3)
    layout = []
    placed = 0
    while placed < num_panels:
        row_count = min(cols, num_panels - placed)
        w = round(1.0 / row_count, 2)
        layout.append([w] * row_count)
        placed += row_count
    return layout