"""数据模型：线索、物品、人物、效果、条件、场景、结局。

所有内容都是**纯数据**（``dataclass``），因此剧情可以整体重写而不动引擎，
引擎也可以被脚本化测试直接驱动。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------
# 条件：纯函数 (state) -> bool
# --------------------------------------------------------------------------

Condition = Callable[[object], bool]

# --------------------------------------------------------------------------
# 内容实体
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    """一条线索或一件物品。

    ``core=True`` 表示「核心证据」：同时满足「必须靠调查取得」与
    「直指真凶的手段／动机／机会」。真结局的门槛就是集齐全部核心证据。
    """

    id: str
    name: str
    desc: str = ""
    core: bool = False
    tag: str = "clue"  # clue | item | testimony | doc

    @property
    def is_item(self) -> bool:
        return self.tag == "item"


@dataclass(frozen=True)
class Character:
    id: str
    name: str
    role: str
    trust: int = 40
    desc: str = ""
    # 好感度达到该值就算「已可深谈」。**999 表示永不深谈**（已故的人、以及
    # 信任只减不增的人）；其余数值必须 ≤ 这个人信任能到的上限——写在够不到
    # 的地方等于没写（`tests/test_story.py` 的 TrustCeilingTest 会查）。
    # 面板上那个「已可深谈」标记**还没做**，别以为现在能看见。
    confide_at: int = 65
    #: 这个人属于哪几桩案子（案号）。面板只列本案的人情——否则案① 开局就能在
    #: 「人情」里看到尚药局那几位，凶手是谁还没死人就先露了底。
    #: 写成元组是为了**跨案**的人：冯保在案② 与案③ 都露面，于是他是 ``(2, 3)``。
    case: Tuple[int, ...] = (1,)


@dataclass
class Effect:
    """一次选择对世界造成的全部改动。"""

    text: Optional[str] = None          # 选择之后追加的旁白
    add_clues: Tuple[str, ...] = ()
    add_items: Tuple[str, ...] = ()
    add_dossiers: Tuple[str, ...] = ()  # 收录档案（只登记，不自动打开）
    trust: Tuple[Tuple[str, int], ...] = ()
    flags: Tuple[str, ...] = ()
    time: Optional[str] = None          # 推进时辰
    scene: Optional[str] = None
    score: int = 0
    hurt: int = 0                       # 自损（如被皇帝忌惮）


@dataclass
class Choice:
    """一个可选动作。"""

    label: str
    to: str = ""
    detail: str = ""                              # 悬停/旁注说明
    effect: Effect = field(default_factory=Effect)
    visible_if: Optional[Condition] = None        # 不满足则不显示
    locked_if: Optional[Condition] = None         # 满足则显示但灰置
    locked_hint: str = ""                         # 灰置原因（需明示，避免玩家瞎猜）
    repeatable: bool = True                       # 做过之后是否仍显示
    locked_by: Optional[Condition] = None         # locked_if 的别名（剧本里更顺手）
    wants: str = ""                               # 该选项关注的角色 id（用于面板高亮）
    tag: str = ""                                 # special: "accuse" | "interrogate" | "ending"
    suspect: str = ""                             # 指认选项：被指认者的角色 id

    @property
    def key(self) -> str:
        # 有些选项没有 to，但带 effect.scene（例如结案指认），key 必须仍然唯一
        return f"{self.effect.scene or self.to}::{self.label}"


@dataclass
class Topic:
    """审讯话题：对一个嫌疑人可以问的一件事。"""

    id: str
    owner: str          # 角色 id
    label: str
    response: str       # 对方的回答（会被写进日志）
    effect: Effect = field(default_factory=Effect)
    present: bool = False   # 是否为「出示证物」（证物对质）

    @property
    def key(self) -> str:
        return f"topic::{self.id}"


@dataclass(frozen=True)
class Dossier:
    """一份档案。

    这是「查档案」玩法的核心单位：档号既是标识也是玩家的操作对象——玩家要
    自己把档号拼出来敲进去（或从档目里点开）。

    档号形状 `时码-地点码-在场人`，例如 `01-FY-WDH`。玩家从已读档案的正文里
    推出下一个档号，这是本作的主要推理动作。

    - `requires`：打开条件。为 `None` 表示「只要敲对档号就能打开」——
      前提是这份档案已经在档目里（`discovered`），或者它本身就没有前置。
      这条是防止玩家开局乱敲档号直达结局的闸门。
    - `links`：这份档案正文里点到的其他档号。档目里显示的灰色 `(n)` 就是
      「这些关联档里还有几份没收集到」——只给数目、不给号码。
    - `found_msg`：玩家第一次打开时追加的那行系统提示。
    """

    id: str
    title: str
    act: int = 1
    time_code: str = ""
    place_code: str = ""
    people: Tuple[str, ...] = ()
    body: str = ""
    links: Tuple[str, ...] = ()
    requires: Optional[Condition] = None
    effect: Effect = field(default_factory=Effect)
    found_msg: str = "//得到新档案——收录至档目//"

    @property
    def act_code(self) -> str:
        """档号里的时辰码（`01`）。"""
        return self.time_code or self.id.split("-")[0]


@dataclass
class Scene:
    id: str
    title: str
    place: str
    time: str
    body: str = ""
    choices: List[Choice] = field(default_factory=list)
    on_enter: Effect = field(default_factory=Effect)
    interlocutor: str = ""   # 非空表示这是审讯场景
    kind: str = "scene"      # scene | title | interrogation | ending
    #: 这一幕属于第几案：0 = 不改动当前案号，1 = 案①凤仪殿，2 = 案②尚药局，3 = 案③景和旧案。
    #: 结局判定按案号分流（见 `GameEngine.pick_ending`），所以每个新案的场景都要写。
    case: int = 0
    #: 这一幕是第几幕：0 = 不改动当前幕号。幕号同时是档号的时码前缀（第六幕 = 06-xx）。
    act: int = 0
    #: 问询场景的退场去处：不写就回 `Content.interrogate_hall`（案① 的侧殿）。
    #: 案② 的问询要回案② 自己的前厅，所以每个 talk_* 场景都要写。
    hall: str = ""


@dataclass
class EndingRule:
    id: str
    title: str
    subtitle: str = ""
    body: str = ""
    rule: Optional[Condition] = None      # 从上往下取第一个命中的
    rank: str = ""                        # 史书评语用
    #: 这条结局属于第几案。`pick_ending` 只在自己那一案的规则里挑，
    #: 否则案① 的判据（比如 `accused_is("WDH")`）在案② 里仍然成立，会把结局抢走。
    case: int = 1


@dataclass
class Content:
    """一整部剧本。"""

    items: Dict[str, Item]
    characters: Dict[str, Character]
    scenes: Dict[str, Scene]
    topics: Dict[str, Topic]
    endings: List[EndingRule]
    start_scene: str
    verdict_scene: str
    interrogate_hall: str = ""
    verdict_scenes: Sequence[str] = ()   # 判决过渡场景（进入后即结算结局）
    verdicts: Dict[str, Tuple[str, str]] = field(default_factory=dict)  # suspect_id -> (场景 id, 结案说明)
    title: str = "宫闱迷踪"
    subtitle: str = "古风宫廷推理 · 终端探案"
    prologue: str = ""
    version: str = "1.0"
    #: 档案库。空字典表示这一版还没有档案层（v1 剧本就是如此）。
    dossiers: Dict[str, Dossier] = field(default_factory=dict)
    #: 开局就在档目里的档号（通常只有 `00-readme`）。
    starter_dossiers: Sequence[str] = ()
    #: 幕号 -> 幕名。玩家可以用「幕 <n> <标题>」覆盖。
    act_titles: Dict[int, str] = field(default_factory=dict)
    #: 幕号 -> 案号。**「哪几幕属于哪一案」的唯一事实源**，剧情锁按它算：
    #: 还没走到的案子，档号即使拼对了也调不出来。缺省视为第一案。
    act_case: Dict[int, int] = field(default_factory=dict)

    def core_items(self) -> List[Item]:
        return [i for i in self.items.values() if i.core]

    def core_total(self) -> int:
        return len(self.core_items())

    # -- 档案 ------------------------------------------------------------
    def dossiers_of_act(self, act: int) -> List[Dossier]:
        """某一幕的全部档案，按时码与档号排序（档目要按这个顺序显示）。"""
        rows = [d for d in self.dossiers.values() if d.act == act]
        rows.sort(key=lambda d: (d.time_code or d.id, d.id))
        return rows

    def act_numbers(self) -> List[int]:
        return sorted({d.act for d in self.dossiers.values()})

    def act_title(self, act: int) -> str:
        if act in self.act_titles:
            return self.act_titles[act]
        rows = self.dossiers_of_act(act)
        return rows[0].act_code if rows else str(act)

    def dossier_place(self, did: str) -> str:
        d = self.dossiers.get(did)
        return d.place_code if d else ""
