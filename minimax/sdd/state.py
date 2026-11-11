"""Actual PowerContext SDK persistence, not a JSON-file substitute."""
import asyncio
import json
from uuid import uuid4
from powercontext.builtin.persistence.sources import SourceRepository
from powercontext.builtin.persistence.sqlite import SQLiteConfig, SQLiteProfile
from powercontext.builtin.persistence.tables import SHARED_TABLES
from powercontext.builtin.sources import CONTENT_SOURCE_ADAPTER, ContentCapture

async def operate(path, task, value=None):
    repository = SourceRepository((CONTENT_SOURCE_ADAPTER,))
    config = SQLiteConfig(url="sqlite+aiosqlite:///" + str(path.resolve()))
    async with SQLiteProfile.open(config, tables=SHARED_TABLES) as profile:
        async with profile.database.transaction() as connection:
            if value is not None:
                source = await CONTENT_SOURCE_ADAPTER.resolve(ContentCapture(
                    source_id=str(uuid4()), content=json.dumps(value, ensure_ascii=False),
                    metadata={"task": task, "kind": "sdd-progress"}))
                stored = await repository.add(connection, task, source)
                return {"operation": "powercontext.add", "ref": stored.ref.model_dump(mode="json"),
                        "journal_position": stored.journal_position, "state": value}
            records = await repository.list(connection, task)
            if not records:
                return {"operation": "powercontext.list", "state": None}
            stored = records[-1]
            return {"operation": "powercontext.list", "ref": stored.ref.model_dump(mode="json"),
                    "journal_position": stored.journal_position,
                    "state": json.loads(stored.value.content)}

def state(path, task, value=None):
    return asyncio.run(operate(path, task, value))
