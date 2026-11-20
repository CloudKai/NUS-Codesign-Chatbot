"""Incremental decoding of the ``response_text`` string from streamed tool-input JSON.

A structured coaching reply arrives as one forced tool call whose JSON input is
streamed in arbitrary fragments. ``ReplyTextExtractor`` follows that JSON and
returns only the newly decoded characters of the top-level ``response_text``
string, so a preview can show the reply while the rest of the object is still
being generated. It validates nothing: the complete object is still parsed and
validated by the provider after the stream ends.
"""

from __future__ import annotations

_SIMPLE_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
_TARGET_KEY = "response_text"
_MAX_KEY_CHARS = 64


class ReplyTextExtractor:
    """Return new ``response_text`` characters from successive JSON fragments.

    Only a string value of a top-level ``response_text`` key is followed.
    Malformed input never raises: extraction stops and later fragments yield
    nothing, because the provider's final parse is the authority.
    """

    def __init__(self) -> None:
        self._depth = 0
        self._in_string = False
        self._escape = ""  # pending characters of an incomplete escape sequence
        self._key_chars: list[str] = []
        self._string_is_key = False
        self._expect_key = False
        self._pending_key = ""  # top-level key read, colon not yet seen
        self._after_colon_key = ""  # top-level key whose value is about to start
        self._streaming_value = False
        self._high_surrogate = ""
        self._done = False
        self._failed = False

    @property
    def finished(self) -> bool:
        """True once the ``response_text`` string closed or extraction stopped."""
        return self._done or self._failed

    def feed(self, fragment: str) -> str:
        """Consume one JSON fragment and return newly decoded reply text."""
        out: list[str] = []
        for char in fragment:
            if self.finished:
                break
            try:
                self._step(char, out)
            except ValueError:
                self._failed = True
        return "".join(out)

    def _step(self, char: str, out: list[str]) -> None:
        if self._in_string:
            self._string_char(char, out)
            return
        if char == '"':
            self._in_string = True
            if self._depth == 1 and self._expect_key:
                self._string_is_key = True
                self._key_chars = []
            elif self._depth == 1 and self._after_colon_key == _TARGET_KEY:
                self._streaming_value = True
            self._after_colon_key = ""
            return
        if char in "{[":
            self._depth += 1
            if self._depth == 1 and char == "{":
                self._expect_key = True
            self._after_colon_key = ""
        elif char in "}]":
            self._depth -= 1
            self._after_colon_key = ""
        elif char == ",":
            self._expect_key = self._depth == 1
            self._after_colon_key = ""
        elif char == ":" and self._depth == 1 and self._pending_key:
            self._after_colon_key = self._pending_key
            self._pending_key = ""
        # Whitespace and scalar characters (numbers, true, null) need no state.

    def _string_char(self, char: str, out: list[str]) -> None:
        if self._escape:
            self._escape += char
            self._finish_escape(out)
            return
        if char == "\\":
            self._escape = "\\"
            return
        if char == '"':
            self._in_string = False
            if self._string_is_key:
                self._string_is_key = False
                self._expect_key = False
                self._pending_key = "".join(self._key_chars)
            elif self._streaming_value:
                self._streaming_value = False
                self._done = True
            return
        if self._string_is_key:
            if len(self._key_chars) >= _MAX_KEY_CHARS:
                raise ValueError("key too long")
            self._key_chars.append(char)
        elif self._streaming_value:
            self._emit(char, out)

    def _finish_escape(self, out: list[str]) -> None:
        body = self._escape[1:]
        if body[0] != "u":
            if body not in _SIMPLE_ESCAPES:
                raise ValueError("bad escape")
            self._escape = ""
            decoded = _SIMPLE_ESCAPES[body]
        else:
            if len(body) < 5:
                return
            try:
                code = int(body[1:5], 16)
            except ValueError as error:
                raise ValueError("bad unicode escape") from error
            self._escape = ""
            if self._streaming_value and 0xD800 <= code <= 0xDBFF:
                self._high_surrogate = chr(code)
                return
            if self._streaming_value and 0xDC00 <= code <= 0xDFFF and self._high_surrogate:
                decoded = (self._high_surrogate + chr(code)).encode("utf-16", "surrogatepass").decode("utf-16")
                self._high_surrogate = ""
            else:
                decoded = chr(code)
        if self._string_is_key:
            self._key_chars.append(decoded)
        elif self._streaming_value:
            self._emit(decoded, out)

    def _emit(self, char: str, out: list[str]) -> None:
        if self._high_surrogate:
            # A lone high surrogate cannot be shown; drop it rather than send invalid text.
            self._high_surrogate = ""
        out.append(char)
