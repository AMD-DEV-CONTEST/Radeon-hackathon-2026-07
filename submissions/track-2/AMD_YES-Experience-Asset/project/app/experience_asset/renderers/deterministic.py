"""Render one stored RouteDraft envelope into preview, HTML, Markdown, and JSON."""

from __future__ import annotations

import json
from html import escape
from uuid import UUID

from app.experience_asset.delivery.models import (
    DeliveryOperation,
    RenderBundleV1,
    RenderedIdentityV1,
    StoredRouteDraftV1,
)


class DeterministicDeliveryRenderer:
    """Pure renderer: identical input and operation always produce identical bytes."""

    @staticmethod
    def identity(draft: StoredRouteDraftV1) -> RenderedIdentityV1:
        return RenderedIdentityV1(
            route_draft_id=draft.draft.route_draft_id,
            asset_id=draft.asset_id,
            version_id=draft.draft.canonical_version_id,
            asset_version_hash=draft.asset_version_hash,
            lineage_version_id=draft.lineage_version_id,
            lineage_parent_version_id=draft.lineage_parent_version_id,
            relation_projection_hash=draft.relation_projection_hash,
            route=draft.draft.route.value,
            language=draft.draft.language,
            route_draft_hash=draft.draft.content_hash,
            renderer_input_identity=draft.renderer_input_identity,
            privacy_state_hash=draft.privacy_state_hash,
            draft_state=draft.state,
        )

    def render(
        self,
        draft: StoredRouteDraftV1,
        *,
        operation: DeliveryOperation,
        approval_id: UUID | None = None,
    ) -> RenderBundleV1:
        if operation is DeliveryOperation.SHAREABLE_EXTERNAL_EXPORT and approval_id is None:
            raise ValueError("external export rendering requires an approval identity")
        identity = self.identity(draft)
        payload = {
            "schema_version": "e7-delivery/v1",
            "identity": identity.model_dump(mode="json"),
            "operation": operation.value,
            "approval_id": str(approval_id) if approval_id else None,
            "content": draft.content.model_dump(mode="json"),
            "notices": self._notices(draft, operation),
        }
        canonical_json = (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        return RenderBundleV1(
            identity=identity,
            operation=operation,
            approval_id=approval_id,
            html=self._html(draft, payload),
            markdown=self._markdown(draft, payload),
            canonical_json=canonical_json,
        )

    @staticmethod
    def _notices(
        draft: StoredRouteDraftV1,
        operation: DeliveryOperation,
    ) -> list[str]:
        language = draft.draft.language
        if operation is DeliveryOperation.SHAREABLE_EXTERNAL_EXPORT:
            delivery = (
                "此文件已通过精确版本绑定的外部交付批准。"
                if language == "zh-CN"
                else "This file has exact-version approval for external delivery."
            )
        else:
            delivery = (
                "私有预览或自用下载; 未批准用于外部分享。"
                if language == "zh-CN"
                else "Private preview or self-use download; not approved for external sharing."
            )
        superseded = []
        if draft.state.value == "SUPERSEDED":
            superseded = [
                "此输出已被新草稿替代 (SUPERSEDED)。"
                if language == "zh-CN"
                else "This output has been SUPERSEDED by a newer draft."
            ]
        return [delivery, *superseded, *draft.content.notices]

    def _html(self, draft: StoredRouteDraftV1, payload: dict[str, object]) -> str:
        identity = payload["identity"]
        assert isinstance(identity, dict)
        notices = "".join(
            f"<li>{escape(item)}</li>" for item in payload["notices"] if isinstance(item, str)
        )
        sections = []
        for section in draft.content.sections:
            claims = "".join(
                '<p data-statement-ids="{}">{}</p>'.format(
                    escape(",".join(str(value) for value in claim.statement_ids), quote=True),
                    escape(claim.text),
                )
                for claim in section.claims
            )
            sections.append(
                f"<details open><summary>{escape(section.heading)}</summary>{claims}</details>"
            )
        identity_json = json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        lang = "zh-CN" if draft.draft.language == "zh-CN" else "en"
        direction = "ltr"
        summary_statement_ids = escape(
            ",".join(str(value) for value in draft.content.summary.statement_ids),
            quote=True,
        )
        return (
            "<!doctype html>\n"
            f'<html lang="{lang}" dir="{direction}">\n'
            "<head>\n"
            '<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
            f'<meta name="e7-route-draft-hash" content="{draft.draft.content_hash}">\n'
            f"<title>{escape(draft.content.title)}</title>\n"
            "<style>"
            ":root{color-scheme:light dark;font-family:system-ui,sans-serif;line-height:1.55}"
            "body{max-width:760px;margin:0 auto;padding:32px 20px}"
            ".identity{font:12px ui-monospace,monospace;overflow-wrap:anywhere;opacity:.75}"
            ".notice{border:1px solid #b58105;border-radius:10px;"
            "padding:12px 16px;background:#fff7df}"
            "details{border-top:1px solid #9995;padding:14px 0}"
            "summary{font-weight:700;cursor:pointer}"
            "@media(prefers-color-scheme:dark){.notice{background:#332807}}"
            "</style>\n"
            "</head>\n"
            f'<body data-draft-state="{draft.state.value}" '
            f'data-asset-id="{draft.asset_id}" '
            f'data-version-id="{draft.draft.canonical_version_id}" '
            f'data-route-draft-hash="{draft.draft.content_hash}" '
            f'data-relation-projection-hash="{draft.relation_projection_hash}" '
            f'data-renderer-input-identity="{draft.renderer_input_identity}">\n'
            f"<header><h1>{escape(draft.content.title)}</h1>"
            f'<p data-statement-ids="{summary_statement_ids}">'
            f"{escape(draft.content.summary.text)}</p></header>\n"
            f'<aside class="notice" aria-label="Delivery status"><ul>{notices}</ul></aside>\n'
            f"<main>{''.join(sections)}</main>\n"
            f'<footer class="identity">version={identity["version_id"]} · '
            f"hash={identity['route_draft_hash']} · state={identity['draft_state']}</footer>\n"
            f'<script type="application/json" id="e7-delivery-identity">{identity_json}</script>\n'
            "</body>\n</html>\n"
        )

    def _markdown(self, draft: StoredRouteDraftV1, payload: dict[str, object]) -> str:
        identity = payload["identity"]
        identity_json = json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        lines = [
            f"<!-- e7-delivery-identity:{identity_json} -->",
            f"# {draft.content.title}",
            "",
            draft.content.summary.text,
            "",
        ]
        for notice in payload["notices"]:
            lines.append(f"> {notice}")
        lines.append("")
        for section in draft.content.sections:
            lines.extend([f"## {section.heading}", ""])
            for claim in section.claims:
                statement_ids = ",".join(str(value) for value in claim.statement_ids)
                lines.extend([claim.text, "", f"<!-- statements:{statement_ids} -->", ""])
        return "\n".join(lines).rstrip() + "\n"
