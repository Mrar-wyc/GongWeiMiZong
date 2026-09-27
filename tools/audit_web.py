"""跨前端一致性门禁：同一串动作，两边逐步比对存档与选项表。

为什么需要这道门禁
------------------
项目有两个前端（终端 TUI 与网页），引擎也就有两份实现：`gongwei/game/engine.py`
与 `web/src/game.js`。剧本数据只有一份（由 `gongwei/web/pack.py` 导出，条件以
AST 形式带上），所以「内容会不会漂移」不用怕；真正会漂的是**算法**——
选项怎么筛、效果怎么落、档案怎么收、结局怎么裁。

这个脚本把同一串动作分别喂给两边，逐步比对：
  * 存档（`GameState.to_save()` 与 JS 的 `toSave()`，逐字相同）
  * 选项表（序号 / 标签 / 是否可用 / 被锁时的提示语）

用法::

    python tools/audit_web.py                 # 跑内置的几条路线
    python tools/audit_web.py --steps 步1 步2 # 比对一条自定义路线
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gongwei.autoplay import (  # noqa: E402
    CASE2_ACT6, CASE2_HEAD, CASE2_SHORT_HEAD, CASE3_ACT9, CASE3_ENTRY,
    CASE3_HEAD, CASE3_ROUTE, EVERYTHING_ROUTE, OPENING_ROUTE, WalkError,
    resolve,
)
from gongwei.data.story import TOPIC_GATES, build_content  # noqa: E402
from gongwei.game import GameEngine  # noqa: E402
from gongwei.web.pack import content_pack  # noqa: E402

DRIVER = os.path.join(ROOT, "web", "src", "driver.js")


def canon(value: Any) -> str:
    """与 JS 侧 `JSON.stringify(sortDeep(...))` 逐字对齐的规范化 JSON。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def option_table(engine: GameEngine) -> List[List[Any]]:
    return [[o.index, o.label, o.enabled, o.hint] for o in engine.options()]


def snapshot(engine: GameEngine) -> Dict[str, Any]:
    """`engine.save()` 的原样（`{"v", "state"}`）—— 这就是跨端共用的存档形状。

    注意 `SaveStore.save()` 另外补的 `title` / `stamp`（写盘时间）不进比对：
    那不是引擎状态，逐字比它只会比出「两台机器时间不同」。
    """
    payload = engine.save()
    return {"v": payload["v"], "state": payload["state"]}


def run_python(engine: GameEngine, steps: List[str]) -> List[Tuple[str, str]]:
    """走一遍并逐步记录 `(存档 JSON, 选项表 JSON)`；解析失败就抛 WalkError。"""
    rows: List[Tuple[str, str]] = []
    for step in steps:
        chosen = resolve(engine, step)
        if chosen is not None:
            chosen.action()
            if engine.at_verdict() and not engine.state.ending:
                engine.finalize()
        rows.append((canon(snapshot(engine)), canon(option_table(engine))))
    return rows


def run_js(pack_json: str, steps: List[str]) -> Tuple[List[Tuple[str, str]], str]:
    """起 node 跑 JS 引擎，返回逐步记录与（可能的）错误文本。"""
    with tempfile.TemporaryDirectory() as tmp:
        pack_path = os.path.join(tmp, "pack.json")
        script_path = os.path.join(tmp, "script.json")
        with open(pack_path, "w", encoding="utf-8") as fh:
            fh.write(pack_json)
        with open(script_path, "w", encoding="utf-8") as fh:
            json.dump({"steps": steps}, fh, ensure_ascii=False)
        proc = subprocess.run(
            ["node", DRIVER, pack_path, script_path],
            capture_output=True, text=True, encoding="utf-8", cwd=ROOT,
        )
    if proc.returncode != 0:
        raw = (proc.stderr or proc.stdout or "").strip()
        # 驱动把失败印成 `ERROR <步号> <消息>`；消息本身要拿来与 Python 侧逐字比，
        # 所以步号单独带出去，不掺进消息里。
        line = raw.splitlines()[-1] if raw else ""
        if line.startswith("ERROR "):
            parts = line.split(" ", 2)
            return [], (parts[2] if len(parts) > 2 else line), (parts[1] if len(parts) > 1 else "?")
        return [], (raw or f"驱动退出码 {proc.returncode}"), "?"
    rows: List[Tuple[str, str]] = []
    for line in proc.stdout.splitlines():
        if not line or line.startswith("PACK\t") or line.startswith("DONE\t"):
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            return [], f"驱动输出无法解析：{line[:120]}", "?"
        rows.append((parts[1], parts[2]))
    return rows, "", ""


def first_diff(a: str, b: str) -> str:
    """指出两串规范化 JSON 第一处不同（按顶层字段定位，便于读）。"""
    if a == b:
        return ""
    try:
        da, db = json.loads(a), json.loads(b)
    except ValueError:
        return "（无法解析，直接给前 200 字）\n  py: " + a[:200] + "\n  js: " + b[:200]
    if isinstance(da, dict) and isinstance(db, dict):
        keys = sorted(set(da) | set(db))
        for key in keys:
            if canon(da.get(key)) != canon(db.get(key)):
                left = canon(da.get(key))
                right = canon(db.get(key))
                cut = next((i for i, (x, y) in enumerate(zip(left, right)) if x != y),
                           min(len(left), len(right)))
                lo = max(0, cut - 60)
                return (f"字段 {key} 不同：\n"
                        f"  py: …{left[lo:cut + 90]}\n"
                        f"  js: …{right[lo:cut + 90]}")
    return "整体不同：\n  py: " + a[:200] + "\n  js: " + b[:200]


#: 内置路线。都是玩家真能走到的走法，覆盖：勘验、阅档、问询、出示、判决、结局。
#: 第三项是 `expect`：``"ok"`` 要求两边都走通且逐步一致，
#: ``"error"`` 要求两边**都在同一步报同一句话**（负例同样要一致）。
def builtin_routes() -> List[Tuple[str, List[str], str]]:
    door = list(OPENING_ROUTE)
    return [
        ("开局四处勘验后收手",
         ["俯身验尸", "细查门窗", "查看茶与香炉", "翻检塌上枕下"], "ok"),
        ("第一幕门槛（顺序读档）", door, "ok"),
        ("只敲档号、不扫现场",
         ["#01-FY-XFE", "#01-FY-XFE-2", "#01-FY-DOR", "#01-FY-CEN"], "ok"),
        ("自拼档号看补遗", ["#01-FY-XFE-2"], "ok"),
        ("打开档目里的第一份", ["#01-DL-SMB"], "ok"),
        ("重读同一份档案", ["#01-DL-SMB", "#01-DL-SMB"], "ok"),
        ("对质王德海（三问后告退）", door + [
            "传唤 · 太监总管王德海", "再问一遍 · 今夜你几时进的殿",
            "追问 · 那盏茶是谁送进去的", "逼问 · 你进过殿内",
            "作揖告退 · 结束对「王德海」的问询",
        ], "ok"),
        ("对质小顺子（四问）", door + [
            "传唤 · 御膳房小监小顺子", "轻声问 · 今夜的茶是你送的吗",
            "问他 · 你在殿后做什么", "问 · 今夜戌时谁被遣退了",
            "把采薇的名字念给他听", "作揖告退 · 结束对「小顺子」的问询",
        ], "ok"),
        ("求见皇后（三问）", door + [
            "求见 · 中宫皇后萧氏", "直问 · 戌时三刻您在凤仪殿",
            "问她 · 太子之死与您有什么关系", "问她 · 本官该报谁的名字",
            "作揖告退 · 结束对「皇后萧氏」的问询",
        ], "ok"),
        ("求见贵妃（两问）", door + [
            "求见 · 贵妃柳氏", "问 · 您送的那碗汤", "问她 · 您手里的安胎药",
            "作揖告退 · 结束对「贵妃柳氏」的问询",
        ], "ok"),
        ("御前问话", door + [
            "求见 · 皇帝萧衍", "问 · 陛下想听什么", "问 · 娘娘走的时候疼不疼",
            "作揖告退 · 结束对「皇帝萧衍」的问询",
        ], "ok"),
        ("指认 · 太监总管", door + [
            "整理证物 · 提笔结案", "「凶手是 —— 太监总管 王德海」"], "ok"),
        ("指认 · 中宫皇后", door + [
            "整理证物 · 提笔结案", "「凶手是 —— 中宫皇后 萧氏」"], "ok"),
        ("指认 · 陛下", door + [
            "整理证物 · 提笔结案", "「凶手是 —— 陛下」"], "ok"),
        ("结案 · 暂无确证", door + [
            "整理证物 · 提笔结案", "「此案 —— 暂无确证，臣请再查」"], "ok"),
        ("结案 · 辞官", door + [
            "整理证物 · 提笔结案", "「臣 —— 验得出来，但臣不说。」"], "ok"),
        ("负例 · 未读全格目就想移步侧殿", ["俯身验尸", "移步侧殿"], "error"),
        ("负例 · 敲一个剧本里没有的档号", ["#01-FY-XXX"], "error"),
        ("负例 · 读一份 requires 未满足的档案", ["#01-FY-END"], "error"),
        # 案②（第六~八幕）：勘验、阅档、问询、指认、结局全都要过一遍。
        ("案② · 第六幕药库勘验到手", CASE2_HEAD + CASE2_ACT6, "ok"),
        ("案② · 指认掌局（短走法）",
         CASE2_SHORT_HEAD + ["「凶手是 —— 尚药局掌局"], "ok"),
        ("案② · 两案连打（满核心线索）", EVERYTHING_ROUTE, "ok"),
        ("负例 · 案② 没读总录就想进前厅",
         CASE2_HEAD + ["推门进去", "移步 · 药局前厅"], "error"),
        # 案③（第九~十一幕）：三案连打、经卷阁勘验、指认、结局。
        ("案③ · 第九幕经卷阁勘验到手",
         CASE3_HEAD + [CASE3_ENTRY] + CASE3_ACT9, "ok"),
        ("案③ · 指认冯保（原页 · 上上）",
         CASE3_ROUTE + ["「凶手是 —— 内官监少监 冯保」"], "ok"),
        ("案③ · 三案连打（满核心线索）",
         CASE3_ROUTE + ["「这三桩案子"], "ok"),
        ("负例 · 案③ 没读总录就想问人",
         CASE3_HEAD + [CASE3_ENTRY] + ["推门进去", "移步 · 阁前问人"], "error"),
    ]


def compare(name: str, steps: List[str], expect: str, pack_json: str,
            verbose: bool) -> bool:
    content = build_content()
    engine = GameEngine(content, gates=TOPIC_GATES)
    py_error = ""
    try:
        py_rows = run_python(engine, steps)
    except WalkError as exc:
        py_rows, py_error = [], str(exc)
    except Exception as exc:                     # noqa: BLE001 - 报出来比崩掉有用
        print(f"✗ {name}：Python 侧异常 —— {type(exc).__name__}: {exc}")
        return False

    js_rows, js_error, js_step = run_js(pack_json, steps)

    if expect == "error":
        if not py_error:
            print(f"✗ {name}：本该被拦住，Python 侧却走通了")
            return False
        if not js_error:
            print(f"✗ {name}：本该被拦住，JS 侧却走通了")
            return False
        if py_error != js_error:
            print(f"✗ {name}：两边报错不同\n  py: {py_error}\n  js: {js_error}")
            return False
        print(f"✓ {name}：两端同报（第 {js_step} 步）—— {py_error}")
        return True

    if py_error:
        print(f"✗ {name}：Python 侧走不通 —— {py_error}")
        return False
    if js_error:
        print(f"✗ {name}：JS 侧报错 —— {js_error}")
        return False
    if len(js_rows) != len(py_rows):
        print(f"✗ {name}：步数不一致 py={len(py_rows)} js={len(js_rows)}")
        return False
    for i, (py_row, js_row) in enumerate(zip(py_rows, js_rows), 1):
        if py_row[0] != js_row[0]:
            print(f"✗ {name} 第 {i} 步「{steps[i - 1]}」存档不同：")
            print("  " + first_diff(py_row[0], js_row[0]).replace("\n", "\n  "))
            return False
        if py_row[1] != js_row[1]:
            print(f"✗ {name} 第 {i} 步「{steps[i - 1]}」选项表不同：")
            print("  " + first_diff(py_row[1], js_row[1]).replace("\n", "\n  "))
            return False
    tail = f"第 {len(steps)} 步后场景 {engine.state.scene}"
    if engine.state.ending:
        tail += f" / 结局 {engine.state.ending}"
    print(f"✓ {name}（{len(steps)} 步）：{tail}")
    if verbose:
        print(f"  存档 {len(py_rows[-1][0])} 字节，选项 {len(json.loads(py_rows[-1][1]))} 项")
    return True


def main(argv: List[str]) -> int:
    verbose = "--verbose" in argv or "-v" in argv
    argv = [a for a in argv if a not in ("--verbose", "-v")]
    steps: Optional[List[str]] = None
    if "--steps" in argv:
        idx = argv.index("--steps")
        steps = argv[idx + 1:]
    if not os.path.exists(DRIVER):
        print(f"找不到驱动 {DRIVER}")
        return 2

    content = build_content()
    pack_json = json.dumps(content_pack(content, TOPIC_GATES), ensure_ascii=False,
                           sort_keys=True, separators=(",", ":"))
    print(f"内容包 {len(pack_json.encode('utf-8'))} 字节 · "
          f"{len(content.dossiers)} 份档案 · {len(content.scenes)} 个场景 · "
          f"{len(content.endings)} 个结局")

    routes = [("自定义路线", steps, "ok")] if steps else builtin_routes()
    ok = True
    for name, route, expect in routes:
        if not route:
            continue
        ok = compare(name, route, expect, pack_json, verbose) and ok
    if ok:
        print("✓ 两端逐步一致：存档与选项表逐字相同，连报错都一致")
        return 0
    print("✗ 两端存在分歧（见上）")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
