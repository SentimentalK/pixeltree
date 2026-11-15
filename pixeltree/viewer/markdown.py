"""Minimal Markdown -> HTML: headings #..####, paragraphs, - / 1. lists (one nesting level), tables,
**bold**, `code`, code blocks, [text](link), > quotes, ---. Links are emitted as written."""

from __future__ import annotations

import html
import re

_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def inline(text: str) -> str:
    # pull inline code out first so that * [ ] inside it are not processed again
    codes: list[str] = []

    def stash(m):
        codes.append("<code>%s</code>" % html.escape(m.group(1)))
        return "\x00%d\x00" % (len(codes) - 1)

    t = _INLINE_CODE.sub(stash, text)
    t = html.escape(t, quote=False)
    t = _LINK.sub(lambda m: '<a href="%s">%s</a>' % (html.escape(m.group(2), quote=True), m.group(1)), t)
    t = _BOLD.sub(r"<strong>\1</strong>", t)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], t)


_LIST = re.compile(r"^(\s*)([-*]|\d+\.)\s+(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def render(md: str) -> str:
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    para: list[str] = []

    def flush_para():
        if para:
            out.append("<p>%s</p>" % inline(" ".join(p.strip() for p in para)))
            para.clear()

    while i < n:
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_para()
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>%s</code></pre>" % html.escape("\n".join(buf)))
            continue
        if not stripped:
            flush_para()
            i += 1
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m:
            flush_para()
            lv = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (lv, inline(m.group(2)), lv))
            i += 1
            continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            flush_para()
            out.append("<hr>")
            i += 1
            continue
        if stripped.startswith(">"):
            flush_para()
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append("<blockquote>%s</blockquote>" % render("\n".join(buf)))
            continue
        if "|" in stripped and i + 1 < n and _TABLE_SEP.match(lines[i + 1]) and "-" in lines[i + 1]:
            flush_para()
            head = _cells(line)
            i += 2
            rows = []
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(_cells(lines[i]))
                i += 1
            h = "".join("<th>%s</th>" % inline(c) for c in head)
            b = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % inline(c) for c in r) for r in rows)
            out.append('<div class="tablewrap"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (h, b))
            continue
        if _LIST.match(line):
            flush_para()
            i = _render_list(lines, i, out)
            continue
        para.append(line)
        i += 1
    flush_para()
    return "\n".join(out)


def _render_list(lines: list[str], i: int, out: list[str]) -> int:
    """Render one list block (with one level of indented nesting). Returns the index of the next line."""
    n = len(lines)
    items: list[tuple[int, str, str]] = []  # (indent, kind, text)
    while i < n:
        m = _LIST.match(lines[i])
        if m:
            kind = "ol" if m.group(2)[0].isdigit() else "ul"
            items.append((len(m.group(1).replace("\t", "    ")), kind, m.group(3)))
            i += 1
        elif lines[i].strip() and lines[i].startswith("  ") and items and not _LIST.match(lines[i]):
            ind, kind, txt = items[-1]  # continuation line
            items[-1] = (ind, kind, txt + " " + lines[i].strip())
            i += 1
        else:
            break
    base = min(x[0] for x in items)
    html_parts: list[str] = []
    cur_kind = None
    j = 0
    while j < len(items):
        ind, kind, txt = items[j]
        if ind > base:  # should not occur at top level; treat it as top level
            ind = base
        if cur_kind != kind:
            if cur_kind:
                html_parts.append("</%s>" % cur_kind)
            html_parts.append("<%s>" % kind)
            cur_kind = kind
        sub = []
        j += 1
        while j < len(items) and items[j][0] > base:
            sub.append(items[j])
            j += 1
        li = "<li>%s" % inline(txt)
        if sub:
            sk = sub[0][1]
            li += "<%s>%s</%s>" % (sk, "".join("<li>%s</li>" % inline(s[2]) for s in sub), sk)
        li += "</li>"
        html_parts.append(li)
    if cur_kind:
        html_parts.append("</%s>" % cur_kind)
    out.append("".join(html_parts))
    return i
