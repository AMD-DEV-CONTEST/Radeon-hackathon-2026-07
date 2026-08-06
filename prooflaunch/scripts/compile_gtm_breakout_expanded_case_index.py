#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from prooflaunch_remix.gtm_breakout_evidence import compile_expanded_case_index, verify_expanded_case_index


SOURCES = {
    "2020_global_effie": "https://effie.org/news/dove-and-tourism-new-zealand-top-the-2020-global-effies/",
    "2020_effie_uk": "https://effie.org/news/effie-uk-reveals-2020-effie-awards-winners/",
    "2020_effie_australia": "https://www.effie.org/news/2020-effie-awards-australia-winners-announced/",
    "2020_effie_germany": "https://effie.org/news/2020-effie-awards-germany-winners-announced-commerzbank-and-thjnk-win-grand-effie/",
    "2020_effie_brazil": "https://effie.org/news/avon-wunderman-thompson-and-mutato-win-the-grand-effie-at-2020-effie-awards-brasil-gala/",
    "2021_reach": "https://www.canneslions.com/news/cannes-lions-2021-winners-day-2",
    "2021_experience": "https://www.canneslions.com/news/cannes-lions-2021-winners-day-4",
    "2022_strategy": "https://www.canneslions.com/news/lions-winners-day-three",
    "2022_b2b": "https://www.canneslions.com/news/lions-winners-day-four",
    "2022_final": "https://www.canneslions.com/news/lions-winners-day-five",
    "2023_engagement": "https://www.canneslions.com/news/further-winners-announced-on-day-three-of-the-cannes-lions-international",
    "2023_entertainment": "https://www.canneslions.com/news/winners-in-the-entertainment-lions-and-craft-lions-tracks",
    "2023_final": "https://www.canneslions.com/news/final-lion-winners-announced-at-the-cannes-lions-international-festival",
    "2024_day1": "https://www.canneslions.com/news/first-winners-announced-at-the-71st-cannes-lions-festival",
    "2024_day2": "https://www.canneslions.com/news/cannes-lions-announces-winners-across-entertainment-and-craft-tracks",
    "2024_day3": "https://www.canneslions.com/news/further-winners-announced-on-day-three-of-cannes-lions",
    "2024_day4": "https://www.canneslions.com/news/lion-winners-announced-on-the-penultimate-day-of-cannes-lions",
    "2025_day1": "https://www.canneslions.com/news/first-winners-announced-at-the-72nd-cannes-lions-international-festival",
    "2025_day2": "https://www.canneslions.com/news/cannes-lions-announces-2025-winners-across-entertainment-and-craft-tracks",
    "2025_day3": "https://www.canneslions.com/news/winners-of-the-creative-data-direct-media-pr-and-social-and-creator-lions-announced",
    "2025_day4": "https://www.canneslions.com/news/lion-winners-announced-for-day-four-of-the-festival",
    "2025_final": "https://www.canneslions.com/news/cannes-lions-announces-2025-final-winners",
    "2026_day1": "https://www.canneslions.com/news/73rd-cannes-lions-international-festival-of-creativity-announces-first-winners",
    "2026_day2": "https://www.canneslions.com/news/cannes-lions-international-festival-of-creativity-announces-winners-across-the-entertainment-and-craft-track-lions",
    "2026_day3": "https://www.canneslions.com/news/cannes-lions-international-festival-of-creativity-announces-lion-winners-on-day-three",
    "2026_day4": "https://www.canneslions.com/news/the-cannes-lions-international-festival-of-creativity-announces-winners-on-its-penultimate-day",
    "2026_final": "https://www.canneslions.com/news/final-winners-announced-for-2026",
}


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def row(year: int, campaign: str, brand: str, category: str, model: str, industry: str, geography: str, source: str) -> dict[str, object]:
    return {
        "case_id": f"discovery-{year}-{slug(campaign)}",
        "year": year,
        "campaign": campaign,
        "brand": brand,
        "award_category": category,
        "business_model": model,
        "industry_family": industry,
        "geography": geography,
        "source_url": SOURCES[source],
        "source_class": "official_award_body",
        "promotion_status": "pending_case_level_claim_audit",
        "training_eligible": False,
        "english_market_transfer_requires_local_validation": True,
        "required_next_evidence": ["baseline", "spend_scope", "time_window", "outcome_chain", "causal_confounds"],
    }


def cases() -> list[dict[str, object]]:
    r = row
    return [
        r(2020, "Project #ShowUs", "Dove", "Global Effie Silver", "b2c", "beauty, representation, and image data", "Global", "2020_global_effie"),
        r(2020, "Good Morning World", "Tourism New Zealand", "Global Effie Silver", "b2c", "travel and destination marketing", "New Zealand and Global", "2020_global_effie"),
        r(2020, "Dove Deodorants: The Big Switch", "Dove Antiperspirants", "Global Effie Bronze", "b2c", "consumer goods and trial conversion", "Global", "2020_global_effie"),
        r(2020, "The Bank of AntandDec", "Santander", "Effie UK", "b2c", "financial services", "United Kingdom", "2020_effie_uk"),
        r(2020, "Subverting the Category Rule Book to Transform a Business", "Confused.com", "Effie UK", "b2c", "insurance comparison and digital services", "United Kingdom", "2020_effie_uk"),
        r(2020, "Stirring Souls and Selling Bowls the Wagamama Way", "Wagamama", "Effie UK", "b2c", "restaurants and hospitality", "United Kingdom", "2020_effie_uk"),
        r(2020, "ALDI Good Different", "ALDI Australia", "Grand Effie Australia", "b2c", "grocery retail", "Australia", "2020_effie_australia"),
        r(2020, "Ponytail", "Commerzbank", "Grand Effie Germany", "b2c", "financial services and sport", "Germany", "2020_effie_germany"),
        r(2020, "Avon Power Stay #Veio Pra Ficar", "Avon", "Grand Effie Brazil", "b2c", "beauty and creator culture", "Brazil", "2020_effie_brazil"),
        r(2020, "We Are Nurses. We Are the NHS", "NHS England", "Effie UK", "public_interest", "healthcare recruitment", "United Kingdom", "2020_effie_uk"),
        r(2021, "Saylists", "Warner Music Group", "Creative Data", "b2c", "health and music technology", "Ireland", "2021_reach"),
        r(2021, "Can't Touch This", "Cheetos", "Creative Strategy", "b2c", "food and beverage", "United States", "2021_reach"),
        r(2021, "Stevenage Challenge", "Burger King", "Direct and Social", "b2c", "food, gaming, and sport", "Global", "2021_reach"),
        r(2021, "Boards of Change", "City of Chicago", "Media", "public_interest", "civic participation", "United States", "2021_reach"),
        r(2021, "Digital Birth Registration", "Telenor Pakistan", "Media", "public_interest", "telecommunications and civic identity", "Pakistan", "2021_reach"),
        r(2021, "Contract for Change", "AB InBev", "PR", "b2b", "agriculture and supply chain", "United States", "2021_reach"),
        r(2021, "The Bread Exam", "Spinneys and Lebanese Breast Cancer Foundation", "PR", "b2c", "retail and health", "Lebanon", "2021_reach"),
        r(2021, "Superb Owl", "Reddit", "Social and Influencer", "mixed", "social platform", "United States", "2021_reach"),
        r(2021, "Raising Profiles", "The Big Issue and LinkedIn", "Brand Experience", "b2b", "employment and media", "United Kingdom", "2021_experience"),
        r(2021, "Tienda Cerca", "AB InBev", "Creative Commerce", "b2b", "local retail enablement", "Colombia", "2021_experience"),
        r(2021, "Act for Food", "Carrefour", "Creative Business Transformation", "b2c", "grocery retail", "France", "2021_experience"),
        r(2022, "The Unfiltered History Tour", "VICE Media", "Brand Experience and Activation", "b2c", "media, culture, and museums", "India and United Kingdom", "2022_strategy"),
        r(2022, "Real Tone", "Google", "Mobile", "b2c", "mobile imaging and inclusion", "United States", "2022_strategy"),
        r(2022, "Contract for Change Effectiveness", "Michelob Ultra", "Creative Effectiveness", "b2b", "agriculture and beverage supply", "United States", "2022_strategy"),
        r(2022, "Speaking in Color", "Sherwin-Williams Coil Coatings", "Creative B2B", "b2b", "manufacturing and industrial coatings", "United States", "2022_b2b"),
        r(2022, "Data Tienda", "We Capital", "Creative Data and Glass", "b2b", "financial services and small business", "Mexico", "2022_final"),
        r(2022, "Long Live the Prince", "Kiyan Prince Foundation and partners", "Titanium", "public_interest", "sport, gaming, and youth", "United Kingdom", "2022_final"),
        r(2023, "Eart4", "B3 and UN Global Compact", "Creative B2B", "b2b", "capital markets and sustainability", "Brazil and Global", "2023_engagement"),
        r(2023, "The Artois Probability", "Stella Artois", "Creative Data", "b2c", "beverage and cultural heritage", "Argentina and Global", "2023_engagement"),
        r(2023, "Runner 321", "adidas", "Direct", "b2c", "sport and inclusion", "Canada and Global", "2023_engagement"),
        r(2023, "Room for Everyone", "Mastercard", "Creative Data", "b2b", "financial services and local commerce", "Poland", "2023_engagement"),
        r(2023, "Clash from the Past", "Clash of Clans", "Entertainment for Gaming", "b2c", "gaming and entertainment", "United States and Global", "2023_entertainment"),
        r(2023, "ADLaM - An Alphabet to Preserve a Culture", "Microsoft", "Design and Business Transformation", "mixed", "software, language, and culture", "United States and West Africa", "2023_entertainment"),
        r(2023, "Never Done Evolving Featuring Serena", "Nike", "Digital Craft", "b2c", "sport, AI, and entertainment", "Global", "2023_entertainment"),
        r(2023, "My Japan Railway", "JR Group", "Industry Craft", "b2c", "transportation and regional identity", "Japan", "2023_entertainment"),
        r(2023, "The First Digital Nation", "Government of Tuvalu", "Titanium", "public_interest", "climate and public service", "Tuvalu and Global", "2023_final"),
        r(2024, "The Misheard Version", "Specsavers", "Audio and Radio and PR", "b2c", "hearing health and retail", "United Kingdom", "2024_day1"),
        r(2024, "The Last Barf Bag", "Dramamine", "Health and Wellness", "b2c", "consumer health", "United States", "2024_day1"),
        r(2024, "Find Your Summer", "Magnum", "Outdoor", "b2c", "food and beverage", "Spain and Europe", "2024_day1"),
        r(2024, "Adoptable by Pedigree", "Pedigree", "Outdoor", "b2c", "pet care and adoption", "New Zealand", "2024_day1"),
        r(2024, "Recycle Me", "Coca-Cola", "Print and Publishing", "b2c", "beverage and circularity", "United States and Global", "2024_day1"),
        r(2024, "Magnetic Stories", "Siemens Healthineers", "Pharma", "b2b", "medical imaging and patient experience", "United States", "2024_day1"),
        r(2024, "Child Wedding Cards", "UN Women", "Grand Prix for Good", "public_interest", "human rights and child protection", "United Arab Emirates and Global", "2024_day1"),
        r(2024, "We Are Ayenda", "WhatsApp", "Entertainment", "b2c", "communications and safety", "United States and Afghanistan", "2024_day2"),
        r(2024, "The Everyday Tactician", "Xbox Game Pass", "Entertainment for Gaming and Direct", "b2c", "gaming and sport", "United Kingdom", "2024_day2"),
        r(2024, "WoMen's Football", "Orange", "Entertainment for Sport", "b2c", "telecommunications and sport", "France", "2024_day2"),
        r(2024, "Sightwalks", "Sol Cement", "Design", "b2b", "construction materials and accessibility", "Peru", "2024_day2"),
        r(2024, "Spreadbeats", "Spotify", "Digital Craft", "b2b", "advertising technology and media", "United States", "2024_day2"),
        r(2024, "Errata at 88", "Johnnie Walker", "Entertainment for Music", "b2c", "beverage, music, and cultural heritage", "Brazil and United States", "2024_day2"),
        r(2024, "The Square Meter", "Hornbach", "Film Craft", "b2c", "home improvement and housing", "Germany", "2024_day2"),
        r(2024, "The 100th Edition", "Frankfurter Allgemeine Zeitung", "Industry Craft", "b2c", "news media and civic culture", "Germany", "2024_day2"),
        r(2024, "Meet Marina Prieto", "JCDecaux", "Creative B2B", "b2b", "outdoor media", "Spain", "2024_day3"),
        r(2024, "Handshake Hunt", "Mercado Libre", "Media", "b2c", "ecommerce and culture", "Brazil", "2024_day3"),
        r(2024, "Michael CeraVe", "CeraVe", "Social and Influencer", "b2c", "skincare", "United States", "2024_day3"),
        r(2024, "A Piece of Me", "KPN", "Creative Strategy", "b2c", "telecommunications and youth safety", "Netherlands", "2024_day4"),
        r(2024, "Refurb", "Philips", "Creative Business Transformation", "b2c", "consumer electronics and circular commerce", "Netherlands", "2024_day4"),
        r(2024, "Renault Cars to Work", "Renault", "Creative Commerce", "b2c", "automotive and employment access", "France", "2024_day4"),
        r(2024, "Voice 2 Diabetes", "KVI Brave Fund", "Innovation", "b2c", "health diagnostics", "Canada", "2024_day4"),
        r(2024, "It Has To Be Heinz", "Heinz", "Creative Effectiveness", "b2c", "food and beverage", "Canada and Global", "2024_day4"),
        r(2024, "The First Edible Mascot", "Pop-Tarts", "Brand Experience and Activation", "b2c", "food, sport, and live experience", "United States", "2024_day4"),
        r(2024, "LOEWE x Suna Fujita", "LOEWE", "Luxury and Lifestyle", "b2c", "luxury, craft, and collaboration", "Spain and Japan", "2024_day4"),
        r(2025, "Night Fishing", "Hyundai IONIQ", "Entertainment", "b2c", "automotive and entertainment", "South Korea", "2025_day2"),
        r(2025, "Make Love Last - Bedroom", "Viatris", "Pharma", "b2c", "pharmaceuticals and intimacy", "China", "2025_day1"),
        r(2025, "One Second Ads", "Budweiser", "Audio and Radio", "b2c", "beverage and music fandom", "Brazil and Global", "2025_day1"),
        r(2025, "Price Packs", "PENNY", "Print and Publishing", "b2c", "grocery retail and price positioning", "Germany", "2025_day1"),
        r(2025, "Phone Break", "KitKat", "Outdoor", "b2c", "food and digital wellbeing", "Czech Republic", "2025_day1"),
        r(2025, "Olympic Games Opening Ceremony Paris 2024", "Paris 2024", "Outdoor", "mixed", "sport, tourism, and public experience", "France and Global", "2025_day1"),
        r(2025, "Call of Discounts", "Mercado Livre", "Entertainment for Gaming", "b2c", "ecommerce and gaming", "Brazil", "2025_day2"),
        r(2025, "Tracking Bad Bunny", "Rimas Music", "Entertainment for Music", "b2c", "music and destination culture", "Puerto Rico", "2025_day2"),
        r(2025, "Haaland Payback Time", "Clash of Clans", "Entertainment for Sport", "b2c", "gaming and sport", "United States and Global", "2025_day2"),
        r(2025, "Caption with Intention", "Academy of Motion Picture Arts and Sciences", "Design and Digital Craft", "b2b", "film technology and accessibility", "United States", "2025_day2"),
        r(2025, "Telstra Better on a Better Network", "Telstra", "Film Craft", "b2c", "telecommunications", "Australia", "2025_day2"),
        r(2025, "Nigrum Corpus", "IDOMED", "Industry Craft", "b2b", "medical education", "Brazil", "2025_day2"),
        r(2025, "B2B Act Like You Know", "GoDaddy Airo", "Creative B2B", "b2b", "small-business software", "United States", "2025_day3"),
        r(2025, "AXA Three Words", "AXA", "Direct and Titanium", "b2c", "insurance and social protection", "France", "2025_day3"),
        r(2025, "Dove Real Beauty Redefined for the AI Era", "Dove", "Media", "b2c", "beauty, AI, and platforms", "United States and Global", "2025_day3"),
        r(2025, "Lucky Yatra", "Indian Railways", "PR", "b2c", "public transport and ticketing", "India", "2025_day3"),
        r(2025, "Vaseline Verified", "Vaseline", "Social and Creator", "b2c", "skincare and creator evidence", "Singapore and Global", "2025_day3"),
        r(2025, "Shot on iPhone", "Apple", "Creative Effectiveness", "b2c", "consumer technology and creator platform", "Global", "2025_day4"),
        r(2025, "Sounds Right", "Museum for the United Nations - UN Live and Spotify", "Innovation", "mixed", "music and conservation funding", "Denmark and Global", "2025_day4"),
        r(2025, "Preserved Promos", "Ziploc", "Creative Commerce", "b2c", "consumer goods and retail promotions", "United States", "2025_day4"),
        r(2025, "Real Beauty Self-Esteem Movement", "Dove", "Glass", "b2c", "beauty and social impact", "United Kingdom and Global", "2025_final"),
        r(2025, "The Amazon Greenventory", "Natura", "Sustainable Development Goals", "b2b", "beauty supply chain and conservation", "Brazil", "2025_final"),
        r(2025, "The Final Copy of Ilon Specht", "L'Oreal Paris", "Film", "b2c", "beauty and brand heritage", "France and Global", "2025_final"),
        r(2025, "The Best Place in the World to Have Herpes", "New Zealand Herpes Foundation", "Grand Prix for Good", "public_interest", "public health", "New Zealand", "2025_final"),
        r(2026, "Original Forever", "adidas", "Entertainment and Music", "b2c", "sport, music, and fandom", "United States, United Kingdom, and Global", "2026_day2"),
        r(2026, "Coquí Alarmed", "Hyundai Puerto Rico", "Audio and Radio", "b2c", "automotive, sound, and local culture", "Puerto Rico", "2026_day1"),
        r(2026, "AB InBev: Creativity at Scale", "AB InBev", "Creative Brand", "mixed", "creative operating model and beverage portfolio", "Belgium and Global", "2026_day1"),
        r(2026, "The Faroe Islands Space Program", "SKF", "Creative B2B", "b2b", "industrial bearings and sustainability", "Sweden and Faroe Islands", "2026_day1"),
        r(2026, "The Periodic Fable", "The Ordinary", "Health and Wellness", "b2c", "beauty and claims literacy", "United Kingdom and Global", "2026_day1"),
        r(2026, "Vehicle of Hope", "Caritas", "Grand Prix for Good", "public_interest", "humanitarian services and mobility", "Sweden and Global", "2026_day1"),
        r(2026, "Field Barcode", "Mercado Livre", "Outdoor", "b2c", "ecommerce, sport, and interactive media", "Brazil", "2026_day1"),
        r(2026, "Relax Your Tight End", "Novartis", "Pharma", "b2c", "pharmaceuticals and cancer screening", "United States", "2026_day1"),
        r(2026, "Look Familiar?", "Heinz", "Print and Publishing", "b2c", "food and distinctive brand assets", "Canada and Global", "2026_day1"),
        r(2026, "Copycats Welcome", "Clash Royale", "Entertainment for Gaming", "b2c", "gaming and community", "United States and Global", "2026_day2"),
        r(2026, "The Thousand Sponsors of Muni", "Club Deportivo Municipal", "Entertainment for Sport", "b2b", "sport sponsorship and local business", "Peru", "2026_day2"),
        r(2026, "SOS POS", "BCP", "Creative Data", "b2c", "banking and fraud response", "Peru", "2026_day3"),
        r(2026, "Build Your Own Super Bowl", "Uber Eats", "Media", "b2c", "delivery commerce and participatory media", "United States", "2026_day3"),
        r(2026, "Uva Uva Bombón", "UVA App", "Direct", "b2c", "challenger delivery and cultural hijack", "Puerto Rico", "2026_day3"),
        r(2026, "The KitKat Heist", "KitKat", "PR", "b2c", "food and real-time reputation", "United Kingdom and Global", "2026_day3"),
        r(2026, "Could Have Been a Heineken", "Heineken", "Social and Creator", "b2c", "beverage and social behavior", "Italy and Global", "2026_day3"),
        r(2026, "The Wedding Rice", "Wikifarmer", "Creative Business Transformation", "b2b", "agriculture and marketplace", "Greece", "2026_day4"),
        r(2026, "The Pub that Refused to Die", "Heineken", "Creative Strategy", "b2b", "hospitality and community ownership", "Ireland", "2026_day4"),
        r(2026, "Lucky Fan Index", "Wisla Krakow", "Creative Commerce", "b2c", "sport and loyalty commerce", "Poland", "2026_day4"),
        r(2026, "Supernova Adaptive", "adidas", "Innovation", "b2c", "sport product design and inclusion", "Canada and Global", "2026_day4"),
        r(2026, "Warmer Together", "Moncler", "Luxury", "b2c", "luxury and human storytelling", "Malta, Italy, and Global", "2026_day4"),
        r(2026, "Expedition Impossible", "Columbia Sportswear", "Brand Experience and Activation", "b2c", "outdoor apparel and participatory challenge", "United Kingdom and Global", "2026_day4"),
        r(2026, "Claude No Ads Films", "Claude", "Film", "b2b", "AI software and brand strategy", "United Kingdom and United States", "2026_final"),
        r(2026, "Haven", "Suncorp Insurance", "Titanium", "b2c", "insurance and climate resilience", "Australia", "2026_final"),
        r(2026, "Nigrum Corpus Glass", "IDOMED and Instituto Yduqs", "Glass", "b2b", "medical education and inclusion", "Brazil", "2026_final"),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile a broad official-award discovery index without promoting claims into training.")
    parser.add_argument("--output", type=Path, default=Path("evidence/v10/gtm-breakout-expanded-case-index-v2.json"))
    args = parser.parse_args()
    result = compile_expanded_case_index(cases())
    verify_expanded_case_index(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "case_count": result["case_count"], "official_source_page_count": result["official_source_page_count"], "content_sha256": result["content_sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
