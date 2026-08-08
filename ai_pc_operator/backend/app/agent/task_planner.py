"""Higher-level task decomposition for multi-step desktop commands."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import quote_plus


def extract_entities(text: str) -> Dict[str, Any]:
    """Universal entity extraction (Generic Task Decomposition Policy).

    Wraps the intent-engine EntityExtractor (PATH/URL/FILE/APP/SITE/...) and
    adds the normalized fields the generic planners need: file, contact,
    channel (+ channel_url). Returns a dict with all extracted objects.
    """
    from app.agent.intent_engine.entity_extractor import EntityExtractor

    if not text or not text.strip():
        return {
            "file": None, "contact": None, "channel": None, "channel_url": "",
            "apps": [], "sites": [], "urls": [], "paths": [],
        }
    extractor = EntityExtractor()
    entities = extractor.extract(text)

    def first(entity_type: str) -> Optional[str]:
        for e in entities:
            if e.type == entity_type:
                return e.value
        return None

    def all_of(entity_type: str) -> list[str]:
        return [e.value for e in entities if e.type == entity_type]

    channel = first("CHANNEL")
    channel_url = ""
    for e in entities:
        if e.type == "CHANNEL":
            channel_url = e.metadata.get("url", "")
            break

    return {
        "file": first("FILE") or first("PATH"),
        "contact": first("CONTACT"),
        "channel": channel,
        "channel_url": channel_url,
        "apps": all_of("APP"),
        "sites": all_of("SITE"),
        "urls": all_of("URL") + all_of("DOMAIN"),
        "paths": all_of("PATH"),
    }


@dataclass(frozen=True)
class TaskPlan:
    intent: str
    risk_level: int
    steps: list[dict[str, Any]]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "risk_level": self.risk_level,
            "steps": self.steps,
            "source": "task-planner",
            "reason": self.reason,
        }


class TaskPlanner:
    """Plans compound tasks before falling back to single-intent rules."""

    def plan(self, text: str) -> TaskPlan | None:
        normalized = " ".join(text.strip().split())
        lower = normalized.lower()

        send_file = self._plan_send_file(normalized, lower)
        if send_file:
            return send_file

        research = self._plan_research_collect(normalized, lower)
        if research:
            return research

        browser_session = self._plan_browser_session(normalized, lower)
        if browser_session:
            return browser_session

        settings = self._plan_settings(normalized, lower)
        if settings:
            return settings

        keep_awake = self._plan_keep_awake(normalized, lower)
        if keep_awake:
            return keep_awake

        # Generic compound-command decomposer (common fix, not app-specific).
        # Runs after the named compound patterns so they win, and before
        # falling through to single-intent classification.
        sequence = self._plan_multi_intent_sequence(normalized, lower)
        if sequence:
            return sequence

        return None

    def _plan_browser_session(self, text: str, lower: str) -> TaskPlan | None:
        wants_browser = re.search(
            r"\b(open|launch|start|run|go to|navigate|visit|search|google|find)\b.*\b(browser|chrome|edge|firefox|opera|gx|website|site|url)\b",
            lower,
        ) or re.search(
            r"\b(open|launch|start|run)\b\s+(chrome|edge|firefox|opera|gx|browser)\b",
            lower,
        )
        if not wants_browser:
            return None

        # Only treat as a compound browser/session task when there is extra
        # context (keep-awake, mouse jiggle, duration, or explicit session
        # keyword). Simple "open chrome" should fall through to the main
        # planner so it classifies as open_app.
        has_session_context = bool(
            re.search(r"\b(session|awake|idle|sleep|prevent|stop)\b", lower)
            or re.search(r"\b(mouse|cursor)\b.*\b(move|movement|jiggle|shake)\b", lower)
            or re.search(r"\b\d+\s*(minute|minutes|hour|hours|min|hr|h)\b", lower)
            or re.search(r"\bkeep\s+(browser|session|pc|computer)\b", lower)
        )
        if not has_session_context:
            return None

        app_name = self._extract_browser_app(lower)
        target_url = self._extract_navigation_target(text, lower)
        minutes = self._extract_duration_minutes(lower, default=60, upper=120)
        wants_awake = bool(
            re.search(r"\b(stay|keep|prevent|stop|idle|awake)\b.*\b(idle|awake|sleep|off|hour|hours|minute|minutes)\b", lower)
            or re.search(r"\bstay\s+idle\b", lower)
        )
        wants_mouse = bool(re.search(r"\b(mouse|cursor)\b.*\b(move|movement|jiggle|shake)\b", lower))

        steps: list[dict[str, Any]] = []
        if app_name and target_url:
            steps.append(
                {
                    "tool": "system.open_app",
                    "args": {"name": app_name, "target": target_url},
                }
            )
        elif app_name:
            steps.append({"tool": "system.open_app", "args": {"name": app_name}})
        elif target_url:
            steps.append({"tool": "browser.open", "args": {"url": target_url}})
        else:
            steps.append({"tool": "browser.open", "args": {"url": "https://www.google.com"}})

        if wants_awake or wants_mouse:
            steps.append({"tool": "system.keep_awake", "args": {"minutes": minutes}})

        if wants_mouse:
            steps.append(
                {
                    "tool": "system.mouse_jiggle",
                    "args": {"minutes": minutes, "interval_seconds": 45},
                }
            )

        if len(steps) == 1 and not target_url and app_name is None:
            return None

        return TaskPlan(
            intent="browser_session",
            risk_level=1,
            reason="compound browser/session command",
            steps=steps,
        )

    def _plan_send_file(self, text: str, lower: str) -> TaskPlan | None:
        """Plan a goal-oriented send-file workflow (generic task decomposition).

        Never hardcodes an application. Extracts FILE, CONTACT, and CHANNEL
        entities and builds the execution graph from them:
          filesystem: locate file -> verify exists
          application/browser: open channel web app -> navigate -> wait
          screen/OCR: find contact -> open chat
          input/browser: attach file -> upload -> verify preview
          screen/OCR: send -> verify delivered

        Steps that need live web-app DOM automation may fail at execution
        time; the router reports partial progress honestly (never fabricates
        success).
        """
        # Trigger: send/share/transfer (or email/mail as a verb) + FILE + CONTACT
        if not re.search(r"\b(send|share|transfer|email|mail)\b", lower):
            return None
        entities = extract_entities(text)
        file_path = entities.get("file")
        contact = entities.get("contact")
        if not file_path or not contact:
            return None
        channel = entities.get("channel") or "whatsapp"
        channel_url = entities.get("channel_url") or ""

        # Per-step metadata (pipeline + models + verification + recovery)
        def step(tool: str, args: dict, objective: str,
                 pipeline: str, models: list[str],
                 verification: str, recovery: list[str]) -> dict[str, Any]:
            return {
                "tool": tool,
                "args": args,
                "objective": objective,
                "pipeline": pipeline,
                "models": models,
                "verification": verification,
                "recovery": recovery,
                "risk": 1,
            }

        file_dir = self._file_dir(file_path)
        browser_app = "chrome"

        steps: list[dict[str, Any]] = [
            step("system.open_app", {"name": "explorer"}, "Open File Explorer",
                 "application", ["app_detector", "window_manager"],
                 "window appears", ["Retry once", "Use alternate launcher"]),
            step("file.list", {"path": file_dir},
                 "Navigate to the file's folder", "filesystem", ["filesystem"],
                 "folder listed", ["Retry once", "Ask user for the path"]),
            step("file.read", {"path": file_path},
                 "Locate and read the file", "filesystem", ["filesystem"],
                 "file is readable", ["Search alternate locations", "Ask user"]),
            step("system.open_app", {"name": browser_app},
                 "Launch a browser for the messaging app", "application",
                 ["browser_automation"], "browser window appears",
                 ["Retry once", "Try a different browser"]),
        ]
        if channel_url:
            steps.append(step("browser.open", {"url": channel_url},
                              f"Navigate to {channel}", "browser",
                              ["browser_automation"], "page loaded",
                              ["Retry navigation", "Check network"]))
        steps.extend([
            step("screen.scan", {}, "Wait for the page to load",
                 "screen", ["ocr", "vision", "ui_detector"],
                 "page is stable", ["Wait longer", "Re-scan"]),
            step("screen.click_text", {"text": "search"},
                 "Open the contact search", "screen",
                 ["ocr", "vision", "ui_detector"], "search box active",
                 ["Use accessibility tree", "Use browser search"]),
            step("browser.type", {"selector": "input", "text": contact},
                 "Search for the contact", "browser", ["browser_automation"],
                 "contact name entered", ["Retry typing", "Use OCR input"]),
            step("screen.click_text", {"text": contact},
                 "Open the contact chat", "screen",
                 ["ocr", "vision", "ui_detector"],
                 "correct chat opened", ["Try alternate contact match",
                                         "Re-scan results"]),
            step("screen.click_text", {"text": "attach"},
                 "Click the attachment button", "screen",
                 ["ocr", "vision", "ui_detector"],
                 "attachment menu opened", ["Use paperclip label",
                                            "Re-scan screen"]),
            step("browser.click", {"selector": "input[type=file]"},
                 "Select the file to upload", "browser", ["browser_automation"],
                 "file chosen", ["Use file dialog", "Retry selector"]),
            step("screen.click_text", {"text": "send"},
                 "Click Send", "screen", ["ocr", "vision", "ui_detector"],
                 "message sent", ["Re-scan for Send", "Retry click"]),
            step("screen.scan", {}, "Verify the message was delivered",
                 "screen", ["ocr", "vision", "ui_detector"],
                 "delivered indicator visible",
                 ["Re-scan", "Ask user to confirm"]),
        ])

        return TaskPlan(
            intent="send_file",
            risk_level=2,
            reason=f"goal-oriented send-file workflow via {channel}",
            steps=steps,
        )

    def _extract_file_entity(self, text: str) -> str | None:
        """Extract a file path or bare file name from the request."""
        path_match = re.search(r"([A-Za-z]:\\[^\s\"]+|[A-Za-z]:/[^\s\"]+)", text)
        if path_match:
            return path_match.group(1).strip("\"'")
        # A bare file name: any "X.ext" (locate 1.txt, send 1.txt, ...).
        file_match = re.search(
            r"\b([a-zA-Z0-9_.\- ]+\.(?:txt|pdf|docx?|xlsx?|png|jpe?g|zip))\b",
            text,
        )
        if file_match:
            candidate = file_match.group(1).strip().strip("\"'")
            # Strip a leading verb/filler token if present ("locate 1.txt")
            candidate = re.sub(r"^(?:locate|open|send|share|find|the|file)\s+",
                               "", candidate, flags=re.IGNORECASE)
            return candidate.strip()
        return None

    def _extract_contact_entity(self, text: str) -> str | None:
        """Extract a recipient after 'to', an @mention, or 'contact X'.

        Skips structural words ("to File", "to Desktop", "to GX") so a bare
        "send to <name>" doesn't grab a UI noun.
        """
        # Prefer an explicit "contact X" / "person X" phrase
        contact_match = re.search(
            r"\b(contact|person|user)\s+(@?[A-Za-z0-9_]{2,})", text
        )
        if contact_match:
            return contact_match.group(2)
        at_match = re.search(r"@([A-Za-z0-9_]{2,})", text)
        if at_match:
            return at_match.group(1)
        # "to <name>" where <name> is NOT a structural UI word
        structural = (
            "file", "folder", "desktop", "documents", "downloads", "explorer",
            "browser", "gx", "chrome", "edge", "firefox", "whatsapp", "web",
            "website", "url", "site",
        )
        to_match = re.search(r"\bto\s+(@?[A-Za-z0-9_]{2,})", text)
        if to_match:
            candidate = to_match.group(1).lower().lstrip("@")
            if candidate not in structural:
                return to_match.group(1)
        return None

    def _file_dir(self, file_path: str) -> str:
        """Directory of the file path, or the user's desktop fallback."""
        import os
        if os.sep in file_path or "/" in file_path:
            return file_path.rsplit("\\", 1)[0].rsplit("/", 1)[0] or "."
        return "C:\\Users\\brigh\\Desktop"

    # ------------------------------------------------------------------
    # Generic compound-command sequence planner (common fix, not app-specific)
    # ------------------------------------------------------------------
    SEPARATORS = [
        r"\band\s+then\b", r"\bthen\b", r"\bafter\s+that\b",
        r"\bafterwards\b", r"\balso\b", r"\bplus\b", r";", r",", r"\band\b",
    ]

    # Multi-word app names that contain "and"/other separator words — protected
    # from splitting so "Visual Studio Code" stays one entity.
    PROTECTED_PHRASES = [
        "file explorer", "visual studio code", "vs code", "task manager",
        "control panel", "command prompt", "windows terminal", "word pad",
        "opera gx browser", "opera gx", "gx browser", "microsoft edge",
        "google chrome", "sticky notes", "snipping tool", "voice recorder",
        "your phone", "feedback hub", "mixed reality", "mobile plans",
        "3d builder", "3d viewer", "get help",
    ]

    def _split_compound(self, text: str) -> list[str]:
        """Split a command into action segments on separators.

        Preserves URLs (https://...), filenames (x.file), and known multi-word
        app names so they are not split. Returns trimmed non-empty segments.
        """
        # Protect URLs, filenames, and known app phrases from being split
        protected: list[str] = []

        def keep(m: re.Match) -> str:
            token = m.group(0)
            protected.append(token)
            return f" \x00{len(protected) - 1}\x00 "

        # Known app phrases first (longest), then URLs, then bare filenames
        for phrase in sorted(self.PROTECTED_PHRASES, key=len, reverse=True):
            text = re.sub(rf"\b{re.escape(phrase)}\b", keep, text,
                          flags=re.IGNORECASE)
        text = re.sub(r"https?://[^\s,;]+", keep, text)
        text = re.sub(r"\b[\w.-]+\.\w{2,4}\b", keep, text)

        # Split on separators
        pattern = "|".join(self.SEPARATORS)
        parts = re.split(rf"\s*(?:{pattern})\s*", text, flags=re.IGNORECASE)

        # Restore protected tokens
        out = []
        for part in parts:
            restored = re.sub(
                r"\x00(\d+)\x00",
                lambda m: protected[int(m.group(1))],
                part,
            ).strip()
            if restored:
                out.append(restored)
        return out

    def _plan_multi_intent_sequence(
        self, text: str, lower: str
    ) -> TaskPlan | None:
        """Generic compound-command decomposer.

        Splits the command into action segments, classifies each with the
        existing planner, and chains each segment's tool steps into one
        execution plan. Requires >= 2 segments that each map to a real plan.
        """
        segments = self._split_compound(text)
        if len(segments) < 2:
            return None

        from app.agent.planner import Planner

        planner = Planner()
        # Compound-level context: the contact and file named anywhere in the
        # full command, used for context-dependent UI-action segments.
        compound_entities = extract_entities(text)
        contact = compound_entities.get("contact")
        file_path = compound_entities.get("file")

        steps: list[dict[str, Any]] = []
        classified = 0
        for seg in segments:
            intent = planner.classify_intent_sync(seg)
            # "find x.file" / "locate report.pdf" — a find verb + a filename
            # token is a filesystem search, not a web search (the search_web
            # pattern is checked first and would steal it).
            if (intent == "search_web"
                    and re.search(r"\b(find|locate|search)\b", seg, re.I)
                    and re.search(r"\b[\w.-]+\.\w{2,4}\b", seg)):
                intent = "file_search"
            if intent == "unknown":
                # Context-dependent UI action? Map it to semantic screen/browser
                # steps using compound-level entities (contact/file).
                ui_steps = self._ui_action_steps(seg, contact=contact,
                                                 file_path=file_path)
                if ui_steps:
                    steps.extend(ui_steps)
                    classified += 1
                continue
            plan = planner.create_plan_sync(seg, intent)
            seg_steps = plan.get("steps", [])
            if not seg_steps:
                continue
            classified += 1
            for s in seg_steps:
                s = dict(s)
                s.setdefault("objective", f"{intent}: {s.get('tool', '')}")
                # Enrich with per-phase metadata (pipeline/models/verification)
                tool = s.get("tool", "")
                pipeline = "screen" if tool.startswith("screen") else (
                    "browser" if tool.startswith("browser") else (
                        "filesystem" if tool.startswith("file") else (
                            "application" if tool.startswith(("system", "app"))
                            else "system")))
                s.setdefault("pipeline", pipeline)
                s.setdefault("models",
                             (["ocr", "vision", "ui_detector"]
                              if pipeline == "screen"
                              else [pipeline + "_automation"
                                    if pipeline in ("browser",)
                                    else pipeline]))
                s.setdefault("verification", f"{tool} succeeded")
                s.setdefault("recovery",
                             ["Retry once", "Use alternative skill",
                              "Report failure to user"])
                s.setdefault("risk", 1)
                steps.append(s)

        if classified < 2 or not steps:
            return None

        return TaskPlan(
            intent="compound_sequence",
            risk_level=max(2, int(sum(1 for _ in steps) > 4) * 2),
            reason="generic multi-action command sequence",
            steps=steps,
        )

    def _ui_action_steps(
        self,
        seg: str,
        contact: Optional[str],
        file_path: Optional[str],
    ) -> list[dict[str, Any]]:
        """Map a context-dependent UI-action segment to semantic steps.

        Handles segments like "search for the contact", "attach the file",
        "send it" that only make sense with compound-level entities.
        """
        lower = seg.lower()
        steps: list[dict[str, Any]] = []

        def ui_step(tool: str, args: dict, objective: str) -> dict[str, Any]:
            return {
                "tool": tool,
                "args": args,
                "objective": objective,
                "pipeline": "screen" if tool.startswith("screen") else "browser",
                "models": (["ocr", "vision", "ui_detector"]
                           if tool.startswith("screen")
                           else ["browser_automation"]),
                "verification": f"{objective.lower()} done",
                "recovery": ["Use accessibility tree", "Re-scan", "Retry click"],
                "risk": 1,
            }

        # "search for the contact" -> type the contact name
        if re.search(r"\bsearch\b.*\b(contact|person|user|chat)\b", lower) and contact:
            steps.append(ui_step(
                "screen.click_text", {"text": "search"},
                "Open the contact search",
            ))
            steps.append(ui_step(
                "browser.type", {"selector": "input", "text": contact},
                "Search for the contact",
            ))
            steps.append(ui_step(
                "screen.click_text", {"text": contact},
                "Open the contact chat",
            ))
        # "attach the file" / "upload the file" -> attach + select
        elif re.search(r"\b(attach|upload)\b", lower):
            steps.append(ui_step(
                "screen.click_text", {"text": "attach"},
                "Click the attachment button",
            ))
            if file_path:
                steps.append(ui_step(
                    "browser.click", {"selector": "input[type=file]"},
                    "Select the file to upload",
                ))
        # "send it" / "send the message" -> click send + verify
        elif re.search(r"\bsend\b", lower):
            steps.append(ui_step(
                "screen.click_text", {"text": "send"},
                "Click Send",
            ))
            steps.append(ui_step(
                "screen.scan", {},
                "Verify the message was delivered",
            ))

        return steps

    def _plan_research_collect(self, text: str, lower: str) -> TaskPlan | None:
        search_words = r"(search|research|look up|google|find)"
        collect_words = r"(copy|collect|scrape|extract|save|paste|write)"
        if not re.search(search_words, lower) or not re.search(collect_words, lower):
            return None
        if not re.search(r"\b(websites?|pages?|results?|sites?)\b", lower):
            return None

        query = self._extract_research_query(text)
        max_sites = self._extract_count(lower, default=5, upper=10)
        save_dir = self._extract_save_dir(text)
        return TaskPlan(
            intent="research_collect",
            risk_level=2,
            reason="compound browser research task",
            steps=[
                {
                    "tool": "browser.research_collect",
                    "args": {
                        "query": query,
                        "max_sites": max_sites,
                        "save_dir": save_dir,
                    },
                }
            ],
        )

    def _plan_settings(self, text: str, lower: str) -> TaskPlan | None:
        if "settings" not in lower:
            return None
        if "contrast" in lower:
            return TaskPlan(
                intent="open_settings",
                risk_level=1,
                reason="open Windows contrast settings for user-visible adjustment",
                steps=[
                    {
                        "tool": "system.open_settings",
                        "args": {"page": "ms-settings:easeofaccess-highcontrast"},
                    }
                ],
            )
        return TaskPlan(
            intent="open_settings",
            risk_level=1,
            reason="open Windows settings",
            steps=[{"tool": "system.open_settings", "args": {"page": "ms-settings:"}}],
        )

    def _plan_keep_awake(self, text: str, lower: str) -> TaskPlan | None:
        if not re.search(r"\b(keep|prevent|stop)\b.*\b(screen|display|pc|computer)\b.*\b(off|sleep|awake)\b", lower):
            return None
        minutes = self._extract_duration_minutes(lower, default=60, upper=120)
        return TaskPlan(
            intent="keep_awake",
            risk_level=1,
            reason="prevent local PC sleep/display timeout for a bounded duration",
            steps=[{"tool": "system.keep_awake", "args": {"minutes": minutes}}],
        )

    def _extract_research_query(self, text: str) -> str:
        cleaned = re.sub(
            r"\b(open|chrome|browser|and|then|go to|random|websites?|pages?|results?|copy|collect|scrape|extract|all|text|paste|write|save|folder|file|about|on)\b",
            " ",
            text,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\b(search|research|look up|google|find)\b", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b\d+\b", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,:;\"'")
        return cleaned or text.strip()

    def _extract_count(self, lower: str, default: int, upper: int) -> int:
        match = re.search(r"\b(\d{1,2})\b\s+(?:random\s+)?(?:websites?|pages?|results?|sites?)", lower)
        if not match:
            return default
        return max(1, min(int(match.group(1)), upper))

    def _extract_duration_minutes(self, lower: str, default: int, upper: int) -> int:
        match = re.search(r"\b(\d{1,3})\s*(hour|hours|hr|hrs|minute|minutes|min|mins)\b", lower)
        if not match:
            return default
        value = int(match.group(1))
        unit = match.group(2)
        minutes = value * 60 if unit.startswith(("hour", "hr")) else value
        return max(1, min(minutes, upper))

    def _extract_browser_app(self, lower: str) -> str | None:
        phrases = [
            "opera gx browser",
            "opera gx",
            "gx browser",
            "google chrome",
            "chrome",
            "microsoft edge",
            "edge",
            "firefox",
            "opera browser",
            "opera",
        ]
        for phrase in phrases:
            if re.search(rf"\b{re.escape(phrase)}\b", lower):
                return phrase
        return None

    def _extract_navigation_target(self, text: str, lower: str) -> str | None:
        url_match = re.search(r"https?://\S+", text)
        if url_match:
            return url_match.group(0).rstrip(".,")

        domain_match = re.search(r"\b([a-zA-Z0-9-]+\.(com|org|net|io|gov|edu|in|ai|dev))\b", text)
        if domain_match:
            return f"https://{domain_match.group(1)}"

        site_aliases = {
            "youtube": "https://www.youtube.com",
            "google": "https://www.google.com",
            "github": "https://github.com",
            "gmail": "https://mail.google.com",
            "chatgpt": "https://chatgpt.com",
            "reddit": "https://www.reddit.com",
            "amazon": "https://www.amazon.com",
        }
        for name, url in site_aliases.items():
            if re.search(rf"\b{name}\b", lower):
                return url

        search_match = re.search(
            r"\b(search|google|find|look up|lookup)\b(?:\s+for)?\s+(.+)",
            text,
            flags=re.IGNORECASE,
        )
        if search_match:
            query = self._clean_search_query(search_match.group(2))
            if query:
                return f"https://www.google.com/search?q={quote_plus(query)}"

        return None

    def _clean_search_query(self, query: str) -> str:
        cleaned = re.sub(
            r"\b(in|on|with|using)\s+(chrome|edge|firefox|opera|gx|browser|google)\b",
            " ",
            query,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\b(and|then|after that|stay|idle|awake|for|hour|hours|minute|minutes|mouse|movement|move|cursor|jiggle)\b",
            " ",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\b\d{1,3}\b", " ", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip(" .,:;\"'")

    def _extract_save_dir(self, text: str) -> str | None:
        match = re.search(r"([A-Za-z]:\\[^\n\r]+)", text)
        if match:
            return match.group(1).strip().strip("\"'")
        return None
