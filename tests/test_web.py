"""网页端的门禁：内容包完整性、单文件产物、跨端逐步一致。

分三层看：

1. **内容包**（`gongwei/web/pack.py` 的产物）—— 剧本交给网页端的是数据，
   所以每一条判定都必须带上可序列化的 AST；漏一条，网页端就会在某个选项上
   静默地永远放行或永远上锁。
2. **产物**（`tools/build_web.py` 的产物）—— 磁盘上的单文件必须与当前剧本
   一致，内联的 JSON 必须真的能被解析，并且一个外部引用都不能有。
3. **两端一致**（`tools/audit_web.py` 的比对）—— 同一串动作喂给 Python 与
   JS 两个引擎，逐步比对存档与选项表。没有 node 就跳过这一层。
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gongwei.autoplay import OPENING_ROUTE  # noqa: E402
from gongwei.data.story import TOPIC_GATES, build_content  # noqa: E402
from gongwei.web.pack import content_pack, pack_json  # noqa: E402

TOOLS = ROOT / "tools"
SRC = ROOT / "web" / "src"
OUT_HTML = ROOT / "web" / "gongwei-mizong.html"
OUT_PACK = ROOT / "web" / "gongwei-pack.json"

#: JS 侧 `evalAst()` 认得的全部指令。多一条少一条都会在运行时报错，
#: 所以这里当作两端共用的词表钉住。
AST_OPS = {
    "always", "never", "clue", "flag", "dossier", "missing_dossier",
    "dossiers_count", "trust", "clues_count", "items_count", "core_count",
    "clues_count_in", "clues_at_least", "suspect", "suspect_in", "visited",
    "time_at", "all", "any", "not",
}


def load_tool(name: str):
    """把 tools/ 下的脚本当模块载入（共用 ``tests.helpers.load_tool``）。"""
    from .helpers import load_tool as _load_tool

    return _load_tool(name)


def walk_ast(node, path: str, problems: list) -> None:
    """递归检查一棵 AST：op 必须在词表里，子节点也要合法。"""
    if not isinstance(node, list) or not node:
        problems.append(f"{path}: 不是 AST（{node!r}）")
        return
    op = node[0]
    if op not in AST_OPS:
        problems.append(f"{path}: 未知指令 {op!r}")
        return
    if op in ("all", "any"):
        if len(node) != 2 or not isinstance(node[1], list):
            problems.append(f"{path}: {op} 需要一串子条件")
            return
        for i, child in enumerate(node[1]):
            walk_ast(child, f"{path}.{op}[{i}]", problems)
    elif op == "not":
        if len(node) != 2:
            problems.append(f"{path}: not 需要一个子条件")
            return
        walk_ast(node[1], f"{path}.not", problems)
    elif op == "clues_count_in":
        if len(node) != 4 or not isinstance(node[1], list):
            problems.append(f"{path}: clues_count_in 形状不对")
    elif op in ("dossiers_count", "clues_count", "items_count", "core_count"):
        if len(node) != 3:
            problems.append(f"{path}: {op} 需要 (op, 数字)")
    elif op == "trust":
        if len(node) != 4:
            problems.append(f"{path}: trust 需要 (人物, op, 数字)")
    elif op == "clues_at_least":
        if len(node) != 3 or not isinstance(node[1], list):
            problems.append(f"{path}: clues_at_least 形状不对")
    elif op == "suspect_in":
        if len(node) != 2 or not isinstance(node[1], list):
            problems.append(f"{path}: suspect_in 需要一串人物")
    elif op in ("clue", "flag", "dossier", "missing_dossier", "suspect",
                "visited", "time_at"):
        if len(node) != 2:
            problems.append(f"{path}: {op} 需要一个参数")


class ContentPackTest(unittest.TestCase):
    """内容包：剧本交出去的那一份数据必须完整、可解释。"""

    @classmethod
    def setUpClass(cls):
        cls.content = build_content()
        cls.pack = content_pack(cls.content, TOPIC_GATES)

    def test_shape(self):
        for key in ("title", "subtitle", "prologue", "version", "start_scene",
                    "verdict_scene", "interrogate_hall", "verdict_scenes",
                    "verdicts", "time_order", "items", "characters", "scenes",
                    "topics", "endings", "dossiers", "starter_dossiers",
                    "act_titles", "act_numbers", "core_total", "help_sections"):
            self.assertIn(key, self.pack)
        self.assertEqual(len(self.pack["scenes"]), len(self.content.scenes))
        self.assertEqual(len(self.pack["dossiers"]), len(self.content.dossiers))
        self.assertEqual(len(self.pack["endings"]), len(self.content.endings))
        self.assertEqual(self.pack["core_total"], self.content.core_total())
        self.assertTrue(self.pack["dossiers"], "档案不该是空的")

    def test_every_condition_is_an_ast(self):
        """所有条件都必须是 AST —— 漏一条，网页端就会永远放行或永远上锁。"""
        problems: list = []
        for tid, scene in self.pack["scenes"].items():
            for i, ch in enumerate(scene["choices"]):
                base = f"场景 {tid} 选项 {i}「{ch['label']}」"
                for field in ("visible_if", "locked_if"):
                    if ch[field] is not None:
                        walk_ast(ch[field], f"{base}.{field}", problems)
            if scene["on_enter"] is None:
                problems.append(f"场景 {tid}: on_enter 缺字段")
        for tp in self.pack["topics"]:
            if tp["gate"] is not None:
                walk_ast(tp["gate"], f"话题 {tp['id']}.gate", problems)
        for did, d in self.pack["dossiers"].items():
            if d["requires"] is not None:
                walk_ast(d["requires"], f"档案 {did}.requires", problems)
        for e in self.pack["endings"]:
            walk_ast(e["rule"], f"结局 {e['id']}.rule", problems)
        self.assertEqual(problems, [], "\n".join(problems))

    def test_pack_covers_everything_the_engine_can_ask(self):
        """包里的东西与 Python 侧的 Content 逐项对得上。"""
        self.assertEqual(set(self.pack["items"]), set(self.content.items))
        self.assertEqual(set(self.pack["characters"]), set(self.content.characters))
        self.assertEqual(set(self.pack["scenes"]), set(self.content.scenes))
        self.assertEqual(set(self.pack["dossiers"]), set(self.content.dossiers))
        self.assertEqual(set(self.pack["verdict_scenes"]),
                         set(self.content.verdict_scenes))
        for did in self.pack["starter_dossiers"]:
            self.assertIn(did, self.pack["dossiers"])
        for sid in self.pack["verdict_scenes"]:
            self.assertIn(sid, self.pack["scenes"])
        self.assertIn(self.pack["start_scene"], self.pack["scenes"])
        # 判定用的 AST 词表：包里出现过的 op 都必须被测试检查过
        used = set()

        def collect(node):
            """只沿着「条件」这一条线走 —— 参数里的 id 串不是指令。"""
            if not isinstance(node, list) or not node or not isinstance(node[0], str):
                return
            used.add(node[0])
            if node[0] in ("all", "any") and len(node) == 2:
                for child in node[1]:
                    collect(child)
            elif node[0] == "not" and len(node) == 2:
                collect(node[1])
        for scene in self.pack["scenes"].values():
            for ch in scene["choices"]:
                collect(ch["visible_if"])
                collect(ch["locked_if"])
        for tp in self.pack["topics"]:
            collect(tp["gate"])
        for d in self.pack["dossiers"].values():
            collect(d["requires"])
        for e in self.pack["endings"]:
            collect(e["rule"])
        self.assertTrue(used, "剧本里一条条件都没有？")
        self.assertTrue(used <= AST_OPS, f"出现了没登记的指令：{used - AST_OPS}")

    def test_choice_keys_are_stable(self):
        """`key` 是两端记录「做过没有」的唯一凭据，不能空、不能重。"""
        for tid, scene in self.pack["scenes"].items():
            keys = [ch["key"] for ch in scene["choices"]]
            self.assertEqual(len(keys), len(set(keys)), f"场景 {tid} 有重名的 key")
            for key in keys:
                self.assertTrue(key and "::" in key, f"场景 {tid} 的 key 形状可疑：{key!r}")

    def test_js_source_has_no_duplicate_declarations(self):
        """同名函数会被后面那个悄悄顶掉 —— 界面曾经因此整屏空白。"""
        for path in sorted(SRC.glob("*.js")):
            text = path.read_text(encoding="utf-8")
            names = re.findall(r"^\s*function\s+(\w+)\s*\(", text, re.M)
            dupes = {n for n in names if names.count(n) > 1}
            self.assertEqual(dupes, set(), f"{path.name} 里重复声明了：{sorted(dupes)}")


class BuildTest(unittest.TestCase):
    """单文件产物：必须与剧本同步，且真的能离线打开。"""

    @classmethod
    def setUpClass(cls):
        cls.build_web = load_tool("build_web")
        cls.outputs = cls.build_web.build()
        cls.html = cls.outputs[OUT_HTML]

    def test_disk_matches_sources(self):
        """磁盘上的产物不能是旧的（改剧本忘了重新打包，就在这里红）。"""
        for path, text in self.outputs.items():
            rel = path.relative_to(ROOT).as_posix()
            self.assertTrue(path.exists(), f"{rel} 不存在，请运行 python tools/build_web.py")
            self.assertEqual(path.read_text(encoding="utf-8"), text,
                             f"{rel} 与当前剧本不一致，请重新运行 python tools/build_web.py")

    def test_offline_only(self):
        for token in ("http://", "https://", "//cdn.", "src=\"/", "href=\"/"):
            self.assertNotIn(token, self.html.lower(), f"单文件里有外部引用 {token!r}")

    def test_inlined_pack_parses_and_matches(self):
        match = re.search(
            r'<script id="pack" type="application/json">(.*?)</script>',
            self.html, re.S)
        self.assertIsNotNone(match, "单文件里没找到内联的内容包")
        inlined = json.loads(match.group(1))
        expected = json.loads(pack_json(build_content(), TOPIC_GATES))
        self.assertEqual(inlined, expected)

    def test_pack_file_parses(self):
        self.assertTrue(OUT_PACK.exists(), "web/gongwei-pack.json 不存在")
        on_disk = json.loads(OUT_PACK.read_text(encoding="utf-8"))
        self.assertEqual(on_disk, json.loads(pack_json(build_content(), TOPIC_GATES)))

    def test_no_leftover_placeholders(self):
        for marker in ("__PACK__", "__STYLE__", "__GAME_JS__", "__UI_JS__"):
            self.assertNotIn(marker, self.html, f"产物里还留着 {marker}")


@unittest.skipUnless(shutil.which("node"), "没有 node，跳过跨端比对")
class CrossEngineTest(unittest.TestCase):
    """同一串动作，两端逐步比对（存档 + 选项表，连报错都要一致）。"""

    @classmethod
    def setUpClass(cls):
        cls.audit = load_tool("audit_web")
        cls.pack_json = pack_json(build_content(), TOPIC_GATES)

    def _compare(self, name, steps, expect="ok"):
        ok = self.audit.compare(name, steps, expect, self.pack_json, verbose=False)
        self.assertTrue(ok, f"{name}：两端逐步比对不一致")

    def test_opening_and_gate(self):
        self._compare("开局与第一幕门槛", list(OPENING_ROUTE))

    def test_dossier_reads(self):
        self._compare("只敲档号不扫现场",
                      ["#01-FY-XFE", "#01-FY-XFE-2", "#01-FY-XFE"])

    def test_unknown_dossier_errors_identically(self):
        self._compare("敲一个没有的档号", ["#01-FY-XXX"], expect="error")

    def test_locked_dossier_errors_identically(self):
        self._compare("读一份还读不到的档案", ["#01-FY-END"], expect="error")


@unittest.skipUnless(shutil.which("node"), "没有 node，跳过 JS 接口对照")
class UiWiringTest(unittest.TestCase):
    """`ui.js` 调的引擎方法/导出必须真的存在。

    这是终端那边 `self.engine.act_title_of()` 那个事故的 JS 版：写错一个方法名，
    界面在某个少见的路径上抛异常，而单测全绿（因为没人跑到那条路径）。
    这里不跑界面，只把 `ui.js` 里所有 `game.X` / `GAME.X` 抓出来，
    对着真实的 `Game` 实例与模块导出逐个查。
    """

    SCRIPT = """
const fs = require('fs');
const GAME = require(process.argv[2]);
const pack = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const names = JSON.parse(process.argv[4]);
const game = new GAME.Game(pack);
// 既不在 Game 实例上（含原型上的属性/方法）、也不在模块导出里的名字，就是写错了
const missing = names.filter((n) => !(n in game) && GAME[n] === undefined);
console.log(JSON.stringify({missing: missing, game: names.length}));
"""

    def test_ui_only_calls_engine_members_that_exist(self):
        import json
        import subprocess
        import tempfile

        src = (SRC / "ui.js").read_text(encoding="utf-8")
        names = sorted(set(re.findall(r"\bgame\.([A-Za-z_]\w*)", src)))
        self.assertTrue(names, "ui.js 里没找到对 game.* 的调用，检查正则是否失效")
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "wiring.js"
            script.write_text(self.SCRIPT, encoding="utf-8")
            proc = subprocess.run(
                ["node", str(script), str(SRC / "game.js"), str(OUT_PACK),
                 json.dumps(names)],
                capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
        self.assertEqual(0, proc.returncode, proc.stderr)
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual([], result["missing"],
                         "ui.js 调了 game.js 里没有的东西：" + "、".join(result["missing"]))
        self.assertGreater(result["game"], 10, "抓到的接口太少，正则大概失效了")


@unittest.skipUnless(shutil.which("node"), "没有 node，跳过顶栏「幕」的对照")
class HeadActTest(unittest.TestCase):
    """顶栏那个「幕」：读档案时跟档案，其余时候跟进度。

    这条规矩是从一个真事故里长出来的：`ui.js` 曾经直接看 `state.open_dossier`
    决定顶栏印第几幕。那是引擎替**存档**记的「上次读到哪儿」，读完退回卷宗、
    或者读一份别人给的旧存档之后，它仍然指着旧档 —— 于是案① 已经结案、人站
    在第六幕的药库前，顶栏写着「第一幕 · 贤妃薨（勘验）」。
    """

    SCRIPT = """
const fs = require('fs');
const GAME = require(process.argv[2]);
const pack = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const game = new GAME.Game(pack);
game.newGame();
const out = {fresh: game.headAct('')};
// 读第二幕的档案：顶栏该说第二幕，哪怕人还在第一幕的现场
out.whileReadingAct2 = game.headAct('02-SY-BOOK');
// 引擎记着「上次读到 01-FY-END」，但那不该影响顶栏
game.state.open_dossier = '01-FY-END';
game.state.chapter = 6;
out.atAct6WithStaleDossier = game.headAct('');
out.unknownDossier = game.headAct('no-such-dossier');
console.log(JSON.stringify(out));
"""

    def test_head_act_follows_what_is_on_screen(self):
        import json
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "headact.js"
            script.write_text(self.SCRIPT, encoding="utf-8")
            proc = subprocess.run(
                ["node", str(script), str(SRC / "game.js"), str(OUT_PACK)],
                capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
        self.assertEqual(0, proc.returncode, proc.stderr)
        got = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(1, got["fresh"], "开局该印第一幕")
        self.assertEqual(2, got["whileReadingAct2"], "读着第二幕的档案，顶栏该跟着变")
        self.assertEqual(6, got["atAct6WithStaleDossier"],
                         "state.open_dossier 是旧档，不该拖住顶栏")
        self.assertEqual(6, got["unknownDossier"], "读一份不存在的档号，退回当前进度")


if __name__ == "__main__":
    unittest.main()
