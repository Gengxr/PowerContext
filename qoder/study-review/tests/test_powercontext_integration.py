"""PowerContext 真实集成测试：Scope/Memory/Source/Search/Context 全链路。

全部请求打到真实 PowerContext Server 子进程（SQLite 持久化），无 mock。
"""

import json
import uuid

import pytest

from app.powercontext_client import PowerContextError


@pytest.fixture()
def scope(pc_client):
    key = "test-scope-" + uuid.uuid4().hex[:8]
    desc = pc_client.create_scope(title="集成测试 " + key, summary="pytest", idempotency_key=key)
    return desc["scope_id"]


def test_health_and_capabilities(pc_client):
    assert pc_client.health_live()["status"] == "ok"
    ready = pc_client.health_ready()
    assert ready["status"] == "ready"
    assert ready["checks"]["database"] == "ready"
    caps = pc_client.capabilities()
    assert isinstance(caps, dict)


def test_scope_idempotent_create(pc_client):
    key = "idem-" + uuid.uuid4().hex[:8]
    a = pc_client.create_scope(title="幂等 " + key, summary="s", idempotency_key=key)
    b = pc_client.create_scope(title="幂等 " + key, summary="s", idempotency_key=key)
    assert a["scope_id"] == b["scope_id"]


def test_remember_list_replace_forget(pc_client, scope):
    rec = pc_client.remember(scope, "knowledge-point",
                             json.dumps({"title": "矩阵乘法"}, ensure_ascii=False), reason="测试")
    assert rec["state"] == "active"
    assert rec["artifact"]["family"] == "atomic-memory"
    aid = rec["artifact"]["artifact_id"]

    items = pc_client.list_all_atomic_memories(scope, kind="knowledge-point", states=["active"])
    assert len(items) == 1

    _, etag = pc_client.get_artifact(scope, aid)
    new_rev = pc_client.replace_atomic_memory(
        scope, aid, "knowledge-point",
        json.dumps({"title": "矩阵乘法", "mastery": 2}, ensure_ascii=False), if_match=etag)
    assert new_rev["revision"] == rec["artifact"]["revision"] + 1

    state = pc_client.get_atomic_state(scope, aid)
    assert state["state"] == "active"

    pc_client.forget_atomic_memory(scope, state["artifact"], state["state_version"])
    assert pc_client.list_all_atomic_memories(scope, kind="knowledge-point", states=["active"]) == []
    inactive = pc_client.list_all_atomic_memories(scope, kind="knowledge-point", states=["forgotten"])
    assert len(inactive) == 1


def test_replace_with_stale_etag_rejected(pc_client, scope):
    rec = pc_client.remember(scope, "fact", "v1")
    aid = rec["artifact"]["artifact_id"]
    _, etag = pc_client.get_artifact(scope, aid)
    pc_client.replace_atomic_memory(scope, aid, "fact", "v2", if_match=etag)
    with pytest.raises(PowerContextError) as ei:
        pc_client.replace_atomic_memory(scope, aid, "fact", "v3", if_match=etag)
    assert ei.value.status in (409, 412, 428)


def test_source_capture_and_search(pc_client, scope):
    pc_client.remember(scope, "decision", "复习间隔采用确定性规则，不使用模型推荐。")
    resp = pc_client.capture_content_source(scope, "src-" + uuid.uuid4().hex[:8],
                                            "复习证据：特征值 需要加强", metadata={"origin": "pytest"})
    assert resp["status"] == "accepted"
    hits = pc_client.search_memory(scope, "确定性规则", limit=5)
    assert len(hits.get("hits", [])) >= 1


def test_prepare_context(pc_client, scope):
    pc_client.remember(scope, "fact", "索引的最左前缀原则决定查询是否命中索引。")
    prepared = pc_client.prepare_context(scope, "最左前缀", max_bytes=2000)
    assert prepared["status"] in ("ready", "empty")
    if prepared["status"] == "ready":
        assert prepared.get("content")


def test_list_pagination(pc_client, scope):
    for i in range(5):
        pc_client.remember(scope, "fact", f"分页条目 {i}")
    page1 = pc_client.list_atomic_memories(scope, kind="fact", limit=2)
    assert len(page1["items"]) == 2
    assert page1["next_cursor"]
    page2 = pc_client.list_atomic_memories(scope, kind="fact", limit=2, cursor=page1["next_cursor"])
    assert len(page2["items"]) == 2
    all_items = pc_client.list_all_atomic_memories(scope, kind="fact")
    assert len(all_items) == 5


def test_scope_isolation_at_powercontext_level(pc_client):
    key_a, key_b = uuid.uuid4().hex[:8], uuid.uuid4().hex[:8]
    sa = pc_client.create_scope(title="隔离A " + key_a, summary="s", idempotency_key="iso-a-" + key_a)["scope_id"]
    sb = pc_client.create_scope(title="隔离B " + key_b, summary="s", idempotency_key="iso-b-" + key_b)["scope_id"]
    pc_client.remember(sa, "fact", "A 的秘密数据")
    assert pc_client.list_all_atomic_memories(sb) == []
    hits = pc_client.search_memory(sb, "秘密数据", limit=5)
    assert hits.get("hits", []) == []