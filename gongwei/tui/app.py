"""全屏终端界面：分栏面板 + 命令行。

布局（宽屏）::

    ┌ 顶栏：第 N 幕 · 地点 · 时辰 · 回合 ────────────────────────┐
    │ 卷宗／档案（正文，可滚动）      │ 记事簿（线索）   │ 档目（档案）│
    ├──────────────────────────────────────────────────────────┤
    │ › 在此输入档号或指令                                        │
    └ 底栏：提示 / toast ────────────────────────────────────────┘

两种操作方式**并存**：查档案要自己敲档号（``01-FY-WDH``），推到对话与抉择时
下方自动列出可选条目，按数字或上下键点选即可。窄屏（< 96 列）合并为单栏，
``C`` 键在「卷宗／记事簿」之间切换。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from ..game.command import (HELP_SECTIONS, Command, ParseError, canon_dossier_id,
                            help_lines, is_dossier_id, parse as parse_command,
                            suggest_dossier_ids)
from ..game.engine import GameEngine, Option
from ..game.models import Content
from ..game.save import SaveStore
from .terminal import (App as _App, Canvas, LineEditor, Terminal, QuitApp,
                       char_width, display_width, pad, paint, read_key,
                       split_columns, truncate, visible_width, wrap_text)

# 配色（终端 16 色）
C_BORDER = "cyan"
C_TITLE = "cyan"
C_SCENE = "white"
C_NARR = "default"
C_CHOICE = "magenta"
C_CLUE = "green"
C_WARN = "red"
C_GOLD = "yellow"
C_DIM = "default"
C_OK = "green"
C_HELP = "cyan"
C_PROMPT = "bright_green"

_KIND_STYLE: Dict[str, Tuple[str, str]] = {
    # kind -> (前缀, 颜色)
    "scene": ("", C_SCENE),
    "narration": ("", C_NARR),
    "choice": ("» ", C_CHOICE),
    "clue": ("◆ ", C_CLUE),
    "item": ("▣ ", C_CLUE),
    "toast": ("· ", C_GOLD),
    "warn": ("! ", C_WARN),
    "ending": ("", C_GOLD),
    "dossier": ("▤ ", C_GOLD),
    "system": ("· ", C_DIM),
}

TRUST_LEVELS: Sequence[Tuple[int, str]] = (
    (80, "bright_green"),
    (60, "green"),
    (40, "cyan"),
    (20, "default"),
    (0, "red"),
)


def trust_color(value: int) -> str:
    for floor, color in TRUST_LEVELS:
        if value >= floor:
            return color
    return "red"


@dataclass
class Toast:
    text: str
    kind: str = "info"
    born: float = field(default_factory=time.monotonic)
    ttl: float = 4.0

    def alive(self, now: Optional[float] = None) -> bool:
        return (now or time.monotonic()) - self.born < self.ttl


@dataclass
class Screen:
    lines: List[str]
    help_visible: bool = False
    narrow: bool = False


# --------------------------------------------------------------------------
# 主界面
# --------------------------------------------------------------------------


class GameApp:
    """把引擎状态渲染成一屏，并处理按键。"""

    MIN_W = 62
    MIN_H = 18

    def __init__(self, content: Content, engine: GameEngine,
                 store: Optional[SaveStore] = None) -> None:
        self.content = content
        self.engine = engine
        self.store = store or SaveStore()
        self.cursor = 0
        self.scroll = 0
        self.panel = "log"          # narrow 模式：log | clues
        self.read_mode = "log"      # 宽屏阅读区：log | dossier
        self.help_visible = False
        self.toast: Optional[Toast] = None
        self.pending: Optional[str] = None   # 确认框动作: new|load|quit
        self.show_title = True
        self.quit = False
        self.editor = LineEditor()
        self.show_command = True
        self.search_term = ""
        self.search_hits: List[Tuple[str, str, str]] = []

    # -- 便捷 ------------------------------------------------------------
    @property
    def state(self):
        return self.engine.state

    def notify(self, text: str, kind: str = "info") -> None:
        if text:
            self.toast = Toast(text=text, kind=kind, ttl=6.0 if kind == "error" else 4.0)

    def options(self) -> List[Option]:
        opts = self.engine.options()
        if self.cursor >= len(opts):
            self.cursor = max(0, len(opts) - 1)
        return opts

    # -- 输入 ------------------------------------------------------------
    def handle(self, key: str) -> None:
        # 帮助浮层排在标题屏之前：浮层自称「按任意键返回」，而标题屏只认
        # 少数几个键（DOWN/ENTER/ESC…），先判 show_title 的话，从标题屏打开的
        # 帮助就只有 ESC/ENTER/h/q 能关掉，其余按键会掉进菜单里。
        if self.help_visible:
            self.help_visible = False
            return
        if self.show_title:
            self._handle_title(key)
            return
        if self.pending:
            self._handle_confirm(key)
            return
        self._handle_game(key)

    # -- 标题屏 ----------------------------------------------------------
    def _handle_title(self, key: str) -> None:
        entries = self._title_entries()
        if key in ("UP", "k", "K"):
            self.cursor = (self.cursor - 1) % len(entries)
        elif key in ("DOWN", "j", "J"):
            self.cursor = (self.cursor + 1) % len(entries)
        elif key in ("1", "2", "3", "4") and int(key) <= len(entries):
            self.cursor = int(key) - 1
            self._activate_title(entries[self.cursor])
        elif key in ("ENTER", " ", "SPACE"):
            self._activate_title(entries[self.cursor])
        elif key in ("ESC", "q", "Q"):
            self.quit = True

    def _title_entries(self) -> List[str]:
        items = ["新案开卷"]
        if self.store.exists():
            items.append("续前案（读档）")
        items += ["玩法说明", "离开"]
        return items

    def _activate_title(self, label: str) -> None:
        if label.startswith("新案开卷"):
            self.engine.state = self.engine.new_game()
            self.show_title = False
            self.cursor = 0
            self.scroll = 0
            self.notify("案卷展开。", "ok")
        elif label.startswith("续前案"):
            ok, msg = self.store.load(self.engine)
            self.notify(msg, "ok" if ok else "error")
            if ok:
                self.show_title = False
                self.cursor = 0
                self.scroll = 0
        elif label.startswith("玩法说明"):
            self.help_visible = True
        else:
            self.quit = True

    # -- 确认框 ----------------------------------------------------------
    def _handle_confirm(self, key: str) -> None:
        action = self.pending
        if key in ("y", "Y", "ENTER"):
            self.pending = None
            if action == "new":
                self.engine.state = self.engine.new_game()
                self.cursor = 0
                self.scroll = 0
                self.notify("重开一案。", "ok")
            elif action == "load":
                ok, msg = self.store.load(self.engine)
                self.notify(msg, "ok" if ok else "error")
                self.cursor = 0
                self.scroll = 0
            elif action == "quit":
                self.quit = True
        elif key in ("n", "N", "ESC"):
            self.pending = None
            self.notify("已取消。")

    # -- 游戏中 ----------------------------------------------------------
    def _handle_game(self, key: str) -> None:
        ending = bool(self.state.ending) or self.engine.at_verdict()
        # 空行时按 1-9：直接选中第 N 项（点选仍然好用，不必先按回车）。
        # 这一支必须排在「单字符进命令行」之前——否则数字会被当成输入吃掉。
        if len(key) == 1 and key.isdigit() and key != "0" and self.editor.empty():
            opts = self.options()
            idx = int(key)
            if 1 <= idx <= len(opts):
                self.cursor = idx - 1
                self._activate()
                return
            self.notify(f"没有第 {idx} 项。", "error")
            return
        # 其余单字符键先给命令行；行是空的才回落到旧快捷键（r 重来、h 帮助…），
        # 所以敲到一半的「r」不会被当成「重来」。
        if len(key) == 1 and key >= " " and self.editor.buffer:
            self.editor.handle(key)
            return
        if key == "ESC":
            if self.editor.buffer:
                self.editor.clear()
            elif self.read_mode == "dossier":
                self._close_dossier()
            elif ending:
                self.show_title = True
                self.cursor = 0
            return
        if key in ("q", "Q"):
            self.pending = "quit"
            return
        if key in ("h", "H", "?"):
            self.help_visible = True
            return
        if key in ("s", "S"):
            self._do_save()
            return
        if key in ("l", "L"):
            if self.store.exists():
                self.pending = "load"
            else:
                self.notify("没有存档。", "error")
            return
        if key in ("r", "R"):
            self.pending = "new"
            return
        if key in ("c", "C"):
            self.panel = "clues" if self.panel == "log" else "log"
            return
        # 翻页的语义跟着阅读模式走：卷宗是「越往上越旧」（0 = 最新一条贴底），
        # 而档案/档目/检索是文档，0 = 从头读起。两者用同一个 self.scroll，
        # 所以方向必须在这里分开算，否则按 PgUp 会往文档更深处跑。
        doc = self.read_mode != "log"
        if key in ("PGUP", "u"):
            self.scroll = max(0, self.scroll - 4) if doc else self.scroll + 4
            return
        if key in ("PGDN", "d"):
            self.scroll = self.scroll + 4 if doc else max(0, self.scroll - 4)
            return
        if key == "HOME":
            self.scroll = 0 if doc else 9999
            return
        if key == "END":
            self.scroll = 9999 if doc else 0
            return
        if key in ("UP", "k", "K"):
            self._move_cursor(-1)
            return
        if key in ("DOWN", "j", "J", "TAB"):
            self._move_cursor(1)
            return
        if key in ("ENTER", " ", "SPACE"):
            if self.editor.empty():
                # 空行回车 = 确认当前高亮项（与点选等价）；结局屏没有选项，
                # 此时回车就是「看完了，回标题」。
                if not self._activate() and ending:
                    self.show_title = True
                    self.cursor = 0
            else:
                self._submit_command()
            return
        self.editor.handle(key)

    def _move_cursor(self, step: int) -> None:
        opts = self.options()
        if not opts:
            return
        self.cursor = (self.cursor + step) % len(opts)

    # -- 命令行 ----------------------------------------------------------
    def _submit_command(self) -> None:
        text = self.editor.text
        self.editor.remember()
        self.editor.clear()
        self._run_command(text)

    def _run_command(self, text: str) -> None:
        """执行一条玩家指令。所有失败都以 toast 呈现，绝不抛出去。"""
        if not text.strip():
            return
        try:
            cmd = parse_command(text)
        except ParseError as exc:
            self.notify(exc.message, "error")
            if exc.hint:
                self.notify(exc.hint, "error")
            return
        try:
            self._dispatch(cmd)
        except Exception as exc:                       # 引擎异常不该炸掉界面
            self.notify(f"出错：{exc}", "error")

    def _dispatch(self, cmd: Command) -> None:
        kind = cmd.kind
        if kind == "read":
            self._cmd_read(cmd.arg)
        elif kind == "list":
            self._cmd_list(cmd.arg)
        elif kind == "search":
            self._cmd_search(cmd.arg)
        elif kind == "note":
            self._cmd_note(cmd.arg)
        elif kind == "edit_note":
            self._cmd_edit_note(cmd)
        elif kind == "delete_note":
            self._cmd_delete_note(cmd)
        elif kind == "review":
            self.read_mode = "log"
            self.notify(f"已知线索 {len(self.state.clues)} 条，核心 "
                        f"{self.state.core_count()}/{self.content.core_total()}。")
        elif kind == "timeline":
            self._cmd_list("")
        elif kind == "help":
            self.help_visible = True
        elif kind == "save":
            self._do_save()
        elif kind == "load":
            if self.store.exists():
                self.pending = "load"
            else:
                self.notify("没有存档。", "error")
        elif kind == "quit":
            self.pending = "quit"
        elif kind in ("ask", "show", "goto", "accuse", "title", "act", "back"):
            self._cmd_act(cmd)
        else:
            self.notify(f"「{cmd.raw}」这条指令还不认识。", "error")

    def _cmd_read(self, did: str) -> None:
        did = canon_dossier_id(did)
        if not did:
            self.notify("要读哪一份？例如：01-FY-WDH", "error")
            return
        if not self.engine.dossier_exists(did):
            near = suggest_dossier_ids(did, self.state.dossier_states.keys())
            tail = f"（是不是：{'、'.join(near)}）" if near else ""
            self.notify(f"档目里没有 {did}。{tail}", "error")
            return
        if not self.engine.can_read_dossier(did):
            case = self.engine.dossier_case(did)
            if case > self.state.case:
                self.notify(f"{did} 是第 {case} 案的档 —— 你还没走到那一案。",
                            "error")
            else:
                self.notify(f"{did} 还没到能看的时候。", "error")
            return
        upd = self.engine.read_dossier(did)
        self._apply_update(upd)
        self.read_mode = "dossier"
        self.scroll = 0

    def _cmd_list(self, arg: str) -> None:
        rows = self.engine.dossier_index()
        if not rows:
            self.notify("档目还是空的。敲 00-readme 试试。", "error")
            return
        total = sum(len(r) for _, r in rows)
        self.read_mode = "index"
        self.scroll = 0
        self.notify(f"档目：已收录 {total} 份。")

    def _cmd_search(self, term: str) -> None:
        if not term.strip():
            self.notify("要查什么词？例如：查 苦杏仁", "error")
            return
        hits = self.engine.search_dossiers(term)
        if not hits:
            self.notify(f"已收集的档案里没有「{term}」。", "error")
            return
        self.search_term = term.strip()
        self.search_hits = hits
        self.read_mode = "search"
        self.scroll = 0
        self.notify(f"「{self.search_term}」命中 {len(hits)} 处。")

    def _cmd_note(self, text: str) -> None:
        if not text.strip():
            self.notify(f"已有笔记 {len(self.state.notes)} 条。", "info")
            return
        self.state.notes.append(text.strip())
        self.notify(f"记下了（第 {len(self.state.notes)} 条）。", "ok")

    def _cmd_delete_note(self, cmd: Command) -> None:
        """按条目号删。以前这里无脑 `pop()`：敲「删 1」删掉的其实是最后一条。"""
        notes = self.state.notes
        idx = cmd.index
        if not notes:
            self.notify("没有笔记可删。", "error")
            return
        if idx is None or idx < 1 or idx > len(notes):
            self.notify(f"记事簿上没有第 {idx} 条。", "error")
            return
        gone = notes.pop(idx - 1)
        self.notify(f"撕掉了第 {idx} 条：{truncate(gone, 24)}", "ok")

    def _cmd_edit_note(self, cmd: Command) -> None:
        """改写第 N 条笔记（`index == -1` 表示改写最后一条）。

        解析层一直认得「改」，但 `_dispatch` 里没有这一支，于是指令被静默丢掉。
        """
        notes = self.state.notes
        if not notes:
            self.notify("还没有笔记可改。", "error")
            return
        idx = cmd.index if cmd.index and cmd.index > 0 else len(notes)
        if idx > len(notes):
            self.notify(f"记事簿上没有第 {idx} 条。", "error")
            return
        text = cmd.arg.strip()
        if not text:
            self.notify("要改成什么？例如：改 2 香炉里有朱砂", "error")
            return
        notes[idx - 1] = text
        self.notify(f"第 {idx} 条改成了：{truncate(text, 24)}", "ok")

    def _cmd_act(self, cmd: Command) -> None:
        """把 ask/show/go/accuse/back 落到当前选项表上。"""
        if cmd.kind == "back":
            self._close_dossier()
            return
        if cmd.kind == "title":
            # `arg` 是时辰码、`what` 才是标题正文；写 `arg` 会把档号当成标题。
            if not self.editor.buffer and cmd.what:
                self.state.dossier_titles[self.state.open_dossier or ""] = cmd.what
                self.notify("换了个标题。", "ok")
            return
        if cmd.kind == "act":
            return
        opts = self.options()
        if not opts:
            self.notify("此时没有可做的事。", "error")
            return
        want = cmd.arg.strip()
        needle = want
        if cmd.kind == "accuse":
            needle = want or "凶手"
        hits = [o for o in opts if needle and needle in o.label]
        if not hits and cmd.who:
            # 「问 王德海 <话题>」：先找人，再在该人话题里找
            who_hits = [o for o in opts if cmd.who in o.label]
            if who_hits:
                sub = [o for o in who_hits if needle and needle in o.label]
                hits = sub or who_hits
        if not hits and cmd.what:
            hits = [o for o in opts if cmd.what in o.label]
        if not hits and want:
            hits = [o for o in opts if want in o.label]
        if not hits:
            self.notify(f"眼下没有「{want or cmd.kind}」这一项。", "error")
            return
        pick = hits[0]
        if not pick.enabled:
            self.notify(pick.hint or "此时还做不到。", "error")
            return
        self.cursor = pick.index - 1
        self._activate()

    def _close_dossier(self) -> None:
        self.read_mode = "log"
        self.scroll = 0
        self.engine.close_dossier()

    def _do_save(self) -> None:
        stamp = time.strftime("%m-%d %H:%M")
        ok = self.store.save(self.engine, stamp=stamp)
        self.notify("已存档：" + stamp if ok else f"存档失败：{self.store.last_error}",
                    "ok" if ok else "error")

    def _activate(self) -> bool:
        """执行当前高亮的动作。返回是否真的执行了（结局屏没有选项，返回 False）。"""
        opts = self.options()
        if not opts:
            return False
        opt = opts[self.cursor]
        if not opt.enabled:
            self.notify(opt.hint or "此时还做不到。", "error")
            return True
        # 选项自带 action 闭包（引擎侧绑好了效果与场景切换），界面只管调用
        upd = opt.action() if opt.action is not None else None
        self._apply_update(upd)
        self.cursor = 0
        self.scroll = 0
        return True

    def _apply_update(self, upd) -> None:
        if upd is None:
            return
        for t in upd.toasts:
            self.notify(t)
        if upd.new_clues:
            names = "、".join(self.state.clue_name(c) for c in upd.new_clues)
            self.notify(f"记下：{names}", "ok")
        if upd.new_items:
            names = "、".join(self.state.clue_name(i) for i in upd.new_items)
            self.notify(f"收入行囊：{names}", "ok")
        # 指认之后：进入判决场景 -> 立刻结算结局
        if self.engine.at_verdict() and not self.state.ending:
            eid = self.engine.finalize()
            ending = self.content.scenes.get(eid)
            if ending is not None:
                self.state.log.append(_log_entry("ending", ending.title))
        elif upd.ended and self.state.ending:
            self.notify("结案。", "ok")

    # -- 渲染 ------------------------------------------------------------
    def render(self, width: int, height: int) -> Screen:
        canvas = Canvas(width, height)
        if self.show_title:
            self._draw_title(canvas, width, height)
        else:
            self._draw_game(canvas, width, height)
        if self.help_visible:
            self._draw_help(canvas, width, height)
        if self.pending:
            self._draw_confirm(canvas, width, height)
        lines = canvas.render()
        return Screen(lines=lines, help_visible=self.help_visible, narrow=width < 96)

    # -- 标题 ------------------------------------------------------------
    def _draw_title(self, canvas: Canvas, w: int, h: int) -> None:
        box_w = min(w - 4, 64)
        box_h = min(h - 4, 20)
        x = (w - box_w) // 2
        y = (h - box_h) // 2
        canvas.box(x, y, box_w, box_h, title=self.content.title, border_color=C_BORDER,
                   title_color=C_TITLE)
        inner = box_w - 6
        row = y + 2
        sub = self.content.subtitle
        canvas.put(x + 3, row, paint(_box_middle(sub, inner), "white", bold=True))
        row += 2
        entries = self._title_entries()
        # 菜单占 len(entries) 行，往上留一行空档；底部两行归副标题与提示。
        menu_row = y + box_h - 5 - len(entries)
        # 序章最多排到菜单上一行：矮终端（62x18）上 box_h 只有 14，
        # 若不夹住，序章末端会撞进菜单里（实测踩过）。
        for line in _wrap_all(self.content.prologue, inner)[: max(0, menu_row - row - 1)]:
            canvas.put(x + 3, row, _box_fit(line, inner))
            row += 1
        for i, label in enumerate(entries):
            here = i == self.cursor
            text = ("▸ " if here else "  ") + f"{i + 1}. {label}"
            canvas.put(x + 4, menu_row + i,
                       paint(_box_fit(text, inner),
                             C_GOLD if here else "default", bold=here))
        canvas.put(x + 3, y + box_h - 2,
                   paint(_box_middle("↑↓ 选择 · Enter 确认 · Q 离开", inner), "default", dim=True))

    # -- 游戏主屏 --------------------------------------------------------
    def _draw_game(self, canvas: Canvas, w: int, h: int) -> None:
        ending = bool(self.state.ending)
        cmd_rows = 1 if (self.show_command and h >= 12) else 0
        footer_rows = 3 if (h - cmd_rows - 3) >= 6 else 2
        body_h = h - 1 - cmd_rows - footer_rows
        if body_h < 4:
            footer_rows = 1
            cmd_rows = 0
            body_h = h - 1 - footer_rows
        self._draw_topbar(canvas, w)
        narrow = w < 96
        if narrow:
            # 窄屏一屏只放得下一块面板：C 键在「卷宗」与「记事簿 + 人情」之间切。
            # 选项永远跟着卷宗走 —— 它是玩家唯一能动手的地方，不能藏。
            if self.panel == "clues":
                trust_h = max(4, min(body_h // 2, 3 + 2 * len(self.content.characters)))
                if body_h >= 8:
                    clues_h = body_h - trust_h - 1
                    self._draw_clues(canvas, 0, 1, w, clues_h)
                    self._draw_clues(canvas, 0, 2 + clues_h, w, trust_h,
                                     title="人情", show_trust=True)
                else:
                    self._draw_clues(canvas, 0, 1, w, body_h)
            else:
                self._draw_left(canvas, 0, 1, w, body_h, ending, narrow=True)
        else:
            col_w = 20 if w >= 112 else 16
            # 手工切分：左侧卷宗尽量宽，中间记事簿，右侧案卷
            dossier_w = col_w
            clues_w = 24 if w >= 112 else 20
            left_w = w - 2 - clues_w - dossier_w
            self._draw_left(canvas, 0, 1, left_w, body_h, ending)
            clues_col = left_w + 1
            dossier_col = clues_col + clues_w + 1
            trust_h = max(5, min(body_h - 6, 3 + 2 * len(self.content.characters)))
            clues_h = body_h - trust_h - 1
            self._draw_clues(canvas, clues_col, 1, clues_w, clues_h)
            self._draw_clues(canvas, clues_col, 2 + clues_h, clues_w, trust_h,
                             title="人情", show_trust=True)
            self._draw_dossier(canvas, dossier_col, 1, dossier_w, body_h)
        if cmd_rows:
            self._draw_command(canvas, w, 1 + body_h)
        self._draw_footer(canvas, w, 1 + body_h + cmd_rows, footer_rows, ending)

    def _draw_command(self, canvas: Canvas, w: int, y: int) -> None:
        """命令行：玩家在此敲档号或指令。"""
        canvas.put(0, y, paint(pad("─" * w, w), "default", dim=True))
        prompt = "› "
        text = self.editor.text
        room = max(4, w - display_width(prompt) - 2)
        shown = truncate(text, room) if display_width(text) > room else text
        line = paint(prompt, C_PROMPT, bold=True) + paint(shown, "white")
        canvas.put(0, y, line)          # 覆掉左侧分隔线，接成「› 输入」的观感
        if not text:
            ghost = "输入档号或指令（如 01-FY-WDH / 帮助）"
            canvas.put(display_width(prompt), y, paint(truncate(ghost, room), "default", dim=True))

    def _reading_rows(self, width: int) -> List[str]:
        """阅读区内容：档案正文 / 档目 / 检索结果 / 卷宗日志。"""
        if self.read_mode == "search":
            out = [paint(f"在已收集的档案里查「{self.search_term}」", C_GOLD, bold=True), ""]
            for did, title, snippet in self.search_hits:
                out.append(paint(f"▤ {did}  {title}", C_TITLE))
                for atom in _wrap_all(snippet, max(4, width - 4)):
                    out.append(paint("    " + atom, "default", dim=True))
                out.append("")
            return out
        did = self.state.open_dossier
        if self.read_mode == "dossier":
            if did and self.engine.dossier_exists(did) and self.state.dossier_read(did):
                head = "▤ "
                indent = " " * display_width(head)
                # dossier_view 已经按宽度折好行了，这里**不能再折一次** ——
                # 否则每行都成了「新段落」，记号会顶在每一行上。
                # 规矩：空行分段，段首放 ▤，段内其余行缩进对齐。
                out: List[str] = []
                fresh = True
                for para in self.engine.dossier_view(did, max(4, width - 2)):
                    if not para:
                        out.append("")
                        fresh = True
                        continue
                    out.append(paint((head if fresh else indent) + para, C_GOLD))
                    fresh = False
                return out
            self.read_mode = "index"            # 正文没了就退回档目
        if self.read_mode == "index":
            rows = self.engine.dossier_index()
            if not rows:
                return [paint("档目还是空的。敲 00-readme 试试。", "default", dim=True)]
            out = [paint("档目", C_GOLD, bold=True), ""]
            for act, entries in rows:
                out.append(paint(f"第 {act} 幕 · {self.state.act_title_of(act)}", C_TITLE))
                for did2, title, hint, read in entries:
                    mark = "▤" if read else "·"
                    tail = f"  (还牵着 {hint} 份)" if hint else ""
                    out.append(paint(f"  {mark} {did2}  {title}{tail}",
                                     C_GOLD if read else "default", dim=not read))
                out.append("")
            return out
        return self._log_lines(width)

    def _draw_left(self, canvas: Canvas, x: int, y: int, w: int, h: int,
                   ending: bool, narrow: bool = False,
                   show_options: bool = True) -> None:
        title = "结案" if ending else (
            {"dossier": "档案", "index": "档目", "search": "检索"}.get(self.read_mode, "卷宗"))
        canvas.box(x, y, w, h, title=title, border_color=C_BORDER, title_color=C_TITLE)
        inner_w = max(4, w - 4)
        top_row = y + 1
        bottom_row = y + h - 2          # 最后一行留空，防止文字贴边

        opts = [] if (ending or not show_options) else self.engine.options()
        sel = opts[self.cursor] if opts and self.cursor < len(opts) else None
        # 选项区实际占用的行数
        opt_rows = len(opts) + 1        # 分隔线 + 每个选项一行
        if sel is not None and sel.detail:
            opt_rows += 1
        if sel is not None and not sel.enabled and sel.hint:
            opt_rows += 1
        opt_top = max(top_row, bottom_row - opt_rows + 1) if opts else bottom_row + 1
        log_rows = max(1, (opt_top - 1) - top_row) if opts else max(1, bottom_row - top_row + 1)

        rows = self._reading_rows(inner_w)
        total = len(rows)
        max_scroll = max(0, total - log_rows)
        self.scroll = min(self.scroll, max_scroll)
        if self.read_mode == "log":
            end = total - self.scroll          # 卷宗：0 = 最新一条贴在底下
            start = max(0, end - log_rows)
        else:
            start = self.scroll                # 文档：0 = 从头读起
            end = min(total, start + log_rows)
        view = rows[start:end]
        row = top_row
        for text in view:
            canvas.put(x + 2, row, pad(text, inner_w))
            row += 1
        above, below = start, total - end
        if above or below:
            more = (f"↑{above} " if above else "") + (f"↓{below} " if below else "")
            canvas.put(max(x + 2, x + w - 3 - display_width(more)), y, paint(more, C_GOLD))
        if not opts or opt_top <= top_row:
            return

        # 分隔线之下是选项：当前项高亮，灰掉的是「条件不足」的门禁
        canvas.put(x + 2, opt_top, paint("┄" * inner_w, "default", dim=True))
        line = opt_top + 1
        for i, opt in enumerate(opts):
            if line > bottom_row:
                break
            here = i == self.cursor
            mark = "❯" if here else " "
            label = opt.label + ("（已问）" if opt.asked else "")
            label = truncate(label, max(4, inner_w - 6))
            color = "red" if not opt.enabled else (C_GOLD if here else "default")
            body = f"{mark} {opt.index}. {label}"
            canvas.put(x + 2, line, paint(pad(body, inner_w), color, bold=here,
                                         dim=not opt.enabled))
            line += 1
        if sel is not None and sel.detail and line <= bottom_row:
            canvas.put(x + 2, line,
                       paint(pad(truncate("   " + sel.detail, inner_w), inner_w),
                             "default", dim=True))
            line += 1
        if sel is not None and not sel.enabled and sel.hint and line <= bottom_row:
            canvas.put(x + 2, line,
                       paint(pad(truncate("   条件不足：" + sel.hint, inner_w), inner_w), C_WARN))

    def _draw_dossier(self, canvas: Canvas, x: int, y: int, w: int, h: int) -> None:
        """第三栏：地点、时辰、进度等速览。"""
        if h < 3 or w < 10:
            return
        canvas.box(x, y, w, h, title="案卷", border_color=C_BORDER, title_color=C_TITLE)
        inner_w = max(4, w - 4)
        rows: List[Tuple[str, str]] = [
            ("时辰", self.state.time or "—"),
            ("地点", self.state.place or "—"),
            ("回合", str(self.state.turn)),
            ("核心", f"{self.state.core_count()}/{self.content.core_total()}"),
            ("线索", str(len(self.state.clues))),
            ("问过", str(len(self.state.topics_asked))),
            ("行囊", str(len(self.state.items_owned))),
            ("评分", str(self.state.score)),
        ]
        if self.state.accused:
            v = self.content.verdicts.get(self.state.accused)
            rows.append(("指认", v[1] if v else self.state.accused))
        row = y + 1
        for label, value in rows:
            if row >= y + h - 1:
                break
            canvas.put(x + 2, row, paint(pad(label, 5), "default", dim=True))
            canvas.put(x + 2 + 5, row, paint(truncate(value, max(2, inner_w - 5)), "white"))
            row += 1

    def _draw_topbar(self, canvas: Canvas, w: int) -> None:
        title = self.engine.current_title
        where = " · ".join(x for x in (self.state.place, self.state.time) if x)
        right = f"回合 {self.state.turn} "
        budget = max(0, w - display_width(right) - 6)
        text = f" {truncate(title, max(0, budget - display_width(where) - 4))}"
        if where:
            text += f"  ·  {where}"
        line = paint(pad(text, w - display_width(right)), C_TITLE, bold=True)
        line += paint(right, C_GOLD, dim=True)
        canvas.put(0, 0, line)

    def _log_lines(self, width: int) -> List[str]:
        rows: List[str] = []
        for entry in self.state.log:
            prefix, color = _KIND_STYLE.get(entry.kind, ("", C_NARR))
            for para in str(entry.text).split("\n"):
                if not para:
                    rows.append("")
                    continue
                atoms = _wrap_all(para, max(4, width - display_width(prefix)))
                for i, atom in enumerate(atoms):
                    head = prefix if i == 0 else " " * display_width(prefix)
                    rows.append(paint(head + atom, color))
        return rows

    def _draw_clues(self, canvas: Canvas, x: int, y: int, w: int, h: int,
                    title: str = "记事簿", show_trust: bool = False) -> None:
        if h < 3:
            return
        canvas.box(x, y, w, h, title=title, border_color=C_BORDER, title_color=C_TITLE)
        inner_w = max(4, w - 4)
        row = y + 1
        if show_trust:
            for cid, ch in self.content.characters.items():
                if self.state.case not in getattr(ch, "case", (1,)):
                    continue          # 别的案子里的人：现在还不该出现在人情里
                if ch.trust <= 0 and not self.state.trust_of(cid):
                    continue          # 未登场、也无信任度的人物不占位
                if row >= y + h - 1:
                    break
                value = self.state.trust_of(cid)
                bar_w = 5
                filled = int(round(value / 100 * bar_w))
                bar = "█" * filled + "·" * (bar_w - filled)
                name = truncate(ch.name, max(2, inner_w - bar_w - 2))
                text = pad(name, max(2, inner_w - bar_w - 1)) + bar
                canvas.put(x + 2, row, paint(truncate(text, inner_w), trust_color(value)))
                row += 1
                if row < y + h - 1:
                    canvas.put(x + 2, row,
                               paint(pad("  " + truncate(ch.role, inner_w - 2), inner_w),
                                     "default", dim=True))
                    row += 1
            return
        clues = [i for i in self.content.items.values() if self.state.has(i.id) and i.core]
        extras = [i for i in self.content.items.values()
                  if self.state.has(i.id) and not i.core]
        total = self.content.core_total()
        if not clues and not extras:
            canvas.put(x + 2, row, paint("（空）", "default", dim=True))
            return
        for item in clues:
            if row >= y + h - 1:
                break
            canvas.put(x + 2, row, paint("◆ " + truncate(item.name, inner_w - 2), C_CLUE))
            row += 1
        if extras and row < y + h - 1:
            canvas.put(x + 2, row, paint("┄" * inner_w, "default", dim=True))
            row += 1
        for item in extras:
            if row >= y + h - 1:
                break
            canvas.put(x + 2, row,
                       paint("· " + truncate(item.name, inner_w - 2), "default", dim=True))
            row += 1
        if row < y + h - 1:
            canvas.put(x + 2, y + h - 2,
                       paint(pad(f"核心 {len(clues)}/{total}", inner_w), C_GOLD, dim=True))

    def _draw_footer(self, canvas: Canvas, w: int, y: int, h: int, ending: bool) -> None:
        """底栏：分隔线 + toast/条件提示 + 按键提示。行数由 `_draw_game` 算好后传进来。"""
        canvas.put(0, y, paint("─" * w, "default", dim=True))
        toast_alive = bool(self.toast and self.toast.alive())
        hot = ""                                     # 最急的一行：toast 或条件不足
        hot_color = C_WARN
        if toast_alive:
            hot = " " + self.toast.text
            hot_color = {"error": C_WARN, "ok": C_OK}.get(self.toast.kind, C_GOLD)
        elif not ending:
            opts = self.engine.options()
            if opts and not opts[self.cursor].enabled and opts[self.cursor].hint:
                hot = " 条件不足：" + opts[self.cursor].hint
        status = f" 线索 {len(self.state.clues)}/{len(self.content.items)}"
        status += f" · 核心 {self.state.core_count()}/{self.content.core_total()}"
        status += f" · 评分 {self.state.score}"
        if self.state.notes:
            status += f" · 笔记 {len(self.state.notes)}"
        keys = ("Enter 重开 · Q 离开" if ending
                else "输入档号阅档 · 数字/↑↓ 选择 · Enter 确认 · S 存 L 读 · R 重来 · H 帮助 · Q 离开")
        if self.panel == "clues" and self.read_mode == "log" and not ending:
            # 窄屏切到了记事簿：得告诉玩家怎么回去，否则选项看起来「不见了」
            keys = "C 回卷宗 · " + keys
        if h <= 1:
            # 只剩一行：只放最急的那条
            text, color = (hot, hot_color) if hot else (status, "white")
            canvas.put(0, y + 1, paint(pad(truncate(text, w), w), color, bold=bool(hot)))
            return
        if h >= 3:
            canvas.put(0, y + 1, paint(pad(truncate(hot or status, w), w),
                                       hot_color if hot else "white", bold=bool(hot)))
            canvas.put(0, y + h - 1, paint(pad(" " + truncate(keys, w - 4), w), "default", dim=True))
            return
        # 两行：状态 + 提示
        canvas.put(0, y + 1, paint(pad(truncate(hot or status, w), w),
                                   hot_color if hot else "white", bold=bool(hot)))

    # -- 帮助 ------------------------------------------------------------
    def _draw_help(self, canvas: Canvas, w: int, h: int) -> None:
        lines = [
            "《宫闱迷踪》玩法",
            "",
            "你是仵作沈墨白。贤妃死于凤仪殿，你要在卯时之前说出一个名字。",
            "两条路并行：敲指令查档案，或按数字点选下方列出的动作。",
            "档案不会自己排队等你——得顺着正文里的号子往下翻。",
            "核心线索（◆）越齐，结案时的指认越站得住；信任会随问话升降。",
            "",
            "指令（在 › 后输入，回车执行）",
        ]
        for head, items in HELP_SECTIONS:
            lines.append(f"  【{head}】")
            for usage, desc in items:
                lines.append(f"    {usage:<16}{desc}")
        lines += [
            "",
            "按键",
            "  ↑↓ / J K / 数字   选择动作、条目（数字在空行时直接选中）",
            "  Enter              执行指令 / 确认当前项",
            "  ↑ ↓（有输入时）    翻指令历史",
            "  Esc                清空输入 / 关闭档案 / 回到标题",
            "  S / L              存档 / 读档",
            "  R                  从头再查一案",
            "  PgUp / PgDn        翻阅正文。卷宗从最新往回翻；档案、档目",
            "                     从标题往下读（标题处 ↑N ↓M 报还剩几行）",
            "  Home / End         卷宗：跳到最新 / 最早；文档：回到开头 / 末尾",
            "  C                  窄屏下切换「卷宗 / 记事簿」",
            "  H / ?              本帮助",
            "  Q                  退出",
        ]
        box_w = min(w - 4, 76)
        box_h = min(h - 2, len(lines) + 4)
        x = (w - box_w) // 2
        y = max(0, (h - box_h) // 2)
        canvas.clear_rect(x, y, box_w, box_h)   # 否则底层的标题屏文字会透进帮助框
        canvas.box(x, y, box_w, box_h, title="帮助", border_color=C_HELP, title_color=C_HELP)
        for i, text in enumerate(lines[: box_h - 2]):
            # 文字从 x+3 起排，「│」在 x+box_w-1，所以一行最多占 box_w-6 列；
            # _box_fit 会连显示宽度一起夹住，别改回 truncate+pad。
            canvas.put(x + 3, y + 1 + i, paint(_box_fit(text, box_w - 6), "white"))
        canvas.put(x + 3, y + box_h - 2,
                   paint(_box_fit("按任意键返回", box_w - 6), "default", dim=True))

    # -- 确认 ------------------------------------------------------------
    def _draw_confirm(self, canvas: Canvas, w: int, h: int) -> None:
        prompts = {
            "quit": "确定离开？未存档的进度会丢掉。",
            "new": "重开一案？当前进度会丢掉。",
            "load": f"读取存档？当前进度会被覆盖。\n{self.store.summary().describe() if self.store.exists() else ''}",
        }
        text = prompts.get(self.pending or "", "确定？")
        lines = text.split("\n")
        box_w = min(w - 6, 62)
        box_h = len(lines) + 4
        x = (w - box_w) // 2
        y = max(0, (h - box_h) // 2)
        canvas.clear_rect(x, y, box_w, box_h)   # 同帮助浮层：先抹干净再画
        canvas.box(x, y, box_w, box_h, title="确认", border_color=C_WARN, title_color=C_WARN)
        for i, line in enumerate(lines):
            canvas.put(x + 3, y + 1 + i, paint(_box_fit(line, box_w - 6), "white"))
        canvas.put(x + 3, y + box_h - 2, paint(_box_fit("Y / Enter 确定    N / Esc 取消", box_w - 6), C_GOLD))


# --------------------------------------------------------------------------
# 循环
# --------------------------------------------------------------------------


def _box_fit(text: str, budget: int) -> str:
    """把一行文字裁到「正好放得进框内」并补齐空格。

    ``budget`` 是这行文字能占的最大列数。裁切同时守住两个上限：
    字符数（``budget``）与显示宽度（``budget - 1``）——后者留出一列，
    免得最后一个宽字符正好压在右边框那一格上：那种情况下 ``Canvas.put``
    只能把它丢掉，整行会短一格（帮助浮层曾因此每行 119 而非 120）。
    """
    keep: List[str] = []
    used = 0
    width_limit = max(1, budget - 1)
    for ch in str(text):
        w = display_width(ch)
        if len(keep) >= budget or used + w > width_limit:
            break
        keep.append(ch)
        used += w
    return pad("".join(keep), budget)


def _box_middle(text: str, budget: int) -> str:
    """在 ``budget`` 列内居中，多余部分交给 ``_box_fit`` 处理。"""
    return _box_fit(_center(text, budget), budget)


def _wrap_all(text: str, width: int) -> List[str]:
    out: List[str] = []
    for para in str(text).split("\n"):
        if not para.strip():
            out.append("")
            continue
        out.extend(wrap_text(para, max(4, width)))
    return out


def _center(text: str, width: int) -> str:
    tw = display_width(text)
    if tw >= width:
        return truncate(text, width)
    left = (width - tw) // 2
    return " " * left + text


def _log_entry(kind: str, text: str):
    from ..game.engine import LogEntry
    return LogEntry(kind, text)


def render_screen(content: Content, engine: GameEngine,
                  width: int = 120, height: int = 34,
                  app: Optional[GameApp] = None) -> List[str]:
    """渲染一屏（供测试与快照用）。"""
    viewer = app or GameApp(content, engine)
    return viewer.render(width, height).lines


def run(content: Content, engine: Optional[GameEngine] = None,
        store: Optional[SaveStore] = None, gates=None) -> int:
    """启动全屏界面，返回进程退出码。"""
    if engine is None:
        engine = GameEngine(content, gates=gates)
    app = GameApp(content, engine, store=store)
    term = Terminal()
    try:
        term.enter()
    except Exception as exc:  # 终端不可用 -> 退回纯文本
        print(f"终端初始化失败：{exc}", flush=True)
        return 1
    try:
        while not app.quit:
            size = term.size()
            w = max(app.MIN_W, size[0])
            h = max(app.MIN_H, size[1])
            term.draw(app.render(w, h).lines)
            key = read_key(block=True)
            if key == "EOF":
                break
            if key:
                app.handle(key)
    except QuitApp:
        pass
    except KeyboardInterrupt:
        pass
    finally:
        term.leave()
    return 0
