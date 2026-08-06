from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from marko import HTMLRenderer, Markdown
from marko.ext.gfm import GFM
from marko.ext.gfm.renderer import GFMRendererMixin
from marko.helpers import MarkoExtension


def render_chat_markdown(markdown: str, *, inline_artifact_images: bool) -> str:
    renderer = _InlineArtifactRenderer if inline_artifact_images else _LinkOnlyArtifactRenderer
    html = Markdown(renderer=renderer, extensions=[_SAFE_GFM_EXTENSION]).convert(markdown).rstrip()
    return _wrap_code_blocks(html)


def normalize_artifact_uri(uri: str) -> str:
    parts = urlsplit(uri)
    if parts.scheme != "artifact":
        return uri

    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key != "view"
        ]
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _wrap_code_blocks(html: str) -> str:
    pre_style = ' style="white-space: pre-wrap; word-wrap: break-word; overflow-wrap: anywhere;"'
    code_style = ' style="white-space: pre-wrap; word-wrap: break-word; overflow-wrap: anywhere;"'
    return html.replace("<pre><code", f"<pre{pre_style}><code{code_style}")


class _BaseChatRenderer(HTMLRenderer):
    inline_artifact_images = False

    def render_html_block(self, element) -> str:  # type: ignore[override]
        return self.escape_html(element.body)

    def render_inline_html(self, element) -> str:  # type: ignore[override]
        return self.escape_html(str(element.children))

    def render_link(self, element) -> str:  # type: ignore[override]
        dest = normalize_artifact_uri(element.dest)
        title = f' title="{self.escape_html(element.title)}"' if element.title else ""
        return '<a href="{}"{}>{}</a>'.format(
            self.escape_url(dest),
            title,
            self.render_children(element),
        )

    def render_image(self, element) -> str:  # type: ignore[override]
        dest = normalize_artifact_uri(element.dest)
        alt = self._plain_text(element)
        title = f' title="{self.escape_html(element.title)}"' if element.title else ""
        if self.inline_artifact_images and urlsplit(dest).scheme == "artifact":
            escaped_dest = self.escape_url(dest)
            return '<a href="{0}"><img src="{0}" alt="{1}"{2} /></a>'.format(
                escaped_dest,
                self.escape_html(alt),
                title,
            )
        link_text = self.escape_html(alt or "Image")
        return '<a href="{}"{}>{}</a>'.format(self.escape_url(dest), title, link_text)

    def _plain_text(self, element) -> str:
        render_func = self.render
        self.render = self.render_plain_text  # type: ignore[method-assign]
        try:
            return str(self.render_children(element))
        finally:
            self.render = render_func  # type: ignore[method-assign]


class _InlineArtifactRenderer(_BaseChatRenderer):
    inline_artifact_images = True


class _LinkOnlyArtifactRenderer(_BaseChatRenderer):
    inline_artifact_images = False


class _SafeGFMRendererMixin(GFMRendererMixin):
    def render_html_block(self, element) -> str:  # type: ignore[override]
        return self.escape_html(element.body)

    def render_inline_html(self, element) -> str:  # type: ignore[override]
        return self.escape_html(str(element.children))

    def render_table(self, element) -> str:  # type: ignore[override]
        head, *body = element.children
        theader = f"<thead>\n{self.render(head)}</thead>"
        tbody = ""
        if body:
            tbody = "\n<tbody>\n{}</tbody>".format(
                "".join(self.render(row) for row in body)
            )
        return (
            '<table border="1" cellspacing="0" cellpadding="4" '
            'style="border-collapse: collapse; border: 1px solid #c7cdd4;">\n'
            f"{theader}{tbody}</table>"
        )

    def render_table_cell(self, element) -> str:  # type: ignore[override]
        tag = "th" if element.header else "td"
        declarations = ["border: 1px solid #c7cdd4", "padding: 4px 6px"]
        if element.header:
            declarations.append("font-weight: bold")
        if element.align:
            declarations.append(f"text-align: {self.escape_html(element.align)}")
        style = "; ".join(declarations)
        return '<{tag} style="{style}">{children}</{tag}>\n'.format(
            tag=tag,
            style=style,
            children=self.render_children(element),
        )


_SAFE_GFM_EXTENSION = MarkoExtension(
    parser_mixins=list(GFM.parser_mixins),
    renderer_mixins=[_SafeGFMRendererMixin],
    elements=list(GFM.elements),
)
