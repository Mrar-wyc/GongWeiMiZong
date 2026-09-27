"""结构体检：同名定义不许出现两次。

这条规矩是被两次真实事故逼出来的，两次都是「后写的悄悄顶掉先写的」，
而且**全套测试照样全绿**，只有人眼在真机上才看得出来：

1. `web/src/ui.js` 里有两个 `function renderOptions()`，第二个只重画右栏、
   没有返回值，于是 `left.appendChild(renderOptions())` 抛
   `TypeError: parameter 1 is not of type 'Node'` —— 整个游戏屏只剩顶栏。
2. `gongwei/tui/app.py` 里有**两个 `_draw_left()` 方法**，第二个是加了阅档功能
   之前的旧版（标题永远写「卷宗」），于是终端里敲档号虽然读进了引擎，
   阅读区却一直显示卷轴日志——「敲档号阅档」这个玩法在终端里等于不存在。

Python 不会为重复方法名报错，JS 也不会为重复函数声明报错，所以只能自己扫。
"""

from __future__ import annotations

import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, ".")

from gongwei.data import CONTENT, TOPIC_GATES
from gongwei.game import GameEngine
from gongwei.game.save import SaveStore
from gongwei.tui.app import GameApp

ROOT = Path(__file__).resolve().parent.parent


def _python_files():
    yield ROOT / "main.py"
    yield from sorted((ROOT / "gongwei").rglob("*.py"))
    yield from sorted((ROOT / "tools").glob("*.py"))


def duplicate_definitions(path: Path):
    """返回 ``[(位置, 名字, 次数)]``：同一模块里重复的函数/类/方法名。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []

    def scan(nodes, where: str):
        seen: dict = {}
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                seen.setdefault(node.name, []).append(node.lineno)
                if isinstance(node, ast.ClassDef):
                    # 类体里的方法名同样会互相顶掉，而且更容易漏看
                    scan(node.body, f"{where}{node.name}.")
        for name, lines in seen.items():
            if len(lines) > 1:
                found.append((where, name, lines))

    scan(tree.body, "")
    return found


class NoDuplicateDefinitionsTest(unittest.TestCase):
    def test_python_sources_have_no_duplicate_definitions(self):
        problems = []
        for path in _python_files():
            rel = path.relative_to(ROOT).as_posix()
            for where, name, lines in duplicate_definitions(path):
                places = "、".join(f"{rel}:{n}" for n in lines)
                problems.append(f"{where}{name} 定义了 {len(lines)} 次（{places}）")
        self.assertEqual([], problems, "同名定义会被悄悄顶掉：\n  " + "\n  ".join(problems))

    def test_the_checker_would_actually_catch_one(self):
        """防止这个测试变成永远为真的摆设。"""
        tree = ast.parse(
            "def a():\n    pass\n\n\nclass C:\n"
            "    def m(self):\n        pass\n\n"
            "    def m(self):\n        pass\n\n\n"
            "def a():\n    pass\n"
        )
        names = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                names.append(node.name)
        self.assertEqual(["a", "C", "a"], names)
        # 探针本身：把同样的源码喂给检查器，必须报出重复
        probe = ROOT / "tests" / "_dup_probe.py"
        probe.write_text(
            "def a():\n    pass\n\n\ndef a():\n    pass\n\n\n"
            "class C:\n    def m(self):\n        pass\n\n"
            "    def m(self):\n        pass\n",
            encoding="utf-8",
        )
        try:
            found = duplicate_definitions(probe)
        finally:
            probe.unlink()
        names = sorted(f"{where}{name}" for where, name, _ in found)
        self.assertEqual(["C.m", "a"], names)


class WiringTest(unittest.TestCase):
    """界面调用的引擎/状态方法必须真的存在。

    又一个「全绿但坏了」的例子：`_reading_rows()` 里写的是
    `self.engine.act_title_of(act)`，可这个方法长在 `GameState` 上（`GameEngine`
    上没有），于是**一打开档目就抛 AttributeError**，把整个 TUI 拖崩。
    属性名写错是这类 bug 的常见来源，而它一行测试都没有，所以在这里扫一遍：
    拿真实的 engine / state / content 对照 `gongwei/tui/app.py` 里所有
    `self.engine.X`、`self.state.X`、`self.content.X` 访问。
    """

    def _app(self):
        handle, path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        os.unlink(path)
        engine = GameEngine(CONTENT, gates=TOPIC_GATES)
        engine.new_game()
        return GameApp(CONTENT, engine, store=SaveStore(path)), engine, path

    def test_every_attribute_the_ui_touches_exists(self):
        app, engine, path = self._app()
        try:
            targets = {"engine": engine, "state": engine.state, "content": CONTENT}
            tree = ast.parse((ROOT / "gongwei" / "tui" / "app.py").read_text(encoding="utf-8"))
            missing = []
            for node in ast.walk(tree):
                if not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Attribute):
                    continue
                holder = node.value
                if not (isinstance(holder.value, ast.Name) and holder.value.id == "self"):
                    continue
                if holder.attr not in targets:
                    continue
                if not hasattr(targets[holder.attr], node.attr):
                    missing.append(f"gongwei/tui/app.py:{node.lineno} "
                                   f"self.{holder.attr}.{node.attr}")
            self.assertEqual([], missing, "界面调了不存在的属性：\n  " + "\n  ".join(missing))
        finally:
            if os.path.exists(path):
                os.unlink(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
