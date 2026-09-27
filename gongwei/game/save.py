"""存档读写。

默认位置：``%USERPROFILE%\\.gongwei\\save.json``（可用 ``GONGWEI_SAVE`` 覆盖）。
写入采用「临时文件 + 原子替换」，避免中途中断导致存档损坏。
读档对任何异常都返回 ``None`` 并给出原因，绝不因为一个坏档让游戏起不来。
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from .engine import GameEngine
from .models import Content

SAVE_VERSION = 1


def default_save_path() -> Path:
    override = os.environ.get("GONGWEI_SAVE")
    if override:
        return Path(override).expanduser()
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    return home / ".gongwei" / "save.json"


@dataclass
class SaveSummary:
    """读档前给玩家看的摘要。"""

    path: Path
    scene_title: str = ""
    time: str = ""
    place: str = ""
    clues: int = 0
    turn: int = 0
    stamp: str = ""
    ending: str = ""

    def describe(self) -> str:
        if not self.scene_title and not self.stamp:
            return "（空存档）"
        bits = [self.stamp or "存于——"]
        if self.scene_title:
            bits.append(self.scene_title)
        where = " · ".join(x for x in (self.place, self.time) if x)
        if where:
            bits.append(where)
        bits.append(f"线索 {self.clues}")
        if self.ending:
            bits.append(f"结局 {self.ending}")
        return " | ".join(bits)


class SaveStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else default_save_path()
        self.last_error: str = ""

    # -- 基础 ------------------------------------------------------------
    def exists(self) -> bool:
        try:
            return self.path.is_file()
        except OSError:
            return False

    def summary(self) -> Optional[SaveSummary]:
        data = self.read_raw()
        if data is None:
            return None
        state = data.get("state") or {}
        return SaveSummary(
            path=self.path,
            scene_title=str(data.get("title") or ""),
            time=str(state.get("time") or ""),
            place=str(state.get("place") or ""),
            clues=len(state.get("clues") or []),
            turn=int(state.get("turn") or 0),
            stamp=str(data.get("stamp") or ""),
            ending=str(state.get("ending") or ""),
        )

    def read_raw(self) -> Optional[dict]:
        if not self.exists():
            self.last_error = "没有找到存档"
            return None
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            self.last_error = f"读取失败：{exc}"
            return None
        try:
            data = json.loads(text)
        except (ValueError, TypeError) as exc:
            self.last_error = f"存档不是合法 JSON：{exc}"
            return None
        if not isinstance(data, dict):
            self.last_error = "存档格式不对（顶层不是对象）"
            return None
        version = data.get("v")
        if version is not None:
            try:
                too_new = int(version) > SAVE_VERSION
            except (TypeError, ValueError):
                # `v` 不是数字（手改坏了、或者别的程序写的）：按「读不动」处理。
                # 这里**绝不能**让 ValueError 穿出去——`summary()` 与 `load()`
                # 都从这里进来，而模块头的约定是「绝不因为一个坏档让游戏起不来」。
                self.last_error = f"存档版本号不是数字：{version!r}"
                return None
            if too_new:
                self.last_error = f"存档版本 {version} 太新，本版本读不了"
                return None
        return data

    # -- 写 --------------------------------------------------------------
    def save(self, engine: GameEngine, stamp: str = "") -> bool:
        payload = engine.save()
        payload["title"] = engine.current_title
        payload["stamp"] = stamp
        payload["v"] = SAVE_VERSION
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".save-", suffix=".tmp",
                                       dir=str(self.path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                    json.dump(payload, fh, ensure_ascii=False, indent=1)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, self.path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except OSError as exc:
            self.last_error = f"写入失败：{exc}"
            return False
        self.last_error = ""
        return True

    # -- 读 --------------------------------------------------------------
    def load(self, engine: GameEngine) -> Tuple[bool, str]:
        data = self.read_raw()
        if data is None:
            return False, self.last_error
        try:
            engine.load(data)
        except (KeyError, ValueError, TypeError) as exc:
            self.last_error = f"存档内容与本剧不匹配：{exc}"
            return False, self.last_error
        # 存档停在判决处，说明当时还没结算；读回来立刻补上结局。
        if engine.at_verdict():
            engine.finalize()
        return True, "读档完成"

    def clear(self) -> bool:
        try:
            self.path.unlink()
            return True
        except OSError as exc:
            self.last_error = f"删除失败：{exc}"
            return False


def describe(content: Content, path: Optional[Path] = None) -> str:
    store = SaveStore(path)
    info = store.summary()
    if info is None:
        return store.last_error or "（空存档）"
    return info.describe()
