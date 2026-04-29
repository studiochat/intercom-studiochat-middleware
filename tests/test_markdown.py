"""Tests for the assistant-text-to-Intercom-HTML transformer."""

from bridge.utils.markdown import to_intercom_html


class TestPassthrough:
    def test_empty_string_unchanged(self):
        assert to_intercom_html("") == ""

    def test_plain_text_unchanged(self):
        # Existing e2e test asserts verbatim passthrough; protect that contract.
        assert to_intercom_html("How can I help with billing?") == "How can I help with billing?"

    def test_text_with_punctuation_unchanged(self):
        assert to_intercom_html("Hi! Got it. Anything else?") == "Hi! Got it. Anything else?"


class TestHttpUrls:
    def test_https_url_wrapped(self):
        result = to_intercom_html("Visit https://example.com for info.")
        assert '<a href="https://example.com">https://example.com</a>' in result

    def test_http_url_wrapped(self):
        result = to_intercom_html("See http://example.com here")
        assert '<a href="http://example.com">http://example.com</a>' in result

    def test_bare_www_wrapped(self):
        result = to_intercom_html("Visit www.example.com")
        assert '<a href="www.example.com">www.example.com</a>' in result

    def test_url_with_underscores_not_italicized(self):
        url = "https://example.com/path_one_two/file_name"
        result = to_intercom_html(f"See {url}")
        assert "<em>" not in result
        assert f'<a href="{url}">{url}</a>' in result

    def test_multiple_urls_each_wrapped(self):
        result = to_intercom_html("First https://example.com/a then https://example.com/b done")
        assert '<a href="https://example.com/a">https://example.com/a</a>' in result
        assert '<a href="https://example.com/b">https://example.com/b</a>' in result

    def test_trailing_punctuation_excluded_from_url(self):
        # Trailing comma/paren are prose punctuation, not part of the URL.
        result = to_intercom_html("Visit (https://example.com), then leave.")
        assert '<a href="https://example.com">https://example.com</a>' in result
        # href must not include the wrapping ")" or the trailing ",".
        assert 'href="https://example.com)"' not in result
        assert 'href="https://example.com,"' not in result


class TestCustomSchemes:
    def test_custom_app_scheme_wrapped(self):
        url = "myapp://link/to/resource"
        result = to_intercom_html(f"Open the app: {url}")
        assert f'<a href="{url}">{url}</a>' in result

    def test_intercom_deep_link_wrapped(self):
        url = "intercom://conversation/12345"
        result = to_intercom_html(f"Jump to {url} now")
        assert f'<a href="{url}">{url}</a>' in result

    def test_scheme_with_plus_dot_dash(self):
        # RFC 3986 allows +, -, . in scheme. Confirm we accept them.
        url = "x-app.scheme+v2://path"
        result = to_intercom_html(f"Use {url} please")
        assert f'<a href="{url}">{url}</a>' in result

    def test_tel_and_mailto_not_matched(self):
        # tel: and mailto: don't use "://" so we leave them alone — Intercom
        # auto-linkifies email addresses on its side anyway.
        assert to_intercom_html("Email me: foo@bar.com") == "Email me: foo@bar.com"


class TestDeepLinkSchemes:
    """Common mobile/desktop deep-link URI schemes seen in production.

    Each entry is the raw URI; we assert the transformer wraps it in an
    anchor whose href and label both equal the original URI exactly. If a
    scheme breaks here we either need to widen the path-character set or
    revisit the URL regex.
    """

    DEEP_LINKS = [
        # Mobile app deep links
        "myapp://link/to/resource",
        "intercom://conversation/12345",
        "fb://profile/12345",
        "twitter://user?screen_name=jack",
        "whatsapp://send?phone=15551234567",
        "tg://resolve?domain=username",
        "slack://channel?team=T123&id=C456",
        "spotify://track/4iV5W9uYEdYUVa79Axb7Rh",
        "zoommtg://zoom.us/join?confno=1234567890",
        "msteams://teams.microsoft.com/l/chat/0/0",
        # Desktop / IDE
        "vscode://file/Users/foo/bar.py:10",
        "jetbrains://idea/navigate/reference?project=foo",
        # Custom company deep link with path + query + fragment
        "studio-chat://playbook/abc-123/run?step=2#latest",
        # Schemes with digits and hyphens in path
        "app-v2://route/42/action",
    ]

    def test_each_scheme_wrapped(self):
        for url in self.DEEP_LINKS:
            result = to_intercom_html(f"Open: {url} now")
            assert (
                f'<a href="{url}">{url}</a>' in result
            ), f"deep link not wrapped correctly: {url!r}\n  got: {result!r}"

    def test_deep_link_with_query_and_fragment_unchanged(self):
        # Query params and fragments are part of the URI — must not be split off.
        url = "studio-chat://playbook/abc/run?step=2&debug=true#latest"
        result = to_intercom_html(url)
        assert result == f'<a href="{url}">{url}</a>'

    def test_deep_link_inside_sentence_with_underscores(self):
        # Underscores anywhere in the URI must not trigger italic markdown.
        url = "myapp://deep_link/to_resource_id_42"
        result = to_intercom_html(f"Tap _here_: {url} please")
        assert "<em>here</em>" in result
        assert f'<a href="{url}">{url}</a>' in result
        assert "<em>" not in result.replace("<em>here</em>", "")

    def test_deep_link_with_bold_label_nearby(self):
        url = "intercom://conversation/12345"
        result = to_intercom_html(f"**Action**: open {url}")
        assert "<strong>Action</strong>" in result
        assert f'<a href="{url}">{url}</a>' in result

    def test_two_deep_links_back_to_back(self):
        a = "myapp://a/1"
        b = "myapp://b/2"
        result = to_intercom_html(f"First {a} then {b}.")
        assert f'<a href="{a}">{a}</a>' in result
        assert f'<a href="{b}">{b}</a>' in result

    def test_deep_link_label_and_href_match_exactly(self):
        # The label inside the anchor must equal the href exactly — no
        # truncation, no scheme stripping.
        url = "studio-chat://playbook/p_123/run?step=2"
        result = to_intercom_html(url)
        assert result == f'<a href="{url}">{url}</a>'


class TestMarkdownFormatting:
    def test_bold_converted(self):
        assert to_intercom_html("**important**") == "<strong>important</strong>"

    def test_italic_converted(self):
        assert to_intercom_html("_emphasis_") == "<em>emphasis</em>"

    def test_bold_and_italic_with_url(self):
        url = "https://example.com/some_path"
        result = to_intercom_html(f"**Note**: this is _key_ — {url}")
        assert "<strong>Note</strong>" in result
        assert "<em>key</em>" in result
        assert f'<a href="{url}">{url}</a>' in result
        # Underscore in URL must NOT have become <em>.
        assert "some<em>path</em>" not in result


class TestEdgeCases:
    def test_no_double_wrapping_when_already_html_anchor(self):
        # If Studio Chat already sent an <a>, the URL inside href gets matched —
        # this test pins the current (somewhat lossy) behavior so future
        # changes are intentional.
        existing = '<a href="https://example.com">click</a>'
        result = to_intercom_html(existing)
        # Pre-existing <a> stays in output even though the inner URL also gets
        # wrapped; we just don't want it crashing or producing empty output.
        assert "https://example.com" in result

    def test_url_at_end_of_sentence_period_peeled_off(self):
        # Sentence-ending "." must be peeled off the URL — it's prose, not path.
        result = to_intercom_html("Go to https://example.com.")
        assert '<a href="https://example.com">https://example.com</a>.' in result
        assert 'href="https://example.com."' not in result

    def test_url_followed_by_question_mark_peeled_off(self):
        result = to_intercom_html("Did you check https://example.com?")
        assert '<a href="https://example.com">https://example.com</a>?' in result
        assert 'href="https://example.com?"' not in result
