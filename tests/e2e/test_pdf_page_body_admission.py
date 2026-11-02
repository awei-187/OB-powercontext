# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""A valid PDF reference alone cannot exempt unrelated long Memory text."""

import pytest

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.artifacts.memory.errors import InvalidMemoryCandidateError
from powercontext.builtin.runtime import open_builtin_contexts
from powercontext.sources import TEXT_EVIDENCE_PROJECTION_KEY, SourceObservation, TextEvidence
from tests.e2e.test_pdf_locations_and_headings import _capture
from tests.e2e.test_pdf_long_pages import dense_pdf


@pytest.mark.parametrize("operation", ("append", "revise"))
@pytest.mark.parametrize("body", ("unrelated", "changed_tail"))
async def test_oversized_pdf_evidence_must_equal_its_authoritative_page(tmp_path, operation, body):
    config, scope, _ = await _capture(tmp_path, {"EXACT_PAGE": dense_pdf()})
    async with open_builtin_contexts(config) as contexts:
        context = await contexts.get(scope)
        service = context.artifacts.memory
        head = await service.head(context.artifacts.memory_artifact_id)
        assert head is not None
        journal = await context.sources.journal.entries()
        previous = next(entry for entry in await service.entries(head) if len(entry.text.encode("utf-8")) > 8192)
        source = next(item.source for item in journal if item.source.name == previous.sources[0].source_id)
        assert isinstance(source, SourceObservation)
        evidence = TextEvidence.model_validate(source.projection(TEXT_EVIDENCE_PROJECTION_KEY))
        assert evidence.metadata["page_number"] == 2
        original = evidence.content.strip()
        assert previous.text == original
        text = "unrelated material " + "z" * 10000 if body == "unrelated" else original + " altered tail"
        candidate = MemoryEntryInput(
            kind="source-evidence", text=text, sources=(source,), entry=previous if operation == "revise" else None
        )
        with pytest.raises(InvalidMemoryCandidateError, match="8192"):
            await service.remember(memory=head, sources=(source,), entries=(candidate,), mode="append")
        assert await service.head(context.artifacts.memory_artifact_id) == head
        assert any(entry == previous for entry in await service.entries(head))


async def test_short_derived_evidence_and_unchanged_long_revision_remain_supported(tmp_path):
    config, scope, _ = await _capture(tmp_path, {"EXACT_PAGE": dense_pdf()})
    async with open_builtin_contexts(config) as contexts:
        context = await contexts.get(scope)
        service = context.artifacts.memory
        head = await service.head(context.artifacts.memory_artifact_id)
        assert head is not None
        previous = next(entry for entry in await service.entries(head) if len(entry.text.encode("utf-8")) > 8192)
        await service.remember(
            memory=head,
            entries=(MemoryEntryInput(kind=previous.kind, text=previous.text, entry=previous),),
            mode="append",
        )
        assert await service.head(context.artifacts.memory_artifact_id) == head
        journal = await context.sources.journal.entries()
        source = next(item.source for item in journal if item.source.name == previous.sources[0].source_id)
        derived = "A short derived observation remains ordinary source evidence."
        updated = await service.remember(
            memory=head,
            sources=(source,),
            entries=(MemoryEntryInput(kind="source-evidence", text=derived, sources=(source,)),),
            mode="append",
        )
        assert updated is not None
        assert any(entry.text == derived for entry in await service.entries(updated))
        assert any(entry == previous for entry in await service.entries(updated))
