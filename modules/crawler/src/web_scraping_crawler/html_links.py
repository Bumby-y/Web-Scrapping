"""HTML URL-reference extraction without executing page scripts."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Iterable, List, Optional, Tuple

from .crawler import LinkReference

_TEXT_URL = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)
_CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
_CSS_IMPORT = re.compile(r"@import\s+(['\"])(.*?)\1", re.IGNORECASE)
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}"
_FILE_LINK_SUFFIXES = (
    ".7z",
    ".csv",
    ".doc",
    ".docx",
    ".epub",
    ".gz",
    ".mp3",
    ".mp4",
    ".pdf",
    ".ppt",
    ".pptx",
    ".rar",
    ".tar",
    ".xls",
    ".xlsx",
    ".zip",
)


class _HTMLLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: List[LinkReference] = []
        self.base_href: Optional[str] = None
        self._ignored_text_depth = 0
        self._style_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: List[Tuple[str, Optional[str]]],
    ) -> None:
        self._handle_tag(tag.lower(), attrs)

    def handle_startendtag(
        self,
        tag: str,
        attrs: List[Tuple[str, Optional[str]]],
    ) -> None:
        self._handle_tag(tag.lower(), attrs)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag == "style" and getattr(self, "_style_depth", 0):
            self._style_depth -= 1
        if normalized_tag in ("script", "style") and self._ignored_text_depth:
            self._ignored_text_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_text_depth:
            if self._in_style:
                self._add_css_urls(data, "style")
            else:
                self._add_text_urls(data, "script_reference", "script")
            return
        self._add_text_urls(data, "in_text", "text", follow=True)

    def _add_text_urls(
        self,
        data: str,
        category: str,
        attribute: str,
        follow: bool = False,
    ) -> None:
        for match in _TEXT_URL.finditer(data):
            self._add(
                match.group(0).rstrip(_TRAILING_URL_PUNCTUATION),
                category,
                attribute,
                follow=follow,
            )

    @property
    def _in_style(self) -> bool:
        return getattr(self, "_style_depth", 0) > 0

    def _handle_tag(
        self,
        tag: str,
        attrs: List[Tuple[str, Optional[str]]],
    ) -> None:
        attribute_names = {name.lower() for name, _ in attrs}
        values = {
            name.lower(): value
            for name, value in attrs
            if value is not None
        }
        if tag in ("script", "style"):
            self._ignored_text_depth += 1
            if tag == "style":
                self._style_depth = getattr(self, "_style_depth", 0) + 1

        if tag == "base" and values.get("href"):
            self.base_href = values["href"]
            self._add(values["href"], "base_reference", "href")

        href = values.get("href") or values.get("xlink:href")
        if href:
            if tag in ("a", "area"):
                path = href.split("?", 1)[0].split("#", 1)[0].lower()
                is_file = (
                    "download" in attribute_names
                    or path.endswith(_FILE_LINK_SUFFIXES)
                )
                self._add(
                    href,
                    "file_link" if is_file else "hyperlink",
                    "href",
                    follow=not is_file,
                )
            elif tag == "link":
                rels = values.get("rel", "").lower().split()
                category = self._link_category(rels)
                self._add(href, category, "href")
            elif tag in ("use", "image"):
                self._add(href, "svg_reference", "href")
            else:
                self._add(href, "hypertext_reference", "href")

        if tag == "img":
            self._add(values.get("src"), "image", "src")
            self._add_srcset(values.get("srcset"), "image", "srcset")
        elif tag == "source":
            self._add(values.get("src"), "media_resource", "src")
            self._add_srcset(values.get("srcset"), "media_resource", "srcset")
        elif tag == "script":
            self._add(values.get("src"), "script_resource", "src")
        elif tag in ("iframe", "frame", "embed"):
            self._add(values.get("src"), "embedded_resource", "src")
        elif tag in ("video", "audio", "track"):
            self._add(values.get("src"), "media_resource", "src")
            if tag == "video":
                self._add(values.get("poster"), "image", "poster")
        elif tag == "input" and values.get("type", "").lower() == "image":
            self._add(values.get("src"), "image", "src")

        if tag == "object":
            self._add(values.get("data"), "embedded_resource", "data")
        if tag == "form":
            self._add(values.get("action"), "form_action", "action")
        if values.get("formaction"):
            self._add(values["formaction"], "form_action", "formaction")
        if values.get("cite"):
            self._add(values["cite"], "citation", "cite")
        if values.get("ping"):
            for url in values["ping"].split():
                self._add(url, "pingback", "ping")
        if values.get("longdesc"):
            self._add(values["longdesc"], "hypertext_reference", "longdesc")
        if values.get("usemap"):
            self._add(values["usemap"], "hypertext_reference", "usemap")
        if values.get("background"):
            self._add(values["background"], "image", "background")

        for name in (
            "data-src",
            "data-original",
            "data-lazy-src",
            "data-url",
            "data-href",
            "data-link",
            "data-image",
            "data-background",
        ):
            if values.get(name):
                category = "image" if "image" in name or "src" in name else "data_reference"
                self._add(values[name], category, name)
        for name in ("data-srcset", "data-lazy-srcset"):
            self._add_srcset(values.get(name), "image", name)

        if values.get("style"):
            self._add_css_urls(values["style"], "style")
        if tag == "meta":
            self._handle_meta(values)

    def _handle_meta(self, attrs: dict[str, str]) -> None:
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        content = attrs.get("content")
        if not content:
            return
        if key in (
            "og:image",
            "og:image:url",
            "og:video",
            "og:audio",
            "twitter:image",
            "twitter:player",
        ):
            self._add(content, "meta_resource", "content")
        elif attrs.get("http-equiv", "").lower() == "refresh":
            match = re.search(r"url\s*=\s*['\"]?([^'\";]+)", content, re.IGNORECASE)
            if match:
                self._add(match.group(1).strip(), "meta_refresh", "content", follow=True)

    @staticmethod
    def _link_category(rels: List[str]) -> str:
        for rel in rels:
            if rel in ("stylesheet", "icon", "manifest", "preload", "modulepreload"):
                return "link_" + rel
        if "canonical" in rels:
            return "canonical"
        return "link_reference"

    def _add_srcset(self, value: Optional[str], category: str, attribute: str) -> None:
        if not value:
            return
        for candidate in value.split(","):
            parts = candidate.strip().split()
            if parts:
                self._add(parts[0], category, attribute)

    def _add_css_urls(self, value: str, attribute: str) -> None:
        for match in _CSS_URL.finditer(value):
            self._add(match.group(2).strip(), "css_resource", attribute)
        for match in _CSS_IMPORT.finditer(value):
            self._add(match.group(2).strip(), "css_resource", attribute)

    def _add(
        self,
        value: Optional[str],
        category: str,
        attribute: Optional[str],
        follow: bool = False,
    ) -> None:
        if not value or value.strip().lower().startswith("data:"):
            return
        self.references.append(
            LinkReference(
                url=value.strip(),
                category=category,
                attribute=attribute,
                follow=follow,
                base_url=self.base_href,
            )
        )


class HTMLLinkDiscoverer:
    """Extract categorized HTTP and non-HTTP references from HTML."""

    def discover_links(self, content: str) -> Iterable[LinkReference]:
        parser = _HTMLLinkParser()
        parser.feed(content)
        parser.close()
        return parser.references
