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

"""Memory reranking through a batched HTTP relevance-scoring service."""

from __future__ import annotations

import json
import math

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision, _validate_bounds
from powercontext.builtin.inference import InferenceUsage


class HTTPMemoryReranker:
    """Score candidates in bounded batches and select globally by service score.

    Each request carries the original one-based ranks of the full candidate pool, so scores
    from every batch take part in one stable selection: score descending, then rank ascending.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = "http-cross-encoder-v1",
    ) -> None:
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("reranker endpoint must be a non-empty string")  # noqa: TRY003
        if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
            raise ValueError("reranker batch_size must be a positive integer")  # noqa: TRY003
        if not isinstance(policy_id, str) or not policy_id:
            raise ValueError("reranker policy_id must be a non-empty string")  # noqa: TRY003
        self.endpoint = endpoint
        self.batch_size = batch_size
        self.policy_id = policy_id
        self._client = client

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        """Request scores for every candidate exactly once and select the top ``limit`` ranks."""

        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("rerank limit must be an integer")  # noqa: TRY003, TRY004
        _validate_bounds(len(candidates), limit)
        scores: dict[int, float] = {}
        requests = 0
        for start in range(0, len(candidates), self.batch_size):
            ranks = tuple(range(start + 1, min(start + self.batch_size, len(candidates)) + 1))
            response = await self._client.post(
                self.endpoint,
                json={
                    "query": query,
                    "candidates": [{"rank": rank, "text": candidates[rank - 1].text} for rank in ranks],
                },
            )
            requests += 1
            response.raise_for_status()
            scores.update(_parse_scores(response.content, ranks))
        selected = sorted(scores, key=lambda rank: (-scores[rank], rank))[:limit]
        return MemoryRerankDecision(selected_ranks=tuple(selected), usage=InferenceUsage(requests=requests))


def _parse_scores(content: bytes, ranks: tuple[int, ...]) -> dict[int, float]:
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("reranker response must be valid JSON") from error  # noqa: TRY003
    if not isinstance(payload, dict) or set(payload) != {"scores"} or not isinstance(payload["scores"], list):
        raise ValueError("reranker response must contain exactly a scores list")  # noqa: TRY003
    expected = set(ranks)
    scores: dict[int, float] = {}
    for item in payload["scores"]:
        if not isinstance(item, dict) or set(item) != {"rank", "score"}:
            raise ValueError("reranker score records must contain exactly rank and score")  # noqa: TRY003
        rank, score = item["rank"], item["score"]
        if not isinstance(rank, int) or isinstance(rank, bool) or rank not in expected or rank in scores:
            raise ValueError("reranker response ranks must cover the batch exactly once")  # noqa: TRY003
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score):
            raise ValueError("reranker scores must be finite numbers")  # noqa: TRY003
        scores[rank] = float(score)
    if len(scores) != len(expected):
        raise ValueError("reranker response ranks must cover the batch exactly once")  # noqa: TRY003
    return scores


__all__ = ["HTTPMemoryReranker"]
