"""学习回顾台 Web 服务（Python 标准库 http.server）。

- 静态前端：app/static/
- JSON API：/api/*，全部业务读写转发到 StudyStore -> PowerContext HTTP API。
- 本进程不落盘任何业务状态；重启后从 PowerContext 恢复。

环境变量：
- STUDY_REVIEW_PC_URL   PowerContext Server 地址（默认 http://127.0.0.1:18080）
- STUDY_REVIEW_PC_TOKEN 可选 Bearer Token（默认无，loopback 免认证）
- STUDY_REVIEW_HOST     应用监听地址（默认 127.0.0.1）
- STUDY_REVIEW_PORT     应用端口（默认 18081）
- STUDY_REVIEW_AUDIT    审计日志路径（默认 runtime/audit.jsonl）
- STUDY_REVIEW_FIXED_NOW 可选固定时钟（ISO8601，仅用于可复现演示/测试）
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import rules
from .models import AppState, Preference
from .powercontext_client import PowerContextClient, PowerContextError
from .store import NotFoundError, StudyStore

STATIC_DIR = Path(__file__).resolve().parent / "static"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def build_store() -> tuple[StudyStore, str]:
    pc_url = os.environ.get("STUDY_REVIEW_PC_URL", "http://127.0.0.1:18080")
    token = os.environ.get("STUDY_REVIEW_PC_TOKEN") or None
    audit = os.environ.get("STUDY_REVIEW_AUDIT", str(PROJECT_ROOT / "runtime" / "audit.jsonl"))
    client = PowerContextClient(pc_url, token=token, audit_path=audit)
    fixed_now = os.environ.get("STUDY_REVIEW_FIXED_NOW")
    if fixed_now:
        frozen = rules.parse_dt(fixed_now)
        clock = lambda: frozen  # noqa: E731
    else:
        clock = rules.utcnow
    store = StudyStore(client, clock=clock)
    app_scope_id = store.ensure_app_scope()
    return store, app_scope_id


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Handler(BaseHTTPRequestHandler):
    server_version = "StudyReview/1.0"
    store: StudyStore
    app_scope_id: str

    def log_message(self, fmt, *args):
        pass

    # ---- 工具 ----
    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > 1_000_000:
            raise ApiError(413, "请求体过大")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ApiError(400, "请求体必须是 JSON")
        if not isinstance(data, dict):
            raise ApiError(400, "请求体必须是 JSON 对象")
        return data

    def _query(self) -> dict:
        parsed = urllib.parse.urlparse(self.path)
        return {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}

    def _learner_scope(self, query: dict) -> str:
        scope_id = query.get("learner")
        if not scope_id:
            raise ApiError(400, "缺少 learner 参数")
        self.store.get_learner(scope_id)
        return scope_id

    # ---- 路由 ----
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path.startswith("/api/"):
                self._handle_api("GET", path, self._query())
            else:
                self._serve_static(path)
        except ApiError as e:
            self._send_json(e.status, {"error": e.message})
        except NotFoundError as e:
            self._send_json(404, {"error": str(e)})
        except (ValueError, KeyError) as e:
            self._send_json(400, {"error": str(e)})
        except PowerContextError as e:
            self._send_json(502, {"error": f"PowerContext 调用失败: {e}"})

    def do_POST(self):
        self._mutate("POST")

    def do_PUT(self):
        self._mutate("PUT")

    def do_DELETE(self):
        self._mutate("DELETE")

    def _mutate(self, method: str):
        parsed = urllib.parse.urlparse(self.path)
        try:
            if not parsed.path.startswith("/api/"):
                raise ApiError(404, "未知路径")
            self._handle_api(method, parsed.path, self._query())
        except ApiError as e:
            self._send_json(e.status, {"error": e.message})
        except NotFoundError as e:
            self._send_json(404, {"error": str(e)})
        except (ValueError, KeyError) as e:
            self._send_json(400, {"error": str(e)})
        except PowerContextError as e:
            self._send_json(502, {"error": f"PowerContext 调用失败: {e}"})

    def _handle_api(self, method: str, path: str, query: dict):
        store = self.store
        if path == "/api/health" and method == "GET":
            pc_ok = True
            try:
                store.client.health_ready()
            except PowerContextError:
                pc_ok = False
            self._send_json(200, {"app": "ok", "powercontext": pc_ok,
                                  "fixed_now": os.environ.get("STUDY_REVIEW_FIXED_NOW")})
            return
        if path == "/api/rules" and method == "GET":
            self._send_json(200, rules.rules_document())
            return
        if path == "/api/learners":
            if method == "GET":
                learners = store.list_learners()
                self._send_json(200, {"learners": [
                    {"scope_id": l.scope_id, "name": l.name} for l in learners]})
                return
            if method == "POST":
                body = self._read_body()
                learner = store.create_learner(str(body.get("name", "")))
                state = store.get_app_state(self.app_scope_id)
                if state.selected_learner_scope_id is None:
                    store.set_app_state(self.app_scope_id, AppState(selected_learner_scope_id=learner.scope_id))
                self._send_json(201, {"scope_id": learner.scope_id, "name": learner.name})
                return
        if path == "/api/state":
            if method == "GET":
                state = store.get_app_state(self.app_scope_id)
                self._send_json(200, state.to_payload())
                return
            if method == "PUT":
                body = self._read_body()
                scope_id = body.get("selected_learner_scope_id")
                if scope_id:
                    store.get_learner(scope_id)
                state = store.set_app_state(self.app_scope_id,
                                            AppState(selected_learner_scope_id=scope_id))
                self._send_json(200, state.to_payload())
                return
        if path == "/api/overview" and method == "GET":
            scope_id = self._learner_scope(query)
            self._send_json(200, store.overview(scope_id))
            return
        if path == "/api/kps":
            scope_id = self._learner_scope(query)
            if method == "GET":
                kps = store.list_kps(scope_id)
                self._send_json(200, {"kps": [kp.to_payload() for kp in kps]})
                return
            if method == "POST":
                body = self._read_body()
                kp = store.add_kp(scope_id, str(body.get("course", "")), str(body.get("title", "")),
                                  str(body.get("notes", "")), int(body.get("mastery", 0)))
                self._send_json(201, kp.to_payload())
                return
        if path == "/api/kp":
            scope_id = self._learner_scope(query)
            kp_id = query.get("kp_id")
            if not kp_id:
                raise ApiError(400, "缺少 kp_id")
            if method == "PUT":
                body = self._read_body()
                mastery = body.get("mastery")
                kp = store.update_kp(
                    scope_id, kp_id,
                    course=body.get("course"), title=body.get("title"), notes=body.get("notes"),
                    mastery=int(mastery) if mastery is not None else None)
                self._send_json(200, kp.to_payload())
                return
            if method == "DELETE":
                store.delete_kp(scope_id, kp_id)
                self._send_json(200, {"deleted": kp_id})
                return
        if path == "/api/review" and method == "POST":
            scope_id = self._learner_scope(query)
            body = self._read_body()
            kp, record = store.complete_review(scope_id, str(body.get("kp_id", "")),
                                               str(body.get("result", "")), str(body.get("note", "")))
            self._send_json(200, {"kp": kp.to_payload(), "record": record.to_payload()})
            return
        if path == "/api/records" and method == "GET":
            scope_id = self._learner_scope(query)
            records = store.list_records(scope_id, kp_id=query.get("kp_id"))
            self._send_json(200, {"records": [r.to_payload() for r in records]})
            return
        if path == "/api/prefs":
            scope_id = self._learner_scope(query)
            if method == "GET":
                prefs = store.get_prefs(scope_id) or Preference()
                self._send_json(200, prefs.to_payload())
                return
            if method == "PUT":
                body = self._read_body()
                current = store.get_prefs(scope_id) or Preference()
                prefs = Preference(
                    daily_goal=int(body.get("daily_goal", current.daily_goal)),
                    show_upcoming=bool(body.get("show_upcoming", current.show_upcoming)),
                    upcoming_horizon_days=int(body.get("upcoming_horizon_days", current.upcoming_horizon_days)),
                )
                prefs = store.set_prefs(scope_id, prefs)
                self._send_json(200, prefs.to_payload())
                return
        raise ApiError(404, f"未知 API: {method} {path}")

    # ---- 静态文件 ----
    def _serve_static(self, path: str):
        if path in ("/", ""):
            path = "/index.html"
        rel = path.lstrip("/")
        target = (STATIC_DIR / rel).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            self._send_json(404, {"error": "not found"})
            return
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
        }.get(target.suffix, "application/octet-stream")
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    host = os.environ.get("STUDY_REVIEW_HOST", "127.0.0.1")
    port = int(os.environ.get("STUDY_REVIEW_PORT", "18081"))
    store, app_scope_id = build_store()
    state = store.get_app_state(app_scope_id)
    Handler.store = store
    Handler.app_scope_id = app_scope_id
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"[study-review] 学习回顾台: http://{host}:{port}", flush=True)
    print(f"[study-review] PowerContext: {store.client.base_url}  app_scope={app_scope_id}", flush=True)
    print(f"[study-review] 恢复的当前学习者: {state.selected_learner_scope_id or '（未选择）'}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0