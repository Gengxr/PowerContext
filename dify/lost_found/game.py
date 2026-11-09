"""剧情状态机。模型只能叙述，不能修改证据、归属或结局判定。"""
from copy import deepcopy


def initial_state():
    return {"opened": False, "timeline": 0, "coins": 4, "clues": {},
            "finished": False, "ending": None, "turn": 0}


def command(text):
    text = text.strip()
    for prefix in ("查验", "查看", "检查", "线索"):
        if text.startswith(prefix):
            target = text[len(prefix):].strip()
            return "inspect", target
    for prefix in ("归还", "认领", "交给"):
        if text.startswith(prefix):
            return "return", text[len(prefix):].strip()
    aliases = {
        "开门": "open", "开始": "open", "接件": "open",
        "状态": "status", "档案": "status", "回执": "status",
        "改写": "rewrite", "拨动": "rewrite",
        "封存": "archive", "帮助": "help", "玩法": "help",
    }
    return aliases.get(text, "invalid"), ""


def transition(before, case, user_text):
    state = deepcopy(before)
    action, target = command(user_text)
    changed, message = False, ""
    version = case["versions"][state["timeline"]]
    if action in ("help", "invalid"):
        message = ("可输入：开门、查验1、查验2、查验3、改写、归还A/B/C、状态、封存。"
                   "查验新线索花一枚明日币；改写只有一次，旧线索保留为历史，当前时间线重新获得两枚币。"
                   "归还或封存将结束本件失物。换一个通行证可开始独立档案。")
    elif action == "status":
        message = "已从档案柜取回当前记录。相同通行证在新会话中也可找回这份档案。"
    elif state["finished"]:
        message = "本件失物已经结案。可输入状态查阅原结局，或用新的通行证开一份独立档案。"
    elif action == "open":
        if state["opened"]:
            message = "柜台上仍是同一件失物，已查验的线索不会被重置。"
        else:
            state["opened"], changed = True, True
            message = case["opening"]
    elif not state["opened"]:
        message = "先输入开门，领取柜台上的失物。"
    elif action == "inspect":
        if target not in ("1", "2", "3"):
            message = "线索编号只能是1、2或3，本次没有消耗明日币。"
        else:
            key = f'{state["timeline"]}:{target}'
            if key in state["clues"]:
                message = "再次查看同一条线索，不额外消耗明日币。"
            elif state["coins"] == 0:
                message = "明日币已用完，可依据现有线索归还、封存；尚未改写时也可以选择改写。"
            else:
                state["clues"][key] = version["clues"][int(target)-1]
                state["coins"] -= 1
                changed = True
                message = "新线索已登记。归属只以当前时间线的线索为准。"
    elif action == "rewrite":
        if state["timeline"] == 1:
            message = "每件失物只能改写一次。本次没有改变时间线。"
        else:
            state["timeline"], state["coins"], changed = 1, 2, True
            message = (f'你选择{case["rewrite"]}。旧线索仍保留在档案中，但不再代表当前未来。'
                       "柜台重新发放两枚明日币，请重新核验线索。")
    elif action == "return":
        chosen = target.upper()
        if chosen not in case["claimants"]:
            matches = [key for key, name in case["claimants"].items() if target == name]
            chosen = matches[0] if len(matches) == 1 else ""
        if not chosen:
            message = "请输入归还A、归还B、归还C，或写出该认领人的完整姓名。"
        else:
            success = chosen == version["owner"]
            state["finished"], changed = True, True
            state["ending"] = {
                "kind": "returned" if success else "misclaimed",
                "chosen": chosen, "correct": version["owner"],
                "text": version["ending"] if success else case["wrong"],
            }
            message = state["ending"]["text"]
    elif action == "archive":
        state["finished"], changed = True, True
        state["ending"] = {"kind": "archived", "text": "失物被封存。你留下了一条尚未决定的未来，这个决定同样会被档案柜记住。"}
        message = state["ending"]["text"]
    if changed:
        state["turn"] += 1
    return state, changed, message


def public_view(state, case, message):
    """不向叙述模型提供未公开的线索、正确失主或未来结局。"""
    return {
        "title": case["title"], "message": message, "claimants": case["claimants"],
        "timeline": state["timeline"], "coins": state["coins"], "turn": state["turn"],
        "clue_names": case["clue_names"],
        "clues": [{"timeline": int(key.split(":")[0]), "number": int(key.split(":")[1]),
                   "text": value, "current": int(key.split(":")[0]) == state["timeline"]}
                  for key, value in state["clues"].items()],
        "finished": state["finished"], "ending": state["ending"],
    }


def ledger(view):
    lines = [
        f'【档案回执】{view["title"]}',
        f'时间线：{view["timeline"]}；明日币：{view["coins"]}；已登记变化：{view["turn"]}次',
        "认领人：" + " / ".join(f"{key} {name}" for key, name in view["claimants"].items()),
        "线索目录：" + " / ".join(f"{i+1} {name}" for i, name in enumerate(view["clue_names"])),
    ]
    for clue in view["clues"]:
        stamp = "当前" if clue["current"] else "旧时间线，仅供历史参考"
        lines.append(f'线索{clue["number"]}〔时间线{clue["timeline"]}，{stamp}〕：{clue["text"]}')
    if view["ending"]:
        ending = view["ending"]
        lines.append("结案：" + ending["text"])
        if "correct" in ending:
            lines.append("本时间线的失主：" + view["claimants"][ending["correct"]])
    lines.append("可用指令：状态 / 帮助" if view["finished"] else
                 "可用指令：开门 / 查验1 / 查验2 / 查验3 / 改写 / 归还A、B、C / 封存 / 状态")
    return "\n".join(lines)
