from contextlib import asynccontextmanager
import hmac
import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .store import Store, RequestConflict


class Turn(BaseModel):
    passport: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    case_id: str = Field(pattern=r"^(ticket|umbrella|echo)$")
    request_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    text: str = Field(min_length=1, max_length=500)


def create_app():
    state = {"store": None, "token": None}

    @asynccontextmanager
    async def lifespan(app):
        token = os.environ.get("LF_API_TOKEN", "")
        if len(token) < 24:
            raise RuntimeError("LF_API_TOKEN须为至少24字符的随机串，不使用默认口令。")
        directory = os.environ.get("LF_DATA_DIR", str(Path.home()/".local/share/tomorrow-lost-found/seekdb"))
        Path(directory).mkdir(parents=True, exist_ok=True)
        state.update(store=Store(directory), token=token)
        yield
        state["store"].close()

    app = FastAPI(title="明日失物招领处", version="1.0.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    def authorize(header):
        supplied = header.removeprefix("Bearer ") if header else ""
        if not state["token"] or not hmac.compare_digest(supplied.encode(), state["token"].encode()):
            raise HTTPException(401, "服务认证失败")

    @app.get("/health")
    def health():
        return {"ok": state["store"] is not None, "service": "tomorrow-lost-found"}

    @app.post("/v1/turn")
    def turn(payload: Turn, authorization: str | None = Header(default=None)):
        authorize(authorization)
        try:
            return state["store"].turn(payload.passport, payload.case_id, payload.request_id, payload.text)
        except RequestConflict as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @app.get("/v1/evidence/{passport}/{case_id}")
    def evidence(passport: str, case_id: str, authorization: str | None = Header(default=None)):
        authorize(authorization)
        if len(passport) > 64 or case_id not in ("ticket", "umbrella", "echo"):
            raise HTTPException(400, "档案编号无效")
        return state["store"].evidence(passport, case_id)

    return app


app = create_app()
