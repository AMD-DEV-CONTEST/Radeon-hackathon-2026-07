from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Mapping

from .v10_agentomnia import Capability
from .v10_contracts import V10ContractError, stable_digest


class ProductLane(str, Enum):
    VIDEO = "video_generation"
    AUDIO = "audio_generation"
    TEXT = "text_generation"
    DATA = "data_analysis"
    GEO = "generative_engine_optimization"
    SEO = "search_engine_optimization"
    EMPLOYEE_AGENT = "employee_agent"
    AD_ACTIVATION = "advertising_activation"


@dataclass(frozen=True)
class ProductReference:
    product: str
    official_url: str
    capability_atoms: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.product.strip() or not self.official_url.startswith("https://"):
            raise V10ContractError("product reference needs a name and official HTTPS URL")
        if not self.capability_atoms or any(not item.strip() for item in self.capability_atoms):
            raise V10ContractError("product reference needs observable capability atoms")


@dataclass(frozen=True)
class FrontierLane:
    lane: ProductLane
    products: tuple[ProductReference, ...]
    lifecycle_outcomes: tuple[str, ...]
    required_capabilities: frozenset[Capability]

    def __post_init__(self) -> None:
        if len(self.products) != 10:
            raise V10ContractError(f"{self.lane.value} needs exactly ten comparison products")
        names = [item.product for item in self.products]
        if len(names) != len(set(names)):
            raise V10ContractError(f"{self.lane.value} product names must be unique")
        if not self.lifecycle_outcomes or not self.required_capabilities:
            raise V10ContractError("lane outcomes and capabilities are required")


@dataclass(frozen=True)
class FrontierLandscape:
    as_of: str
    lanes: tuple[FrontierLane, ...]
    observation_policy: str
    training_policy: str
    ranking_claim: str = "comparison_set_not_a_global_rank_claim"

    def __post_init__(self) -> None:
        if set(item.lane for item in self.lanes) != set(ProductLane):
            raise V10ContractError("frontier landscape must cover all eight product lanes")
        if len(self.lanes) != len(ProductLane):
            raise V10ContractError("frontier landscape contains duplicate lanes")
        if "official" not in self.observation_policy.lower():
            raise V10ContractError("observation policy must be bound to official sources")
        if "licensed" not in self.training_policy.lower():
            raise V10ContractError("training policy must require licensed inputs")

    def to_dict(self) -> dict:
        return {
            "schema": "ProofLaunchFrontierLandscapeV10",
            "as_of": self.as_of,
            "ranking_claim": self.ranking_claim,
            "observation_policy": self.observation_policy,
            "training_policy": self.training_policy,
            "lanes": [
                {
                    "lane": lane.lane.value,
                    "products": [asdict(product) for product in lane.products],
                    "lifecycle_outcomes": list(lane.lifecycle_outcomes),
                    "required_capabilities": sorted(
                        item.value for item in lane.required_capabilities
                    ),
                }
                for lane in self.lanes
            ],
        }

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())


def _product(name: str, url: str, *atoms: str) -> ProductReference:
    return ProductReference(name, url, atoms)


COMMON_AGENT_CAPABILITIES = frozenset(
    {
        Capability.TASK_UNDERSTANDING,
        Capability.INFORMATION_GATHERING,
        Capability.PLANNING_DECISION,
        Capability.STATE_MANAGEMENT,
        Capability.TOOL_USE,
        Capability.RELIABILITY_SAFETY,
    }
)


def default_frontier_landscape() -> FrontierLandscape:
    # These are non-ranked comparison sets. Product outputs are not corpus assets.
    lanes: Mapping[ProductLane, tuple[ProductReference, ...]] = {
        ProductLane.VIDEO: (
            _product("Runway", "https://runwayml.com/product/ai-video-generator", "multi-model timeline", "video editing"),
            _product("Google Veo", "https://deepmind.google/models/veo/", "prompt adherence", "native audio-video"),
            _product("Kling AI", "https://klingai.com/", "motion control", "image-to-video"),
            _product("Seedance", "https://seed.bytedance.com/en/seedance", "multi-shot narrative", "audio-video generation"),
            _product("Adobe Firefly Video", "https://www.adobe.com/products/firefly/features/ai-video-generator.html", "brand workflow", "commercial controls"),
            _product("Luma Dream Machine", "https://lumalabs.ai/dream-machine", "camera control", "modify video"),
            _product("Hailuo AI Video", "https://hailuoai.video/", "text-to-video", "image-to-video"),
            _product("Pika", "https://pika.art/", "creative effects", "scene transformation"),
            _product("Vidu", "https://www.vidu.com/", "reference consistency", "video generation"),
            _product("HunyuanVideo", "https://github.com/Tencent-Hunyuan/HunyuanVideo", "open implementation", "video foundation model"),
        ),
        ProductLane.AUDIO: (
            _product("ElevenLabs", "https://elevenlabs.io/", "speech", "music", "dubbing"),
            _product("Suno", "https://suno.com/", "song generation", "music editing"),
            _product("Udio", "https://www.udio.com/", "music generation", "audio extension"),
            _product("Google Lyria", "https://deepmind.google/models/lyria/", "music generation", "watermarking"),
            _product("Adobe Firefly Audio", "https://www.adobe.com/products/firefly/features/generate-sound-effects.html", "sound effects", "creative workflow"),
            _product("Stable Audio", "https://stability.ai/stable-audio", "text-to-audio", "audio-to-audio"),
            _product("MiniMax Audio", "https://www.minimax.io/audio", "speech", "voice design"),
            _product("PlayAI", "https://play.ai/", "speech generation", "voice agents"),
            _product("Murf", "https://murf.ai/", "voiceover", "localization"),
            _product("Descript", "https://www.descript.com/overdub", "voice editing", "timeline production"),
        ),
        ProductLane.TEXT: (
            _product("ChatGPT", "https://openai.com/chatgpt/", "writing", "research", "tools"),
            _product("Claude", "https://www.anthropic.com/claude", "long context", "artifacts"),
            _product("Gemini", "https://gemini.google.com/", "multimodal", "workspace grounding"),
            _product("Qwen Chat", "https://chat.qwen.ai/", "reasoning", "multilingual"),
            _product("DeepSeek", "https://www.deepseek.com/", "reasoning", "coding"),
            _product("Kimi", "https://www.kimi.com/", "long context", "agentic work"),
            _product("Z.ai", "https://chat.z.ai/", "reasoning", "agentic coding"),
            _product("Le Chat", "https://chat.mistral.ai/", "enterprise assistant", "multilingual"),
            _product("Perplexity", "https://www.perplexity.ai/", "answer engine", "citations"),
            _product("Meta AI", "https://www.meta.ai/", "consumer assistant", "multimodal creation"),
        ),
        ProductLane.DATA: (
            _product("ChatGPT Data Analysis", "https://help.openai.com/en/articles/8437071-data-analysis-with-chatgpt", "code execution", "charts"),
            _product("Claude Analysis", "https://www.anthropic.com/news/analysis-tool", "analysis tool", "artifacts"),
            _product("Gemini in Sheets", "https://workspace.google.com/products/sheets/ai/", "spreadsheet analysis", "formula generation"),
            _product("Power BI Copilot", "https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-introduction", "semantic models", "report creation"),
            _product("Tableau Agent", "https://www.tableau.com/products/tableau-agent", "visual analytics", "calculation assistance"),
            _product("Databricks Genie", "https://www.databricks.com/product/ai-bi/genie", "natural-language BI", "governed data"),
            _product("Snowflake Cortex Analyst", "https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst", "text-to-SQL", "semantic model"),
            _product("ThoughtSpot Spotter", "https://www.thoughtspot.com/product/spotter", "analytics agent", "conversational BI"),
            _product("Julius", "https://julius.ai/", "data analysis", "visualization"),
            _product("Hex", "https://hex.tech/product/hex-magic-ai/", "notebook copilot", "data apps"),
        ),
        ProductLane.GEO: (
            _product("Profound", "https://www.tryprofound.com/", "AI visibility", "citation analysis"),
            _product("Scrunch", "https://scrunch.com/", "agent experience", "AI search visibility"),
            _product("Peec AI", "https://peec.ai/", "prompt monitoring", "brand visibility"),
            _product("Semrush AI Visibility", "https://www.semrush.com/kb/1547-ai-visibility-toolkit", "AI visibility", "competitor analysis"),
            _product("Ahrefs Brand Radar", "https://ahrefs.com/brand-radar", "brand mentions", "citation gaps"),
            _product("Otterly.AI", "https://otterly.ai/", "AI search monitoring", "link citations"),
            _product("Writesonic GEO", "https://writesonic.com/generative-engine-optimization-geo", "content optimization", "AI traffic analytics"),
            _product("ZipTie", "https://ziptie.dev/", "AI search monitoring", "citation tracking"),
            _product("AirOps", "https://www.airops.com/", "content operations", "AI search workflows"),
            _product("AthenaHQ", "https://www.athenahq.ai/", "AI visibility", "content actioning"),
        ),
        ProductLane.SEO: (
            _product("Semrush", "https://www.semrush.com/", "keyword research", "site audit"),
            _product("Ahrefs", "https://ahrefs.com/", "web index", "backlink analysis"),
            _product("Surfer", "https://surferseo.com/", "content optimization", "SERP modeling"),
            _product("Clearscope", "https://www.clearscope.io/", "content grading", "topic coverage"),
            _product("MarketMuse", "https://www.marketmuse.com/", "content planning", "authority modeling"),
            _product("BrightEdge", "https://www.brightedge.com/", "enterprise SEO", "search intelligence"),
            _product("Conductor", "https://www.conductor.com/", "organic marketing", "content intelligence"),
            _product("seoClarity", "https://www.seoclarity.net/", "enterprise SEO", "automation"),
            _product("Screaming Frog", "https://www.screamingfrog.co.uk/seo-spider/", "technical crawl", "site diagnostics"),
            _product("SE Ranking", "https://seranking.com/", "rank tracking", "site audit"),
        ),
        ProductLane.EMPLOYEE_AGENT: (
            _product("Microsoft 365 Copilot", "https://www.microsoft.com/en-us/microsoft-365-copilot", "work graph", "office execution"),
            _product("Salesforce Agentforce", "https://www.salesforce.com/agentforce/", "CRM agents", "governed actions"),
            _product("Gemini Enterprise", "https://cloud.google.com/gemini-enterprise", "enterprise search", "agents"),
            _product("ServiceNow AI Agents", "https://www.servicenow.com/products/ai-agents.html", "workflow agents", "enterprise governance"),
            _product("UiPath Agentic Automation", "https://www.uipath.com/platform/agentic-automation", "agents plus robots", "orchestration"),
            _product("ChatGPT Enterprise", "https://openai.com/chatgpt/enterprise/", "enterprise assistant", "data analysis"),
            _product("Claude Enterprise", "https://www.anthropic.com/enterprise", "knowledge work", "enterprise controls"),
            _product("Glean Agents", "https://www.glean.com/product/agents", "enterprise search", "agent builder"),
            _product("Amazon Q Business", "https://aws.amazon.com/q/business/", "enterprise knowledge", "actions"),
            _product("Moveworks", "https://www.moveworks.com/us/en/platform/agentic-ai-assistant", "employee support", "enterprise workflows"),
        ),
        ProductLane.AD_ACTIVATION: (
            _product("Google Performance Max", "https://support.google.com/google-ads/answer/10724817", "cross-channel bidding", "creative automation"),
            _product("Meta Advantage+", "https://www.facebook.com/business/ads/meta-advantage-plus", "audience automation", "creative optimization"),
            _product("TikTok Symphony", "https://ads.tiktok.com/business/en-US/symphony", "creative generation", "brand controls"),
            _product("LinkedIn Accelerate", "https://business.linkedin.com/marketing-solutions/accelerate", "B2B campaign setup", "optimization"),
            _product("Amazon Ads AI", "https://advertising.amazon.com/solutions/products/ai-creative-studio", "commerce creative", "campaign assets"),
            _product("Microsoft Advertising Copilot", "https://about.ads.microsoft.com/en/tools/productivity/copilot-in-microsoft-advertising", "campaign assistance", "asset generation"),
            _product("Adobe GenStudio", "https://business.adobe.com/products/genstudio-for-performance-marketing/adobe-genstudio-for-performance-marketing.html", "brand content supply chain", "performance insights"),
            _product("The Trade Desk Kokai", "https://www.thetradedesk.com/us/kokai", "programmatic optimization", "measurement"),
            _product("Smartly", "https://www.smartly.io/", "cross-channel creative", "media automation"),
            _product("Skai", "https://skai.io/", "omnichannel media", "optimization"),
        ),
    }
    outcome_map = {
        ProductLane.VIDEO: ("brief-to-storyboard", "identity-consistent edit", "4K-master delivery"),
        ProductLane.AUDIO: ("sonic-strategy-to-master", "voice consistency", "rights receipt"),
        ProductLane.TEXT: ("evidence-to-message", "brand voice", "claim-safe variants"),
        ProductLane.DATA: ("question-to-analysis", "reproducible computation", "decision memo"),
        ProductLane.GEO: ("prompt universe", "citation diagnosis", "measured visibility lift"),
        ProductLane.SEO: ("technical audit", "intent map", "measured organic lift"),
        ProductLane.EMPLOYEE_AGENT: ("goal-to-workflow", "durable recovery", "human release"),
        ProductLane.AD_ACTIVATION: ("plan-to-build", "budget guardrails", "causal incrementality"),
    }
    lane_objects = tuple(
        FrontierLane(
            lane=lane,
            products=lanes[lane],
            lifecycle_outcomes=outcome_map[lane],
            required_capabilities=(
                COMMON_AGENT_CAPABILITIES
                | (
                    frozenset({Capability.OFFICE_DOCUMENTS, Capability.DATA_ANALYSIS})
                    if lane in {ProductLane.DATA, ProductLane.GEO, ProductLane.SEO}
                    else frozenset()
                )
            ),
        )
        for lane in ProductLane
    )
    return FrontierLandscape(
        as_of="2026-07-31",
        lanes=lane_objects,
        observation_policy=(
            "Observe official product documentation, public APIs, papers, and reproducible "
            "first-party feature behavior; record revisions and falsifiers."
        ),
        training_policy=(
            "Admit only owned, permissive, public-domain, or expressly licensed examples; "
            "product outputs and marketing claims are benchmark references, not corpus assets."
        ),
    )

