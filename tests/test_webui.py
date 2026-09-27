"""网页版界面的冒烟测试：在 node 里用最小 DOM 把 `web/src/ui.js` 真跑一遍。

为什么单独有这一条：`web/src/ui.js` 近千行，却是仓库里唯一没有任何测试**执行**过的部分。
`tests/test_web.py` 只用正则扫重名函数、只用 node 验证 `ui.js` 调用的 `game.X` 存在，
没有一条断言「点下去、敲进去，屏幕上真的出现东西」。网页版「读档」被正则吃成「阅 档」、
「关于」里的幕数写少，都是从这个盲区溜过去的。

真正干活的在 `tests/webui_harness.js`：手写一个刚好够用的假 DOM（零依赖，也不引 jsdom），
把 ui.js 当脚本执行，然后用「点按钮 / 往 #cmd 里敲指令再回车」这样的真动作走一遍主要界面，
最后把 `OK <检查名>` / `FAIL <检查名> :: 原因` / `CHECKS <总数> <失败数>` 打到标准输出。
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, ".")  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARNESS = os.path.join(REPO, "tests", "webui_harness.js")
UI_SOURCE = os.path.join(REPO, "web", "src", "ui.js")


def node_binary():
    return shutil.which("node") or shutil.which("node.exe")


def ending_save() -> dict:
    """走一遍真结局，拿一份真存档（形状与网页版 writeSave 写的完全一样）。"""
    from gongwei.data.story import CONTENT
    from gongwei.game.engine import GameEngine
    from gongwei import autoplay

    engine = GameEngine(CONTENT)
    engine.new_game()
    autoplay.play(engine, list(autoplay.TRUE_ENDING))
    return engine.save()


@unittest.skipUnless(node_binary(), "本机没有 node")
class WebUiSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from gongwei.web.art import art_tables

        cls.tmp = tempfile.mkdtemp(prefix="gongwei-webui-")
        cls.seed_path = os.path.join(cls.tmp, "seed.json")
        with open(cls.seed_path, "w", encoding="utf-8") as fh:
            json.dump(ending_save(), fh, ensure_ascii=False)
        # 页面上那块图景台账与这里导出的是同一份 JSON（都由 gongwei/web/art.py 生成），
        # 不给的话 ui.js 走的是「空台账」退化路——两条路都得能跑，但检查要覆盖真台账。
        cls.art_path = os.path.join(cls.tmp, "art.json")
        with open(cls.art_path, "w", encoding="utf-8") as fh:
            json.dump(art_tables(), fh, ensure_ascii=False)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_harness(self, ui_src: str = "") -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["GONGWEI_SEED_SAVE"] = self.seed_path
        env["GONGWEI_ART_FILE"] = self.art_path
        if ui_src:
            env["GONGWEI_UI_SRC"] = ui_src
        return subprocess.run(
            [node_binary(), HARNESS],
            cwd=REPO, env=env, capture_output=True, text=True, encoding="utf-8",
        )

    @staticmethod
    def parsed(stdout: str):
        passed, failed, total = [], [], 0
        for line in stdout.splitlines():
            if line.startswith("OK "):
                passed.append(line[3:].strip())
            elif line.startswith("FAIL "):
                failed.append(line[5:].strip())
            elif line.startswith("CHECKS "):
                total = int(line.split()[1])
        return passed, failed, total

    def test_the_web_ui_screens_and_commands_really_work(self):
        proc = self.run_harness()
        passed, failed, total = self.parsed(proc.stdout)
        self.assertEqual(
            proc.returncode, 0,
            "网页版界面冒烟测试没通过：\n" + "\n".join(failed) + "\n" + proc.stdout + proc.stderr,
        )
        self.assertGreaterEqual(total, 31, f"只跑了 {total} 项检查，覆盖面缩水了")
        self.assertEqual(failed, [])
        for name in ("开屏是标题屏", "点「新案」进第一幕", "敲档号能阅档",
                     "「读档」开存读面板，点「读本机存档」不出错", "读回一份结案存档",
                     "图景槽在标题屏上是默认景，且落在 #app 外面",
                     "进场报幕：幕次、幕名、地点色调都跟着走",
                     "「案外」页：幕册 / 结局册 / 行囊 / 音画设定",
                     "音画设定：点一下当场生效，也写进本机",
                     "说话人名牌：名字真在人物表里才点金",
                     "顶栏分主次：四项读数带 meta-extra，窄屏交给 CSS 收",
                     "浮层的出口：顶上「收起」当场合上，body 上记着有没有遮罩",
                     "档案里的 // 旁注行：淡墨点金，字一个不改",
                     "对话行新皮：说话人点金，正文一字不改",
                     "【线索】/【物证】的记号只包前缀，整行一字不改",
                     "行动记录折叠条：aria 跟着开合走，条数与卷宗对得上",
                     "右栏四张仪表卡：信任条按 confide_at 折算，到线才点金",
                     "标题屏的落花与印章只做样子，一个字都不吐",
                     "卷首过场：点「新案」起幕帘，Esc 与轻触都能落下",
                     "游戏屏顶栏：图标键只带 aria/title，不跟文字按钮抢名字",
                     "选项卡：序号与标签分家，锁着的仍写「条件不足：」"):
            self.assertIn(name, passed, f"没跑到「{name}」这一项")

    def test_a_broken_ui_is_actually_caught(self):
        """自检：把 ui.js 弄坏一处，这套检查必须报出来。"""
        with open(UI_SOURCE, encoding="utf-8") as fh:
            source = fh.read()
        broken = source.replace("function doSave()", "function doSaveButNobodyCallsThis()")
        self.assertNotEqual(broken, source, "没能在 ui.js 里找到 doSave()，自检失效")
        path = os.path.join(self.tmp, "ui_broken.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(broken)
        proc = self.run_harness(ui_src=path)
        self.assertNotEqual(proc.returncode, 0, "弄坏 ui.js 之后冒烟测试竟然还是绿的")
        self.assertIn("FAIL", proc.stdout)

    def test_the_old_load_command_bug_would_be_caught(self):
        """自检：把「读档」从系统指令里摘掉（批次 1 修过的那类 bug），必须报出来。"""
        with open(UI_SOURCE, encoding="utf-8") as fh:
            source = fh.read()
        old = "if (/^(读档|读取|load|l)$/i.test(text))"
        new = "if (/^(读取|load|l)$/i.test(text))"
        self.assertIn(old, source, "ui.js 里的「读档」分支变了，这条自检要跟着改")
        path = os.path.join(self.tmp, "ui_old_load.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(source.replace(old, new))
        proc = self.run_harness(ui_src=path)
        self.assertNotEqual(proc.returncode, 0, "「读档」坏掉了，冒烟测试却没吭声")
        self.assertIn("读档", proc.stdout)

    def test_the_seed_save_really_is_an_ending(self):
        """自检：那条「读回结案存档」检查不能是空跑。"""
        from gongwei.data.story import CONTENT

        with open(self.seed_path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data.get("v"), 1)
        ending = data["state"]["ending"]
        self.assertIn(ending, {e.id for e in CONTENT.endings})
        self.assertEqual(data["state"]["scene"], ending)


if __name__ == "__main__":
    unittest.main()
