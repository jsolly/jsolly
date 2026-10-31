#!/usr/bin/env python3
"""The profile README's contract: what the public page at github.com/jsolly must keep saying.

README.md is the whole deliverable (AGENTS.md -> Purpose). These offline checks run in the
gate, so a README edit that drops the role line, a required exit link or image alt text, or
breaks the HTML, fails PR CI instead of reaching the profile.
"""
from html.parser import HTMLParser
from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"
ROLE = "CTO of Enterprise Health at Leidos Digital"
REQUIRED_LINKS = (
    "https://www.jsolly.com/",
    "https://www.jsolly.com/John-Solly-Resume.pdf",
    "https://www.jsolly.com/blog/",
    "https://www.jsolly.com/contact/",
)
PLACEHOLDER_ALTS = {"image", "img", "picture", "banner", "logo", "icon", "typing svg"}
VOID_TAGS = {"br", "hr", "img", "source", "wbr"}


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.open_tags: list[str] = []
        self.mismatched: list[str] = []
        self.hrefs: list[str] = []
        self.image_alts: list[str | None] = []
        self.target_tags: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if "target" in values:
            self.target_tags.append(tag)
        if tag == "a" and values.get("href"):
            self.hrefs.append(values["href"])
        if tag == "img":
            self.image_alts.append(values.get("alt"))
        if tag not in VOID_TAGS:
            self.open_tags.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.open_tags.pop()

    def handle_endtag(self, tag: str) -> None:
        if self.open_tags and self.open_tags[-1] == tag:
            self.open_tags.pop()
        else:
            self.mismatched.append(tag)

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def _page() -> _Page:
    page = _Page()
    page.feed(README.read_text(encoding="utf-8"))
    page.close()
    return page


def test_the_profile_states_the_current_role_on_its_first_screen():
    assert ROLE in " ".join("".join(_page().text).split())


def test_the_profile_links_the_site_resume_blog_and_contact_page():
    hrefs = _page().hrefs
    assert [link for link in REQUIRED_LINKS if link not in hrefs] == []


def test_every_profile_image_has_descriptive_alt_text():
    alts = _page().image_alts
    assert [alt for alt in alts if not alt or alt.strip().lower() in PLACEHOLDER_ALTS] == []


def test_the_profile_uses_no_target_attribute_github_would_strip():
    assert _page().target_tags == []


def test_the_profile_html_is_balanced():
    page = _page()
    assert (page.open_tags, page.mismatched) == ([], [])
