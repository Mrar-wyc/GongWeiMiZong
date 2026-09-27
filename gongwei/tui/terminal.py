"""零依赖全屏 TUI 引擎（Windows / POSIX 通用）。

设计要点
--------
* **纯标准库**：Windows 上不需要 ``windows-curses``，直接使用 ANSI 转义序列 +
  ``msvcrt`` 读取按键；POSIX 上回退到 ``termios``/``tty``。
* **全屏无闪烁**：进入备用屏幕缓冲（alternate screen buffer），整帧先拼成字符串
  一次性写出，配合 ``\\x1b[H`` 归位，避免逐行刷新造成的撕裂。
* **CJK 双宽排版**：自带 ``char_width`` / ``display_width`` / ``wrap_text``，
  表格与边框在中文、日文、全角标点混排时依然对齐。
* **布局是纯函数**：``compose_frame`` 不碰终端，只吃 ``(state, size)`` 返回行列表，
  因此可以被单元测试与快照测试直接调用。
"""

from __future__ import annotations

import os
import shutil
import sys
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------
# ANSI 转义序列
# --------------------------------------------------------------------------

ESC = "\x1b"
RESET = f"{ESC}[0m"
BOLD = f"{ESC}[1m"
DIM = f"{ESC}[2m"
REVERSE = f"{ESC}[7m"
HIDE_CURSOR = f"{ESC}[?25l"
SHOW_CURSOR = f"{ESC}[?25h"
ENTER_ALT = f"{ESC}[?1049h"
LEAVE_ALT = f"{ESC}[?1049l"
CLEAR = f"{ESC}[2J"
HOME = f"{ESC}[H"

FG = {
    "black": 30,
    "red": 31,
    "green": 32,
    "yellow": 33,
    "blue": 34,
    "magenta": 35,
    "cyan": 36,
    "white": 37,
    "default": 39,
}

#: ``--no-color`` 置位；``NO_COLOR`` 环境变量另外在 color_enabled() 里看。
_COLOR_OFF = False
FG_BRIGHT = {
    "black": 90,
    "red": 91,
    "green": 92,
    "yellow": 93,
    "blue": 94,
    "magenta": 95,
    "cyan": 96,
    "white": 97,
}


def color_enabled() -> bool:
    """彩色现在是否开着。

    两条关掉的路子，都按 no-color.org 的约定：环境变量 ``NO_COLOR`` 只要非空
    就关（不论值是多少，包括 ``0``），命令行 ``--no-color`` 走 :func:`set_color`。
    """
    return not _COLOR_OFF and not os.environ.get("NO_COLOR")


def set_color(enabled: bool) -> None:
    """全局开关彩色（``main.py --no-color`` 用）。关掉后 :func:`fg` 返回空串，
    :func:`paint` 原样返回文本，屏幕上不会留下任何颜色码。"""
    global _COLOR_OFF
    _COLOR_OFF = not enabled


def fg(color: str, bright: bool = False) -> str:
    """返回设置前景色的转义序列；彩色关掉时返回空串。"""
    if not color_enabled():
        return ""
    table = FG_BRIGHT if bright else FG
    code = table.get(color, FG["default"])
    return f"{ESC}[{code}m"


def paint(text: str, color: Optional[str] = None, bright: bool = False,
          bold: bool = False, dim: bool = False) -> str:
    """给文本套上样式；``text`` 里如果已有样式也不会被破坏（结束时统一 RESET）。

    彩色关掉（``NO_COLOR`` / ``--no-color``）时连粗体、暗色一起省掉：无色出口
    的意思是「一个转义序列都不发」，而不是「只留下 BOLD/DIM」。
    """
    if not color_enabled():
        return text
    prefix = ""
    if color:
        prefix += fg(color, bright)
    if bold:
        prefix += BOLD
    if dim:
        prefix += DIM
    return f"{prefix}{text}{RESET}" if prefix else text


# --------------------------------------------------------------------------
# 宽字符与排版
# --------------------------------------------------------------------------


def char_width(ch: str) -> int:
    """单个字符在终端里占用的列数（0 / 1 / 2）。"""
    if ch == "\t":
        return 4
    code = ord(ch)
    if code == 0:
        return 0
    if code < 32 or 0x7F <= code < 0xA0:
        return 0
    if unicodedata.combining(ch):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    return 1


def display_width(text: str) -> int:
    """字符串在终端里的显示宽度。"""
    return sum(char_width(ch) for ch in text)


def strip_ansi(text: str) -> str:
    """去掉 ANSI 转义序列，用于测量已着色文本的宽度。"""
    out: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == ESC and i + 1 < n and text[i + 1] == "[":
            j = i + 2
            while j < n and not ("@" <= text[j] <= "~"):
                j += 1
            i = j + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def visible_width(text: str) -> int:
    """已着色文本的显示宽度。"""
    return display_width(strip_ansi(text))


def truncate(text: str, width: int, ellipsis: str = "…") -> str:
    """按显示宽度截断（不含 ANSI 处理，传入纯文本）。"""
    if width <= 0:
        return ""
    if display_width(text) <= width:
        return text
    limit = max(0, width - display_width(ellipsis))
    out: List[str] = []
    used = 0
    for ch in text:
        w = char_width(ch)
        if used + w > limit:
            break
        out.append(ch)
        used += w
    return "".join(out) + ellipsis


def wrap_text(text: str, width: int) -> List[str]:
    """按显示宽度折行。

    规则：
    * 显式 ``\\n`` 强制换行；
    * CJK 任意位置可断行，但避免行首出现收尾标点（、。，：；！？）」』】）；
    * 拉丁单词整体不拆断（放不下时整词移到下一行）。
    """
    if width <= 1:
        return [text] if text else [""]
    lines: List[str] = []
    for raw_line in text.split("\n"):
        if raw_line == "":
            lines.append("")
            continue
        lines.extend(_wrap_one(raw_line, width))
    return lines


_NO_LINE_START = "、。，．：；！？）」』】》〉·%…"
_NO_LINE_END = "（「『【《〈"


def _wrap_one(line: str, width: int) -> List[str]:
    out: List[str] = []
    cur: List[str] = []
    cur_w = 0
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        # 拉丁词整体处理
        if ch.isascii() and (ch.isalnum() or ch in "-_'"):
            j = i
            while j < n and line[j].isascii() and (line[j].isalnum() or line[j] in "-_'"):
                j += 1
            word = line[i:j]
            ww = display_width(word)
            if cur_w + ww > width and cur:
                out.append("".join(cur))
                cur, cur_w = [], 0
            if ww <= width:
                cur.append(word)
                cur_w += ww
            else:  # 超长单词硬切
                for c in word:
                    w = char_width(c)
                    if cur_w + w > width and cur:
                        out.append("".join(cur))
                        cur, cur_w = [], 0
                    cur.append(c)
                    cur_w += w
            i = j
            continue

        w = char_width(ch)
        if cur_w + w > width and cur:
            # 避免收尾标点被推到行首：把上一行末尾的字挪下来
            if ch in _NO_LINE_START and len(cur) > 1:
                moved = cur.pop()
                # `cur` 里既可能是一个汉字，也可能是一整个拉丁词（见上面 word 分支）：
                # 宽度要按 display_width 算，而且挪下来会撑破行宽时宁可不守禁则。
                if display_width(moved) + w <= width:
                    out.append("".join(cur))
                    cur = [moved, ch]
                    cur_w = display_width(moved) + w
                    i += 1
                    continue
                cur.append(moved)
            # 避免开引号/开括号落在行尾
            if cur and cur[-1] in _NO_LINE_END:
                moved = cur.pop()
                if display_width(moved) + w <= width:
                    out.append("".join(cur))
                    cur = [moved, ch]
                    cur_w = display_width(moved) + w
                    i += 1
                    continue
                cur.append(moved)
            out.append("".join(cur))
            cur, cur_w = [], 0
        cur.append(ch)
        cur_w += w
        i += 1
    out.append("".join(cur))
    return out


def pad(text: str, width: int, align: str = "left", fill: str = " ") -> str:
    """把（可能是着色过的）文本补/截到指定显示宽度。"""
    plain = strip_ansi(text)
    w = display_width(plain)
    if w > width:
        return truncate(plain, width)
    gap = width - w
    if align == "right":
        return fill * gap + text
    if align == "center":
        left = gap // 2
        return fill * left + text + fill * (gap - left)
    return text + fill * gap


# --------------------------------------------------------------------------
# 画笔：按显示列绘制，自动跳过宽字符占用的第二列
# --------------------------------------------------------------------------

#: 宽字符右半格的哨兵。用 NUL 而不是空串，是为了和「未写入的空格」区分开：
#: 空串会让后续 put() 把半个汉字覆盖掉（曾导致整屏右移一格）。
WIDE_TAIL = "\x00"


class Canvas:
    """字符画布：``put`` 以显示列定位，中文占两列会被正确占位。"""

    def __init__(self, width: int, height: int, fill: str = " ") -> None:
        self.width = width
        self.height = height
        self._grid: List[List[str]] = [[fill] * width for _ in range(height)]

    def put(self, x: int, y: int, text: str) -> None:
        """写入一段可能带样式的文本。

        样式转义序列被解析成「待输出前缀」，跟随下一个可见字符一起落到对应单元格，
        因此 ``display_width`` 与画布列号始终一致；文本末尾若出现过样式，会补一个 RESET。
        """
        if y < 0 or y >= self.height:
            return
        col = x
        pending = ""
        styled = False
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            if ch == ESC:
                j = i + 1
                if j < n and text[j] in "[(":
                    j += 1
                    while j < n and (text[j].isdigit() or text[j] == ";"):
                        j += 1
                    if j < n:
                        j += 1
                pending += text[i:j]
                i = j
                continue
            i += 1
            w = char_width(ch)
            if w == 0:
                continue
            if col >= self.width:
                break
            if col + w > self.width:
                # 宽字符右半格会越界：跳过它、空出最后一格，继续写后面的字符。
                # 若此处用 break，整行会短一格（``display_width`` 与画布列号脱节，
                # 曾在帮助浮层上表现为每行 119 而非 120）。调用方塞文字时请用
                # ``xxx_width - 4`` 之类留出右边距，别贴到边框上。
                col += 1
                continue
            if self._grid[y][col] == WIDE_TAIL:
                # 目标列是某个宽字符的右半格：吞掉这个字符，从下一列重试，
                # 否则会写出「半个汉字」。
                continue
            self._grid[y][col] = (pending + ch) if pending else ch
            if w == 2:
                # 宽字符占两格：右半格用哨兵标记，既不会被后写入的文本覆盖，
                # 也不会在拼接时冒出多余字符。
                self._grid[y][col + 1] = WIDE_TAIL
            if pending:
                styled = True
                pending = ""
            col += w
        if styled:
            last = self.width - 1
            while last >= 0 and self._grid[y][last] == WIDE_TAIL:
                last -= 1
            if last >= 0:
                self._grid[y][last] = self._grid[y][last] + RESET

    def hline(self, x: int, y: int, length: int, ch: str = "─") -> None:
        self.put(x, y, ch * max(0, length))

    def fill_rect(self, x: int, y: int, w: int, h: int, ch: str = " ") -> None:
        for row in range(y, y + h):
            self.put(x, row, ch * max(0, w))

    def clear_rect(self, x: int, y: int, w: int, h: int) -> None:
        """把一块矩形区域抹成空格（浮层/确认框画之前必须先抹）。

        没有这一步，底层画面会**从浮层里透出来**：``box()`` 只写边框和
        框内文字占用的格子，其余格子保留原样，于是标题屏的序章、副标题
        会正好落在帮助浮层的正文行上（实测帮助框里冒出「贤妃死风宫廷
        推理 · 终端探案」这类串行文字）。抹的时候连宽字符的右半格一起
        处理，免得留下半个汉字。
        """
        x2 = x + max(0, w)
        for row in range(y, y + h):
            if not (0 <= row < self.height):
                continue
            line = self._grid[row]
            for col in range(max(0, x), min(self.width, x2)):
                if line[col] == WIDE_TAIL and col > 0:
                    line[col - 1] = " "
                line[col] = " "

    def box(self, x: int, y: int, w: int, h: int, title: str = "",
            title_color: Optional[str] = None, border_color: Optional[str] = None,
            mark: str = "", mark_color: Optional[str] = None) -> None:
        """画一个圆角边框；``title`` 嵌在上边框里，``mark`` 是标题前的记号。

        ``mark``（如朱砂 ``◆``）自带颜色，占「记号 + 一格间隔」；记号与标题
        合起来仍然只吃 ``w - 4`` 列，右边框的 ``─`` 因此不会被挤掉。
        """
        if w < 2 or h < 2:
            return
        bc = border_color or "yellow"
        top = "╭" + "─" * (w - 2) + "╮"
        bot = "╰" + "─" * (w - 2) + "╯"
        self.put(x, y, paint(top, bc))
        self.put(x, y + h - 1, paint(bot, bc))
        for row in range(y + 1, y + h - 1):
            self.put(x, row, paint("│", bc))
            self.put(x + w - 1, row, paint("│", bc))
        if title:
            tc = title_color or bc
            if mark:
                # 记号单独上一段色，标题再接着画：两者颜色不同，不能拼成一个 label。
                head = f" {mark} "
                self.put(x + 2, y, paint(head, mark_color or tc))
                rest = truncate(f"{title} ", max(0, w - 4 - display_width(head)))
                self.put(x + 2 + display_width(head), y, paint(rest, tc, bold=True))
            else:
                self.put(x + 2, y, paint(truncate(f" {title} ", max(0, w - 4)), tc, bold=True))

    def render(self) -> List[str]:
        """把网格拼成每行恰好 ``width`` 显示列的字符串。

        ``put()`` 遇到「宽字符右半格越界」时会空出最后一格，所以这里再兜一次底：
        不够就补空格、超了就按显示宽裁掉。渲染层因此可以无条件断言
        ``visible_width(line) == width``，调用方不必逐处算边距。
        """
        out: List[str] = []
        for row in self._grid:
            line = "".join(row).replace(WIDE_TAIL, "")
            w = visible_width(line)
            if w < self.width:
                line += " " * (self.width - w)
            elif w > self.width:
                line = truncate(line, self.width)
            out.append(line)
        return out


# --------------------------------------------------------------------------
# 布局原语（纯函数，可测试）
# --------------------------------------------------------------------------


@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int


def split_columns(total_width: int, specs: Sequence[int], gap: int = 1) -> List[int]:
    """把总宽度按比例（``specs`` 为权重）切成若干列，保证总和不超过 total_width。"""
    if not specs:
        return []
    gaps = gap * (len(specs) - 1)
    usable = max(0, total_width - gaps)
    total_weight = sum(specs) or 1
    widths: List[int] = []
    used = 0
    for idx, weight in enumerate(specs):
        if idx == len(specs) - 1:
            widths.append(max(0, usable - used))
        else:
            w = usable * weight // total_weight
            widths.append(w)
            used += w
    return widths


# --------------------------------------------------------------------------
# 命令行编辑器
# --------------------------------------------------------------------------

class LineEditor:
    """一行文本的编辑状态：缓冲区 + 光标 + 历史。

    纯逻辑，不碰终端，所以可以脱离 tty 直接单测。中文字符按**字符**计数，
    显示宽度由 `display_width` 负责——两者不能混用，否则中文会算错光标位置。
    """

    def __init__(self, limit: int = 80) -> None:
        self.limit = limit
        self.buffer = ""
        self.cursor = 0                  # 字符下标，0..len(buffer)
        self.history: List[str] = []
        self._hist_at: Optional[int] = None
        self._draft = ""                 # 翻历史前正在敲的内容，翻回来时还原

    # -- 查询 ------------------------------------------------------------
    @property
    def text(self) -> str:
        return self.buffer

    def width(self) -> int:
        return display_width(self.buffer)

    def cursor_width(self) -> int:
        """光标左侧的显示宽度，用于把终端光标放到正确位置。"""
        return display_width(self.buffer[: self.cursor])

    def empty(self) -> bool:
        return not self.buffer.strip()

    # -- 编辑 ------------------------------------------------------------
    def insert(self, ch: str) -> bool:
        """插入一段文本（中文字符就是一个字符）。超出 limit 则拒收。"""
        if not ch:
            return False
        if len(self.buffer) + len(ch) > self.limit:
            return False
        self.buffer = self.buffer[: self.cursor] + ch + self.buffer[self.cursor:]
        self.cursor += len(ch)
        return True

    def backspace(self) -> bool:
        if self.cursor <= 0:
            return False
        self.buffer = self.buffer[: self.cursor - 1] + self.buffer[self.cursor:]
        self.cursor -= 1
        return True

    def delete(self) -> bool:
        if self.cursor >= len(self.buffer):
            return False
        self.buffer = self.buffer[: self.cursor] + self.buffer[self.cursor + 1:]
        return True

    def left(self) -> bool:
        if self.cursor <= 0:
            return False
        self.cursor -= 1
        return True

    def right(self) -> bool:
        if self.cursor >= len(self.buffer):
            return False
        self.cursor += 1
        return True

    def home(self) -> None:
        self.cursor = 0

    def end(self) -> None:
        self.cursor = len(self.buffer)

    def clear(self) -> None:
        self.buffer = ""
        self.cursor = 0
        self._hist_at = None
        self._draft = ""

    def kill_to_end(self) -> None:
        self.buffer = self.buffer[: self.cursor]

    def kill_word(self) -> None:
        """Ctrl+W：删掉光标前的一个词（按空白切）。"""
        i = self.cursor
        while i > 0 and self.buffer[i - 1] == " ":
            i -= 1
        while i > 0 and self.buffer[i - 1] != " ":
            i -= 1
        self.buffer = self.buffer[:i] + self.buffer[self.cursor:]
        self.cursor = i

    # -- 历史 ------------------------------------------------------------
    def remember(self, text: Optional[str] = None) -> None:
        text = self.buffer if text is None else text
        text = text.strip()
        if text and (not self.history or self.history[-1] != text):
            self.history.append(text)
        if len(self.history) > 200:
            del self.history[:-200]
        self._hist_at = None
        self._draft = ""

    def history_prev(self) -> bool:
        if not self.history:
            return False
        if self._hist_at is None:
            self._draft = self.buffer
            self._hist_at = len(self.history)
        if self._hist_at <= 0:
            return False
        self._hist_at -= 1
        self.buffer = self.history[self._hist_at]
        self.cursor = len(self.buffer)
        return True

    def history_next(self) -> bool:
        if self._hist_at is None:
            return False
        if self._hist_at >= len(self.history) - 1:
            self._hist_at = None
            self.buffer = self._draft
            self.cursor = len(self.buffer)
            self._draft = ""
            return True
        self._hist_at += 1
        self.buffer = self.history[self._hist_at]
        self.cursor = len(self.buffer)
        return True

    # -- 按键 ------------------------------------------------------------
    def handle(self, key: str) -> Optional[str]:
        """喂一个键。返回 `"ENTER"` 表示玩家提交了这一行，其余情况返回 None。"""
        if key == KEY_ENTER:
            return KEY_ENTER
        if key == KEY_BACKSPACE:
            self.backspace()
        elif key == "DELETE":
            self.delete()
        elif key == KEY_LEFT:
            self.left()
        elif key == KEY_RIGHT:
            self.right()
        elif key == "HOME":
            self.home()
        elif key == "END":
            self.end()
        elif key == KEY_UP:
            self.history_prev()
        elif key == KEY_DOWN:
            self.history_next()
        elif key == "CTRL_U":
            self.clear()
        elif key == "CTRL_K":
            self.kill_to_end()
        elif key == "CTRL_W":
            self.kill_word()
        elif len(key) == 1 and key >= " ":
            self.insert(key)
        return None


# --------------------------------------------------------------------------
# 按键读取
# --------------------------------------------------------------------------

KEY_UP = "UP"
KEY_DOWN = "DOWN"
KEY_LEFT = "LEFT"
KEY_RIGHT = "RIGHT"
KEY_ENTER = "ENTER"
KEY_ESC = "ESC"
KEY_BACKSPACE = "BACKSPACE"
KEY_TAB = "TAB"
KEY_RESIZE = "RESIZE"
KEY_EOF = "EOF"

_WIN_SPECIAL = {
    "H": KEY_UP,
    "P": KEY_DOWN,
    "K": KEY_LEFT,
    "M": KEY_RIGHT,
    "I": "PGUP",
    "Q": "PGDN",
    "G": "HOME",
    "O": "END",
    "S": "DELETE",
    "R": "INSERT",
    "k": KEY_LEFT,
}

_POSIX_ESCAPE = {
    "A": KEY_UP,
    "B": KEY_DOWN,
    "C": KEY_RIGHT,
    "D": KEY_LEFT,
    "5": "PGUP",
    "6": "PGDN",
    "H": "HOME",
    "F": "END",
}


class InputError(RuntimeError):
    """输入源不可用。"""


def read_key(block: bool = True) -> str:
    """读取一个按键，返回统一键名（可打印字符原样返回）。

    * Windows：``msvcrt.getwch``；方向键以 ``\\x00``/``\\xe0`` 前缀返回，被翻译。
    * POSIX：``termios`` 原始模式 + ``select``。
    """
    if os.name == "nt":
        import msvcrt

        if not block and not msvcrt.kbhit():
            return ""
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            nxt = msvcrt.getwch()
            return _WIN_SPECIAL.get(nxt, nxt)
        if ch == "\r":
            return KEY_ENTER
        if ch == "\n":
            return KEY_ENTER
        if ch == "\x1b":
            return KEY_ESC
        if ch == "\x08":
            return KEY_BACKSPACE
        if ch == "\t":
            return KEY_TAB
        if ch == "\x03":
            raise KeyboardInterrupt
        if ch == "\x04":
            return KEY_EOF
        if ch == "\x1a":
            raise KeyboardInterrupt
        return ch

    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        if not block and not select.select([fd], [], [], 0)[0]:
            return ""
        ch = os.read(fd, 1).decode("utf-8", "replace")
        if ch != "\x1b":
            if ch in ("\r", "\n"):
                return KEY_ENTER
            if ch == "\x7f":
                return KEY_BACKSPACE
            if ch == "\t":
                return KEY_TAB
            if ch == "\x03":
                raise KeyboardInterrupt
            if ch == "\x04":
                return KEY_EOF
            # UTF-8 多字节续读
            if ord(ch) >= 0x80:
                need = 1
                b = ord(ch)
                if b >= 0xF0:
                    need = 3
                elif b >= 0xE0:
                    need = 2
                extra = os.read(fd, need).decode("utf-8", "replace")
                return ch + extra
            return ch
        # 可能是转义序列
        if not select.select([fd], [], [], 0.05)[0]:
            return KEY_ESC
        seq = os.read(fd, 1).decode("utf-8", "replace")
        if seq == "[":
            if not select.select([fd], [], [], 0.05)[0]:
                return KEY_ESC
            final = os.read(fd, 1).decode("utf-8", "replace")
            return _POSIX_ESCAPE.get(final, final)
        return KEY_ESC
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


# --------------------------------------------------------------------------
# 终端会话
# --------------------------------------------------------------------------


class Terminal:
    """终端接管与整帧输出。同时兼容 Windows 控制台与 POSIX TTY。"""

    def __init__(self) -> None:
        self._entered = False
        self._saved_attrs = None

    # -- 生命周期 ---------------------------------------------------------
    def __enter__(self) -> "Terminal":
        self.enter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.leave()

    def enter(self) -> None:
        if self._entered:
            return
        if os.name == "nt":
            self._enable_windows_vt()
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        self._write(ENTER_ALT + CLEAR + HOME + HIDE_CURSOR)
        self._entered = True

    def leave(self) -> None:
        if not self._entered:
            return
        self._write(RESET + SHOW_CURSOR + LEAVE_ALT)
        self._entered = False

    @staticmethod
    def _enable_windows_vt() -> None:
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            for handle_id in (-11, -12):  # STDOUT, STDERR
                handle = kernel32.GetStdHandle(handle_id)
                mode = ctypes.c_ulong()
                if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                    continue
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VT
            kernel32.SetConsoleOutputCP(65001)
            kernel32.SetConsoleCP(65001)
        except Exception:
            pass

    # -- 尺寸与输出 -------------------------------------------------------
    @staticmethod
    def size() -> Tuple[int, int]:
        try:
            cols, rows = shutil.get_terminal_size(fallback=(100, 30))
        except Exception:
            cols, rows = 100, 30
        return max(40, cols), max(12, rows)

    @staticmethod
    def _write(text: str) -> None:
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except Exception:
            pass

    def draw(self, lines: Sequence[str]) -> None:
        """整帧重绘：游标归位后逐行写出，行尾清除残留。"""
        cols, _ = self.size()
        buf = [HOME]
        for line in lines:
            buf.append(line)
            w = visible_width(line)
            if w < cols:
                buf.append(" " * (cols - w))
            buf.append(f"{ESC}[K\r\n")
        self._write("".join(buf))


# --------------------------------------------------------------------------
# 主循环
# --------------------------------------------------------------------------


@dataclass
class App:
    """把「布局（纯函数）」与「终端」粘起来的最小应用框架。

    ``compose(state, cols, rows) -> (lines, keymap, should_quit)``：
    ``keymap`` 把键名映射到一个无参回调；回调抛 ``QuitApp`` 可退出。
    """

    compose: Callable[[int, int], Tuple[List[str], Dict[str, Callable[[], None]]]]
    self_driven: bool = True
    _quit: bool = False

    def quit(self) -> None:
        self._quit = True

    def run(self) -> int:
        term = Terminal()
        term.enter()
        try:
            while not self._quit:
                cols, rows = term.size()
                try:
                    lines, keymap = self.compose(cols, rows)
                except QuitApp:
                    break
                term.draw(lines)
                key = read_key(True)
                if key == "":
                    continue
                action = keymap.get(key)
                if action is None and key == "q":
                    break
                if action is None:
                    continue
                try:
                    action()
                except QuitApp:
                    break
        except KeyboardInterrupt:
            pass
        finally:
            term.leave()
        return 0


class QuitApp(Exception):
    """在按键回调里抛出以退出应用。"""
