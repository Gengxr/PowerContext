"""MiniMax OpenAI-compatible HTTP adapter; retain public final output only."""
import ast
import json
import os
from urllib.parse import urlparse
import httpx
from dotenv import load_dotenv

def generate(context):
    load_dotenv(".env", override=False)
    key = os.environ.get("MINIMAX_API_KEY", "")
    if not key or key == "replace-locally":
        raise RuntimeError("Missing MINIMAX_API_KEY; no model evidence can be produced.")
    base = os.environ.get("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1").rstrip("/")
    if urlparse(base).scheme != "https" or urlparse(base).hostname not in {
        "api.minimaxi.com", "api.minimax.io"}:
        raise ValueError("Use an official MiniMax HTTPS endpoint")
    request = {"model":os.environ.get("MINIMAX_MODEL","MiniMax-M2.5"),
               "messages":[
                   {"role":"system","content":(
                       "Modify only tickets.py according to the supplied engineering context. "
                       "Return only a JSON object with key code containing the complete Python file. "
                       "Do not change tests or data. Do not return reasoning. No imports, file I/O, "
                       "network, eval, exec or extra top-level statements. Define only list_tickets.")},
                   {"role":"user","content":json.dumps(context,ensure_ascii=False)}],
               "temperature":0.0,"max_tokens":4096}
    with httpx.Client(timeout=180) as client:
        response=client.post(base+"/chat/completions",
                             headers={"Authorization":"Bearer "+key},json=request)
        response.raise_for_status()
        data=response.json()
    if data.get("base_resp",{}).get("status_code",0) != 0:
        raise RuntimeError("MiniMax rejected request: " + str(data["base_resp"].get("status_code")))
    choice=data["choices"][0]
    if choice.get("finish_reason") not in ("stop",None):
        raise RuntimeError("Incomplete model generation")
    content=choice["message"]["content"].strip()
    if content.startswith("```"):
        content=content.split("\n",1)[1].rsplit("```",1)[0].strip()
    code=json.loads(content)["code"]
    tree=ast.parse(code)
    funcs=[node for node in tree.body if isinstance(node,ast.FunctionDef)]
    if len(funcs)!=1 or funcs[0].name!="list_tickets" or len(tree.body)!=1 or funcs[0].decorator_list:
        raise ValueError("Model must return only list_tickets")
    forbidden={"eval","exec","compile","open","__import__","getattr","setattr","globals","locals"}
    for node in ast.walk(tree):
        if isinstance(node,(ast.Import,ast.ImportFrom)) or (
            isinstance(node,ast.Name) and node.id in forbidden) or (
            isinstance(node,ast.Attribute) and node.attr.startswith("__")):
            raise ValueError("Rejected unexpected code operation")
    return code, {"provider":"MiniMax","endpoint":base+"/chat/completions",
                  "request":request,"response_id":data.get("id"),
                  "model":data.get("model",request["model"]),"usage":data.get("usage"),
                  "finish_reason":choice.get("finish_reason"),
                  "final_content":content,
                  "note":"Only public final content retained; reasoning fields intentionally excluded."}
