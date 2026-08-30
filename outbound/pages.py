"""Build the static pages the emails link to.

Three things, all self contained HTML with no external requests:

  site/index.html            the careers page
  site/roles/<key>.html      one job description per live role
  site/unsubscribe.html      the opt out page

Upload `site/` to the recruiting domain. Do not host it on a live brand
domain, and do not redirect it to one. See docs/OPSEC.md.

The markdown subset is deliberately small: headings, paragraphs, bullet lists,
bold, and bare URLs. The job descriptions are written to that subset.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from .compose import build_context, lint, render_text
from .config import REPO_ROOT, Role, Settings
from .errors import OutboundError

CONTENT_DIR = REPO_ROOT / "content" / "jd"
SITE_DIR = REPO_ROOT / "site"

CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  margin: 0 auto; padding: 3rem 1.25rem 6rem; max-width: 42rem;
  font: 16px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  color: #16181d; background: #fbfaf8;
}
h1 { font-size: 1.9rem; line-height: 1.2; margin: 0 0 .4rem; letter-spacing: -.01em; }
h2 { font-size: 1.1rem; margin: 2.4rem 0 .6rem; letter-spacing: .02em; text-transform: uppercase; color: #5c6270; }
p, li { margin: 0 0 .85rem; }
ul { padding-left: 1.15rem; }
a { color: #1a4fd6; }
.lede { font-size: 1.15rem; color: #3d434e; margin-bottom: 2rem; }
.meta { font-size: .9rem; color: #5c6270; border-top: 1px solid #e2ded7; border-bottom: 1px solid #e2ded7; padding: .8rem 0; margin: 1.5rem 0 2rem; }
.cta { display: inline-block; margin: 1rem 0 0; padding: .7rem 1.15rem; background: #16181d; color: #fbfaf8; text-decoration: none; border-radius: 3px; }
.roles { list-style: none; padding: 0; }
.roles li { border-bottom: 1px solid #e2ded7; padding: 1rem 0; }
.roles a { font-size: 1.15rem; text-decoration: none; }
.roles span { display: block; color: #5c6270; font-size: .93rem; }
footer { margin-top: 4rem; padding-top: 1.2rem; border-top: 1px solid #e2ded7; font-size: .85rem; color: #6b7280; }
label { display: block; margin: 1rem 0 .35rem; font-weight: 600; }
input[type=email] { width: 100%; padding: .6rem; font-size: 1rem; border: 1px solid #c9c4bb; border-radius: 3px; background: #fff; }
button { margin-top: 1rem; padding: .7rem 1.15rem; font-size: 1rem; background: #16181d; color: #fbfaf8; border: 0; border-radius: 3px; cursor: pointer; }
@media (prefers-color-scheme: dark) {
  body { color: #e8e6e3; background: #14161a; }
  h2, .meta, .roles span, footer { color: #9aa1ad; }
  .lede { color: #c3c7ce; }
  a { color: #7aa2f7; }
  .meta, .roles li, footer { border-color: #2a2e36; }
  .cta, button { background: #e8e6e3; color: #14161a; }
  input[type=email] { background: #1c1f25; border-color: #3a3f49; color: #e8e6e3; }
}
"""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="{robots}">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
{body}
<footer>
{footer}
</footer>
</body>
</html>
"""

_URL = re.compile(r"(?<![\"'=>])(https?://[^\s<)]+)")


def _inline(text: str) -> str:
    out = html.escape(text)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = _URL.sub(r'<a href="\1">\1</a>', out)
    return out


def markdown_to_html(text: str) -> tuple[str, str]:
    """Return (title, body html). The title is the first `# ` heading."""
    title = ""
    parts: list[str] = []
    buffer: list[str] = []
    in_list = False
    lede_done = False

    def flush_paragraph() -> None:
        nonlocal lede_done
        if not buffer:
            return
        joined = " ".join(buffer).strip()
        buffer.clear()
        if not joined:
            return
        css_class = "" if lede_done else ' class="lede"'
        lede_done = True
        parts.append(f"<p{css_class}>{_inline(joined)}</p>")

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            parts.append("</ul>")
            in_list = False

    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            flush_paragraph()
            close_list()
            continue
        if line.startswith("# "):
            flush_paragraph()
            close_list()
            title = line[2:].strip()
            parts.append(f"<h1>{_inline(title)}</h1>")
            continue
        if line.startswith("## "):
            flush_paragraph()
            close_list()
            lede_done = True
            parts.append(f"<h2>{_inline(line[3:].strip())}</h2>")
            continue
        if line.lstrip().startswith("- "):
            flush_paragraph()
            if not in_list:
                parts.append("<ul>")
                in_list = True
            parts.append(f"<li>{_inline(line.lstrip()[2:].strip())}</li>")
            continue
        if in_list:
            # A continuation line inside a bullet.
            parts[-1] = parts[-1][:-5] + " " + _inline(line.strip()) + "</li>"
            continue
        buffer.append(line.strip())

    flush_paragraph()
    close_list()
    return title, "\n".join(parts)


def _footer(settings: Settings) -> str:
    postal = html.escape(str(settings.get("identity.postal_address", "")))
    unsub = str(settings.get("identity.unsubscribe_url", "")).split("?")[0]
    return (
        f"<p>{postal}</p>"
        f'<p><a href="{html.escape(unsub)}">Do not contact me again</a></p>'
    )


def build_role_page(settings: Settings, role: Role) -> tuple[str, str]:
    source = CONTENT_DIR / f"{role.key}.md"
    if not source.exists():
        raise OutboundError(
            f"no job description at {source}. Write it, or set the role status "
            f"to draft."
        )
    context = build_context(settings, role, {"first_name": "there"}, "")
    rendered = render_text(source.read_text(encoding="utf-8"), context, str(source))
    problems = lint(role.title, rendered, strict=False)
    # A job description is longer than an email, so the word cap does not apply.
    problems = [p for p in problems if "words" not in p and "links in the body" not in p]
    if problems:
        raise OutboundError(f"copy check failed for {source}:\n  " + "\n  ".join(problems))
    title, body = markdown_to_html(rendered)
    screener = html.escape(str(settings.get("booking.screener_url", "")))
    minutes = html.escape(str(settings.get("booking.screener_minutes", 10)))
    meta = (
        f'<p class="meta">{html.escape(role.employment)} &middot; '
        f"{html.escape(role.comp)}</p>"
    )
    body = body.replace("</h1>", "</h1>\n" + meta, 1)
    body += f'\n<p><a class="cta" href="{screener}">Book a {minutes} minute call</a></p>'
    page = PAGE.format(
        robots="index,follow",
        title=html.escape(f"{title} - {settings.get('identity.from_name', '')}"),
        css=CSS,
        body=body,
        footer=_footer(settings),
    )
    return f"roles/{role.key}.html", page


def build_index(settings: Settings, roles: dict[str, Role]) -> tuple[str, str]:
    live = [r for r in roles.values() if r.is_live and (CONTENT_DIR / f"{r.key}.md").exists()]
    items = "\n".join(
        f'<li><a href="roles/{r.key}.html">{html.escape(r.title)}</a>'
        f"<span>{html.escape(r.one_liner)} &middot; {html.escape(r.employment)}</span></li>"
        for r in sorted(live, key=lambda r: r.title)
    )
    body = (
        "<h1>Open roles</h1>\n"
        '<p class="lede">A small trading firm in alternative assets, around fifty '
        "people, rebuilding the operating side this quarter. Every role below is "
        "remote.</p>\n"
        f'<ul class="roles">\n{items}\n</ul>'
    )
    page = PAGE.format(
        robots="index,follow",
        title=html.escape(f"Open roles - {settings.get('identity.from_name', '')}"),
        css=CSS,
        body=body,
        footer=_footer(settings),
    )
    return "index.html", page


def build_unsubscribe(settings: Settings) -> tuple[str, str]:
    """A working opt out page.

    The form action is left as a placeholder on purpose. Point it at whatever
    records the address: a form service, a function, or your own endpoint.
    Export the results and load them with `outbound suppress --from-file`.
    """
    body = (
        "<h1>Do not contact me again</h1>\n"
        '<p class="lede">Put in the address we wrote to. We will not email you '
        "about a job again.</p>\n"
        '<form method="post" action="FORM_ENDPOINT_GOES_HERE">\n'
        '<label for="email">Email address</label>\n'
        '<input id="email" name="email" type="email" required '
        'autocomplete="email" placeholder="you@company.com">\n'
        '<button type="submit">Remove me</button>\n'
        "</form>\n"
        "<p>It takes effect the same day. If you would rather just reply to the "
        "email saying stop, that works too.</p>"
    )
    page = PAGE.format(
        robots="noindex,nofollow",
        title="Unsubscribe",
        css=CSS,
        body=body,
        footer=f"<p>{html.escape(str(settings.get('identity.postal_address', '')))}</p>",
    )
    return "unsubscribe.html", page


def build_all(settings: Settings, roles: dict[str, Role], out_dir: Path | None = None) -> list[Path]:
    target = out_dir or SITE_DIR
    written: list[Path] = []
    pages: list[tuple[str, str]] = [build_index(settings, roles), build_unsubscribe(settings)]
    for role in roles.values():
        if not role.is_live:
            continue
        if not (CONTENT_DIR / f"{role.key}.md").exists():
            continue
        pages.append(build_role_page(settings, role))
    for relative, html_text in pages:
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html_text, encoding="utf-8")
        written.append(path)
    return written
