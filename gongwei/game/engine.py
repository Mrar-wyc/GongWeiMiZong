"""游戏引擎：状态、选项生成、效果应用、审讯与结案。

引擎是**纯逻辑**——不认识终端，也不认识 ANSI；所有交互都通过
``GameEngine`` 暴露的方法与 ``GameState`` 完成，因此可以脚本化跑完整局。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .conditions import as_condition, time_index
from .models import Choice, Content, Dossier, Effect, Scene, Topic


# --------------------------------------------------------------------------
# 状态
# --------------------------------------------------------------------------


@dataclass
class LogEntry:
    kind: str          # narration | choice | clue | system | scene | dossier
    text: str


@dataclass
class DossierState:
    """玩家与某一份档案的关系。

    `read` 与 `guessed` 是两个不同的事实：读过了说明知道内容，`guessed` 说明
    这份档案**不在**档目里、是玩家自己把档号拼出来敲进去的。后者会在结案时
    改变评语——不该翻的东西翻了，本身就是一个叙事结果。
    """

    read: bool = False
    guessed: bool = False


@dataclass
class GameState:
    scene: str = ""
    chapter: int = 1
    #: 当前在第几案（1 = 案①凤仪殿，2 = 案②尚药局，3 = 案③景和旧案）。
    #: 由场景上的 `Scene.case` 推进；结局判定按它分流。
    case: int = 1
    time: str = "子时三刻"
    place: str = "凤仪殿"
    clues: List[str] = field(default_factory=list)
    items_owned: List[str] = field(default_factory=list)
    trust: Dict[str, int] = field(default_factory=dict)
    flags: Set[str] = field(default_factory=set)
    visited: Set[str] = field(default_factory=set)
    seen_choices: Set[str] = field(default_factory=set)
    topics_asked: List[str] = field(default_factory=list)
    log: List[LogEntry] = field(default_factory=list)
    accused: str = ""
    score: int = 0
    hurt: int = 0
    ending: str = ""
    turn: int = 0
    interrogating: str = ""
    #: 档号 -> 该档的状态。**键的存在即表示「已收录进档目」**；`guessed` 的条目
    #: 也在这里，但它的 read 为 True 而 discovered 语义要靠 `guessed` 排除。
    dossier_states: Dict[str, DossierState] = field(default_factory=dict)
    #: 玩家自己写的记事簿。
    notes: List[str] = field(default_factory=list)
    #: 玩家自己取的标题：档号 -> 标题；幕号 -> 标题（幕号以字符串存，便于序列化）。
    dossier_titles: Dict[str, str] = field(default_factory=dict)
    act_titles: Dict[str, str] = field(default_factory=dict)
    #: 当前摊开在案上的档案（纯显示状态，也存进档里，免得读档后案上空着）。
    open_dossier: str = ""
    _content: Optional[Content] = field(default=None, repr=False, compare=False)

    # -- 查询 ------------------------------------------------------------
    def trust_of(self, cid: str) -> int:
        return self.trust.get(cid, 0)

    def core_count(self) -> int:
        """已入手的核心证据数。

        注意：核心证据既可能是「线索」（入册）也可能是「物证」（入行囊）——
        `tea_set 安神茶盏` 就是后者。只数 `clues` 会漏算一件。
        """
        c = self._content
        if c is None:
            return 0
        held = set(self.clues) | set(self.items_owned)
        return sum(1 for x in held if x in c.items and c.items[x].core)

    def clue_name(self, cid: str) -> str:
        c = self._content
        if c and cid in c.items:
            return c.items[cid].name
        return cid

    def has(self, cid: str) -> bool:
        return cid in self.clues or cid in self.items_owned

    # -- 档案 ------------------------------------------------------------
    def dossier_known(self, did: str) -> bool:
        """这份档案在不在档目里（即：玩家已经收集到它）。"""
        st = self.dossier_states.get(did)
        return st is not None and not st.guessed

    def dossier_read(self, did: str) -> bool:
        st = self.dossier_states.get(did)
        return st is not None and st.read

    def dossier_guessed(self, did: str) -> bool:
        st = self.dossier_states.get(did)
        return st is not None and st.guessed

    def known_dossiers(self) -> List[str]:
        """档目内容：已收录的档号。自猜出来的不算——它们本来就不在册上。"""
        return sorted(d for d, st in self.dossier_states.items() if not st.guessed)

    def title_of_dossier(self, did: str) -> str:
        """档案的称谓：优先取玩家自己取的标题，其次取剧本里的标题。"""
        custom = self.dossier_titles.get(did, "")
        if custom:
            return custom
        c = self._content
        if c and did in c.dossiers:
            return c.dossiers[did].title
        return did

    def act_title_of(self, act: int) -> str:
        custom = self.act_titles.get(str(act), "")
        if custom:
            return custom
        c = self._content
        return c.act_title(act) if c else str(act)

    # -- 序列化 ----------------------------------------------------------
    def to_save(self) -> dict:
        return {
            "scene": self.scene,
            "chapter": self.chapter,
            "case": self.case,
            "time": self.time,
            "place": self.place,
            "clues": list(self.clues),
            "items_owned": list(self.items_owned),
            "trust": dict(self.trust),
            "flags": sorted(self.flags),
            "visited": sorted(self.visited),
            "seen_choices": sorted(self.seen_choices),
            "topics_asked": list(self.topics_asked),
            "log": [[e.kind, e.text] for e in self.log[-160:]],
            "accused": self.accused,
            "score": self.score,
            "hurt": self.hurt,
            "ending": self.ending,
            "turn": self.turn,
            "interrogating": self.interrogating,
            "dossiers": {d: [st.read, st.guessed] for d, st in sorted(self.dossier_states.items())},
            "notes": list(self.notes),
            "dossier_titles": dict(sorted(self.dossier_titles.items())),
            "act_titles": dict(sorted(self.act_titles.items())),
            "open_dossier": self.open_dossier,
        }

    @classmethod
    def from_save(cls, data: dict, content: Content) -> "GameState":
        state = cls(scene=data.get("scene") or content.start_scene, _content=content)
        state.chapter = int(data.get("chapter", 1))
        state.case = int(data.get("case", 1))
        state.time = data.get("time", state.time)
        state.place = data.get("place", state.place)
        state.clues = list(data.get("clues", []))
        state.items_owned = list(data.get("items_owned", []))
        state.trust = {k: int(v) for k, v in (data.get("trust") or {}).items()}
        state.flags = set(data.get("flags", []))
        state.visited = set(data.get("visited", []))
        state.seen_choices = set(data.get("seen_choices", []))
        state.topics_asked = list(data.get("topics_asked", []))
        state.log = [LogEntry(k, t) for k, t in data.get("log", [])]
        state.accused = data.get("accused", "")
        state.score = int(data.get("score", 0))
        state.hurt = int(data.get("hurt", 0))
        state.ending = data.get("ending", "")
        state.turn = int(data.get("turn", 0))
        state.interrogating = data.get("interrogating", "")
        for did, pair in (data.get("dossiers") or {}).items():
            read, guessed = (list(pair) + [False, False])[:2]
            state.dossier_states[did] = DossierState(bool(read), bool(guessed))
        state.notes = list(data.get("notes", []))
        state.dossier_titles = {k: v for k, v in (data.get("dossier_titles") or {}).items()}
        state.act_titles = {str(k): v for k, v in (data.get("act_titles") or {}).items()}
        state.open_dossier = data.get("open_dossier", "")
        return state


# --------------------------------------------------------------------------
# 菜单项与变化摘要
# --------------------------------------------------------------------------


@dataclass
class Option:
    index: int
    label: str
    detail: str = ""
    enabled: bool = True
    hint: str = ""
    wants: str = ""
    tag: str = ""
    gated: bool = False
    asked: bool = False
    action: Optional[Callable[[], object]] = field(default=None, repr=False)


@dataclass
class Update:
    toasts: List[str] = field(default_factory=list)
    new_clues: List[str] = field(default_factory=list)
    new_items: List[str] = field(default_factory=list)
    new_dossiers: List[str] = field(default_factory=list)
    trust_changes: List[Tuple[str, int]] = field(default_factory=list)
    narration: List[str] = field(default_factory=list)
    scene_changed: bool = False
    ended: bool = False


# --------------------------------------------------------------------------
# 引擎
# --------------------------------------------------------------------------


class GameEngine:
    def __init__(self, content: Content, state: Optional[GameState] = None,
                 gates: Optional[Dict[str, Tuple[Callable[[GameState], bool], str]]] = None) -> None:
        self.content = content
        self._topic_by_char: Dict[str, List[Topic]] = {}
        for topic in content.topics.values():
            self._topic_by_char.setdefault(topic.owner, []).append(topic)
        self._topic_gate: Dict[str, Callable[[GameState], bool]] = {}
        self._topic_hint: Dict[str, str] = {}
        for tid, (gate, hint) in (gates or {}).items():
            self.register_topic_gate(tid, gate, hint)
        self.state = state or self.new_game()
        self.state._content = content

    # -- 构建 ------------------------------------------------------------
    def new_game(self) -> GameState:
        c = self.content
        state = GameState(
            scene=c.start_scene,
            time="",
            place="",
            _content=c,
        )
        state.trust = {cid: ch.trust for cid, ch in c.characters.items()}
        for did in c.starter_dossiers:
            if did in c.dossiers:
                state.dossier_states[did] = DossierState(read=False, guessed=False)
        self.state = state
        self.go_to(c.start_scene)
        return state

    # -- 场景 ------------------------------------------------------------
    @property
    def scene(self) -> Scene:
        return self.content.scenes[self.state.scene]

    @property
    def current_title(self) -> str:
        return self.scene.title

    # -- 档案：读取与收录 ------------------------------------------------
    def dossier_exists(self, did: str) -> bool:
        return did in self.content.dossiers

    def dossier_case(self, did: str) -> int:
        """这份档案属于第几案（按它的幕号查 `Content.act_case`）。"""
        d = self.content.dossiers.get(did)
        if d is None:
            return 0
        return self.content.act_case.get(d.act, 1)

    def can_read_dossier(self, did: str) -> bool:
        """这份档案现在能不能打开。

        - 档号不存在 → 不能
        - 已经在档目里 → 能
        - `requires` 条件满足 → 能（用于少数「必须先知道某件事」的档案）
        - 属于还没走到的案子 → 不能（剧情锁：后面的案子，档号拼对了也调不到）
        - 否则 → 不能：玩家得先在别的档案里找到它
        """
        d = self.content.dossiers.get(did)
        if d is None:
            return False
        if self.state.dossier_known(did):
            return True
        gate = _cond(d.requires)
        if gate is not None and bool(gate(self.state)):
            return True
        if self.dossier_case(did) > self.state.case:
            return False
        return gate is None

    def collect_dossier(self, did: str, upd: Optional[Update] = None,
                        guessed: bool = False) -> bool:
        """把一份档案收进档目。已收录则返回 False（不重复报喜）。"""
        if did not in self.content.dossiers:
            return False
        st = self.state.dossier_states.get(did)
        if st is None:
            self.state.dossier_states[did] = DossierState(read=False, guessed=guessed)
            if upd is not None and not guessed:
                upd.new_dossiers.append(did)
            return True
        return False

    def read_dossier(self, did: str) -> Update:
        """打开一份档案。这是本作最主要的动作。"""
        upd = Update()
        d = self.content.dossiers.get(did)
        if d is None:
            raise KeyError(f"剧本缺少档案: {did}")
        if not self.can_read_dossier(did):
            raise PermissionError(f"这份档案还不能调阅: {did}")
        first = not self.state.dossier_read(did)
        guessed = False
        if did not in self.state.dossier_states:
            # 档目里没有、也没有 requires 拦着——玩家是自己拼出档号的
            guessed = True
            self.collect_dossier(did, upd, guessed=True)
        st = self.state.dossier_states[did]
        st.read = True
        self.state.open_dossier = did
        self.state.turn += 1
        if first:
            upd.new_dossiers.append(did)
            upd.toasts.append(d.found_msg or "//得到新档案——收录至档目//")
            body = d.body
            if guessed:
                body = body + "\n\n——这份档案不在册上。是你自己把档号拼出来的。"
            self.state.log.append(LogEntry("dossier", body))
            upd.narration.append(body)
        else:
            self.state.log.append(LogEntry(
                "system", f"重阅 {did} · {self.state.title_of_dossier(did)}"))
        self.apply_effect(d.effect, upd)
        for link in d.links:
            self.collect_dossier(link, upd)
        return upd

    def close_dossier(self) -> None:
        self.state.open_dossier = ""

    def dossier_hints(self, did: str) -> int:
        """档目里那个灰色数字：这份档案牵着的、玩家还没收集到的档数。

        只给数目、不给号码——玩家得从正文里自己推出下一个档号。
        """
        d = self.content.dossiers.get(did)
        if d is None:
            return 0
        missing = 0
        for link in d.links:
            if link not in self.content.dossiers:
                continue                      # 悬空关联由审计器负责报错
            if not self.state.dossier_known(link):
                missing += 1
        return missing

    def dossier_index(self) -> List[Tuple[int, List[Tuple[str, str, int, bool]]]]:
        """档目：按幕分组。

        返回 `[(幕号, [(档号, 标题, 未收集关联数, 是否读过), ...]), ...]`。
        """
        out: List[Tuple[int, List[Tuple[str, str, int, bool]]]] = []
        for act in self.content.act_numbers():
            rows: List[Tuple[str, str, int, bool]] = []
            for did in self.state.known_dossiers():
                d = self.content.dossiers.get(did)
                if d is None or d.act != act:
                    continue
                rows.append((did, self.state.title_of_dossier(did),
                             self.dossier_hints(did), self.state.dossier_read(did)))
            if rows:
                out.append((act, rows))
        return out

    def search_dossiers(self, term: str, limit: int = 40) -> List[Tuple[str, str, str]]:
        """在**已读**档案里检索，返回 `[(档号, 标题, 命中片段), ...]`。

        只搜已读的：没读过的档案对玩家来说还不存在，搜出来就是剧透。
        """
        t = (term or "").strip()
        if not t:
            return []
        out: List[Tuple[str, str, str]] = []
        for did in sorted(self.state.dossier_states):
            if not self.state.dossier_read(did):
                continue
            d = self.content.dossiers.get(did)
            if d is None:
                continue
            hay = f"{d.title}\n{d.body}"
            idx = hay.find(t)
            if idx < 0:
                continue
            lo = max(0, idx - 18)
            hi = min(len(hay), idx + len(t) + 22)
            snippet = hay[lo:hi].replace("\n", " ")
            if lo > 0:
                snippet = "…" + snippet
            if hi < len(hay):
                snippet = snippet + "…"
            out.append((did, self.state.title_of_dossier(did), snippet))
            if len(out) >= limit:
                break
        return out

    def dossier_view(self, did: str, width: int = 74) -> List[str]:
        """把一份档案排成可显示的正文行（两端共用，避免各写一套排版）。"""
        d = self.content.dossiers.get(did)
        if d is None:
            return [f"找不到档案：{did}"]
        lines: List[str] = []
        head = f"{did} · {self.state.title_of_dossier(did)}"
        lines.append(head)
        meta = self._dossier_meta(d)
        if meta:
            lines.append(meta)
        lines.append("")
        for para in (d.body or "").split("\n"):
            if not para.strip():
                lines.append("")
                continue
            lines.extend(_wrap_cjk(para, width))
        hints = self.dossier_hints(did)
        if hints:
            lines.append("")
            lines.append(f"——这份档案还牵着 {hints} 份未收集的档。")
        return lines

    def _dossier_meta(self, d: Dossier) -> str:
        bits: List[str] = []
        if d.time_code:
            bits.append(d.time_code)
        if d.place_code:
            bits.append(d.place_code)
        if d.people:
            names = []
            for pid in d.people:
                ch = self.content.characters.get(pid)
                names.append(ch.name if ch else pid)
            bits.append("、".join(names))
        return " · ".join(bits)

    # -- 选项 ------------------------------------------------------------
    def options(self) -> List[Option]:
        scene = self.scene
        state = self.state
        if scene.kind == "ending":
            return []
        raw: List[Tuple[Choice, Optional[str]]] = [(ch, None) for ch in scene.choices]
        if scene.interlocutor:
            raw.extend((ch, tid) for ch, tid in self._interrogation_choices(scene.interlocutor))
        options: List[Option] = []
        for choice, topic_id in raw:
            vis = _cond(choice.visible_if)
            lock = _cond(choice.locked_if or choice.locked_by)
            if vis is not None and not vis(state):
                continue
            if not choice.repeatable and choice.key in state.seen_choices:
                continue
            enabled = True
            hint = ""
            if lock is not None and lock(state):
                enabled = False
                hint = choice.locked_hint or "条件不足"
            asked = choice.key in state.seen_choices
            options.append(Option(
                index=0,
                label=choice.label,
                detail=choice.detail,
                enabled=enabled,
                hint=hint,
                wants=choice.wants,
                tag=choice.tag,
                gated=(vis is not None or lock is not None),
                asked=asked,
                action=(lambda c=choice, t=topic_id: self.choose(c, t)),
            ))
        for i, opt in enumerate(options, start=1):
            opt.index = i
        return options

    # -- 审讯 ------------------------------------------------------------
    def register_topic_gate(self, topic_id: str, gate, hint: str) -> None:
        self._topic_gate[topic_id] = gate
        self._topic_hint[topic_id] = hint

    def topics_for(self, cid: str) -> List[Topic]:
        return self._topic_by_char.get(cid, [])

    def _interrogation_choices(self, cid: str) -> List[Tuple[Choice, Optional[str]]]:
        out: List[Tuple[Choice, Optional[str]]] = []
        scene_hall = getattr(self.scene, "hall", "")
        for topic in self.topics_for(cid):
            gate = self._topic_gate.get(topic.id)
            enabled = True
            hint = ""
            if gate is not None and not gate(self.state):
                enabled = False
                hint = self._topic_hint.get(topic.id, "尚不可问")
            asked = topic.key in self.state.seen_choices
            if asked and enabled:
                continue                     # 问过且没新内容：收起来
            ch = Choice(
                label=topic.label,
                detail="出示证物" if topic.present else "",
                to="",
                effect=topic.effect,
                locked_if=(lambda s: True) if not enabled else None,
                locked_hint=hint,
                wants=cid,
                tag="interrogate",
                repeatable=False,
            )
            out.append((ch, topic.id))
        leave = Choice(
            label="作揖告退 · 结束对「{}」的问询".format(
                self.content.characters[cid].name if cid in self.content.characters else cid
            ),
            # 案② 的问询回到案② 的前厅：`Scene.hall` 不写才用全局那个（案① 的侧殿）。
            to=scene_hall or self.content.interrogate_hall,
            tag="interrogate",
            wants=cid,
            repeatable=True,
        )
        out.append((leave, None))
        return out

    # -- 选择 ------------------------------------------------------------
    def choose(self, choice: Choice, topic_id: Optional[str] = None) -> Update:
        upd = Update()
        self.state.seen_choices.add(choice.key)
        if choice.suspect:
            self.state.accused = choice.suspect
            self.state.flags.add("accused")
        if topic_id:
            self.state.seen_choices.add(f"topic::{topic_id}")
            if topic_id not in self.state.topics_asked:
                self.state.topics_asked.append(topic_id)
            said = self.content.topics[topic_id].response
            if said:
                self.state.log.append(LogEntry("narration", said))
                upd.narration.append(said)
        self.apply_effect(choice.effect, upd)
        self.state.turn += 1
        target = choice.effect.scene or choice.to
        if target:
            self.go_to(target, upd)
        elif not topic_id:
            self.state.log.append(LogEntry("choice", choice.label))
        return upd

    # -- 效果 ------------------------------------------------------------
    def apply_effect(self, eff: Optional[Effect], upd: Optional[Update] = None) -> Update:
        upd = upd or Update()
        if eff is None:
            return upd
        state = self.state
        c = self.content
        for cid in eff.add_clues:
            if cid in state.clues or cid in state.items_owned:
                continue
            state.clues.append(cid)
            item = c.items.get(cid)
            name = item.name if item else cid
            upd.new_clues.append(name)
            upd.toasts.append(f"得到线索 · {name}")
            state.log.append(LogEntry("clue", f"【线索】{name} —— {item.desc if item else ''}"))
        for iid in eff.add_items:
            if iid in state.items_owned or iid in state.clues:
                continue
            state.items_owned.append(iid)
            item = c.items.get(iid)
            name = item.name if item else iid
            upd.new_items.append(name)
            upd.toasts.append(f"收入行囊 · {name}")
            state.log.append(LogEntry("clue", f"【物证】{name} —— {item.desc if item else ''}"))
        for cid, delta in eff.trust:
            if cid not in c.characters:
                continue
            before = state.trust_of(cid)
            after = max(0, min(100, before + delta))
            state.trust[cid] = after
            if after != before:
                upd.trust_changes.append((cid, after - before))
        for flag in eff.flags:
            state.flags.add(flag)
        for did in eff.add_dossiers:
            self.collect_dossier(did, upd)
        if eff.time and time_index(eff.time) >= time_index(state.time):
            state.time = eff.time
        state.score += eff.score
        state.hurt += eff.hurt
        if eff.text:
            state.log.append(LogEntry("narration", eff.text))
            upd.narration.append(eff.text)
        return upd

    # -- 场景切换 --------------------------------------------------------
    def go_to(self, scene_id: str, upd: Optional[Update] = None) -> Update:
        upd = upd or Update()
        if scene_id not in self.content.scenes:
            raise KeyError(f"剧本缺少场景: {scene_id}")
        scene = self.content.scenes[scene_id]
        self.state.scene = scene_id
        first_visit = scene_id not in self.state.visited
        self.state.visited.add(scene_id)
        if scene.time and time_index(scene.time) >= time_index(self.state.time):
            self.state.time = scene.time
        if scene.place:
            self.state.place = scene.place
        # 场景自带幕号/案号时才推进——多数场景（问询、查证）沿用当前那一幕。
        if scene.act:
            self.state.chapter = scene.act
        if scene.case:
            self.state.case = scene.case
        self.state.interrogating = scene.interlocutor
        upd.scene_changed = True
        if scene.body and first_visit:
            self.state.log.append(LogEntry("scene", scene.body))
        if scene.on_enter is not None:
            self.apply_effect(scene.on_enter, upd)
        if scene.kind == "ending":
            self.state.ending = scene_id
            upd.ended = True
        return upd

    # -- 结案 ------------------------------------------------------------
    def at_verdict(self) -> bool:
        """当前是否停在「判决过渡场景」（应当立即结算结局）。"""
        return self.state.scene in set(self.content.verdict_scenes)

    def accuse(self, suspect_id: str) -> Update:
        self.state.accused = suspect_id
        self.state.flags.add("accused")
        upd = Update()
        target = self.content.verdicts.get(suspect_id, ("", ""))[0]
        if target:
            self.go_to(target, upd)
        return upd

    def pick_ending(self) -> str:
        """按规则表取第一个命中的结局（只在本案的规则里挑）。

        规则表全不命中时退回「查不出来」——那是剧本里语义上的兜底，
        而**不是**列表最后一条（最后一条是「辞官」，只能由 resign flag 触发）。
        """
        fallback = "ending_bystander"
        rules = [e for e in self.content.endings if e.case == self.state.case]
        if not rules:
            rules = list(self.content.endings)
        if any(e.id == fallback for e in rules):
            preferred = fallback
        else:
            preferred = rules[-1].id
        for rule in rules:
            if rule.rule is None or rule.rule(self.state):
                return rule.id
        return preferred

    def finalize(self) -> str:
        eid = self.pick_ending()
        self.go_to(eid)
        self.state.ending = eid
        return eid

    # -- 存档 ------------------------------------------------------------
    def save(self) -> dict:
        return {"v": 1, "state": self.state.to_save()}

    def load(self, data: dict) -> None:
        self.state = GameState.from_save(data.get("state", {}), self.content)
        self.state._content = self.content


def _cond(spec):
    if spec is None:
        return None
    if callable(spec):
        return spec
    return as_condition(str(spec))


# --------------------------------------------------------------------------
# 排版辅助
# --------------------------------------------------------------------------

def char_width(ch: str) -> int:
    """单个字符占几列（东亚宽字符占两列）。

    这里有意重复了 `gongwei/tui/terminal.py` 里的同名逻辑：引擎**不能**依赖
    终端层（网页端与测试脚本都要用引擎，而它们不认得 ANSI）。两份实现的一致性
    由 `tests/test_dossier.py` 里的一条对照测试盯着。
    """
    import unicodedata
    if not ch:
        return 0
    if unicodedata.combining(ch):
        return 0
    cp = ord(ch)
    if 0x1F300 <= cp <= 0x1FAFF:          # emoji 与符号
        return 2
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def display_width(text: str) -> int:
    return sum(char_width(ch) for ch in text)


def _wrap_cjk(text: str, width: int) -> List[str]:
    """按显示宽度折行；不切散宽字符（否则终端里会错位）。"""
    if width <= 0:
        return [text]
    out: List[str] = []
    cur = ""
    used = 0
    for ch in text:
        w = char_width(ch)
        if used + w > width and cur:
            out.append(cur)
            cur, used = "", 0
        cur += ch
        used += w
    if cur:
        out.append(cur)
    return out


def group_options(options: Sequence[Option]) -> List[Tuple[str, List[Option]]]:
    """把选项按类型分节，便于 UI 展示。"""
    buckets: List[Tuple[str, List[Option]]] = []
    for opt in options:
        if opt.detail.startswith("出示证物"):
            title = "出示证物"
        elif opt.tag == "interrogate":
            title = "问询"
        elif opt.tag == "accuse":
            title = "结案陈词"
        else:
            title = "调查"
        if not buckets or buckets[-1][0] != title:
            buckets.append((title, []))
        buckets[-1][1].append(opt)
    return buckets
