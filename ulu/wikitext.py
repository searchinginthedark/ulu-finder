"""Just enough wikitext handling to pull Wikivoyage listings out of an article.

Listing templates nest other templates and links that contain pipes, so splitting
on "|" with a regex corrupts fields. This scanner tracks {{ }} and [[ ]] depth instead.
"""
import re

LISTING_NAMES = {"see", "do", "buy", "eat", "drink", "sleep", "listing", "go"}

_HEADING = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$", re.M)


def _match_close(text, i):
    """Index just past the }} that closes the {{ at text[i]; -1 when unbalanced."""
    depth = 0
    n = len(text)
    while i < n:
        if text.startswith("{{", i):
            depth += 1
            i += 2
        elif text.startswith("}}", i):
            depth -= 1
            i += 2
            if depth == 0:
                return i
        else:
            i += 1
    return -1


def split_params(body):
    """Split a template body on top-level pipes. Returns (name, positional, named)."""
    parts, buf, curly, square, i = [], [], 0, 0, 0
    while i < len(body):
        two = body[i:i + 2]
        if two == "{{":
            curly += 1; buf.append(two); i += 2; continue
        if two == "}}":
            curly -= 1; buf.append(two); i += 2; continue
        if two == "[[":
            square += 1; buf.append(two); i += 2; continue
        if two == "]]":
            square -= 1; buf.append(two); i += 2; continue
        c = body[i]
        if c == "|" and curly == 0 and square == 0:
            parts.append("".join(buf)); buf = []
        else:
            buf.append(c)
        i += 1
    parts.append("".join(buf))
    name = parts[0].strip()
    positional, named = [], {}
    for p in parts[1:]:
        k, eq, v = p.partition("=")
        # "=" inside a nested link or template value is not a key separator
        if eq and "{{" not in k and "[[" not in k and k.strip():
            named[k.strip().lower()] = v.strip()
        else:
            positional.append(p.strip())
    return name, positional, named


def iter_templates(text):
    """Yield (start, end, name, positional, named) for every top-level template."""
    i = 0
    while True:
        i = text.find("{{", i)
        if i < 0:
            return
        end = _match_close(text, i)
        if end < 0:
            return
        name, pos, named = split_params(text[i + 2:end - 2])
        yield i, end, name, pos, named
        i = end


def section_at(headings, pos):
    """Name of the level-2 section containing pos."""
    current = ""
    for start, level, title in headings:
        if start > pos:
            break
        if level == 2:
            current = title
    return current


def headings(text):
    return [(m.start(), len(m.group(1)), clean(m.group(2))) for m in _HEADING.finditer(text)]


def listings(text):
    """Every listing template in the article, with the level-2 section it sits under."""
    hs = headings(text)
    out = []
    for start, _end, name, _pos, named in iter_templates(text):
        key = name.strip().lower()
        if key not in LISTING_NAMES:
            continue
        typ = key
        if key == "listing":
            typ = (named.get("type") or "").strip().lower() or "listing"
        out.append({"template": typ, "section": section_at(hs, start), "params": named})
    return out


_UNITS = {"km", "m", "mi", "ft", "kg", "km2", "mm", "cm"}


def _render_template(name, pos, named):
    n = name.strip().lower()
    if n in ("lang", "native"):
        return pos[-1] if pos else ""
    if n in _UNITS and pos:
        return f"{pos[0]} {n}"
    if n in ("nowrap", "smaller", "small", "w", "rint") and pos:
        return pos[-1] if n == "rint" else pos[0]
    # Inline wrappers like {{RM|2}} carry their text in one argument; page furniture like
    # {{pagebanner|X.jpg}} also has one argument, so filenames never pass through.
    if len(pos) == 1 and not named and len(n) <= 12 and not _FILE.search(pos[0]):
        return pos[0]
    return ""


_FILE = re.compile(r"\.(?:jpe?g|png|svg|gif|webp|tiff?)\s*$", re.I)


def clean(s, limit=None):
    """Wiki markup to plain text."""
    if not s:
        return ""
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"<ref[^>/]*/>", "", s)
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    # templates, innermost first, until none remain
    for _ in range(6):
        if "{{" not in s:
            break
        out, last = [], 0
        for a, b, name, pos, named in iter_templates(s):
            out.append(s[last:a])
            out.append(_render_template(name, [clean(p) for p in pos], named))
            last = b
        out.append(s[last:])
        s = "".join(out)
    s = re.sub(r"\[\[(?:File|Image):[^\]]*\]\]", "", s, flags=re.I)
    s = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\[\[([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\[https?://\S+\s+([^\]]*)\]", r"\1", s)
    s = re.sub(r"\[https?://\S+\]", "", s)
    s = re.sub(r"'{2,}", "", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    s = re.sub(r"\s+", " ", s).strip()
    if limit and len(s) > limit:
        cut = s[:limit].rsplit(" ", 1)[0].rstrip(",;:")
        s = cut + "…"
    return s


def lede(text, limit=400):
    """First prose paragraph of an article (park articles become spots)."""
    body = text
    m = _HEADING.search(text)
    if m:
        body = text[:m.start()]
    # lines that are only a template (banner, quickbar) are page furniture, not prose
    body = "\n".join(l for l in body.split("\n") if not re.fullmatch(r"\s*\{\{.*\}\}\s*", l))
    for para in re.split(r"\n\s*\n", body):
        p = para.strip()
        if not p or p.startswith(("{{", "[[File", "[[Image", "__")):
            # a paragraph that is only templates or an image
            if clean(p) == "":
                continue
        c = clean(p, limit)
        if len(c) > 40:
            return c
    return ""


def status_template(text):
    """Wikivoyage article status, e.g. 'usablepark', 'guidecity', 'outlineregion'."""
    m = re.search(r"\{\{\s*((?:stub|outline|usable|guide|star)\w+)\s*[|}]", text, re.I)
    return m.group(1).lower() if m else ""
