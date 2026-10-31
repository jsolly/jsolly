#!/usr/bin/env python3
"""Exercise the README link checker against a real local HTTP server."""
import importlib.util
import http.server
import socket
import threading
import urllib.parse
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "check_readme_links", Path(__file__).resolve().parent / "check-readme-links.py"
)
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)
Reference = checker.Reference

# The profile banner as README.md has shipped it: a raw `&center=` query parameter that a
# legacy-entity decoder would turn into `¢er=`.
BANNER = (
    "https://readme-typing-svg.herokuapp.com?font=Helvetica&size=22&duration=5000&pause=1000"
    "&color=0B3B8E&center=true&vCenter=true&width=400&lines=Always+Learning+New+Things+%F0%9F%92%A1"
)
PROFILE_HTML = f"""<h1 align="center">Hello world, I'm John! 👋</h1>
<!-- <img alt="retired" src="https://retired.example/old.svg" /> [old](https://retired.example/) -->
<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)"
      srcset="https://readme-typing-svg.herokuapp.com?color=E6EDF3&amp;lines=Hello,+world 1x,
              https://readme-typing-svg.herokuapp.com?color=E6EDF3&amp;width=800
              2x," />
    <img alt="Typing -> SVG <3" src="{BANNER}" />
  </picture>
</p>
<p align="center">
  <a title="Home > profile" href="https://www.jsolly.com/">jsolly.com 🔗</a> ·
  <a href='https://www.jsolly.com/John-Solly-Resume.pdf'>Resume</a> ·
  <a href="https://www.jsolly.com/">jsolly.com again</a> ·
  <a href="mailto:hello@jsolly.com">Email</a>
</p>
"""


class _Handler(http.server.BaseHTTPRequestHandler):
    hits: dict[str, int] = {}
    requested: list[str] = []

    def do_GET(self):  # noqa: N802 (http.server API)
        _Handler.requested.append(self.path)
        path = urllib.parse.urlsplit(self.path).path
        hits = _Handler.hits[path] = _Handler.hits.get(path, 0) + 1
        if path == "/garbage-status-once" and hits == 1:
            self.wfile.write(b"NOT-HTTP\r\n\r\n")
            return
        if path == "/drop-once" and hits == 1:
            self.close_connection = True
            return
        if path == "/hang":
            threading.Event().wait(0.5)
        status = 200 if path in {"/ok", "/garbage-status-once", "/drop-once", "/image.svg", "/IMAGE.svg",
                                 "/html-not-image", "/folded-type"} else 404
        if path == "/flaky-503-once":
            status = 503 if hits == 1 else 200
        content_type = {
            "/image.svg": "image/svg+xml",
            "/IMAGE.svg": "Image/SVG+XML",
            "/folded-type": "text/html\r\n ~~~\r\n @someone ##[error]Click https://phish.example/",
        }.get(path, "text/html")
        body = b"<html></html>"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def server(monkeypatch):
    """A loopback HTTP server; the checker's https-only rule is widened to reach it."""
    monkeypatch.setattr(checker, "REMOTE_SCHEMES", ("https://", "http://"))
    _Handler.hits, _Handler.requested = {}, []
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.daemon_threads = False  # server_close() then joins request threads, e.g. /hang
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()
    thread.join()


@pytest.fixture(autouse=True)
def backoff(monkeypatch):
    """Record retry backoff instead of sleeping through it."""
    slept: list[float] = []
    monkeypatch.setattr(checker, "_sleep", slept.append)
    return slept


@pytest.fixture
def closed_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_profile_page_references_are_found_as_github_renders_them():
    references, unsupported = checker.extract_references(PROFILE_HTML)
    assert references == [
        Reference("https://readme-typing-svg.herokuapp.com?color=E6EDF3&lines=Hello,+world", is_image=True),
        Reference("https://readme-typing-svg.herokuapp.com?color=E6EDF3&width=800", is_image=True),
        Reference(BANNER, is_image=True),
        Reference("https://www.jsolly.com/", is_image=False),
        Reference("https://www.jsolly.com/John-Solly-Resume.pdf", is_image=False),
        Reference("mailto:hello@jsolly.com", is_image=False),
    ]
    assert unsupported == []


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("<img src=https://img.shields.io/badge/ci?style=flat&logo=github>",
         [Reference("https://img.shields.io/badge/ci?style=flat&logo=github", is_image=True)]),
        ('<img alt="broken" src>', [Reference("", is_image=True)]),
        ('<img alt="none" srcset="">', [Reference("", is_image=True)]),
        ('<img alt="pair" srcset="https://a.example/x.svg, https://a.example/y.svg">',
         [Reference("https://a.example/x.svg", is_image=True), Reference("https://a.example/y.svg", is_image=True)]),
    ],
)
def test_attributes_are_read_as_github_renders_them(html, expected):
    assert checker.extract_references(html) == (expected, [])


def test_banner_query_string_is_requested_literally(server):
    # Regression: Python < 3.13's HTMLParser decoded `&cent` in `&center=` to `¢`, so the
    # request could not be encoded and every run crashed while the page was healthy.
    [reference], _ = checker.extract_references(
        f'<img alt="Typing SVG" src="{server}/image.svg?color=0B3B8E&center=true&amp;v=1" />'
    )
    assert checker.check_reference(reference) is None
    assert _Handler.requested == ["/image.svg?color=0B3B8E&center=true&v=1"]


@pytest.mark.parametrize(
    ("snippet", "form"),
    [
        ("[![CI](https://img.shields.io/badge/ci-green)](https://github.com/jsolly/jsolly/actions)",
         "Markdown link syntax"),
        ("[Blog](https://www.jsolly.com/blog/ 'Posts')", "Markdown link syntax"),
        ("[Blog][blog]\n\n[blog]: https://www.jsolly.com/blog/", "Markdown link syntax"),
        ("   [blog]: https://www.jsolly.com/blog/", "Markdown link reference definition"),
        ("See https://www.jsolly.com/blog/ for posts.", "bare URL"),
        ("<https://www.jsolly.com/blog/>", "autolink"),
        ("Posts live at www.jsolly.com/blog these days.", "bare URL"),
        ('Visit <a href="https://www.jsolly.com/">https://broken.example/</a> now', "bare URL"),
        ("Blog: _www.jsolly.com/blog_", "bare URL"),
        ("Files at ftp://files.example/x", "bare URL"),
    ],
)
def test_link_forms_the_checker_cannot_verify_fail_instead_of_passing(snippet, form):
    _, unsupported = checker.extract_references(f'<a href="https://www.jsolly.com/">site</a>\n{snippet}')
    assert unsupported and unsupported[0].startswith(form)


def test_a_healthy_profile_passes_and_says_so(server, tmp_path, capsys):
    readme = tmp_path / "README.md"
    readme.write_text(f'<a href="{server}/ok">site</a>\n<img alt="Banner" src="{server}/image.svg" />')
    assert checker.main(["check", str(readme)]) == 0
    out, err = capsys.readouterr()
    assert "✓ all 2 README references resolve" in out
    assert err == ""


def test_a_retired_page_is_reported_after_every_retry(server, backoff):
    failure = checker.check_reference(Reference(f"{server}/retired", False))
    assert failure == f"{server}/retired: HTTP 404 after {checker.ATTEMPTS} attempts"
    assert _Handler.hits["/retired"] == checker.ATTEMPTS
    assert backoff == [2, 4]


def test_a_brief_host_outage_is_retried_then_passes(server, backoff):
    assert checker.check_reference(Reference(f"{server}/flaky-503-once", False)) is None
    assert _Handler.hits["/flaky-503-once"] == 2
    assert backoff == [2]


@pytest.mark.parametrize("path", ["/garbage-status-once", "/drop-once"])
def test_a_protocol_hiccup_is_retried_then_passes(server, path):
    assert checker.check_reference(Reference(f"{server}{path}", False)) is None
    assert _Handler.hits[path] == 2


def test_a_hung_host_times_out_and_is_reported_after_every_retry(server, monkeypatch):
    monkeypatch.setattr(checker, "TIMEOUT_SECONDS", 0.1)
    failure = checker.check_reference(Reference(f"{server}/hang", False))
    assert failure.startswith(f"{server}/hang: request failed (")
    assert failure.endswith(f"after {checker.ATTEMPTS} attempts")
    assert _Handler.hits["/hang"] == checker.ATTEMPTS


def test_an_image_host_serving_a_web_page_fails(server):
    failure = checker.check_reference(Reference(f"{server}/html-not-image", True))
    assert failure == f"{server}/html-not-image: image answered with content-type text/html"


def test_an_uppercase_image_content_type_passes(server):
    assert checker.check_reference(Reference(f"{server}/IMAGE.svg", True)) is None


def test_remote_header_text_cannot_start_a_report_line(server):
    failure = checker.check_reference(Reference(f"{server}/folded-type", True))
    assert "\n" not in failure and "\r" not in failure
    assert failure.startswith(f"{server}/folded-type: image answered with content-type text/html ~~~ ")


def test_an_unreachable_host_is_reported_after_every_retry(closed_port, monkeypatch):
    monkeypatch.setattr(checker, "REMOTE_SCHEMES", ("https://", "http://"))
    url = f"http://127.0.0.1:{closed_port}/"
    failure = checker.check_reference(Reference(url, False))
    assert failure.startswith(f"{url}: request failed (")
    assert failure.endswith(f"after {checker.ATTEMPTS} attempts")


@pytest.mark.parametrize("suffix", ["/a b", "/café"])
def test_a_malformed_url_is_reported_without_crashing_the_run(server, suffix):
    failure = checker.check_reference(Reference(f"{server}{suffix}", False))
    assert failure.startswith(f"{server}{suffix}: malformed URL (")
    assert _Handler.hits == {}


def test_an_empty_image_source_fails():
    assert checker.extract_references('<img alt="broken" src="">') == ([Reference("", is_image=True)], [])
    assert checker.check_reference(Reference("", True)) == "empty image source"


@pytest.mark.parametrize(
    "url", ["assets/banner.svg", "/assets/banner.svg", "ftp://example.com/x", "http://www.jsolly.com/"]
)
def test_a_reference_that_is_not_a_remote_https_url_fails(url):
    assert checker.check_reference(Reference(url, True)) == (
        f"{url}: not an https URL (README.md is HTML plus remote https images)"
    )


@pytest.mark.parametrize("url", ["mailto:hello@jsolly.com", "#top"])
def test_email_and_in_page_links_pass_without_a_request(server, url):
    assert checker.check_reference(Reference(url, False)) is None
    assert _Handler.requested == []


def test_every_problem_is_reported_in_one_run(server, tmp_path, capsys):
    readme = tmp_path / "README.md"
    readme.write_text(
        f'<a href="{server}/a b">bad</a> <img alt="b" src="{server}/retired" /> <a href="{server}/ok">ok</a>\n'
        "[Blog](https://www.jsolly.com/blog/)"
    )
    assert checker.main(["check", str(readme)]) == 1
    out, err = capsys.readouterr()
    assert f"checking link: {server}/ok" in out
    assert "✗ 3 README problem(s) across 3 references" in err
    assert f"- {server}/retired: HTTP 404" in err
    assert "- Markdown link syntax near" in err


def test_a_page_with_no_references_is_not_a_pass(tmp_path, capsys):
    readme = tmp_path / "README.md"
    readme.write_text("<h1>No links</h1>")
    assert checker.main(["check", str(readme)]) == 1
    assert "refusing to report a vacuous pass" in capsys.readouterr().err


def test_the_shipped_readme_uses_only_forms_the_checker_verifies():
    # Offline, so the gate (PR CI) catches an unverifiable link form before it reaches main.
    readme = Path(__file__).resolve().parent.parent / "README.md"
    references, unsupported = checker.extract_references(readme.read_text(encoding="utf-8"))
    assert unsupported == []
    assert references
    assert all(r.url.startswith("https://") or r.url.startswith(("mailto:", "#")) for r in references)
