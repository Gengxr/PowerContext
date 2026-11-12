"""pytest 共享夹具：启动真实 PowerContext Server（独立临时 SQLite），固定时钟。

不使用任何 mock 替代 PowerContext：所有集成测试都打到真实服务器进程。
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import rules
from app.powercontext_client import PowerContextClient
from app.store import StudyStore


class ManualClock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_ready(url: str, timeout: float = 180.0) -> None:
    deadline = time.monotonic() + timeout
    last_err = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + "/health/ready", timeout=3) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, OSError) as e:
            last_err = e
        time.sleep(1.0)
    raise RuntimeError(f"PowerContext Server 未在 {timeout}s 内就绪: {last_err}")


@pytest.fixture(scope="session")
def pc_server(tmp_path_factory):
    """会话级真实 PowerContext Server 子进程（临时 SQLite，独立 POWERCONTEXT_HOME）。"""
    base = tmp_path_factory.mktemp("pc-server")
    home = base / "home"
    home.mkdir()
    port = _free_port()
    db_url = "sqlite+aiosqlite:///" + str(base / "powercontext.db").replace("\\", "/")
    env_file = base / "pc.env"
    env_file.write_text(
        "\n".join([
            "POWERCONTEXT_SERVER_HTTP_HOST=127.0.0.1",
            f"POWERCONTEXT_SERVER_HTTP_PORT={port}",
            "POWERCONTEXT_SERVER_DATABASE_KIND=sqlite",
            f"POWERCONTEXT_SERVER_DATABASE_URL={db_url}",
            "POWERCONTEXT_SERVER_ACCESS_MODE=disabled",
            "POWERCONTEXT_SERVER_DASHBOARD_ENABLED=false",
            "POWERCONTEXT_SERVER_LOGGING_LEVEL=WARNING",
            "",
        ]),
        encoding="utf-8",
    )
    exe = Path(sys.executable).parent / ("powercontext.exe" if os.name == "nt" else "powercontext")
    assert exe.exists(), f"未找到 powercontext CLI: {exe}"
    env = dict(os.environ)
    env["POWERCONTEXT_HOME"] = str(home)
    log = (base / "server.log").open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [str(exe), "server", "run", "--env-file", str(env_file)],
        stdout=log, stderr=subprocess.STDOUT, env=env, cwd=str(base),
    )
    url = f"http://127.0.0.1:{port}"
    try:
        _wait_ready(url)
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


@pytest.fixture()
def pc_client(pc_server, tmp_path):
    return PowerContextClient(pc_server, audit_path=tmp_path / "audit.jsonl")


@pytest.fixture()
def clock():
    return ManualClock(rules.parse_dt("2026-11-08T09:00:00Z"))


@pytest.fixture()
def store(pc_client, clock):
    return StudyStore(pc_client, clock=clock)


@pytest.fixture()
def unique_name():
    return "测试" + uuid.uuid4().hex[:8]


@pytest.fixture()
def app_server(pc_server, tmp_path):
    """应用 Web 服务子进程（真实进程，用于 API 与跨进程重启测试）。"""
    port = _free_port()
    env = dict(os.environ)
    env.update({
        "STUDY_REVIEW_PC_URL": pc_server,
        "STUDY_REVIEW_HOST": "127.0.0.1",
        "STUDY_REVIEW_PORT": str(port),
        "STUDY_REVIEW_AUDIT": str(tmp_path / "app-audit.jsonl"),
        "PYTHONIOENCODING": "utf-8",
    })
    log = (tmp_path / "app.log").open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "app"],
        stdout=log, stderr=subprocess.STDOUT, env=env, cwd=str(ROOT),
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    ready = False
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=3) as resp:
                if resp.status == 200:
                    ready = True
                    break
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    if not ready:
        proc.kill()
        log.close()
        raise RuntimeError("应用服务未就绪，日志: " + (tmp_path / "app.log").read_text(encoding="utf-8", errors="replace")[-2000:])
    yield {"url": url, "proc": proc, "env": env, "tmp": tmp_path, "log": log}
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    log.close()