# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""Extract declared replacement strings for marked text-show content.

The logical-string/original-width technique is informed by singer-civilization/
powercontext commit 566fd324cf9eb75a519444c3c226ec7196162ddb (Apache-2.0).
This isolated implementation adds explicit scope/error tracking; no global patches.
Only Span/Artifact marked text-show operands are replaced. Structure-tree
ActualText and replacement for graphics without text-show operands are not
implemented. Replacement is author-declared logical text, not a verification
that painted glyphs communicate the same content.
"""

from dataclasses import dataclass

from pypdf._font import Font
from pypdf._text_extraction import get_text_operands
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    NameObject,
    NullObject,
    NumberObject,
    StreamObject,
    TextStringObject,
    create_string_object,
)
from typing_extensions import override


class LogicalText(TextStringObject):
    """Keep pypdf's glyph advance while emitting the logical replacement."""

    glyphs: str

    def __new__(cls, logical: str, glyphs: str):
        value = super().__new__(cls, logical)
        value.glyphs = glyphs
        return value

    @override
    def __iter__(self):
        return iter(getattr(self, "glyphs", str(self)))


@dataclass
class Span:
    replacement: str
    emitted: bool = False


def resolve(value):
    return value.get_object() if value is not None else None


def resources_of(obj):
    visited = set()
    while isinstance(obj, DictionaryObject) and id(obj) not in visited:
        visited.add(id(obj))
        resources = resolve(obj.get("/Resources"))
        if isinstance(resources, DictionaryObject):
            return resources
        obj = resolve(obj.get("/Parent"))
    return DictionaryObject()


def replacement(properties, resources):
    properties = resolve(properties)
    if isinstance(properties, NameObject):
        definitions = resolve(resources.get("/Properties"))
        if not isinstance(definitions, DictionaryObject) or properties not in definitions:
            raise ValueError("Marked-content properties are not defined")  # noqa: TRY003
        properties = resolve(definitions[properties])
    if not isinstance(properties, DictionaryObject):
        raise TypeError("Marked-content properties must be a dictionary")  # noqa: TRY003
    value = resolve(properties.get("/ActualText"))
    if value is None or isinstance(value, NullObject):
        return None
    if isinstance(value, bytes):
        # Avoid pypdf's tolerant fallback for malformed Unicode text strings.
        if value.startswith(b"\xfe\xff"):
            return value[2:].decode("utf-16-be", errors="strict")
        if value.startswith(b"\xff\xfe"):
            return value[2:].decode("utf-16-le", errors="strict")
        if value.startswith(b"\xef\xbb\xbf"):
            return value[3:].decode("utf-8", errors="strict")
        value = create_string_object(value)
    if not isinstance(value, TextStringObject):
        raise TypeError("ActualText must be a text string")  # noqa: TRY003
    return str(value)


class MarkedText:
    def __init__(self, page):
        self.resources = resources_of(page)
        self.font = None
        self.font_cache = {}
        self.graphics = []
        self.spans = []
        self.forms = []
        self.active_forms = set()
        self.modified = []
        self.failure = None
        self.floor = 0

    def restore(self):
        for values, index, old in reversed(self.modified):
            values[index] = old
        self.modified.clear()

    def before(self, operator, operands, cm, tm):
        try:
            self._before(operator, operands, cm, tm)
        except Exception as error:
            # pypdf catches exceptions inside Form extraction and continues.
            # Retain the failure so the document boundary cannot accept a prefix.
            self.failure = error
            raise

    def _before(self, operator, operands, cm, tm):  # noqa: C901
        if operator == b"q":
            self.graphics.append(self.font)
        elif operator == b"Q" and self.graphics:
            self.font = self.graphics.pop()
        elif operator == b"Tf" and operands:
            fonts = resolve(self.resources.get("/Font"))
            self.font = resolve(fonts.get(operands[0])) if isinstance(fonts, DictionaryObject) else None
        elif operator == b"Do":
            objects = resolve(self.resources.get("/XObject"))
            form = resolve(objects.get(operands[0])) if isinstance(objects, DictionaryObject) and operands else None
            if isinstance(form, StreamObject) and resolve(form.get("/Subtype")) == "/Form":
                if id(form) in self.active_forms:
                    raise ValueError("Cyclic Form invocation")  # noqa: TRY003
                self.forms.append((form, self.resources, self.font, self.graphics, self.floor))
                self.active_forms.add(id(form))
                self.resources, self.font, self.graphics, self.floor = resources_of(form), None, [], len(self.spans)
            else:
                self.forms.append(None)
        if operator in (b"BMC", b"BDC"):
            if not operands or not isinstance(operands[0], NameObject):
                raise ValueError("Marked content requires a name tag")  # noqa: TRY003
            if operator == b"BMC" and len(operands) != 1:
                raise ValueError("BMC requires exactly one tag")  # noqa: TRY003
            text = None
            if operator == b"BDC":
                if len(operands) != 2:
                    raise ValueError("BDC requires a property list")  # noqa: TRY003
                if operands[0] in ("/Span", "/Artifact"):
                    text = replacement(operands[1], self.resources)
            self.spans.append(Span(text) if text is not None else None)
        elif operator == b"EMC":
            if operands:
                raise ValueError("EMC does not accept operands")  # noqa: TRY003
            if len(self.spans) <= self.floor:
                raise ValueError("Unmatched marked-content end")  # noqa: TRY003
            self.spans.pop()
        elif operator in (b"Tj", b"TJ", b"'", b'"'):
            span = next((span for span in self.spans if span is not None), None)
            if span is not None:
                self.replace_show(operator, operands, span, cm, tm)

    def replace_show(self, operator, operands, span, cm, tm):
        if operator == b"TJ":
            if not operands or not isinstance(operands[0], ArrayObject):
                raise ValueError("TJ requires an array")  # noqa: TRY003
            values, indices = operands[0], range(len(operands[0]))
        else:
            index = 2 if operator == b'"' else 0
            if len(operands) <= index:
                raise ValueError("Text show requires a string")  # noqa: TRY003
            values, indices = operands, (index,)
        for index in indices:
            value = values[index]
            if operator == b"TJ" and isinstance(value, (int, float)):
                # Spacing inside a replaced span belongs to the original glyphs,
                # not to the declared logical string (which may be a single word).
                self.modified.append((values, index, value))
                values[index] = NumberObject(0)
            elif isinstance(value, (bytes, TextStringObject)):
                # An empty string still anchors the replacement at this show.
                # Its original glyph advance remains zero; EMC adds no fallback.
                glyphs = str(value) if isinstance(value, str) else value.decode("latin-1")
                if isinstance(self.font, DictionaryObject):
                    font = self.font_cache.get(id(self.font))
                    if font is None:
                        font = Font.from_font_resource(self.font)
                        self.font_cache[id(self.font)] = font
                    glyphs, _ = get_text_operands([value], cm, tm, font, (0, 90, 180, 270))
                self.modified.append((values, index, value))
                values[index] = LogicalText("" if span.emitted else span.replacement, glyphs)
                span.emitted = True
            else:
                raise ValueError("Text show operand has an invalid type")  # noqa: TRY003

    def after(self, operator, operands, cm, tm):
        self.restore()
        if operator != b"Do":
            return
        try:
            frame = self.forms.pop()
            if frame is not None:
                if len(self.spans) != self.floor:
                    raise ValueError("Unclosed marked content inside Form")  # noqa: TRY003, TRY301
                form, self.resources, self.font, self.graphics, self.floor = frame
                self.active_forms.remove(id(form))
        except Exception as error:
            self.failure = error
            raise


def extract_actual_text(page):
    visitor = MarkedText(page)
    try:
        text = page.extract_text(visitor_operand_before=visitor.before, visitor_operand_after=visitor.after) or ""
        if visitor.failure is not None:
            raise ValueError("Marked text extraction failed") from visitor.failure  # noqa: TRY003
        if visitor.spans or visitor.forms:
            raise ValueError("Unclosed marked-content sequence")  # noqa: TRY003
        return text
    finally:
        visitor.restore()
