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

"""Cross-call request coalescing and bounded vector caching for Embedding models."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel, QueryEmbeddingModel

if TYPE_CHECKING:
    from powercontext.builtin.artifacts.memory.models import EmbeddingProfile


@dataclass(eq=False, slots=True)
class _Batch:
    """One provider request; its usage is charged once to every caller waiting on it."""

    usage: InferenceUsage | None = None


@dataclass(slots=True)
class _Channel:
    """Shared state for one embedding entry point (documents or queries)."""

    embed: Callable[[tuple[str, ...]], Awaitable[EmbeddingResult]]
    cache: OrderedDict[str, EmbeddingVector] = field(default_factory=OrderedDict)
    inflight: dict[str, asyncio.Future[tuple[EmbeddingVector, _Batch]]] = field(default_factory=dict)
    pending: dict[str, None] = field(default_factory=dict)
    flush_scheduled: bool = False


class CoalescingEmbeddingModel:
    """Share in-flight provider work between concurrent calls and cache successful vectors.

    Calls arriving within ``coalesce_ms`` are deduplicated into provider batches of at most
    ``max_batch_size`` texts; later calls reuse batches that are still running. Successful
    vectors enter an LRU cache of ``cache_size`` texts. Failures reach only the callers
    waiting on the failed batch and are never cached, and cancelling one caller never
    cancels provider work that other callers still await.
    """

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        if type(max_batch_size) is not int or max_batch_size < 1:
            raise ValueError("max_batch_size must be a positive integer")  # noqa: TRY003
        if isinstance(coalesce_ms, bool) or not isinstance(coalesce_ms, (int, float)) or not coalesce_ms >= 0:
            raise ValueError("coalesce_ms must be a non-negative number")  # noqa: TRY003
        if type(cache_size) is not int or cache_size < 0:
            raise ValueError("cache_size must be a non-negative integer")  # noqa: TRY003
        self._model = model
        self._max_batch_size = max_batch_size
        self._coalesce_seconds = float(coalesce_ms) / 1000
        self._cache_size = cache_size
        self._documents = _Channel(model.embed)
        # Asymmetric providers embed queries in their own space; symmetric ones share documents.
        self._queries = (
            _Channel(model.embed_query) if isinstance(model, QueryEmbeddingModel) else self._documents
        )
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def profile(self) -> EmbeddingProfile:
        return self._model.profile

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        return await self._embed(self._documents, tuple(texts))

    async def embed_query(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        return await self._embed(self._queries, tuple(texts))

    async def _embed(self, channel: _Channel, texts: tuple[str, ...]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(vectors=(), usage=InferenceUsage(requests=0))
        vectors: dict[str, EmbeddingVector] = {}
        waits: dict[str, asyncio.Future[tuple[EmbeddingVector, _Batch]]] = {}
        for text in dict.fromkeys(texts):
            cached = channel.cache.get(text)
            if cached is not None:
                channel.cache.move_to_end(text)
                vectors[text] = cached
                continue
            future = channel.inflight.get(text)
            if future is None:
                future = asyncio.get_running_loop().create_future()
                future.add_done_callback(_consume_exception)
                channel.inflight[text] = future
                channel.pending[text] = None
            waits[text] = future
        if channel.pending and not channel.flush_scheduled:
            self._schedule_flush(channel)

        batches: dict[int, _Batch] = {}
        if waits:
            # Shield shared futures: cancelling this caller must not cancel other waiters.
            results = await asyncio.gather(*(asyncio.shield(future) for future in waits.values()))
            for text, (vector, batch) in zip(waits, results, strict=True):
                vectors[text] = vector
                batches[id(batch)] = batch
        return EmbeddingResult(
            vectors=tuple(vectors[text] for text in texts),
            usage=_sum_usage(batch.usage for batch in batches.values()),
        )

    def _schedule_flush(self, channel: _Channel) -> None:
        channel.flush_scheduled = True
        loop = asyncio.get_running_loop()
        if self._coalesce_seconds == 0:
            loop.call_soon(self._flush, channel)
        else:
            loop.call_later(self._coalesce_seconds, self._flush, channel)

    def _flush(self, channel: _Channel) -> None:
        channel.flush_scheduled = False
        texts = tuple(channel.pending)
        channel.pending.clear()
        for start in range(0, len(texts), self._max_batch_size):
            task = asyncio.get_running_loop().create_task(
                self._run_batch(channel, texts[start : start + self._max_batch_size])
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _run_batch(self, channel: _Channel, texts: tuple[str, ...]) -> None:
        futures = {text: channel.inflight[text] for text in texts}
        try:
            result = await channel.embed(texts)
            if len(result.vectors) != len(texts):
                raise ValueError(  # noqa: TRY301
                    f"embedding model returned {len(result.vectors)} vectors for {len(texts)} texts"
                )
        except asyncio.CancelledError:
            self._release(channel, futures, None)
            raise
        except Exception as error:
            self._release(channel, futures, error)
            return
        batch = _Batch(result.usage)
        for (text, future), vector in zip(futures.items(), result.vectors, strict=True):
            if channel.inflight.get(text) is future:
                del channel.inflight[text]
            self._remember(channel, text, vector)
            if not future.done():
                future.set_result((vector, batch))

    @staticmethod
    def _release(
        channel: _Channel,
        futures: dict[str, asyncio.Future[tuple[EmbeddingVector, _Batch]]],
        error: Exception | None,
    ) -> None:
        """Fail a batch's waiters without caching, so the texts can be retried."""

        for text, future in futures.items():
            if channel.inflight.get(text) is future:
                del channel.inflight[text]
            if future.done():
                continue
            if error is None:
                future.cancel()
            else:
                future.set_exception(error)

    def _remember(self, channel: _Channel, text: str, vector: EmbeddingVector) -> None:
        if self._cache_size == 0:
            return
        channel.cache[text] = vector
        channel.cache.move_to_end(text)
        while len(channel.cache) > self._cache_size:
            channel.cache.popitem(last=False)


def _consume_exception(future: asyncio.Future[object]) -> None:
    # Every waiter may have been cancelled; retrieving here avoids unobserved-error noise.
    if not future.cancelled():
        future.exception()


def _sum_usage(usages) -> InferenceUsage:
    requests = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    for usage in usages:
        if usage is None:
            continue
        requests += usage.requests
        if usage.input_tokens is not None:
            input_tokens = (input_tokens or 0) + usage.input_tokens
        if usage.output_tokens is not None:
            output_tokens = (output_tokens or 0) + usage.output_tokens
    return InferenceUsage(requests=requests, input_tokens=input_tokens, output_tokens=output_tokens)


__all__ = ["CoalescingEmbeddingModel"]
