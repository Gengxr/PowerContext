# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Query-driven selection of literal Memory fragments under a complete UTF-8 budget."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

from powercontext.artifacts import ArtifactAddress
from powercontext.builtin.runtime.prepared_text import TRUST_POLICY

_BEGIN_MARKER = "BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1"
_END_MARKER = "END_POWERCONTEXT_PREPARED_CONTEXT_V1"
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_SENTENCE_END = re.compile(r"(?<=[.!?。！？;；])[\"')\]]*\s+|\n+")
_STOPWORDS = frozenset(
    """a an the and or but of to in on at by for from with as is are was were be been being it its this that these
    those there their they them we our you your he she his her not no than then so such which who whom what when where
    why how can could may might will would shall should do does did has have had into onto over under about between
    during after before also only more most less very via per both either neither each other another same""".split()
)
# Adjacent sentences usually continue the same evidence and share one citation.
_ADJACENT_BONUS = 0.35
# Retrieval order is a strong relevance prior for which entry holds the evidence.
_RANK_DECAY = 0.6
# Bridging a short gap between chosen spans costs less than a second citation.
_BRIDGE_CHARS = 200
_MIN_FRAGMENT_CHARS = 24
# Reported findings, rather than restated background, usually carry the evidence a query
# needs; such sentences and later positions in an entry get a mild multiplicative boost.
_FINDING = re.compile(
    r"\b(?:conclusions?|results?|found|finds?|show(?:s|ed|n)?|demonstrat\w*|associat\w*|significant\w*|"
    r"increas\w*|decreas\w*|reduc\w*|lower|higher|risk|compared|odds|hazard|ratio|effects?|"
    r"improv\w*|no difference)\b|\d+(?:\.\d+)?\s?%|\bp\s?[<=>]|\bci\b",
    re.IGNORECASE,
)
_FINDING_BOOST = 1.3
_POSITION_WEIGHT = 1.0


@dataclass(frozen=True)
class EvidenceCandidate:
    """One Memory entry body offered to selection, with its exact identity."""

    rank: int
    memory: ArtifactAddress
    entry_id: str
    entry_version_id: str
    text: str


@dataclass(frozen=True)
class SelectedSpan:
    """A half-open character interval of one candidate's literal text."""

    candidate: EvidenceCandidate
    start: int
    end: int

    @property
    def text(self) -> str:
        return self.candidate.text[self.start : self.end]


@dataclass(frozen=True)
class _Sentence:
    candidate: int
    index: int
    start: int
    end: int
    terms: frozenset[str]


def select_evidence(
    query: str, candidates: Sequence[EvidenceCandidate], max_bytes: int
) -> tuple[str | None, tuple[SelectedSpan, ...]]:
    """Choose literal sentence spans relevant to ``query`` whose rendered context fits ``max_bytes``."""

    sentences = [
        _Sentence(position, index, start, end, frozenset(_terms(candidate.text[start:end])))
        for position, candidate in enumerate(candidates)
        for index, (start, end) in enumerate(_sentence_spans(candidate.text))
    ]
    if not sentences:
        return None, ()
    query_terms = set(_terms(query))
    frequency: dict[str, int] = {}
    for sentence in sentences:
        for term in sentence.terms & query_terms:
            frequency[term] = frequency.get(term, 0) + 1
    count = len(sentences)
    weights = {term: math.log(1.0 + count / (seen + 0.5)) for term, seen in frequency.items()}
    document_scores = [0.0] * len(candidates)
    sentence_counts = [0] * len(candidates)
    for sentence in sentences:
        sentence_counts[sentence.candidate] += 1
    scores: dict[tuple[int, int], float] = {}
    for sentence in sentences:
        matched = sentence.terms & query_terms
        score = sum(weights[term] for term in matched)
        if score:
            score /= max(1.0, len(sentence.terms)) ** 0.25
            score /= 1.0 + _RANK_DECAY * candidates[sentence.candidate].rank
            total = sentence_counts[sentence.candidate]
            relative = sentence.index / (total - 1) if total > 1 else 1.0
            score *= 1.0 - _POSITION_WEIGHT / 2 + _POSITION_WEIGHT * relative
            text = candidates[sentence.candidate].text[sentence.start : sentence.end]
            if _FINDING.search(text):
                score *= _FINDING_BOOST
        scores[(sentence.candidate, sentence.index)] = score
        document_scores[sentence.candidate] = max(document_scores[sentence.candidate], score)
    best_document = max(document_scores, default=0.0)
    if best_document <= 0.0:
        return None, ()

    by_key = {(sentence.candidate, sentence.index): sentence for sentence in sentences}
    chosen: set[tuple[int, int]] = set()
    skipped: set[tuple[int, int]] = set()
    first_skipped: tuple[int, int] | None = None
    rendered: tuple[str | None, tuple[SelectedSpan, ...]] = (None, ())
    while True:
        best_key: tuple[int, int] | None = None
        best_value = 0.0
        for key, sentence in by_key.items():
            if key in chosen or key in skipped:
                continue
            adjacent = (key[0], key[1] - 1) in chosen or (key[0], key[1] + 1) in chosen
            if scores[key] <= 0.0 and not adjacent:
                continue
            value = scores[key] + 0.5 * document_scores[sentence.candidate]
            if adjacent:
                value += _ADJACENT_BONUS * best_document
            if value > best_value:
                best_key, best_value = key, value
        if best_key is None:
            break
        trial = _render_selection(candidates, by_key, chosen | {best_key})
        if trial[0] is not None and len(trial[0].encode("utf-8")) <= max_bytes:
            chosen.add(best_key)
            rendered = trial
        else:
            skipped.add(best_key)
            if first_skipped is None:
                first_skipped = best_key
    if first_skipped is not None:
        # Spend what remains on a word-bounded prefix of the best sentence that did not fit.
        partial = _fit_partial(candidates, by_key, chosen, first_skipped, max_bytes)
        if partial is not None:
            rendered = partial
    return rendered


def render_fragments(spans: Sequence[SelectedSpan]) -> str:
    """Render selected spans in the prepared-context envelope with exact citations."""

    items = [
        {
            "citation": {
                "scope_id": span.candidate.memory.scope_id,
                "memory_ref": span.candidate.memory.artifact.model_dump(mode="json"),
                "entry_id": span.candidate.entry_id,
                "entry_version_id": span.candidate.entry_version_id,
            },
            "content": span.text,
            "start": span.start,
            "end": span.end,
        }
        for span in spans
    ]
    encoded = json.dumps({"trust": "untrusted_history", "items": items}, ensure_ascii=False, separators=(",", ":"))
    return "\n\n".join((TRUST_POLICY, f"{_BEGIN_MARKER}\n{encoded}\n{_END_MARKER}"))


def _render_selection(
    candidates: Sequence[EvidenceCandidate],
    sentences: dict[tuple[int, int], _Sentence],
    chosen: set[tuple[int, int]],
    extra: SelectedSpan | None = None,
) -> tuple[str | None, tuple[SelectedSpan, ...]]:
    spans: list[SelectedSpan] = []
    for key in sorted(chosen):
        sentence = sentences[key]
        if spans and spans[-1].candidate is candidates[key[0]] and _joinable(spans[-1], sentence):
            spans[-1] = SelectedSpan(spans[-1].candidate, spans[-1].start, sentence.end)
        else:
            spans.append(SelectedSpan(candidates[key[0]], sentence.start, sentence.end))
    if extra is not None:
        spans.append(extra)
        spans.sort(key=lambda span: (span.candidate.rank, span.start))
    if not spans:
        return None, ()
    return render_fragments(spans), tuple(spans)


def _joinable(span: SelectedSpan, sentence: _Sentence) -> bool:
    return sentence.start - span.end <= _BRIDGE_CHARS


def _fit_partial(
    candidates: Sequence[EvidenceCandidate],
    sentences: dict[tuple[int, int], _Sentence],
    chosen: set[tuple[int, int]],
    key: tuple[int, int],
    max_bytes: int,
) -> tuple[str | None, tuple[SelectedSpan, ...]] | None:
    """Fit the longest word-bounded prefix of one sentence beside the chosen ones."""

    sentence = sentences[key]
    candidate = candidates[key[0]]
    low, high = sentence.start + _MIN_FRAGMENT_CHARS, sentence.end - 1
    best: tuple[str | None, tuple[SelectedSpan, ...]] | None = None
    while low <= high:
        middle = (low + high) // 2
        end = _word_boundary(candidate.text, sentence.start, middle)
        if end <= sentence.start:
            low = middle + 1
            continue
        trial = _render_selection(candidates, sentences, chosen, SelectedSpan(candidate, sentence.start, end))
        if trial[0] is not None and len(trial[0].encode("utf-8")) <= max_bytes:
            best = trial
            low = middle + 1
        else:
            high = middle - 1
    return best


def _word_boundary(text: str, start: int, end: int) -> int:
    cut = end
    while cut > start and not text[cut - 1].isspace() and cut < len(text) and not text[cut].isspace():
        cut -= 1
    while cut > start and text[cut - 1].isspace():
        cut -= 1
    return cut if cut > start else end


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    position = 0
    for match in _SENTENCE_END.finditer(text):
        _append_span(text, position, match.start(), spans)
        position = match.end()
    _append_span(text, position, len(text), spans)
    return spans


def _append_span(text: str, start: int, end: int, spans: list[tuple[int, int]]) -> None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if end > start:
        spans.append((start, end))


def _terms(text: str) -> list[str]:
    terms: list[str] = []
    for word in _WORD.findall(text.casefold()):
        if word in _STOPWORDS:
            continue
        if word.isascii():
            if len(word) < 2 and not word.isdigit():
                continue
            terms.append(word if word.isdigit() else _stem(word))
        else:
            # Unsegmented scripts: use overlapping character bigrams.
            terms.extend(word[index : index + 2] for index in range(max(1, len(word) - 1)))
    return terms


def _stem(word: str) -> str:
    for suffix in ("ations", "ation", "ments", "ment", "ness", "ings", "ing", "ies", "ied", "ers", "ed", "es", "ly", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[: -len(suffix)]
            break
    return word[:7]


__all__ = ["EvidenceCandidate", "SelectedSpan", "render_fragments", "select_evidence"]
