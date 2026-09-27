#!/usr/bin/env python3
"""《宫闱迷踪 · 古风宫廷推理》—— 终端版入口。

    python main.py              开始游戏
    python main.py --help       查看参数

零第三方依赖：只用 Python 标准库（含 Windows 下的 msvcrt），
不需要 `pip install` 任何东西，也不需要 `curses`。
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gongwei.data import CONTENT, TOPIC_GATES
from gongwei.game import GameEngine
from gongwei.game.save import SaveStore
from gongwei.tui import terminal
from gongwei.tui.app import run


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gongwei",
        description="《宫闱迷踪》—— 在终端里查一桩宫廷命案。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "游戏内按键：\n"
            "  ↑↓ / J K      选择动作        Enter / 空格   确认\n"
            "  1-9           直接选第 N 项   S / L          存档 / 读档\n"
            "  PgUp / PgDn   翻阅卷宗        C              窄屏切换面板\n"
            "  H / ?         帮助            Q / Esc        退出\n"
        ),
    )
    p.add_argument("--save", metavar="PATH", default=None,
                   # 注意：argparse 会对 help 做 %-格式化，路径里的 % 必须写成 %%。
                   help="存档文件路径（默认 %%USERPROFILE%%\\.gongwei\\save.json）")
    p.add_argument("--continue", dest="cont", action="store_true",
                   help="直接读取存档继续（没有存档则从新案开始）")
    p.add_argument("--no-save", dest="no_save", action="store_true",
                   help="禁用存读档（存档功能不可用，用于纯净试玩）")
    p.add_argument("--no-color", dest="no_color", action="store_true",
                   help="关掉全部颜色与粗体（等同于设置环境变量 NO_COLOR）")
    p.add_argument("--version", action="version", version="宫闱迷踪 1.0.0")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    # 无色出口：--no-color 与 NO_COLOR 环境变量等效，都在这里定下来；
    # 关掉之后 paint/fg 原样返回文本，整帧不含任何颜色转义序列。
    if args.no_color:
        terminal.set_color(False)

    engine = GameEngine(CONTENT, gates=TOPIC_GATES)
    engine.new_game()

    store = None
    if not args.no_save:
        store = SaveStore(args.save)
        if args.cont:
            ok, msg = store.load(engine)
            if not ok:
                print(f"（{msg}，从新案开始）", file=sys.stderr)

    # 交互式 TUI 需要真正的终端；被重定向时（管道/CI）直接说清楚，
    # 免得画出一堆谁也看不懂的转义序列。
    if not sys.stdout.isatty():
        print("《宫闱迷踪》需要一个交互式终端才能玩（当前输出被重定向）。", file=sys.stderr)
        print("请在 PowerShell / CMD 里直接运行： python main.py", file=sys.stderr)
        return 2

    return run(CONTENT, engine, store=store, gates=TOPIC_GATES)


if __name__ == "__main__":
    raise SystemExit(main())
