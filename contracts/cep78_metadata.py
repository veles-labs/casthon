# SPDX-License-Identifier: Apache-2.0
"""CEP-78 metadata validation, including deterministic Rust pretty formatting.

The frozen runtime has no json module. This bounded reader accepts JSON values
without relying on eval or on differences between CPython and MicroPython JSON.
Only string-valued metadata and the upstream custom schema are retained.
"""

from typing import Any

from contracts import cep78_errors as errors
from contracts.cep78_modalities import NFTMetadataKind


class _JsonReader:
    def __init__(self, text: str) -> None:
        self.text, self.position = text, 0

    def whitespace(self) -> None:
        while self.position < len(self.text) and self.text[self.position] in " \t\r\n":
            self.position += 1

    def take(self, expected: str) -> None:
        self.whitespace()
        if not self.text.startswith(expected, self.position):
            raise ValueError("Invalid JSON")
        self.position += len(expected)

    def string(self) -> str:
        self.take('"')
        result = ""
        while self.position < len(self.text):
            char = self.text[self.position]
            self.position += 1
            if char == '"':
                return result
            if char == "\\":
                if self.position == len(self.text):
                    break
                escape = self.text[self.position]
                self.position += 1
                if escape == "u":
                    code = self.hex_quad()
                    if 0xD800 <= code <= 0xDBFF:
                        # No whitespace is permitted within a surrogate pair.
                        if not self.text.startswith("\\u", self.position):
                            raise ValueError("Invalid JSON surrogate")
                        self.position += 2
                        low = self.hex_quad()
                        if not 0xDC00 <= low <= 0xDFFF:
                            raise ValueError("Invalid JSON surrogate")
                        code = 0x10000 + ((code - 0xD800) << 10) + low - 0xDC00
                    elif 0xDC00 <= code <= 0xDFFF:
                        raise ValueError("Invalid JSON surrogate")
                    char = chr(code)
                else:
                    escapes = {'"': '"', "\\": "\\", "/": "/", "b": "\b",
                               "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
                    if escape not in escapes:
                        raise ValueError("Invalid JSON escape")
                    char = escapes[escape]
            elif ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF:
                raise ValueError("Invalid JSON character")
            result += char
        raise ValueError("Unterminated JSON string")

    def hex_quad(self) -> int:
        digits = self.text[self.position:self.position + 4]
        if len(digits) != 4 or any(char not in "0123456789abcdefABCDEF" for char in digits):
            raise ValueError("Invalid JSON escape")
        self.position += 4
        return int(digits, 16)

    def value(self, depth: int = 0) -> Any:
        self.whitespace()
        if depth > 32 or self.position == len(self.text):
            raise ValueError("Invalid JSON nesting")
        char = self.text[self.position]
        if char == '"':
            return self.string()
        if char == "{":
            self.position += 1
            result: dict[str, Any] = {}
            self.whitespace()
            if self.text[self.position:self.position + 1] == "}":
                self.position += 1
                return result
            while True:
                key = self.string()
                self.take(":")
                if key in result:
                    raise ValueError("Duplicate JSON field")
                result[key] = self.value(depth + 1)
                self.whitespace()
                if self.text[self.position:self.position + 1] == "}":
                    self.position += 1
                    return result
                self.take(",")
        if char == "[":
            self.position += 1
            items: list[Any] = []
            self.whitespace()
            if self.text[self.position:self.position + 1] == "]":
                self.position += 1
                return items
            while True:
                items.append(self.value(depth + 1))
                self.whitespace()
                if self.text[self.position:self.position + 1] == "]":
                    self.position += 1
                    return items
                self.take(",")
        for literal, value in (("true", True), ("false", False), ("null", None)):
            if self.text.startswith(literal, self.position):
                self.position += len(literal)
                return value
        # Numbers are only needed in ignored extension fields. Validate the JSON
        # grammar without floating point conversion or retaining a numeric value.
        if char == "-":
            self.position += 1
        start = self.position
        if self.text[self.position:self.position + 1] == "0":
            self.position += 1
        else:
            while self.position < len(self.text) and self.text[self.position] in "0123456789":
                self.position += 1
            if self.position == start:
                raise ValueError("Invalid JSON value")
        for marker in (".", "eE"):
            if self.position < len(self.text) and self.text[self.position] in marker:
                self.position += 1
                if marker == "eE" and self.text[self.position:self.position + 1] in ("+", "-"):
                    self.position += 1
                start = self.position
                while self.position < len(self.text) and self.text[self.position] in "0123456789":
                    self.position += 1
                if start == self.position:
                    raise ValueError("Invalid JSON number")
        return 0


def _object(text: str) -> dict[str, Any]:
    reader = _JsonReader(text)
    result = reader.value()
    reader.whitespace()
    if reader.position != len(text) or not isinstance(result, dict):
        raise ValueError("Expected a JSON object")
    return result


def validate_schema(text: str) -> dict[str, bool]:
    try:
        schema = _object(text)
        properties = schema["properties"]
        if not isinstance(properties, dict):
            raise ValueError("Invalid properties")
        result = {}
        for name, property in properties.items():
            if (not isinstance(property, dict) or type(property.get("name")) is not str
                    or type(property.get("description")) is not str
                    or type(property.get("required")) is not bool):
                raise ValueError("Invalid property")
            result[name] = property["required"]
        return result
    except (ValueError, KeyError):
        raise errors.InvalidJsonSchema()


def json_string(text: str) -> str:
    # serde_json's short control escapes differ from the event SDK's equivalent
    # unicode escapes. Preserve the exact stored metadata text.
    result = '"'
    escapes = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f",
               "\n": "\\n", "\r": "\\r", "\t": "\\t"}
    for char in text:
        result += escapes.get(char, "\\u%04x" % ord(char) if ord(char) < 32 else char)
    return result + '"'


def validate_metadata(kind: NFTMetadataKind, text: str, schema: str = "") -> str:
    if kind is NFTMetadataKind.RAW:
        return text
    parse_error: type[errors.Cep78Error] = errors.FailedToParseCustomMetadata
    invalid: type[errors.Cep78Error] = errors.InvalidCustomMetadata
    fields: tuple[str, ...] = ()
    if kind is NFTMetadataKind.CEP78:
        fields = ("name", "token_uri", "checksum")
        parse_error, invalid = errors.FailedToParseCep99Metadata, errors.InvalidCEP99Metadata
    elif kind is NFTMetadataKind.NFT721:
        fields = ("name", "symbol", "token_uri")
        parse_error, invalid = errors.FailedToParse721Metadata, errors.InvalidNFT721Metadata
    try:
        data = _object(text)
        if fields:
            if any(type(data.get(name)) is not str for name in fields):
                raise ValueError("Missing string field")
        elif any(type(value) is not str for value in data.values()):
            raise ValueError("Expected string metadata")
    except ValueError:
        raise parse_error()
    if fields:
        if any(not data[name] for name in fields):
            raise invalid()
    else:
        properties = validate_schema(schema)
        if any(required and name not in data for name, required in properties.items()):
            raise invalid()
        fields = tuple(sorted(data))
    if not fields:
        return "{}"
    return "{\n" + ",\n".join("  " + json_string(name) + ": " + json_string(data[name]) for name in fields) + "\n}"
