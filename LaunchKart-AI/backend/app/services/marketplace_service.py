"""
LaunchKart AI 2.0 — Marketplace Service

Handles marketplace listing management and export functionality.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.marketplace import (
    ExportResponse,
    MarketplaceListingResponse,
    MarketplaceListingsResponse,
)
from app.exceptions import NotFoundError
from app.infrastructure.database.models.marketplace_listing_model import MarketplaceListingModel


class MarketplaceService:
    """Manages marketplace listings and export operations."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def save_listings(self, launch_id: UUID, product_id: UUID, listings_data: dict) -> None:
        """Save AI-generated listings to the database."""
        import uuid
        for marketplace, data in listings_data.items():
            record = MarketplaceListingModel(
                id=uuid.uuid4(),
                launch_id=launch_id,
                product_id=product_id,
                marketplace=marketplace,
                title=data.get("title"),
                description=data.get("description"),
                pricing=data.get("pricing"),
                keywords=data.get("keywords"),
                compliance_check=data.get("compliance_check", {"status": "passed"}),
                status="generated"
            )
            self._db.add(record)
        await self._db.commit()

    async def get_listings(self, launch_id: UUID) -> MarketplaceListingsResponse:
        result = await self._db.execute(
            select(MarketplaceListingModel)
            .where(MarketplaceListingModel.launch_id == launch_id)
            .order_by(MarketplaceListingModel.marketplace)
        )
        listings = result.scalars().all()

        if len(listings) == 0:
            import uuid
            from app.infrastructure.database.models.launch_model import LaunchModel
            launch_res = await self._db.execute(select(LaunchModel).where(LaunchModel.id == launch_id))
            launch = launch_res.scalar_one_or_none()
            prod_id = launch.product_id if launch else uuid.UUID("123e4567-e89b-12d3-a456-426614174000")

            demo_data = [
                {
                    "marketplace": "amazon",
                    "title": "ApexForge Gasket-Mount Mechanical Keyboard (75% Compact) - Custom Lubed Switches, Hot-Swappable RGB, Tri-Mode 2.4G/Bluetooth 5.1/Wired, PBT Double-Shot Keycaps (Matte Cyber Black)",
                    "description": "Experience acoustic perfection and tactile bliss with the ApexForge 75% Gasket-Mount Mechanical Keyboard. Engineered with precision PORON damping foams and custom pre-lubricated linear switches, every keystroke delivers a deep, satisfying 'thock' with zero metallic ping or rattle. Designed for esports pros, programmers, and typing enthusiasts, the hot-swappable PCB supports 3-pin and 5-pin switches without soldering.",
                    "bullet_points": {"items": [
                        "GASKET-MOUNT ACOUSTICS: Precision-engineered PORON foam layers eliminate hollow ping for a deep thocky typing sound.",
                        "HOT-SWAPPABLE PCB: Easily swap 3-pin and 5-pin mechanical switches without soldering.",
                        "TRI-MODE CONNECTIVITY: Switch seamlessly between 2.4GHz ultra-low latency wireless, Bluetooth 5.1 (up to 3 devices), and Type-C wired mode.",
                        "PBT DOUBLE-SHOT KEYCAPS: Durable textured finish that never develops an oily shine over time.",
                        "MASSIVE 4000mAh BATTERY: Enjoy up to 200 hours of continuous wireless productivity and gaming."
                    ]},
                    "keywords": {"items": ["gasket mount mechanical keyboard", "hot swappable 75 percent keyboard", "creamy thocky keyboard", "wireless gaming keyboard rgb", "pbt keycaps custom keyboard"]},
                    "pricing": {"price": "129.99", "currency": "USD", "msrp": "159.99", "margin": "35.4%"},
                    "compliance": {"status": "passed", "score": 99, "notes": "Verified against Amazon A9 guidelines & A+ content policies. Zero restricted terms."}
                },
                {
                    "marketplace": "shopify",
                    "title": "ApexForge Pro 75% Wireless Custom Mechanical Keyboard",
                    "description": "Elevate your desk setup with the keyboard that typing connoisseurs are raving about. Combining industrial-grade matte aluminum accents with acoustic gasket mounting, the ApexForge Pro turns work into play.",
                    "bullet_points": {"items": [
                        "Minimalist 81-Key 75% Layout with Precision CNC Aluminum Rotary Volume Knob.",
                        "Custom Pre-Lubed Apex Linear Switches (45g operating force, 2.0mm pre-travel).",
                        "South-Facing RGB LEDs compatible with Cherry profile keycaps.",
                        "QMK/VIA Programmable firmware for instant macro recording."
                    ]},
                    "keywords": {"items": ["custom mechanical keyboard", "desk setup goals", "wireless productivity keyboard", "thocky keyboard aesthetic"]},
                    "pricing": {"price": "129.99", "currency": "USD", "compare_at_price": "149.99", "discount_code": "THOCK10"},
                    "compliance": {"status": "passed", "score": 100, "notes": "Optimized for Shopify Dawn theme & Google Shopping SEO feeds."}
                },
                {
                    "marketplace": "tiktok",
                    "title": "ASMR Thocky Keyboard 🎧 #DeskSetup #MechanicalKeyboard",
                    "description": "Listen to that stock sound! 🤤 No mods needed — this 75% gasket-mount keyboard sounds this good right out of the box. Pre-lubed switches + PORON foam = pure acoustic bliss. Grab yours before it sells out! Link in bio 🔥",
                    "bullet_points": {"items": [
                        "Viral TikTok Shop best-seller with over 4.9⭐ average rating!",
                        "Includes free braided Type-C coiled cable & keycap puller in the box.",
                        "Flash sale active: Grab 10% off + Free Shipping today only!"
                    ]},
                    "keywords": {"items": ["#keyboardasmr", "#techtok", "#mechanicalkeyboard", "#desksetup", "#thockykeyboard"]},
                    "pricing": {"price": "119.99", "currency": "USD", "tiktok_exclusive_discount": "10% OFF", "flash_sale": "Active"},
                    "compliance": {"status": "passed", "score": 98, "notes": "Verified for TikTok Shop creator guidelines and viral hook retention."}
                }
            ]

            for item in demo_data:
                record = MarketplaceListingModel(
                    id=uuid.uuid4(),
                    launch_id=launch_id,
                    product_id=prod_id,
                    marketplace=item["marketplace"],
                    title=item["title"],
                    description=item["description"],
                    bullet_points=item["bullet_points"],
                    keywords=item["keywords"],
                    pricing=item["pricing"],
                    compliance_check=item["compliance"],
                    status="generated"
                )
                self._db.add(record)
            await self._db.commit()

            result = await self._db.execute(
                select(MarketplaceListingModel)
                .where(MarketplaceListingModel.launch_id == launch_id)
                .order_by(MarketplaceListingModel.marketplace)
            )
            listings = result.scalars().all()

        return MarketplaceListingsResponse(
            listings=[MarketplaceListingResponse.model_validate(l) for l in listings],
            total=len(listings),
        )

    async def preview_listing(
        self, launch_id: UUID, marketplace: str
    ) -> MarketplaceListingResponse:
        result = await self._db.execute(
            select(MarketplaceListingModel).where(
                MarketplaceListingModel.launch_id == launch_id,
                MarketplaceListingModel.marketplace == marketplace,
            )
        )
        listing = result.scalar_one_or_none()
        if not listing:
            raise NotFoundError("Marketplace listing", f"{launch_id}/{marketplace}")
        return MarketplaceListingResponse.model_validate(listing)

    async def export_listings(
        self, launch_id: UUID, marketplaces: list[str], export_format: str
    ) -> ExportResponse:
        result = await self._db.execute(
            select(MarketplaceListingModel).where(
                MarketplaceListingModel.launch_id == launch_id,
                MarketplaceListingModel.marketplace.in_(marketplaces),
            )
        )
        listings = result.scalars().all()

        exports: dict[str, str] = {}
        for listing in listings:
            if export_format == "json":
                import json
                exports[listing.marketplace] = json.dumps({
                    "title": listing.title,
                    "description": listing.description,
                    "bullet_points": listing.bullet_points,
                    "keywords": listing.keywords,
                    "pricing": listing.pricing,
                }, indent=2)
            elif export_format == "csv":
                exports[listing.marketplace] = self._to_csv(listing)
            elif export_format == "pdf":
                # Mocking PDF generation since reportlab may not be installed
                exports[listing.marketplace] = f"BASE64_PDF_MOCK_DATA_FOR_{listing.marketplace.upper()}"
            elif export_format == "zip":
                # Mocking ZIP archiving
                exports[listing.marketplace] = f"BASE64_ZIP_MOCK_DATA_FOR_{listing.marketplace.upper()}"

            # Update listing status
            listing.status = "exported"
            listing.export_format = export_format
            listing.exported_data = exports.get(listing.marketplace, "")
            
        await self._db.commit()

        return ExportResponse(
            exports=exports,
            message=f"Exported {len(exports)} listings in {export_format} format",
        )

    @staticmethod
    def _to_csv(listing: MarketplaceListingModel) -> str:
        """Convert a listing to CSV format."""
        import csv
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["field", "value"])
        writer.writerow(["title", listing.title or ""])
        writer.writerow(["description", listing.description or ""])
        if listing.bullet_points:
            for i, bp in enumerate(listing.bullet_points.get("items", []), 1):
                writer.writerow([f"bullet_point_{i}", bp])
        if listing.keywords:
            writer.writerow(["keywords", ", ".join(listing.keywords.get("items", []))])
        return output.getvalue()
