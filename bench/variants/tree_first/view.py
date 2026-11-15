"""X2 coordinate view: the F3 text carries screen pixels (1920x1080); the agent works in 1280x720 (screen / 1.5).

to_view(text) converts only what is a coordinate or the screen size, line by line:
  * a first line starting `screen 1920x1080` -> `screen 1280x720`;
  * an element line (`<id> role ["name"] cx,cy`, `+ <id> ...`, `~ <id> "name" cx,cy`) -> its trailing ` cx,cy` becomes
    int(c / 1.5 + 0.5) (sign kept for negative values);
  * `- <id>` lines and the `changes:` / `no change` headers are not touched.
Only the part after the last closing quote is read as coordinates: a name such as "12,34" or "a \\"b\\" 9,9" never is.
"""
import re

SCALE = 1.5
_TRAIL = re.compile(r" (-?\d+),(-?\d+)$")


def _conv(v):
    v = int(v)
    r = int(abs(v) / SCALE + 0.5)
    return -r if v < 0 else r


def _quotes_before(s):
    """Number of unescaped double quotes in s."""
    n, i = 0, 0
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == '"':
            n += 1
        i += 1
    return n


def _line(line):
    if line.startswith("- ") or line.startswith("changes:") or line.startswith("no change"):
        return line
    m = _TRAIL.search(line)
    if not m or _quotes_before(line[:m.start()]) % 2:      # inside an open quote: it is part of a name
        return line
    return f"{line[:m.start()]} {_conv(m.group(1))},{_conv(m.group(2))}"


def to_view(text):
    lines = text.split("\n")
    out = []
    for k, line in enumerate(lines):
        if k == 0 and line.startswith("screen 1920x1080"):
            out.append("screen 1280x720" + line[len("screen 1920x1080"):])
        else:
            out.append(_line(line))
    return "\n".join(out)
