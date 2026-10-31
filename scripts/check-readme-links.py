"""Check that every link and image in README.md still resolves.

README.md is HTML plus remote images (AGENTS.md -> Purpose). Every ``href``,
``src`` and ``srcset`` must be an https URL answering 2xx; image sources must
also answer ``image/*``. ``mailto:`` and ``#`` links are not fetched. Anything
this checker cannot verify fails instead of passing unchecked: Markdown link
syntax, autolinks, bare ``https://`` or ``www.`` URLs, non-https references and
empty or valueless attributes. Operator guide: docs/development.md -> README health.
"""

import http.client
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

ATTEMPTS = 3
TIMEOUT_SECONDS = 20
USER_AGENT = "jsolly-readme-health/1 (+https://github.com/jsolly/jsolly)"
REMOTE_SCHEMES = ("https://",)
_sleep = time.sleep  # the checker's own binding, so tests can record backoff without a global stub

# GitHub, like any HTML5 parser, keeps `&center=` in an attribute literal; html.parser on
# Python < 3.13 decodes the legacy `&cent` inside it. Escaping every `&` that does not start a
# semicolon-terminated reference makes html.parser's attribute values match GitHub's.
_BARE_AMPERSAND = re.compile(r"&(?!(?:#[0-9]+|#[xX][0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]*);)")
# Every URL-looking text run fails, even as <a> link text: GitHub may autolink it unchecked.
_UNSUPPORTED_TEXT = (
    (re.compile(r"\]\(|\]\["), "Markdown link syntax"),
    (re.compile(r"^ {0,3}\[[^\]]+\]:\s*\S", re.M), "Markdown link reference definition"),
    (re.compile(r"(?<![A-Za-z0-9])(?:https?://|ftp://|www\.)", re.I), "bare URL"),
)
_UNSUPPORTED_HINT = "is not checked; write it as an HTML <a href> or <img src> with an https URL"


@dataclass(frozen=True)
class Reference:
    url: str
    is_image: bool


def _srcset_urls(value: str) -> list[str]:
    """Candidate URLs per the HTML srcset rules: a URL runs to whitespace; commas separate."""
    urls, position, length = [], 0, len(value)
    while True:
        while position < length and (value[position].isspace() or value[position] == ","):
            position += 1
        if position >= length:
            return urls
        start = position
        while position < length and not value[position].isspace():
            position += 1
        url = value[start:position]
        if url.endswith(","):
            urls.append(url.rstrip(","))
            continue
        urls.append(url)
        depth = 0
        while position < length and not (value[position] == "," and depth == 0):
            if value[position] == "(":
                depth += 1
            elif value[position] == ")" and depth:
                depth -= 1
            position += 1


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[Reference] = []
        self.unsupported: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if ":" in tag:
            self.unsupported.append(f"autolink <{tag}...> {_UNSUPPORTED_HINT}")
            return
        is_image_tag = tag in ("img", "source")
        for name, raw_value in attrs:
            value = (raw_value or "").strip()
            if name == "href":
                self.references.append(Reference(value, is_image=False))
            elif name == "src":
                self.references.append(Reference(value, is_image=is_image_tag))
            elif name == "srcset":
                self.references.extend(Reference(url, is_image=True) for url in _srcset_urls(value) or [""])

    def handle_data(self, data: str) -> None:
        for pattern, form in _UNSUPPORTED_TEXT:
            match = pattern.search(data)
            if match:
                snippet = " ".join(data[max(0, match.start() - 20) : match.end() + 40].split())
                self.unsupported.append(f"{form} near {snippet!r} {_UNSUPPORTED_HINT}")
                return  # one report per text run; a Markdown link's URL is not also a bare URL


def extract_references(text: str) -> tuple[list[Reference], list[str]]:
    """Return the distinct references in document order, and every unsupported link form."""
    collector = _Collector()
    collector.feed(_BARE_AMPERSAND.sub("&amp;", text))
    collector.close()
    return list(dict.fromkeys(collector.references)), collector.unsupported


def _printable(text: str) -> str:
    """Collapse remote-supplied text to one line so it cannot start a log or summary line."""
    return " ".join("".join(c if c.isprintable() else " " for c in text).split())


def _fetch(url: str) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            response.read(1)
            return response.status, response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type", "") if error.headers else ""


def check_reference(reference: Reference) -> str | None:
    """Return a one-line failure description, or None when the reference is healthy."""
    url = reference.url
    if not url:
        return f"empty {'image source' if reference.is_image else 'link'}"
    if url.startswith(("mailto:", "#")):
        return None
    if not url.lower().startswith(REMOTE_SCHEMES):
        return f"{url}: not an https URL (README.md is HTML plus remote https images)"
    last_error = ""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            status, content_type = _fetch(url)
        except (ValueError, http.client.InvalidURL) as error:  # incl. UnicodeEncodeError; retrying cannot help
            return f"{url}: malformed URL ({_printable(str(error))})"
        except (http.client.HTTPException, OSError) as error:  # OSError covers URLError and timeouts
            last_error = f"request failed ({_printable(f'{type(error).__name__}: {error}')})"
        else:
            if not 200 <= status < 300:
                last_error = f"HTTP {status}"
            elif reference.is_image and not content_type.lower().startswith("image/"):
                return f"{url}: image answered with content-type {_printable(content_type) or '(none)'}"
            else:
                return None
        if attempt < ATTEMPTS:
            _sleep(2**attempt)
    return f"{url}: {last_error} after {ATTEMPTS} attempts"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check-readme-links.py <README.md>", file=sys.stderr)
        return 2
    references, failures = extract_references(Path(argv[1]).read_text(encoding="utf-8"))
    for failure in failures:
        print(f"- {failure}", file=sys.stderr, flush=True)
    if not references and not failures:
        print(f"✗ {argv[1]} has no links or images; refusing to report a vacuous pass", file=sys.stderr)
        return 1
    for reference in references:
        print(f"checking {'image' if reference.is_image else 'link'}: {reference.url}", flush=True)
        failure = check_reference(reference)
        if failure:
            failures.append(failure)
            print(f"- {failure}", file=sys.stderr, flush=True)
    if failures:
        print(f"✗ {len(failures)} README problem(s) across {len(references)} references", file=sys.stderr)
        return 1
    print(f"✓ all {len(references)} README references resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
