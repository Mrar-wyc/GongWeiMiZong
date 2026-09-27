"""测试共用前奏：把「开局到第一幕结束」这套动作写在一个地方。

第一幕是有真门槛的（见 ``story.CRIME_SCENE`` 里那条 ``locked_if``）：

* 只走现场选项、不读档案，是过不去这一幕的；
* 而「勘验总录」（``01-FY-END``）自己又挂着 ``requires``——尸格、门户格、
  炉格、枕下笺纸、值夜单、小顺子问供都得先读过。

路线本身定义在 ``gongwei/autoplay.py``（``tools/walk.py`` 也从那里取），
这里只做转手与几个便利函数，**不要另抄一份路线**：门槛一调整，抄出去的那份
就会悄悄开始说谎。
"""

from __future__ import annotations

from typing import List

from gongwei.autoplay import (
    ACT1_GATE_READS as _ACT1_GATE_READS,
    OPENING_AT_GATE as _OPENING_AT_GATE,
    OPENING_NEXT as _OPENING_NEXT,
    OPENING_ROUTE as _OPENING_ROUTE,
    SCENE_SWEEP as _SCENE_SWEEP,
)
from gongwei.game import GameEngine

#: 现场四处勘验（不含「再验一次」——那一步在侧殿里还有入口）。
SCENE_SWEEP: List[str] = list(_SCENE_SWEEP)

#: 过第一幕门槛所需的**最小**阅读序（勘验总录自己挂着 requires，绕不过去）。
ACT1_GATE_READS: List[str] = list(_ACT1_GATE_READS)

#: 从开局到**刚站进侧殿**为止。绝大多数测试要的是这个：它跑完，玩法才真正展开。
OPENING: List[str] = list(_OPENING_ROUTE)

#: 只走到门槛前一步：还留在凤仪殿，而「移步侧殿」刚刚亮起来。
#: 想测「门槛到底拦没拦住」就用它。
OPENING_AT_GATE: List[str] = list(_OPENING_AT_GATE)


def preface(steps: List[str]) -> List[str]:
    """把一段路线接在「开场前奏」后面。

    给只关心后半程的测试用：``helpers.preface(["整理证物", ...])`` 就够了。
    前奏末尾已经迈过 ``"移步侧殿"``，调用方照旧写着它也不会出错——重复的那一步
    会被吃掉；``#`` 阅档同理，读过就跳过。
    """
    tail = list(steps)
    while tail and tail[0] == _OPENING_NEXT:
        tail.pop(0)
    return list(OPENING) + tail


def gate_preface(steps: List[str]) -> List[str]:
    """只用「刚好过门槛」的阅读序当前奏，不额外扫现场。

    给关心「证据很少时结局怎么判」的测试用：它刻意让核心线索尽量少。
    ``移步侧殿`` 要自己写在 ``steps`` 里（这一步本来就得玩家自己迈）。
    """
    return list(ACT1_GATE_READS) + list(steps)


def sweep_scene(engine: GameEngine) -> GameEngine:
    """走完现场勘验（含复看）并读全第一幕档案，返回同一个引擎。"""
    from gongwei.autoplay import play

    engine, _ = play(engine, OPENING)
    return engine


def open_act1(engine: GameEngine) -> GameEngine:
    """``sweep_scene`` 的别名，语义更清楚：把第一幕开完。"""
    return sweep_scene(engine)


def load_tool(name: str):
    """把 ``tools/`` 下的脚本当模块载入（tools 不是包，所以走 importlib）。

    测试要验的正是「这些工具自己会不会说谎」，所以必须加载磁盘上那一份，
    而不是把它的逻辑抄进测试里。
    """
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    path = root / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_tool_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
