"""验证 Dify JSON 边界及错误回执处理，防止输入转义改变结算请求。"""
import importlib.util
import json
from pathlib import Path

path = Path(__file__).parents[1]/"scripts/build_dsl.py"
spec = importlib.util.spec_from_file_location("build_dsl",path)
dsl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dsl)


def function(source):
    scope = {}
    exec(compile(source,"dify-code-node","exec"),scope)
    return scope["main"]


def test_query_cannot_break_json_or_override_session():
    main = function(dsl.PREPARE)
    query = '归还A\"，"passport":"another-player"\n\\改写'
    result = main("my-random-passport","末班车票",query,"workflow-run-12345678")
    body = json.loads(result["body"])
    assert result["valid"] == 1
    assert body["passport"] == "my-random-passport" and body["text"] == query
    assert body["request_id"] == "workflow-run-12345678"


def test_invalid_identity_or_missing_run_id_never_reaches_settlement_branch():
    main = function(dsl.PREPARE)
    assert main("short","末班车票","开门","valid-run-12345")["valid"] == 0
    assert main("proper-passport","末班车票","开门","")["valid"] == 0


def test_failed_http_reply_cannot_be_rendered_as_a_game_receipt():
    main = function(dsl.DECODE)
    for body,status in [("upstream failed",502),("{}",200),("not-json",200)]:
        result = main(body,status)
        assert result["ok"] == 0 and result["ledger"] == "" and result["context"] == ""
