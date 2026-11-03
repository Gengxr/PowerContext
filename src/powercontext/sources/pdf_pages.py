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

"""Captured physical-page Sources for complete PDF documents and page retrieval."""

from __future__ import annotations

import hashlib
import io
import math
import re
import unicodedata
from itertools import pairwise
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

PDF_PAGE_SOURCE_NAME = "pdf-page"
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_HORIZONTAL_SPACE = re.compile(r"[^\S\n]+")


class PDFDocumentInput(BaseModel):
    """One complete original PDF and the caller-stable document identity."""

    model_config = ConfigDict(frozen=True)

    document_id: str
    content: bytes


class PDFPageInput(BaseModel):
    """Extractable text of one physical page of one exact PDF revision."""

    model_config = ConfigDict(frozen=True)

    document_id: str
    document_sha256: str
    page_number: int = Field(ge=1, strict=True)
    text: str

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        _validate_document_id(value)
        return value

    @field_validator("document_sha256")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if not _SHA256_HEX.fullmatch(value):
            raise ValueError("document_sha256 must be a lowercase SHA-256 hex digest")  # noqa: TRY003
        return value


class PDFPageSource(Source):
    """A captured PDF page addressed by document, revision digest and physical page."""

    document_id: str
    document_sha256: str
    page_number: int
    text: str


def pdf_page_source_id(document_id: str, document_sha256: str, page_number: int) -> str:
    """Return a stable, collision-free page identity bounded by the Source limit."""

    identity = f"pdf:{quote(document_id, safe='')}:{document_sha256}:{page_number}"
    if len(identity) <= MAX_SOURCE_ID_LENGTH:
        return identity
    document_digest = hashlib.sha256(document_id.encode("utf-8")).hexdigest()
    return f"pdf-sha256:{document_digest}:{document_sha256}:{page_number}"


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Extract every physical page in order, or fail without returning partial pages."""

    _validate_document_id(value.document_id)
    content = value.content
    if not content or b"%PDF-" not in content[:1024]:
        raise ValueError("PDF document must be a non-empty PDF file")  # noqa: TRY003
    digest = hashlib.sha256(content).hexdigest()
    try:
        texts = _extract_page_texts(content)
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(f"PDF document could not be parsed completely: {error}") from error  # noqa: TRY003
    return tuple(
        PDFPageInput(document_id=value.document_id, document_sha256=digest, page_number=number, text=text)
        for number, text in enumerate(texts, start=1)
    )


def _extract_page_texts(content: bytes) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content), strict=False)
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError("PDF document requires a user password")  # noqa: TRY003
    count = len(reader.pages)
    if count < 1:
        raise ValueError("PDF document has no pages")  # noqa: TRY003
    return [_normalize_page_text(reader.pages[index].extract_text() or "") for index in range(count)]


def _normalize_page_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text.replace("\x00", ""))
    lines = (_HORIZONTAL_SPACE.sub(" ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def _validate_document_id(document_id: str) -> None:
    if not document_id or not document_id.strip():
        raise ValueError("PDF document_id must not be blank")  # noqa: TRY003


class PDFPageSourceAdapter:
    """Resolve and read captured PDF pages."""

    input_class = PDFPageInput
    name = PDF_PAGE_SOURCE_NAME
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        return PDFPageSource(
            name=pdf_page_source_id(value.document_id, value.document_sha256, value.page_number),
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            document_sha256=value.document_sha256,
            page_number=value.page_number,
            text=value.text,
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(
            document_id=source.document_id,
            document_sha256=source.document_sha256,
            page_number=source.page_number,
            text=source.text,
        )


class PDFPageTextEvidenceProjection:
    """Expose one page as document-labelled text with its exact physical location."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PDF_PAGE_SOURCE_NAME,
            source_id=source.name,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


PDF_PAGE_SOURCE_DEFINITION = AdapterSourceDefinition(
    PDFPageSourceAdapter(),
    projections=(PDFPageTextEvidenceProjection(),),
)


# Offline query processing for page retrieval. The lexicon only maps generic financial
# reporting concepts to the wording filings use; it never names documents or answers.
_WORD = re.compile(r"[a-z]+|\d+")
_QUESTION_NOISE = frozenset([
    "a",
    "an",
    "the",
    "and",
    "or",
    "for",
    "of",
    "to",
    "in",
    "on",
    "at",
    "by",
    "from",
    "with",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "what",
    "which",
    "who",
    "whom",
    "how",
    "why",
    "when",
    "where",
    "do",
    "does",
    "did",
    "can",
    "could",
    "should",
    "would",
    "will",
    "shall",
    "may",
    "might",
    "must",
    "i",
    "we",
    "you",
    "it",
    "its",
    "our",
    "your",
    "their",
    "this",
    "that",
    "these",
    "those",
    "there",
    "here",
    "please",
    "if",
    "not",
    "no",
    "yes",
    "than",
    "then",
    "so",
    "such",
    "any",
    "all",
    "some",
    "each",
    "per",
    "via",
    "into",
    "over",
    "under",
    "about",
    "against",
    "between",
    "during",
    "before",
    "after",
    "since",
    "until",
    "up",
    "down",
    "out",
    "off",
    "very",
    "more",
    "most",
    "less",
    "much",
    "many",
    "few",
    "other",
    "another",
    "same",
    "own",
    "only",
    "also",
    "just",
    "has",
    "have",
    "had",
    "having",
    "state",
    "stated",
    "answer",
    "answers",
    "respond",
    "response",
    "question",
    "questions",
    "assume",
    "assuming",
    "assumption",
    "perspective",
    "investment",
    "investor",
    "analyst",
    "analysts",
    "details",
    "detail",
    "shown",
    "show",
    "shows",
    "within",
    "using",
    "use",
    "used",
    "define",
    "defined",
    "defining",
    "definition",
    "calculate",
    "calculated",
    "calculation",
    "compute",
    "computed",
    "round",
    "rounded",
    "decimal",
    "places",
    "place",
    "usd",
    "dollars",
    "dollar",
    "million",
    "millions",
    "billion",
    "billions",
    "thousand",
    "thousands",
    "percent",
    "percentage",
    "fy",
    "fiscal",
    "year",
    "years",
    "yr",
    "quarter",
    "quarters",
    "reported",
    "report",
    "reports",
    "reporting",
    "company",
    "companys",
    "companies",
    "business",
    "firm",
    "figure",
    "figures",
    "number",
    "numbers",
    "amount",
    "amounts",
    "total",
    "value",
    "values",
    "metric",
    "metrics",
    "useful",
    "profile",
    "improving",
    "improved",
    "improve",
    "declined",
    "decline",
    "declining",
    "change",
    "changed",
    "changes",
    "changing",
    "compared",
    "compare",
    "comparison",
    "able",
    "primarily",
    "primary",
    "mainly",
    "mostly",
    "major",
    "material",
    "materially",
    "important",
    "ongoing",
    "directly",
    "outlined",
    "explicitly",
    "unadjusted",
    "adjusted",
    "based",
    "basis",
    "term",
    "terms",
    "like",
    "give",
    "given",
    "provide",
    "provided",
    "list",
    "listed",
    "describe",
    "explain",
    "explained",
    "ratio",
])
_STATEMENT_TITLES = {
    "income": re.compile(
        r"statements? of (?:consolidated )?(?:income|operations|earnings|comprehensive (?:income|loss))"
        r"|income statements?"
    ),
    "balance": re.compile(r"balance sheets?|statements? of (?:consolidated )?financial (?:position|condition)"),
    "cash": re.compile(r"statements? of (?:consolidated )?cash flows?|cash flows? statements?"),
}
_LEXICON: tuple[tuple[re.Pattern[str], tuple[str, ...], frozenset[str]], ...] = tuple(
    (re.compile(pattern), expansions, frozenset(statements))
    for pattern, expansions, statements in (
        (
            r"\bcapex\b|capital expenditure|capital spending",
            (
                "capital spending",
                "capital expenditures",
                "purchases of property",
                "property plant equipment",
                "investing activities",
            ),
            ("cash",),
        ),
        (
            r"ebitda",
            ("operating profit", "operating income", "depreciation amortization", "net revenue"),
            ("income", "cash"),
        ),
        (
            r"operating (?:margin|income|profit)",
            ("operating income", "operating profit", "total revenues", "net revenue", "net sales"),
            ("income",),
        ),
        (
            r"gross (?:margin|profit)",
            (
                "gross profit",
                "gross margin",
                "cost of sales",
                "cost of goods sold",
                "cost of revenue",
                "net revenue",
                "net sales",
            ),
            ("income",),
        ),
        (
            r"net (?:income|profit|earnings|margin)|\beps\b|earnings per share",
            ("net income", "net earnings", "per share"),
            ("income",),
        ),
        (
            r"income statement|statement of (?:income|operations)|p&l",
            ("statement of income", "statement of operations", "total revenues", "net income"),
            ("income",),
        ),
        (r"(?:revenue|sales) growth|top line", ("net revenue", "total revenues", "net sales"), ("income",)),
        (
            r"quick ratio|current ratio|liquidity|working capital|acid test",
            (
                "current assets",
                "current liabilities",
                "cash and cash equivalents",
                "receivables",
                "inventories",
                "short-term investments",
            ),
            ("balance",),
        ),
        (
            r"balance sheet|liabilit|total assets|shareholders.? equity|stockholders.? equity|book value",
            ("total liabilities", "total assets", "balance sheet", "equity"),
            ("balance",),
        ),
        (
            r"cash flow|operating activities|free cash",
            ("statement of cash flows", "operating activities", "investing activities", "capital spending"),
            ("cash",),
        ),
        (
            r"(?:effective )?tax rate|income tax",
            ("effective tax rate", "income taxes", "provision for income taxes", "tax expense"),
            ("income",),
        ),
        (
            r"inventory turnover|days inventory|\bdio\b",
            ("inventories", "cost of sales", "cost of goods sold"),
            ("income", "balance"),
        ),
        (r"days payable|\bdpo\b|payables? turnover", ("accounts payable", "cost of sales"), ("income", "balance")),
        (
            r"days sales|\bdso\b|receivables? turnover",
            ("accounts receivable", "receivables", "net revenue"),
            ("income", "balance"),
        ),
        (
            r"return on (?:assets|equity)|\broa\b|\broe\b",
            ("net income", "total assets", "total equity"),
            ("income", "balance"),
        ),
        (
            r"debt|leverage|borrowing|interest coverage",
            ("long-term debt", "borrowings", "notes payable", "interest expense"),
            ("balance",),
        ),
        (
            r"capital[- ]intensi|asset[- ](?:light|heavy|intensi)|fixed assets",
            (
                "capital expenditures",
                "capital spending",
                "purchases of property",
                "property plant and equipment",
                "total assets",
                "depreciation",
            ),
            ("cash", "balance"),
        ),
        (r"dividend", ("dividends declared", "dividends paid", "cash dividends", "per share"), ("cash",)),
        (
            r"organic|growth|m&a|acquisition|divestiture",
            ("organic", "sales growth", "acquisitions", "divestitures", "segment"),
            (),
        ),
        (
            r"repurchase|buyback|buy back",
            ("share repurchases", "repurchased", "treasury stock", "repurchase program"),
            ("cash",),
        ),
        (
            r"legal|litigation|lawsuit|court|settlement",
            ("legal proceedings", "litigation", "lawsuits", "contingencies", "investigations"),
            (),
        ),
        (
            r"geograph|region|countr|international",
            (
                "geographic",
                "geographic areas",
                "regions",
                "international",
                "countries",
                "north america",
                "europe",
                "asia",
            ),
            (),
        ),
        (
            r"customer",
            ("customer accounted", "customers", "largest customer", "major customers", "percent of net revenue"),
            (),
        ),
        (
            r"segment|product (?:categor|line)|business line|service categor",
            ("segment", "segments", "reportable segments", "revenues by", "net sales by"),
            (),
        ),
        (r"cyclical", ("cyclical", "cyclicality", "economic conditions", "demand"), ()),
        (r"restructuring", ("restructuring", "restructuring charges", "impairment"), ("income",)),
        (r"retain|retention|attrition|churn", ("retention", "attrition", "loyalty", "card members"), ()),
        (r"guidance|outlook|forecast", ("outlook", "guidance", "expects", "fiscal"), ()),
    )
)


def _words(text: str) -> list[str]:
    return _WORD.findall(text.casefold())


def _stem(word: str) -> str:
    return word if word.isdigit() else word[:6]


async def search_pdf_pages(memory, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:  # noqa: C901
    """Return up to ``limit`` exact citations of distinct pages relevant to ``question``.

    Candidates come only from Memory full-text searches: the question itself, each salient
    question term and a few generic financial-reporting expansions. The pooled pages are then
    reranked offline with BM25, phrase overlap, primary-statement cues and document targeting.
    """

    from powercontext.builtin.runtime import GetMemoryEntryRequest, SearchMemoryRequest

    if limit < 1:
        raise ValueError("limit must be positive")  # noqa: TRY003
    folded = question.casefold()
    question_words = _words(question)
    salient = [word for word in dict.fromkeys(question_words) if word not in _QUESTION_NOISE and len(word) > 1]
    expansions: list[str] = []
    statements: set[str] = set()
    for pattern, phrases, kinds in _LEXICON:
        if pattern.search(folded):
            expansions.extend(phrases)
            statements.update(kinds)
    for kind, title in _STATEMENT_TITLES.items():
        if title.search(folded):
            statements.add(kind)

    queries = [question, *salient, *dict.fromkeys(expansions)]
    pool: dict[tuple[str, str, str], object] = {}
    for query in queries:
        if not _words(query):
            continue
        page = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=max(200, limit * 10)))
        for hit in page.hits:
            pool.setdefault((hit.memory_ref.artifact_id, hit.entry_id, hit.entry_version_id), hit)
    if not pool:
        return ()

    hits = list(pool.values())
    documents = [hit.text.split("\n", 1)[0].strip() for hit in hits]
    tokens = [[_stem(word) for word in _words(hit.text)] for hit in hits]
    document_weight = _document_weights(question, set(documents))

    weights: dict[str, float] = {}
    for word in salient:
        weights[_stem(word)] = max(weights.get(_stem(word), 0.0), 0.5 if word.isdigit() else 1.0)
    for phrase in expansions:
        for word in _words(phrase):
            if word not in _QUESTION_NOISE:
                weights.setdefault(_stem(word), 0.5)
    for document in set(documents):
        for word in _words(document.replace("_", " ")):
            if _stem(word) in weights:
                weights[_stem(word)] = min(weights[_stem(word)], 0.2)

    count = len(hits)
    frequency: dict[str, int] = {}
    for page_tokens in tokens:
        for term in set(page_tokens).intersection(weights):
            frequency[term] = frequency.get(term, 0) + 1
    average_length = sum(len(page_tokens) for page_tokens in tokens) / count or 1.0
    phrases = _query_bigrams(question_words, expansions)

    scored: list[tuple[float, int]] = []
    for index, (hit, page_tokens) in enumerate(zip(hits, tokens, strict=True)):
        counts: dict[str, int] = {}
        for term in page_tokens:
            if term in weights:
                counts[term] = counts.get(term, 0) + 1
        length_norm = 0.25 + 0.75 * len(page_tokens) / average_length
        score = 0.0
        for term, tf in counts.items():
            idf = math.log(1.0 + (count - frequency[term] + 0.5) / (frequency[term] + 0.5))
            score += weights[term] * idf * tf * 2.2 / (tf + 1.2 * length_norm)
        page_bigrams = set(pairwise(page_tokens))
        score += 1.5 * sum(1 for phrase in phrases if phrase in page_bigrams)
        if statements:
            score += 6.0 * _statement_cue(hit.text, statements)
        scored.append((score * document_weight.get(documents[index], 1.0), index))
    scored.sort(key=lambda item: (-item[0], item[1]))

    citations: list[MemoryCitation] = []
    seen: set[str] = set()
    for _score, index in scored:
        hit = hits[index]
        citation = MemoryCitation(
            memory_ref=hit.memory_ref, entry_id=hit.entry_id, entry_version_id=hit.entry_version_id
        )
        sources = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry.sources
        if len(sources) != 1 or sources[0].source_type != PDF_PAGE_SOURCE_NAME or sources[0].source_id in seen:
            continue
        seen.add(sources[0].source_id)
        citations.append(citation)
        if len(citations) == limit:
            break
    return tuple(citations)


def _query_bigrams(question_words: list[str], expansions: list[str]) -> set[tuple[str, str]]:
    bigrams: set[tuple[str, str]] = set()
    for words in (question_words, *(_words(phrase) for phrase in expansions)):
        content = [_stem(word) for word in words if word not in _QUESTION_NOISE or word in {"of"}]
        content = [word for word in content if word != "of"]
        bigrams.update(pairwise(content))
    return bigrams


def _statement_cue(text: str, statements: set[str]) -> float:
    lines = text.split("\n")[1:9]
    head = " ".join(lines).casefold()
    matched = [kind for kind, title in _STATEMENT_TITLES.items() if title.search(head)]
    if len(matched) != 1 or matched[0] not in statements:
        return 0.0
    words = _words(text)
    numbers = sum(1 for word in words if word.isdigit())
    return 1.0 if words and numbers / len(words) >= 0.2 else 0.3


def _document_weights(question: str, documents: set[str]) -> dict[str, float]:
    words = _words(question)
    joined = {"".join(words[start : start + size]) for size in (1, 2, 3) for start in range(len(words))}
    proper = [word.casefold() for word in re.findall(r"\b[A-Z][A-Za-z0-9&]{1,}\b|\b\d[A-Za-z]+\b", question)]
    years = {word[-4:] for word in words if word.isdigit() and len(word) == 4}
    years.update(f"20{word[2:]}" for word in words if re.fullmatch(r"fy\d{2}", word))
    years.update(word[2:] for word in words if re.fullmatch(r"fy\d{4}", word))

    scores: dict[str, float] = {}
    for document in documents:
        parts = [part.casefold() for part in document.split("_") if part]
        name_parts: list[str] = []
        for part in parts:
            if re.fullmatch(r"\d{4}.*", part):
                break
            name_parts.append(part)
        name = "".join(name_parts)
        score = 0.0
        if name and (name in joined or any(part in joined for part in name_parts if len(part) >= 4)):
            score = 2.0
        elif name and any(len(word) >= 3 and word[0] == name[0] and _is_subsequence(word, name) for word in proper):
            score = 1.0
        if score and any(year in document for year in years):
            score += 0.5
        scores[document] = score
    best = max(scores.values(), default=0.0)
    if best <= 0.0:
        return {}
    return {document: 1.0 if score == best else 0.6 if score > 0.0 else 0.25 for document, score in scores.items()}


def _is_subsequence(word: str, name: str) -> bool:
    remaining = iter(name)
    return all(character in remaining for character in word)
