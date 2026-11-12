"""PowerContext 官方 HTTP API 客户端（仅用 Python 标准库）。

对接真实 PowerContext Server（powercontext[cli,server]==1.5.1，SQLite 持久化，
基本记忆模式，无需模型 API）。

契约来源：运行中服务器提供的 /openapi.json（1.5.1 实际契约，已存档
evidence/live-openapi-1.5.1.json）。注意 1.5.1 使用 Atomic Memory 契约：
- 写入：POST /v1/memory/remember -> {changed, records:[AtomicMemoryRecord]}
- 列表：POST /v1/atomic-memory/list（kind/states 过滤 + 游标分页）
- 更新：GET  /v1/scopes/{sid}/artifacts/atomic-memory/{aid} 取 ETag，
        PUT  同路径 + If-Match + {content:{schema,kind,text}} 提交新 Revision
- 删除：POST /v1/atomic-memory/lifecycle（state="forgotten"）
- 证据：POST /v1/sources/content（202）
- 检索：POST /v1/memory/search；上下文：POST /v1/context/prepare

每次请求可写入 JSONL 审计日志（runtime/audit.jsonl），作为真实集成证据。
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ATOMIC_FAMILY = "atomic-memory"
ATOMIC_SCHEMA = "powercontext.atomic-memory.v1"


class PowerContextError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


class PowerContextClient:
    def __init__(self, base_url: str, token: str | None = None, timeout: float = 60.0,
                 audit_path: str | Path | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.audit_path = Path(audit_path) if audit_path else None
        self._audit_lock = threading.Lock()
        if self.audit_path:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)

    # ---- 底层请求 ----
    def _request(self, method: str, path: str, payload: dict | None = None,
                 params: dict | None = None, headers: dict | None = None,
                 want_headers: bool = False):
        url = self.base_url + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            url += "?" + urllib.parse.urlencode(clean)
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req_headers = {"Accept": "application/json"}
        if data is not None:
            req_headers["Content-Type"] = "application/json"
        if headers:
            req_headers.update(headers)
        if self.token:
            req_headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        started = time.monotonic()
        status = None
        body_text = ""
        resp_headers: dict = {}
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status = resp.status
                resp_headers = {k.lower(): v for k, v in resp.getheaders()}
                body_text = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            status = e.code
            body_text = e.read().decode("utf-8", errors="replace")
            self._audit(method, path, status, started, payload, error=body_text[:500])
            raise PowerContextError(
                f"PowerContext {method} {path} 失败 HTTP {status}: {body_text[:500]}",
                status=status, body=body_text) from e
        except urllib.error.URLError as e:
            self._audit(method, path, None, started, payload, error=str(e))
            raise PowerContextError(f"无法连接 PowerContext {url}: {e}") from e
        self._audit(method, path, status, started, payload)
        body = {}
        if body_text:
            try:
                body = json.loads(body_text)
            except json.JSONDecodeError as e:
                raise PowerContextError(f"PowerContext 返回非 JSON: {body_text[:200]}") from e
        if want_headers:
            return body, resp_headers
        return body

    def _audit(self, method: str, path: str, status, started: float,
               payload: dict | None, error: str | None = None) -> None:
        if not self.audit_path:
            return
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "method": method,
            "path": path,
            "status": status,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            "scope_id": (payload or {}).get("scope_id"),
            "kind": (payload or {}).get("kind"),
            "ok": error is None and status is not None and 200 <= status < 300,
        }
        if error:
            record["error"] = error
        with self._audit_lock:
            with self.audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _post(self, path: str, payload: dict) -> dict:
        return self._request("POST", path, payload=payload)

    def _get(self, path: str, params: dict | None = None) -> dict:
        return self._request("GET", path, params=params)

    # ---- 健康与能力 ----
    def health_live(self) -> dict:
        return self._get("/health/live")

    def health_ready(self) -> dict:
        return self._get("/health/ready")

    def capabilities(self) -> dict:
        return self._get("/v1/capabilities")

    # ---- Scope ----
    def create_scope(self, title: str, summary: str, idempotency_key: str) -> dict:
        return self._post("/v1/scopes", {
            "title": title, "summary": summary, "idempotency_key": idempotency_key,
        })

    def list_scopes(self, query: str | None = None, query_field: str | None = None,
                    limit: int = 100, cursor: str | None = None) -> dict:
        return self._get("/v1/scopes", {
            "query": query, "query_field": query_field, "limit": limit, "cursor": cursor,
        })

    # ---- Atomic Memory ----
    def remember(self, scope_id: str, kind: str, text: str, reason: str | None = None) -> dict:
        """写入一条显式 Memory，返回 AtomicMemoryRecord。"""
        payload = {"scope_id": scope_id, "kind": kind, "text": text}
        if reason:
            payload["reason"] = reason
        resp = self._post("/v1/memory/remember", payload)
        records = resp.get("records") or []
        if not records:
            raise PowerContextError(f"remember 未返回记录: {resp}")
        return records[0]

    def list_atomic_memories(self, scope_id: str, kind: str | None = None,
                             states: list[str] | None = None, limit: int = 100,
                             cursor: str | None = None) -> dict:
        payload: dict = {"scope_id": scope_id, "limit": limit}
        if kind:
            payload["kind"] = kind
        if states:
            payload["states"] = states
        if cursor:
            payload["cursor"] = cursor
        return self._post("/v1/atomic-memory/list", payload)

    def list_all_atomic_memories(self, scope_id: str, kind: str | None = None,
                                 states: list[str] | None = None) -> list[dict]:
        items: list[dict] = []
        cursor = None
        while True:
            page = self.list_atomic_memories(scope_id, kind=kind, states=states, cursor=cursor)
            items.extend(page.get("items", []))
            cursor = page.get("next_cursor")
            if not cursor:
                return items

    def get_artifact(self, scope_id: str, artifact_id: str, family: str = ATOMIC_FAMILY) -> tuple[dict, str]:
        """返回 (ArtifactRevision, ETag)。ETag 用于 If-Match 条件写。"""
        path = f"/v1/scopes/{urllib.parse.quote(scope_id, safe='')}/artifacts/{family}/{artifact_id}"
        body, headers = self._request("GET", path, want_headers=True)
        etag = headers.get("etag")
        if not etag:
            raise PowerContextError(f"GET {path} 未返回 ETag")
        return body, etag

    def replace_atomic_memory(self, scope_id: str, artifact_id: str, kind: str, text: str,
                              if_match: str) -> dict:
        """以 If-Match 条件写提交完整新 Revision，返回 ArtifactRevision。"""
        path = f"/v1/scopes/{urllib.parse.quote(scope_id, safe='')}/artifacts/{ATOMIC_FAMILY}/{artifact_id}"
        return self._request("PUT", path, payload={
            "content": {"schema": ATOMIC_SCHEMA, "kind": kind, "text": text},
        }, headers={"If-Match": if_match})

    def get_atomic_state(self, scope_id: str, artifact_id: str) -> dict:
        path = (f"/v1/scopes/{urllib.parse.quote(scope_id, safe='')}"
                f"/artifacts/{ATOMIC_FAMILY}/{artifact_id}/state")
        return self._get(path)

    def forget_atomic_memory(self, scope_id: str, artifact: dict, state_version: int) -> dict:
        """生命周期操作：forgotten（应用层“删除”）。"""
        return self._post("/v1/atomic-memory/lifecycle", {
            "scope_id": scope_id,
            "target": {"artifact": artifact, "state_version": state_version},
            "state": "forgotten",
        })

    def search_memory(self, scope_id: str, query: str, limit: int = 10) -> dict:
        return self._post("/v1/memory/search", {"scope_id": scope_id, "query": query, "limit": limit})

    # ---- Source ----
    def capture_content_source(self, scope_id: str, source_id: str, content: str,
                               metadata: dict | None = None) -> dict:
        payload = {"scope_id": scope_id, "source_id": source_id, "content": content}
        if metadata:
            payload["metadata"] = metadata
        return self._post("/v1/sources/content", payload)

    # ---- Context ----
    def prepare_context(self, scope_id: str, query: str, max_bytes: int = 4000) -> dict:
        return self._post("/v1/context/prepare", {
            "scope_id": scope_id, "query": query, "max_bytes": max_bytes,
        })