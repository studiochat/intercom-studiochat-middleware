"""Render assistant-authored text into HTML for Intercom replies.

Intercom's reply ``body`` field renders HTML, so we promote URLs to clickable
``<a>`` tags and translate the ``**bold**`` / ``_italic_`` markdown that
Studio Chat assistants commonly emit. Messages without URLs or markdown pass
through unchanged.
"""

import re

# RFC 3986 scheme: ALPHA *( ALPHA / DIGIT / "+" / "-" / "." ) followed by "://".
# This intentionally accepts custom schemes (e.g. ``myapp://`` or
# ``intercom://``) in addition to ``http``/``https``. ``www.`` is matched as
# a fallback for schemeless URLs people often type.
#
# The path is greedy but stops at whitespace and characters that commonly
# delimit URLs in prose so we don't swallow trailing punctuation.
_URL_PATTERN = re.compile(
    r"[A-Za-z][A-Za-z0-9+\-.]*://[^\s\(\)\[\]>,]+" r"|www\.[^\s\(\)\[\]>,]+",
    re.IGNORECASE,
)
_BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_PATTERN = re.compile(r"_(.+?)_")

# Sentence-ending punctuation that should never be part of the URL even
# though it isn't whitespace. URLs technically can contain ".", but a
# trailing one is overwhelmingly prose, not path.
_TRAILING_PUNCT = ".,;:!?"


def to_intercom_html(content: str) -> str:
    """Convert assistant text into HTML safe to send as an Intercom reply body.

    - URLs (any scheme that matches RFC 3986, plus bare ``www.``) become
      ``<a href="URL">URL</a>``.
    - ``**text**`` becomes ``<strong>text</strong>``.
    - ``_text_`` becomes ``<em>text</em>``.

    URLs are extracted before markdown substitution so underscores or
    asterisks inside a URL aren't mistaken for markdown markers.
    """
    if not content:
        return content

    placeholders: dict[str, str] = {}
    matches = list(_URL_PATTERN.finditer(content))
    # Replace from the end so earlier match offsets remain valid.
    for i, match in enumerate(reversed(matches)):
        idx = len(matches) - 1 - i
        raw = match.group(0)
        # Peel sentence punctuation off the tail so "Visit foo://bar." doesn't
        # produce an href ending in ".".
        end = len(raw)
        while end > 0 and raw[end - 1] in _TRAILING_PUNCT:
            end -= 1
        url, tail = raw[:end], raw[end:]
        if not url:
            # All-punctuation match (shouldn't happen given the regex, but
            # guard against it) — leave the original text in place.
            continue
        token = f"\x00URL{idx}\x00"
        placeholders[token] = url
        content = content[: match.start()] + token + tail + content[match.end() :]

    content = _BOLD_PATTERN.sub(r"<strong>\1</strong>", content)
    content = _ITALIC_PATTERN.sub(r"<em>\1</em>", content)

    for token, url in placeholders.items():
        content = content.replace(token, f'<a href="{url}">{url}</a>')

    return content
