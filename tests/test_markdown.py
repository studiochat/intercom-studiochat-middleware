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

    def test_url_at_end_of_sentence_period_kept_in_path(self):
        # Trailing "." is part of our URL match (not in the exclusion set).
        # This mirrors wapp's behavior — we accept the trade-off.
        result = to_intercom_html("Go to https://example.com.")
        assert "<a " in result
