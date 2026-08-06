from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from prooflaunch_remix.four_a_campaign_distillation import (
    AgencyReference,
    AssertionKind,
    CampaignDistillationCase,
    CampaignSource,
    CorpusPartition,
    FourACampaignDistillationContract,
    LayerAssertion,
    REQUIRED_DISTILLATION_LAYERS,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "config" / "north_america_4a_research_cohort_2026.json"
EVIDENCE = ROOT / "evidence" / "v10" / "four-a-campaign-research-audit.json"
RETRIEVED_AT = "2026-07-30"
RANKING_URL = (
    "https://www.oneclub.org/awards/rankings/"
    "-archive/agency/2026/all/all/1/702"
)
ARCHIVE_URL = (
    "https://www.oneclub.org/awards/theoneshow/"
    "-archive/awards/2026/77/all/select"
)


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def source(
    source_id: str,
    url: str,
    locator: str,
    snapshot: object,
) -> CampaignSource:
    return CampaignSource(
        source_id=source_id,
        url=url,
        publisher="The One Club for Creativity",
        retrieved_at=RETRIEVED_AT,
        locator=locator,
        snapshot_sha256=digest(snapshot),
        snapshot_kind="metadata_transcription",
    )


AGENCY_ROWS = (
    ("area23-new-york", "Area 23", "New York", "US", 1, 927.0),
    ("vml-new-york", "VML", "New York", "US", 2, 814.50),
    ("rethink-toronto", "Rethink", "Toronto", "Canada", 3, 789.0),
    ("fcb-canada-toronto", "FCB Canada", "Toronto", "Canada", 4, 555.0),
    ("klick-health-toronto", "Klick Health", "Toronto", "Canada", 5, 429.0),
    (
        "tbwa-media-arts-lab-los-angeles",
        "TBWA Media Arts Lab",
        "Los Angeles",
        "US",
        6,
        402.0,
    ),
    ("mccann-new-york", "McCann", "New York", "US", 7, 358.0),
    ("ogilvy-new-york", "Ogilvy", "New York", "US", 8, 348.75),
    ("droga5-new-york", "Droga5, part of Accenture Song", "New York", "US", 9, 231.0),
    ("courage-toronto", "Courage Inc.", "Toronto", "Canada", 10, 207.0),
)


SEED_CASE_ROWS = (
    (
        "os26-fi093m",
        "area23-new-york",
        "Kyikatejê",
        "Gavião Kyikatejê Futebol Clube",
        "OS26_FI093M",
        "https://www.oneclub.org/awards/theoneshow/-award/64206/kyikatej/",
        "Film & Video / Film & Video for Good",
    ),
    (
        "os26-ce001g",
        "rethink-toronto",
        "Can't Unsee It",
        "Kraft Heinz",
        "OS26_CE001G",
        "https://www.oneclub.org/awards/theoneshow/-award/63776/cant-unsee-it/",
        "Creative Effectiveness / Consumer Packaged Goods",
    ),
    (
        "os26-ce002g",
        "vml-new-york",
        "Preserved Promos",
        "SC Johnson / Ziploc",
        "OS26_CE002G",
        "https://www.oneclub.org/awards/theoneshow/-award/63777/preserved-promos/",
        "Creative Effectiveness / Consumer Products",
    ),
    (
        "os26-ce003g",
        "rethink-toronto",
        "U up?",
        "IKEA",
        "OS26_CE003G",
        "https://www.oneclub.org/awards/theoneshow/-award/63778/u-upa/",
        "Creative Effectiveness / Retail",
    ),
    (
        "os26-ce010b",
        "vml-new-york",
        "Kleenex Score",
        "Kimberly-Clark / Kleenex",
        "OS26_CE010B",
        "https://www.oneclub.org/awards/theoneshow/-award/63785/kleenex-score/",
        "Creative Effectiveness / Consumer Products",
    ),
    (
        "os26-ce014m",
        "rethink-toronto",
        "See My Name",
        "Molson Coors Beverage Company",
        "OS26_CE014M",
        "https://www.oneclub.org/awards/theoneshow/-award/63789/see-my-name/",
        "Creative Effectiveness / Beverages",
    ),
    (
        "os26-ce021m",
        "courage-toronto",
        "Kyle F*cking Connor",
        "KFC Canada",
        "OS26_CE021M",
        "https://www.oneclub.org/awards/theoneshow/-award/63796/kyle-fcking-connor/",
        "Creative Effectiveness / Restaurants",
    ),
    (
        "os26-mi026b",
        "fcb-canada-toronto",
        "The Count",
        "SickKids Foundation",
        "OS26_MI026B",
        "https://www.oneclub.org/awards/theoneshow/-award/64548/the-count/",
        "Moving Image Craft & Production / Cinematography",
    ),
    (
        "os26-mi003g",
        "klick-health-toronto",
        "18 Months",
        "Second Nurture",
        "OS26_MI003G",
        "https://www.oneclub.org/awards/theoneshow/-award/64525/18-months/",
        "Moving Image Craft & Production / Animation",
    ),
    (
        "os26-be037m",
        "tbwa-media-arts-lab-los-angeles",
        "Someday",
        "Apple",
        "OS26_BE037M",
        "https://www.oneclub.org/awards/theoneshow/-award/63629/someday/",
        "Branded Entertainment / Long Form Video",
    ),
    (
        "os26-dm049m",
        "mccann-new-york",
        "Abracadabra: From Fan to Featured",
        "Mastercard",
        "OS26_DM049M",
        (
            "https://www.oneclub.org/awards/theoneshow/"
            "-award/64031/abracadabra-from-fan-to-featured/"
        ),
        "Direct Marketing / Social Media",
    ),
    (
        "os26-dm000g",
        "ogilvy-new-york",
        "Vaseline Verified",
        "Vaseline",
        "OS26_DM000G",
        "https://www.oneclub.org/awards/theoneshow/-award/63982/vaseline-verified/",
        "Direct Marketing / Best of Direct Marketing",
    ),
    (
        "os26-mi042m",
        "droga5-new-york",
        "Wake Up",
        "Xbox",
        "OS26_MI042M",
        "https://www.oneclub.org/awards/theoneshow/-award/64564/wake-up/",
        "Moving Image Craft & Production / Direction",
    ),
)

DISCOVERY_PAGES = (
    {
        "agency_id": "area23-new-york",
        "url": (
            "https://www.oneclub.org/awards/adcawards/"
            "-country/United%2BStates/2026/all/all"
        ),
        "years": [2026],
        "observed_unique_titles": [
            "Kyikatejê",
            "The EarliShow",
            "Zip Code Exam",
            "Cracked",
            "The Unnoticed Sponsorship",
        ],
    },
    {
        "agency_id": "vml-new-york",
        "url": "https://www.oneclub.org/awards/theoneshow/-network/VML/2026/all/all",
        "years": [2026],
        "observed_unique_titles": [
            "Preserved Promos",
            "Kleenex Score",
            "Name This OREO",
            "PainVisible",
            "Coca-Cola Classic",
        ],
    },
    {
        "agency_id": "rethink-toronto",
        "url": (
            "https://www.oneclub.org/awards/theoneshow/"
            "-independentnetwork/rethink/2026/all/all"
        ),
        "years": [2026],
        "observed_unique_titles": [
            "Can't Unsee It",
            "U up?",
            "See My Name",
            "Heinz Dipper",
            "Sleep Talk Reviews",
            "You can't have fries without Heinz",
            "Protest March Of The Penguins",
            "Too True Crime",
        ],
    },
    {
        "agency_id": "fcb-canada-toronto",
        "url": "https://www.oneclub.org/awards/theoneshow/-country/canada/2026/all/all",
        "years": [2026],
        "observed_unique_titles": ["The Count"],
    },
    {
        "agency_id": "klick-health-toronto",
        "url": (
            "https://www.oneclub.org/awards/theoneshow/"
            "-independantagency/Klick%20Health%20%5Bs%5D%20Toronto/2026"
        ),
        "years": [2026],
        "observed_unique_titles": ["18 Months", "Love Captured", "The Trial"],
    },
    {
        "agency_id": "tbwa-media-arts-lab-los-angeles",
        "url": "https://www.oneclub.org/awards/theoneshow/-search/tbwa",
        "years": [2026],
        "observed_unique_titles": [
            "A Decade of Partnership and Trust",
            "A Critter Carol",
            "Someday",
            "ATV Rebrand",
            "Shot on iPhone | Red Bull Island Hopper",
        ],
    },
    {
        "agency_id": "mccann-new-york",
        "url": (
            "https://www.oneclub.org/awards/theoneshow/"
            "-agency/McCann%20%5Bs%5D%20New%20York/2026"
        ),
        "years": [2026],
        "observed_unique_titles": [
            "Abracadabra: From Fan to Featured",
            "For Papa!",
            "Own Your Flow",
        ],
    },
    {
        "agency_id": "ogilvy-new-york",
        "url": (
            "https://www.oneclub.org/awards/theoneshow/"
            "-network/ogilvy%2Bgroup/2026/all/all"
        ),
        "years": [2026],
        "observed_unique_titles": ["Vaseline Verified", "Get Unready"],
    },
    {
        "agency_id": "droga5-new-york",
        "url": (
            "https://www.oneclub.org/awards/theoneshow/-agency/"
            "droga5%2C%20part%20of%20accenture%20song%20%5Bs%5D%20new%20york/2026"
        ),
        "years": [2026],
        "observed_unique_titles": [
            "Wake Up",
            "Obstructed Brews",
            "See You on the Road",
        ],
    },
    {
        "agency_id": "courage-toronto",
        "url": "https://www.oneclub.org/awards/theoneshow/-country/canada/2026/all/all",
        "years": [2026],
        "observed_unique_titles": [
            "Kyle F*cking Connor",
            "Winter Delivery Fleet",
        ],
    },
)


def observed(text: str, *source_ids: str) -> LayerAssertion:
    return LayerAssertion(
        text=text,
        kind=AssertionKind.OBSERVED,
        source_ids=tuple(source_ids),
        confidence=1.0,
    )


def inferred(text: str, *source_ids: str) -> LayerAssertion:
    return LayerAssertion(
        text=text,
        kind=AssertionKind.INFERRED,
        source_ids=tuple(source_ids),
        confidence=0.75,
    )


CASE_PROFILES = {
    "os26-ce001g": {
        "problem": "Keep a 150-year-old ketchup brand culturally relevant and central to a highly contested summer sales period.",
        "audience": "Give entertainment audiences a discovery they can recognize and discuss without interrupting the story.",
        "tension": "A famous brand has instant recognition but must earn relevance inside entertainment rather than force product placement.",
        "choice": "Use an entertainment partnership to make the brand's distinctive visual codes an audience discovery mechanism.",
        "idea": "Once a distinctive brand cue is noticed inside culture, the audience cannot stop seeing it.",
        "brand": "Heinz supplies the recognizable visual memory structure while the entertainment property supplies cultural attention.",
        "channels": "Entertainment partnership, film content, social discovery, PR, out-of-home and retail reinforcement.",
        "tool": "A reveal system prompts audiences to identify recurring brand-coded forms and share the recognition.",
        "craft": "Use a minimal, instantly recognizable visual code and stage the reveal so recognition feels audience-earned.",
        "constraints": "Partner IP approval, placement truth, trademark integrity, global recognizability, spoiler control and retail continuity.",
        "measure": "Measure incremental brand attribution, unaided recall, social discovery and sales against partnership exposure without the visual-reveal device.",
        "outcomes": "The 2026 archive records Gold creative-effectiveness recognition; the captured public detail does not expose a randomized causal design.",
        "failure": "Forced placement, weak brand-code recognition or claiming franchise reach as brand effect would fail.",
        "counterfactual": "Compare the discovery-led partnership with standard co-branded media, an unbranded visual puzzle and a matched-market holdout.",
        "transfer": "Turn a genuinely distinctive brand code into a participatory recognition game inside a culturally relevant partner system.",
        "specifics": "Heinz and partner IP, exact visual cue, scenes, copy, layouts, footage, retail assets and reported metrics remain non-transferable.",
        "channels_list": ("partnership", "film", "social", "pr", "out-of-home", "retail"),
    },
    "os26-ce010b": {
        "problem": "Reverse facial-tissue share decline after cold-and-flu demand waned and a better-funded competitor gained momentum.",
        "audience": "Help at-home movie viewers anticipate emotional intensity and prepare for cathartic viewing moments.",
        "tension": "Tissues are usually framed around illness, while entertainment creates an adjacent but under-owned need state.",
        "choice": "Create an emotional film-rating utility at the point where viewers choose what to watch.",
        "idea": "A tear-intensity score turns emotional data into useful preparation and a natural commerce trigger.",
        "brand": "Kleenex becomes the enabling companion while IMDb supplies trusted movie-decision context.",
        "channels": "IMDb integration, mobile experience, curated content, social, PR and Amazon commerce.",
        "tool": "An interactive tear-drop rating and curated title system links movie choice to frictionless product purchase.",
        "craft": "Make the rating native to the host platform, instantly readable and useful before adding the commerce path.",
        "constraints": "Rating methodology, partner integrity, data disclosure, mobile accessibility, inventory and purchase attribution.",
        "measure": "Use matched periods or markets to separate incremental share, new buyers and spend from seasonality, media and retailer effects.",
        "outcomes": "The case reports category share rising from 48% to 50%, first-week and week-four sales gains, 35% more new buyers and IMDb traffic gains; causal design is not published.",
        "failure": "An arbitrary score, intrusive shopping prompt or treating period-over-period lift as isolated causality would fail.",
        "counterfactual": "Compare the rating-plus-commerce system with ordinary tearjerker content, commerce-only placement and a matched untreated cohort.",
        "transfer": "Create a trusted micro-utility at the moment an adjacent need becomes predictable, then shorten the path to action.",
        "specifics": "Kleenex and IMDb identities, tear-drop design, film list, copy, commerce integration, assets and reported figures remain reference-only.",
        "channels_list": ("platform-integration", "mobile", "content", "social", "pr", "commerce"),
    },
    "os26-fi093m": {
        "problem": "Secure durable support for an Indigenous-owned football club that had no official sponsor despite on-field success.",
        "audience": "Give potential sponsors a credible reason and mechanism to support the club rather than merely notice it.",
        "tension": "Football has mass cultural visibility while Indigenous teams remain structurally under-supported.",
        "choice": "Turn the absence of sponsors into the visible organizing idea and a direct invitation to participate.",
        "idea": "Use the unfilled sponsorship system itself as the message and conversion surface.",
        "brand": "The club remains the protagonist; participating brands enter as long-term supporters.",
        "channels": "Film, earned media, influencer and journalist amplification, government endorsement, and sponsorship conversion.",
        "tool": "A public sponsorship appeal links cultural attention to concrete long-term commitments.",
        "craft": "Center Indigenous ownership, specificity and agency; make the missing commercial support visually legible.",
        "constraints": "Community consent, Indigenous consultation, factual representation, sponsorship terms and benefit governance.",
        "measure": "Track qualified sponsor leads, signed multi-year value, community-governed investment and sentiment against a passive-awareness baseline.",
        "outcomes": "The case reports more than R$500,000 in long-term sponsorships plus investment in youth development and facilities.",
        "failure": "Extractive storytelling, symbolic one-off support or making the agency the hero would invalidate the mechanism.",
        "counterfactual": "Compare an awareness film with no sponsorship path against the invitation-led system and a direct B2B outreach control.",
        "transfer": "Expose a missing market role and give institutions a concrete, accountable way to fill it.",
        "specifics": "The team identity, Indigenous culture, story, visuals, copy, sponsor terms and production assets remain non-transferable.",
        "channels_list": ("film", "earned-media", "influencer", "government-relations", "b2b"),
    },
    "os26-ce021m": {
        "problem": "Enter hockey culture against better-funded QSR competitors without trying to outspend them.",
        "audience": "Give Winnipeg hockey fans a sponsorship they can recognize, repeat, wear and celebrate.",
        "tension": "Category competitors dominate spend, while a player-name and brand-initial coincidence creates scarce cultural permission.",
        "choice": "Build the sponsorship around the exact intersection of KFC identity and Kyle Connor fandom.",
        "idea": "Convert a naming coincidence into a participatory cultural partnership rather than conventional logo placement.",
        "brand": "KFC supplies the semantic and physical system; Kyle Connor and fans remain the cultural carriers.",
        "channels": "Partnership, live experience, merchandise, retail, creator, social, PR and sports media.",
        "tool": "A sponsorship platform turns the KFC/KFC coincidence into shareable fan objects and moments.",
        "craft": "One immediately legible mnemonic spans naming, typography, objects, speech and fan ritual.",
        "constraints": "Talent rights, league rules, trademark use, retail operations, inventory and fan authenticity.",
        "measure": "Use matched markets and pre/post brand-health panels; separate incremental sales and affinity from earned-media proxies.",
        "outcomes": "The award case reports a 22% store-sales increase, 358% brand-affinity increase and $364M earned-media value; causal design is not published.",
        "failure": "A pun-only stunt, weak retail linkage or overclaiming media value as revenue would fail.",
        "counterfactual": "Compare standard player sponsorship, the naming system without retail activation, and a matched-market holdout.",
        "transfer": "Find a culturally native equivalence that can become a repeatable operating system across fan touchpoints.",
        "specifics": "Player identity, KFC marks, phrase, merchandise, league footage, event assets and reported figures remain reference-only.",
        "channels_list": ("partnership", "experiential", "retail", "social", "pr", "merchandise"),
    },
    "os26-mi026b": {
        "problem": "Mark SickKids' 150th anniversary in a fresh way that motivates donors while remaining true to the institution.",
        "audience": "Help donors feel that another birthday is a concrete outcome worth fighting for.",
        "tension": "An institutional milestone can become self-congratulatory, while patients are fighting for future birthdays.",
        "choice": "Reframe the anniversary count around each child's next birthday.",
        "idea": "Turn a corporate-age number into an emotionally precise human counting device.",
        "brand": "SickKids is the care institution enabling future birthdays, not the celebrant taking center stage.",
        "channels": "Long-form film, broadcast, cinema, digital video, fundraising and earned conversation.",
        "tool": "A patient-centered narrative converts institutional history into a donor-facing reason to act.",
        "craft": "Use restrained cinematography, real-person casting, sound, writing and temporal counting to preserve dignity.",
        "constraints": "Patient consent, health privacy, safeguarding, truthful representation, accessibility and fundraising compliance.",
        "measure": "Pre-register completed donations, donor quality, recall and emotional response against a conventional anniversary film.",
        "outcomes": "The official page documents the brief and award recognition; it does not publish causal fundraising effect sizes.",
        "failure": "Sentimental manipulation, patient objectification or an anniversary message with no donation path would fail.",
        "counterfactual": "Compare the patient-centered count with an institutional-history film and a direct-response-only control.",
        "transfer": "Translate an organization-centric milestone into the next meaningful outcome for the people it serves.",
        "specifics": "Patient stories, likenesses, SickKids identity, film, script, score and fundraising assets remain non-transferable.",
        "channels_list": ("film", "broadcast", "cinema", "digital", "fundraising"),
    },
    "os26-mi003g": {
        "problem": "Challenge the belief that only biological families are real families and reduce stigma around adoption.",
        "audience": "Help prospective parents and the public recognize the legal and emotional labor of building an adoptive family.",
        "tension": "The culturally dominant nine-month birth narrative hides much longer adoption journeys.",
        "choice": "Mirror adoption's legal and personal journey through an expanded gestational metaphor.",
        "idea": "Make eighteen months, rather than nine, the emotionally legible duration of becoming a family.",
        "brand": "Second Nurture enables adoption understanding and support without displacing the family's lived experience.",
        "channels": "Animation, long-form film, social, education and advocacy outreach.",
        "tool": "An animated family story makes an otherwise invisible process understandable and discussable.",
        "craft": "Use temporal mirroring, humane character animation and non-clinical visual metaphor without flattening complexity.",
        "constraints": "Family consent, child privacy, trauma-informed review, inclusive language, regional legal variation and accessibility.",
        "measure": "Test adoption-attitude change, qualified inquiries and comprehension against a factual explainer and untreated control.",
        "outcomes": "The official case states the cultural objective and narrative mechanism; causal adoption outcomes are not published.",
        "failure": "Universalizing one story, romanticizing hardship or implying adoption equivalence without nuance would fail.",
        "counterfactual": "Compare the story-led metaphor with a service explainer and a stigma-awareness message lacking the temporal device.",
        "transfer": "Make an invisible process legible through a respectful time or system metaphor grounded in lived experience.",
        "specifics": "Family story, character designs, animation, script, organization identity and case assets remain non-transferable.",
        "channels_list": ("animation", "film", "social", "education", "advocacy"),
    },
    "os26-be037m": {
        "problem": "Launch AirPods 4 distinctively in a saturated audio market without relying only on feature claims or media weight.",
        "audience": "Let people experience how product, music and design can change the emotional texture of everyday life.",
        "tension": "Technical parity makes feature demonstrations forgettable, while entertainment can lose product causality.",
        "choice": "Place emotional transformation and music-led storytelling at the center of the launch.",
        "idea": "A long-form entertainment experience makes the product's value felt before it is explained.",
        "brand": "AirPods are the enabling device inside the transformation rather than an interrupted product placement.",
        "channels": "Long-form film, Instagram, Apple Music, creator remixing, behind-the-scenes content and search behavior.",
        "tool": "A film plus platform-native derivatives invites audiences to remix and extend the launch.",
        "craft": "Sustain cinematic authorship while designing moments, music and gestures that can travel natively across social formats.",
        "constraints": "Product truth, music and talent rights, accessibility, platform cuts, global localization and derivative governance.",
        "measure": "Separate paid and organic reach; test product comprehension, incremental consideration and remix contribution against feature-demo creative.",
        "outcomes": "The case reports 20% of views from UGC, record account-level reach, music-chart movement and search/reshare signals without a randomized causal design.",
        "failure": "Beautiful entertainment with weak product attribution or engineered virality presented as business lift would fail.",
        "counterfactual": "Compare the full story system with a feature demonstration, film-only release and equivalent paid-media holdout.",
        "transfer": "Design a product demonstration as a felt transformation whose moments can become participatory media primitives.",
        "specifics": "Apple and AirPods identity, film, talent, music, choreography, dialogue, footage and metrics remain reference-only.",
        "channels_list": ("film", "instagram", "music-platform", "creator", "search", "earned-media"),
    },
    "os26-dm049m": {
        "problem": "Reintroduce Mastercard's Priceless platform to Gen Z through contemporary music behavior.",
        "audience": "Let fans participate in a cultural release instead of remaining passive spectators.",
        "tension": "Music discovery is bottom-up and participatory, while brand sponsorships often remain top-down exposure.",
        "choice": "Turn a major music-video debut into an open social casting system.",
        "idea": "Fans move from audience to featured collaborators through choreography and community participation.",
        "brand": "Mastercard provides the access mechanism and Priceless framing connecting participation to cultural proximity.",
        "channels": "GRAMMYs broadcast, TikTok, YouTube, creator tutorials, community management, BTS and fan-edit release.",
        "tool": "A social audition, choreography toolkit and responsive community operation culminate in a fan-starring edit.",
        "craft": "Create recognizable movement units and feedback loops that remain coherent from broadcast spectacle to user video.",
        "constraints": "Talent and music rights, participant releases, moderation, selection fairness, minors, accessibility and platform policy.",
        "measure": "Use exposed/control brand lift, follower quality, participation depth and new-card cohorts; do not equate views with preference.",
        "outcomes": "The case reports 1.4B views, nearly tripled followers and +29% Gen-Z brand lift; underlying study design is not published.",
        "failure": "Extracting fan labor, opaque selection or a final asset that sidelines participants would invalidate the promise.",
        "counterfactual": "Compare open casting with creator-only seeding, passive sponsorship and a fan-participation holdout.",
        "transfer": "Convert a sponsored cultural moment into a governed participation ladder with a visible consequential endpoint.",
        "specifics": "Mastercard, Lady Gaga, music, choreography, fan videos, costumes, footage, copy and reported results remain non-transferable.",
        "channels_list": ("broadcast", "tiktok", "youtube", "creator", "community", "film"),
    },
    "os26-dm000g": {
        "problem": "Help a legacy skin-care product create trustworthy value inside a chaotic ecosystem of viral hacks.",
        "audience": "Help creators and shoppers distinguish useful community practices from unsafe or unsupported claims.",
        "tension": "Mass participation creates discovery and misinformation simultaneously; brand authority can either clarify or suppress community knowledge.",
        "choice": "Verify selected community uses and make trust itself a creator and commerce system.",
        "idea": "A verification mark turns product truth into an expandable social proof and reward mechanism.",
        "brand": "Vaseline acts as evidence steward and commerce enabler rather than merely borrowing viral reach.",
        "channels": "TikTok, Instagram, creator collaboration, verification content, social commerce, retail taxonomy and PR.",
        "tool": "A verification workflow identifies practices, validates them and returns a recognizable trust signal and opportunity to creators.",
        "craft": "Use a legible trust icon, repeatable proof format and creator-first explanation without impersonating platform verification.",
        "constraints": "Claims substantiation, medical review, creator consent, conflicts disclosure, platform policy and regional regulation.",
        "measure": "Track verified-hack comprehension, unsafe-use reduction, creator participation and incremental commerce against unverified and brand-only controls.",
        "outcomes": "The official page reports broad creator/community adoption and award recognition; published causal commerce effect sizes are not available in the captured source.",
        "failure": "Rubber-stamping claims, hiding sponsorship, or turning community knowledge into uncredited brand property would fail.",
        "counterfactual": "Compare evidence-backed verification with ordinary influencer seeding and an icon-only placebo lacking validation.",
        "transfer": "Transform domain authority into a transparent verification and reward loop inside existing user behavior.",
        "specifics": "Vaseline identity, verification mark, creator content, claims, retail placements and campaign assets remain reference-only.",
        "channels_list": ("tiktok", "instagram", "creator", "commerce", "retail", "pr"),
    },
    "os26-mi042m": {
        "problem": "Reassert Xbox's cultural point of view while new game titles already supplied short-term attention.",
        "audience": "Remind players that games can restore active human feeling in environments designed for passive sedation.",
        "tension": "A platform wants cultural relevance, but category communications can collapse into product availability or nostalgia.",
        "choice": "Use a provocative brand film to dramatize the human state Xbox wants to awaken.",
        "idea": "Make passive modern life the antagonist and play the activation mechanism.",
        "brand": "Xbox stands for active play across devices rather than a single hardware feature.",
        "channels": "Brand film, gaming press, entertainment press, social discussion and cross-device product cues.",
        "tool": "A high-craft film supplies a repeatable cultural frame that product and community communications can inherit.",
        "craft": "Build a visually unsettling sedated world, then use rhythm, performance and device behavior to create an awakening contrast.",
        "constraints": "Platform and device truth, tone safety, VFX continuity, localization, accessibility and cut-down coherence.",
        "measure": "Test brand-health and play-intent change against product-only and nostalgia-led creative with matched media delivery.",
        "outcomes": "The case reports press reach, advertising-value equivalency, social reactions and brand-health movement without publishing causal effect sizes.",
        "failure": "Shock without product meaning, nostalgia substitution, or presenting reach proxies as brand causality would fail.",
        "counterfactual": "Compare the cultural film with a game-title montage, cross-device demonstration and equivalent-media holdout.",
        "transfer": "Externalize a category's passive default as an antagonist, then make the product behavior the resolution.",
        "specifics": "Xbox identity, film world, performances, devices, effects, copy, footage and reported metrics remain non-transferable.",
        "channels_list": ("film", "gaming-press", "entertainment-press", "social", "product"),
    },
}


def profile_layers(case_id: str) -> dict[str, LayerAssertion]:
    profile = CASE_PROFILES.get(case_id)
    if profile is None:
        return {}
    detail = f"oneclub-{case_id}-detail"
    discovery = f"oneclub-{case_id}-agency-discovery"
    return {
        "business_problem": observed(profile["problem"], detail),
        "audience_job": inferred(profile["audience"], detail),
        "evidence_and_tension": inferred(profile["tension"], detail),
        "strategy_choice": inferred(profile["choice"], detail),
        "big_idea_mechanism": inferred(profile["idea"], detail),
        "brand_role": inferred(profile["brand"], detail),
        "channel_system": inferred(profile["channels"], detail, discovery),
        "experience_or_tool_mechanism": inferred(profile["tool"], detail),
        "craft_grammar": inferred(profile["craft"], detail),
        "production_constraints": inferred(profile["constraints"], detail),
        "measurement_design": inferred(profile["measure"], detail),
        "reported_outcomes": observed(profile["outcomes"], detail),
        "failure_modes": inferred(profile["failure"], detail),
        "counterfactuals": inferred(profile["counterfactual"], detail),
        "transferable_principles": inferred(profile["transfer"], detail),
        "non_transferable_specifics": observed(
            profile["specifics"], detail, discovery
        ),
    }


def layers_for(case_id: str) -> dict[str, LayerAssertion]:
    archive = "oneclub-os26-creative-effectiveness"
    detail = f"oneclub-{case_id}-detail"
    if case_id == "os26-ce002g":
        return {
            "business_problem": observed(
                "Make food-storage utility commercially salient while reducing coupon-expiry friction.",
                detail,
            ),
            "audience_job": inferred(
                "Help value-seeking grocery shoppers recover value from expired food promotions.",
                detail,
            ),
            "evidence_and_tension": observed(
                "The case links widespread coupon use with extremely low redemption and difficult expiry tracking.",
                detail,
            ),
            "strategy_choice": inferred(
                "Turn a product promise about preservation into a transaction-level savings mechanism.",
                detail,
            ),
            "big_idea_mechanism": inferred(
                "Preserve the promotion as well as the food.",
                detail,
            ),
            "brand_role": observed(
                "Ziploc is required in the cart and acts as the enabling product.",
                detail,
            ),
            "channel_system": observed(
                "Mobile commerce, influencer activity, social and PR form the reported channel system.",
                detail,
            ),
            "experience_or_tool_mechanism": observed(
                "A mobile experience converts eligible expired food promotions into grocery savings.",
                detail,
            ),
            "craft_grammar": inferred(
                "Use a simple semantic bridge between expiry, preservation and saving.",
                detail,
            ),
            "production_constraints": inferred(
                "Coupon validation, retailer integration, offer abuse prevention and cart eligibility must remain reliable.",
                detail,
            ),
            "measurement_design": inferred(
                "Pre-register redemption, incremental buyers, sales lift and channel benchmarks against matched baselines.",
                detail,
            ),
            "reported_outcomes": observed(
                "The award case reports sales growth, new shoppers and benchmark-exceeding social and PR response without publishing causal effect sizes.",
                detail,
            ),
            "failure_modes": inferred(
                "A discount-only execution would weaken brand meaning; false eligibility or attribution would break trust.",
                detail,
            ),
            "counterfactuals": inferred(
                "Compare expired-promotion recovery against an equivalent ordinary Ziploc discount and a no-offer holdout.",
                detail,
            ),
            "transferable_principles": inferred(
                "Translate a brand promise into a useful market mechanism at the moment the problem occurs.",
                detail,
            ),
            "non_transferable_specifics": observed(
                "Campaign title, Ziploc identity, exact offer, case imagery and executional assets remain reference-only.",
                archive,
                detail,
            ),
        }
    if case_id == "os26-ce003g":
        return {
            "business_problem": observed(
                "Increase mattress sales and strengthen IKEA's sleep authority.",
                detail,
            ),
            "audience_job": observed(
                "Reach awake, sleep-deprived consumers at the moment poor sleep is felt.",
                detail,
            ),
            "evidence_and_tension": inferred(
                "The media moment and the product need coincide late at night, but conventional sales messaging is easy to ignore.",
                detail,
            ),
            "strategy_choice": observed(
                "Reframe a familiar late-night message as an immediate sleep solution.",
                detail,
            ),
            "big_idea_mechanism": inferred(
                "Subvert cultural shorthand so the reveal is both relevant and transactional.",
                detail,
            ),
            "brand_role": observed(
                "IKEA supplies the mattress solution and discount at response time.",
                detail,
            ),
            "channel_system": observed(
                "Late-night direct messages connect cultural entry, interaction and conversion.",
                detail,
            ),
            "experience_or_tool_mechanism": observed(
                "Respondents receive an immediate mattress discount.",
                detail,
            ),
            "craft_grammar": inferred(
                "Use brevity, timing, conversational tension and a brand-safe reveal.",
                detail,
            ),
            "production_constraints": inferred(
                "Consent, platform policy, targeting, frequency, localisation and late-night brand safety are hard constraints.",
                detail,
            ),
            "measurement_design": inferred(
                "Compare incremental response, qualified traffic and mattress conversion against time-matched conventional messages.",
                detail,
            ),
            "reported_outcomes": observed(
                "The public case describes the mechanism as an immediate sales driver but does not expose causal effect sizes.",
                detail,
            ),
            "failure_modes": inferred(
                "Untimely delivery, creepy targeting, weak reveal or offer-only framing would destroy the idea.",
                detail,
            ),
            "counterfactuals": inferred(
                "Test the same offer with neutral copy, daytime delivery and no-discount variants.",
                detail,
            ),
            "transferable_principles": inferred(
                "Align cultural syntax, need-state timing and a one-step conversion path.",
                detail,
            ),
            "non_transferable_specifics": observed(
                "Campaign title, exact phrase, IKEA identity, discount and creative assets remain reference-only.",
                archive,
                detail,
            ),
        }
    if case_id == "os26-ce014m":
        return {
            "business_problem": inferred(
                "Increase meaningful brand participation in women's hockey without taking attention from players.",
                detail,
            ),
            "audience_job": observed(
                "Make player names visible during play.",
                detail,
            ),
            "evidence_and_tension": observed(
                "The usual jersey placement made names difficult to see while sponsor space was prominent.",
                detail,
            ),
            "strategy_choice": observed(
                "Use paid sponsorship space to change the jersey system rather than add a conventional message.",
                detail,
            ),
            "big_idea_mechanism": inferred(
                "Brand visibility is deliberately sacrificed to create athlete visibility.",
                detail,
            ),
            "brand_role": observed(
                "Molson uses its logo placement to enable the player-name relocation.",
                detail,
            ),
            "channel_system": inferred(
                "The redesigned jersey is the core medium, amplified through match coverage, PR and social discussion.",
                detail,
            ),
            "experience_or_tool_mechanism": observed(
                "Sponsor and player-name placements are re-engineered on the garment.",
                detail,
            ),
            "craft_grammar": inferred(
                "Make the physical intervention legible enough that the sacrifice explains itself.",
                detail,
            ),
            "production_constraints": inferred(
                "League approval, legibility, uniform rules, broadcast framing and manufacturing must all pass.",
                detail,
            ),
            "measurement_design": inferred(
                "Measure aided player-name recognition, broadcast visibility, earned attention and brand attribution against standard jerseys.",
                detail,
            ),
            "reported_outcomes": observed(
                "The public award page describes the intervention and award status but supplies no causal business result.",
                detail,
            ),
            "failure_modes": inferred(
                "If the sponsor sacrifice is unclear or names remain illegible, the mechanism becomes symbolic only.",
                detail,
            ),
            "counterfactuals": inferred(
                "Compare standard placement, enlarged names without sponsor sacrifice and the full redesign.",
                detail,
            ),
            "transferable_principles": inferred(
                "Convert sponsorship inventory into a product or system improvement for the represented community.",
                detail,
            ),
            "non_transferable_specifics": observed(
                "Campaign title, jersey design, league context, identities and assets remain reference-only.",
                archive,
                detail,
            ),
        }
    return profile_layers(case_id)


def main() -> None:
    ranking_snapshot = {
        "year": 2026,
        "region": "North America",
        "rows": AGENCY_ROWS,
    }
    sources = [
        source(
            "oneclub-na-agency-ranking-2026",
            RANKING_URL,
            "North America agency ranking rows 1-10",
            ranking_snapshot,
        ),
        source(
            "oneclub-os26-creative-effectiveness",
            ARCHIVE_URL,
            "2026 Creative Effectiveness archive rows OS26_CE001G-Ce021M",
            SEED_CASE_ROWS,
        ),
    ]
    discovery_by_agency = {
        page["agency_id"]: page for page in DISCOVERY_PAGES
    }
    for row in SEED_CASE_ROWS:
        case_id, agency_id, title, brand, annual_id, url, category = row
        discovery_page = discovery_by_agency[agency_id]
        sources.append(
            source(
                f"oneclub-{case_id}-agency-discovery",
                discovery_page["url"],
                f"Agency discovery row for {title}",
                {
                    "agency_id": agency_id,
                    "title": title,
                    "year": 2026,
                },
            )
        )
        sources.append(
            source(
                f"oneclub-{case_id}-detail",
                url,
                f"Annual ID {annual_id}; {category}",
                {
                    "case_id": case_id,
                    "agency_id": agency_id,
                    "title": title,
                    "brand": brand,
                    "annual_id": annual_id,
                    "category": category,
                    "source_bound_profile": CASE_PROFILES.get(case_id),
                },
            )
        )

    agencies = tuple(
        AgencyReference(
            agency_id=agency_id,
            display_name=display_name,
            city=city,
            country=country,
            rank=rank,
            points=points,
            ranking_source_id="oneclub-na-agency-ranking-2026",
        )
        for agency_id, display_name, city, country, rank, points in AGENCY_ROWS
    )
    cases = tuple(
        CampaignDistillationCase(
            case_id=case_id,
            agency_id=agency_id,
            title=title,
            brand=brand,
            year=2026,
            annual_id=annual_id,
            channels=(
                ("mobile", "commerce", "influencer", "social", "pr")
                if case_id == "os26-ce002g"
                else ("direct-message", "social", "commerce")
                if case_id == "os26-ce003g"
                else ("product-design", "broadcast", "pr", "social")
                if case_id == "os26-ce014m"
                else CASE_PROFILES[case_id]["channels_list"]
                if case_id in CASE_PROFILES
                else ()
            ),
            partition=CorpusPartition.RESEARCH_REFERENCE,
            source_ids=(
                f"oneclub-{case_id}-agency-discovery",
                f"oneclub-{case_id}-detail",
            ),
            layers=layers_for(case_id),
        )
        for case_id, agency_id, title, brand, annual_id, _, _ in SEED_CASE_ROWS
    )

    contract = FourACampaignDistillationContract()
    audit = contract.evaluate(agencies, tuple(sources), cases)
    payload = {
        "contract": contract.to_dict(),
        "cohort_basis": {
            "description": (
                "North-American agency reference cohort, not an assertion of "
                "4As trade-association membership."
            ),
            "ranking_url": RANKING_URL,
            "ranking_retrieved_at": RETRIEVED_AT,
            "selection": "Top ten rows in the frozen 2026 regional ranking.",
        },
        "distillation_layers": list(REQUIRED_DISTILLATION_LAYERS),
        "agencies": [asdict(item) for item in agencies],
        "sources": [asdict(item) for item in sources],
        "seed_cases": [
            {
                **asdict(item),
                "partition": item.partition.value,
                "layers": {
                    key: {
                        **asdict(value),
                        "kind": value.kind.value,
                    }
                    for key, value in item.layers.items()
                },
                "identity_sha256": item.identity_sha256,
            }
            for item in cases
        ],
        "acquisition_queue": {
            "discovery_pages": DISCOVERY_PAGES,
            "observed_unique_candidate_count": len(
                {
                    (
                        page["agency_id"],
                        title.casefold(),
                    )
                    for page in DISCOVERY_PAGES
                    for title in page["observed_unique_titles"]
                }
            ),
            "dedupe_key": "agency_id + normalized_title",
            "next_capture_requirement": (
                "Each candidate needs an individual case URL, brand/client, annual "
                "ID, at least one second locator, all sixteen distilled layers, "
                "observed/inferred labels, channels, and evaluator-split clearance."
            ),
            "award_category_rows_are_not_distinct_campaigns": True,
        },
        "admission": {
            "research_reference": audit.research_reference_ready,
            "training": False,
            "training_reason": (
                "The source-bound research corpus is 13/300 and therefore has not "
                "cleared the declared scale, balance, and split gate for a training "
                "run. Research-teacher use does not by itself prove model training."
            ),
            "raw_campaign_assets_stored": False,
            "award_is_effectiveness_proof": False,
        },
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["manifest_sha256"] = hashlib.sha256(canonical).hexdigest()
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(
        json.dumps(asdict(audit), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "manifest": str(OUTPUT),
                "evidence": str(EVIDENCE),
                "agencies": len(agencies),
                "seed_cases": len(cases),
                "fully_distilled": sum(bool(case.layers) for case in cases),
                "full_gate_passed": audit.passed,
                "training_admitted": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
