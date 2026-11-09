"""真实 seekdb 持久化；请求去重、状态更新和事件回执在同一事务中提交。"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import threading

import pylibseekdb
import pymysql

from .game import initial_state, transition, public_view, ledger


class RequestConflict(ValueError):
    pass


class Store:
    def __init__(self, directory):
        self.runtime = pylibseekdb.open(str(Path(directory).resolve()))
        self.options = self.runtime.connection_options()
        self.lock = threading.Lock()
        with closing(self.connect()) as conn, conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS lf_cases (
                case_id VARCHAR(32) PRIMARY KEY, payload LONGTEXT NOT NULL)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS lf_sessions (
                session_id CHAR(64) PRIMARY KEY, case_id VARCHAR(32) NOT NULL,
                state_json LONGTEXT NOT NULL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ON UPDATE CURRENT_TIMESTAMP)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS lf_requests (
                session_id CHAR(64) NOT NULL, request_id VARCHAR(128) NOT NULL,
                fingerprint CHAR(64) NOT NULL, response_json LONGTEXT NOT NULL,
                PRIMARY KEY (session_id, request_id))""")
            cur.execute("""CREATE TABLE IF NOT EXISTS lf_events (
                session_id CHAR(64) NOT NULL, turn_no INT NOT NULL,
                request_id VARCHAR(128) NOT NULL, event_json LONGTEXT NOT NULL,
                PRIMARY KEY (session_id, turn_no))""")
            cases = json.loads(Path(__file__).with_name("cases.json").read_text(encoding="utf-8"))
            for case in cases:
                encoded = json.dumps(case, ensure_ascii=False, sort_keys=True)
                cur.execute("INSERT IGNORE INTO lf_cases VALUES (%s,%s)", (case["id"], encoded))
                cur.execute("SELECT payload FROM lf_cases WHERE case_id=%s", (case["id"],))
                if cur.fetchone()["payload"] != encoded:
                    raise RuntimeError("剧情定义版本不一致，请使用新数据目录或显式迁移，不能覆盖现有档案。")
            conn.commit()

    def connect(self):
        return pymysql.connect(database="test", autocommit=False, charset="utf8mb4",
                               cursorclass=pymysql.cursors.DictCursor, **self.options)

    def close(self):
        self.runtime.close()

    def health(self):
        with closing(self.connect()) as conn, conn.cursor() as cur:
            cur.execute("SELECT VERSION() AS version")
            version = cur.fetchone()["version"]
            cur.execute("SELECT COUNT(*) AS cases FROM lf_cases")
            return {"engine": "seekdb", "version": version, "cases": cur.fetchone()["cases"]}

    def turn(self, passport, case_id, request_id, text):
        session = hashlib.sha256((passport + "\0" + case_id).encode()).hexdigest()
        fingerprint = hashlib.sha256(text.encode()).hexdigest()
        # 单进程锁限制嵌入实例压力；行锁和主键同时提供数据库层的一致性约束。
        with self.lock, closing(self.connect()) as conn, conn.cursor() as cur:
            try:
                conn.begin()
                cur.execute("SELECT payload FROM lf_cases WHERE case_id=%s", (case_id,))
                row = cur.fetchone()
                if row is None:
                    raise ValueError("未知失物编号")
                case = json.loads(row["payload"])
                cur.execute("INSERT IGNORE INTO lf_sessions(session_id,case_id,state_json) VALUES (%s,%s,%s)",
                            (session, case_id, json.dumps(initial_state())))
                cur.execute("SELECT state_json FROM lf_sessions WHERE session_id=%s FOR UPDATE", (session,))
                state = json.loads(cur.fetchone()["state_json"])
                cur.execute("SELECT fingerprint,response_json FROM lf_requests WHERE session_id=%s AND request_id=%s",
                            (session, request_id))
                saved = cur.fetchone()
                if saved:
                    if saved["fingerprint"] != fingerprint:
                        raise RequestConflict("同一请求编号不能用于不同指令")
                    conn.rollback()
                    return json.loads(saved["response_json"])
                after, changed, message = transition(state, case, text)
                view = public_view(after, case, message)
                response = {"view": view, "ledger": ledger(view),
                            "narration_context": json.dumps(view, ensure_ascii=False),
                            "receipt": {"session": session[:16], "turn": after["turn"],
                                        "timeline": after["timeline"], "request_id": request_id}}
                encoded = json.dumps(response, ensure_ascii=False)
                if changed:
                    cur.execute("UPDATE lf_sessions SET state_json=%s WHERE session_id=%s",
                                (json.dumps(after, ensure_ascii=False), session))
                    cur.execute("INSERT INTO lf_events VALUES (%s,%s,%s,%s)",
                                (session, after["turn"], request_id, encoded))
                cur.execute("INSERT INTO lf_requests VALUES (%s,%s,%s,%s)",
                            (session, request_id, fingerprint, encoded))
                conn.commit()
                return response
            except Exception:
                conn.rollback()
                raise

    def evidence(self, passport, case_id):
        session = hashlib.sha256((passport + "\0" + case_id).encode()).hexdigest()
        with closing(self.connect()) as conn, conn.cursor() as cur:
            cur.execute("SELECT state_json FROM lf_sessions WHERE session_id=%s", (session,))
            row = cur.fetchone()
            cur.execute("SELECT turn_no,request_id,event_json FROM lf_events WHERE session_id=%s ORDER BY turn_no",
                        (session,))
            return {"state": json.loads(row["state_json"]) if row else None,
                    "events": [{"turn": item["turn_no"], "request_id": item["request_id"],
                                "response": json.loads(item["event_json"])} for item in cur.fetchall()],
                    "database": self.health()}
