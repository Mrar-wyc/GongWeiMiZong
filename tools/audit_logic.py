"""游戏逻辑体检：查那些「不报错、但会坏事」的判定漏洞。

`audit_story.py` 证明「东西都摸得到」，`audit_gates.py` 证明「门禁都够得着」。
本工具补的是第三类问题——**摸得到、也够得着，但顺序不对 / 出口会消失 / 兜底会走偏**：

1. **幕推进有没有上锁**：某个选项把玩家带到更靠后的一幕（或下一案），
   但它既没有 `locked_if` 也没有 `visible_if` —— 那就是一条可以直穿的后门。
   （`tag="accuse"` 的结案选项不算：提前收手本身就是一条设计好的路。）

   **「靠后」按图上的远近算，不按幕号算**：幕号不是游玩顺序 —— 第二幕
   「尚药局与掖庭」其实是第三幕侧殿问询里才开的两间侧屋，`回侧殿` 是回程。
   所以判据是「从起点出发，目标比这里更晚才到得了吗」（`_scene_depths()`），
   比这儿更早到得了的一律算回程，不报。
2. **开局剧透面**：刚开局（什么都没读）时，哪些档案只要敲对档号就能打开。
   **跨案的**是问题（剧情锁该挡住），**同案后面幕的**只是提示 —— 同案内
   「拼档号翻旧档」是这游戏的核心玩法，不该被锁。
3. **选项 key 冲突**：`Choice.key` 是 `目标::标签`，而 `seen_choices` 是全局的。
   两个不同的选项撞了同一个 key，且其中一个不可重复 —— 做过一个，另一个就永远消失。
4. **结局兜底**：`pick_ending()` 在没有任何规则命中时，按案取兜底结局。
   兜底必须落在「什么都没查出来」那一档上，不能兜出一个好结局。
5. **死胡同**：某个状态下**一个可见选项都没有**（门禁没开的选择根本不上桌，
   不可重复的又都做过了），场景里就再也没有出口。这时按「手上的档还救不救得了场」
   分三档：

   * **硬死**（没有可见选项、也没有可读的档）——问题；
   * **翻不动的软卡**（还有档可读，但翻开任何一份都不改变任何东西：没有新线索／
     物证／档目／旗标／信任／分数，没有选项变亮，也没有别的档因此变得可读）——
     问题，玩家被钉在原地翻页；
   * **正常的软卡**（翻档能翻出新东西，新线索开出新选项）——设计好的节奏，不报，
     加 `-v` 才列明细。
6. **门禁缺开发者可读的原因**：被 `locked_if` / `locked_by` 挡住的选项没写
   `locked_hint`，`hidden_options()` 就只剩一句兜底的「条件不足」。门禁既然不摆在
   桌上，这行字便只有审计与排障会读 —— 缺了它，被挡住的原因只能回头翻剧本去猜。
7. **问询退场归属**：`talk_*` 场景的 `hall` 必须回到**同一案**的前厅，
   否则案③ 问完人会被送回案① 的侧殿，案号跟着回退，结局判定就串了。
8. **可重复的选项带一次性收益**：`repeatable=True` 而效果里有分数／信任／线索／
   档案 —— 线索与物证引擎会去重，**分数和信任不会**，玩家连点同一个选项就能刷分
   （`acting()` 因此默认把这类动作设成不可重复）。
9. **结局判定与结局屏对不上**：每一条结局路线实际走一遍，看 `pick_ending()` 判出的
   是不是那条路线的结局 —— 「走进辞官那屏、却被判成查不出来」这类顺序错误，
   只有真跑一遍才看得出来。

用法::

    python tools/audit_logic.py [预算步数] [-v]

`-v` 只影响第 5 节：把「正常软卡」的明细也列出来（默认只报个数）。

有任何一项不干净，退出码是 1。
"""

from __future__ import annotations

import sys
from collections import deque
from typing import Dict, List, Set, Tuple

sys.path.insert(0, ".")
sys.path.insert(0, "tools")

from gongwei.data import CONTENT, TOPIC_GATES  # noqa: E402
from gongwei.game import GameEngine  # noqa: E402
from audit_story import fingerprint, pack  # noqa: E402

BUDGET = 120000


# --------------------------------------------------------------------------
# 1. 幕推进 / 案推进 是否上锁
# --------------------------------------------------------------------------


def _scene_depths() -> Dict[str, int]:
    """从起点出发的静态最短距离（只走 ``effect.scene`` / ``to``，不看锁）。

    锁是运行时的事，这里要的是**图上的先后**：谁先到得了。
    """
    depths: Dict[str, int] = {CONTENT.start_scene: 0}
    queue = deque([CONTENT.start_scene])
    while queue:
        sid = queue.popleft()
        scene = CONTENT.scenes.get(sid)
        if scene is None:
            continue
        for ch in scene.choices:
            nxt = ch.effect.scene or ch.to
            if nxt in CONTENT.scenes and nxt not in depths:
                depths[nxt] = depths[sid] + 1
                queue.append(nxt)
    return depths


def unlocked_progression() -> List[str]:
    """找出「往后推进却没上锁」的选项。

    只认**显式**的后门：选项带着锁就不算后门 —— 哪怕那把锁只是
    `missing_dossier()`，它也已经把推进权绑在剧情上了。结案选项
    （`tag="accuse"`）不算：提前收手是设计好的路。

    「往后」= 图上比这里更晚才到得了（见模块 docstring 第 1 条）。
    """
    depths = _scene_depths()
    bad: List[str] = []
    for sid, scene in sorted(CONTENT.scenes.items()):
        for ch in scene.choices:
            if ch.tag == "accuse":
                continue
            target_id = ch.effect.scene or ch.to
            target = CONTENT.scenes.get(target_id)
            if target is None:
                continue
            later_act = target.act and scene.act and target.act > scene.act
            later_case = target.case and scene.case and target.case > scene.case
            if not (later_act or later_case):
                continue
            if (ch.locked_if is not None or ch.locked_by is not None
                    or ch.visible_if is not None):
                continue
            # 回程：目标比这里更早就能到（`回侧殿` 从第二幕的侧屋回第三幕的
            # 问询厅，幕号是变大了，可那本来就是玩家来的路）。
            if depths.get(target_id, 10 ** 6) < depths.get(sid, -1):
                continue
            what = f"第{scene.act}幕→第{target.act}幕" if later_act else \
                   f"案{scene.case}→案{target.case}"
            bad.append(f"{sid} · {ch.label}（{what}，直接可点）")
    return bad


# --------------------------------------------------------------------------
# 2. 开局剧透面
# --------------------------------------------------------------------------


def opening_surface() -> Tuple[List[str], List[str], List[str]]:
    """开局（未读任何档案）时，哪些档案能靠自拼档号打开。

    返回 (开局就开得了的档号, 其中在后一幕的档号, 其中**跨案**的档号)。
    最后一项必须为空：那是剧情锁该挡住的东西。
    """
    engine = GameEngine(CONTENT, gates=TOPIC_GATES)
    engine.new_game()
    open_now = [did for did in sorted(CONTENT.dossiers)
                if engine.can_read_dossier(did)]
    start_act = CONTENT.scenes[CONTENT.start_scene].act or 1
    later = [did for did in open_now if CONTENT.dossiers[did].act > start_act]
    cross = [did for did in open_now if engine.dossier_case(did) > engine.state.case]
    return open_now, later, cross


# --------------------------------------------------------------------------
# 3. 选项 key 冲突
# --------------------------------------------------------------------------


def key_collisions() -> List[str]:
    """同一个 key 被多个选项用掉，且有不可重复的那个。"""
    where: Dict[str, List[Tuple[str, bool]]] = {}
    for sid, scene in CONTENT.scenes.items():
        for ch in scene.choices:
            where.setdefault(ch.key, []).append((f"{sid} · {ch.label}", ch.repeatable))
    for tid, topic in CONTENT.topics.items():
        where.setdefault(topic.key, []).append((f"topic:{tid}", False))
    out: List[str] = []
    for key, users in sorted(where.items()):
        if len(users) < 2:
            continue
        if all(rep for _w, rep in users):
            continue                      # 都可重复：撞了也不影响
        names = "；".join(w for w, _r in users)
        out.append(f"{key} ← {names}")
    return out


# --------------------------------------------------------------------------
# 4. 结局兜底
# --------------------------------------------------------------------------


def ending_fallbacks() -> List[str]:
    """每个案子的「什么都没查出来」会兜到哪条结局。"""
    from gongwei.data.story import CONTENT as _C

    out: List[str] = []
    cases = sorted({e.case for e in _C.endings})
    for case in cases:
        engine = GameEngine(_C, gates=TOPIC_GATES)
        engine.new_game()
        engine.state.case = case
        eid = engine.pick_ending()
        rule = next((e for e in _C.endings if e.id == eid), None)
        rank = rule.rank if rule else ""
        zero = rule.rule is None or rule.rule(engine.state)
        out.append(f"案{case}：空手结案 → {eid}（{rule.title if rule else '?'}"
                   f"／评级 {rank or '—'}）零条件命中={zero}")
    return out


def unconditional_rules() -> List[str]:
    """除了兜底那一条，还有没有「无条件成立」的结局规则。"""
    out: List[str] = []
    for e in CONTENT.endings:
        if e.rule is not None:
            continue
        if e.id in {r.split("→")[1].split("（")[0].strip()
                    for r in ending_fallbacks()}:
            continue
        out.append(f"{e.id} {e.title}（案{e.case}）没有条件 —— 会抢在后面的规则前面")
    return out


# --------------------------------------------------------------------------
# 5. 死胡同
# --------------------------------------------------------------------------


def _readable_unread(engine: GameEngine) -> Set[str]:
    """这一格还能翻开的档（在档目里或够得着，且还没读过）。"""
    return {did for did in CONTENT.dossiers
            if not engine.state.dossier_read(did) and engine.can_read_dossier(did)}


def _progress_signature(engine: GameEngine) -> Tuple:
    """玩家手上「变了才算进展」的东西。

    刻意不含「哪些档还没读」：读一份档必然把它自己从那里拿走，
    但那只是翻页本身，不是进展。

    选项面就是 ``engine.options()`` 的标签集：门禁没开的不上桌，所以看得见的
    就是亮着的 —— 这一格少了哪一项，就说明那份档翻开真的开出了新路。
    """
    st = engine.state
    return (frozenset(st.clues), frozenset(st.items_owned),
            frozenset(st.known_dossiers()), frozenset(st.flags),
            tuple(sorted(st.trust.items())), st.score,
            frozenset(o.label for o in engine.options()))


def _flip_opens_something(raw: Dict, did: str, others: Set[str]) -> bool:
    """翻开 `did` 之后，除了「这份档从此读过」，还有没有别的变化。

    有 = 这份档真的推进了什么（给了线索/物证/档目/旗标/信任/分数、让某个选项变亮、
    或者让别的档变得可读）。没有 = 翻页无用。
    """
    probe = GameEngine(CONTENT, gates=TOPIC_GATES)
    probe.state = type(probe.state).from_save(raw, CONTENT)
    before = _progress_signature(probe)
    probe.read_dossier(did)
    if _progress_signature(probe) != before:
        return True
    return (_readable_unread(probe) - {did}) != others


def dead_ends(budget: int = BUDGET) -> Tuple[List[str], List[str], List[str], int]:
    """撒网找「没有任何出口」的状态。

    出口 = `engine.options()` 里摆着的那个（门禁没开的选择根本不上桌，所以看得见
    的就是能点的），或者一份**翻开来会改变点什么**的档案。
    三个清单依次是：硬死（没有可见选项、也没档）、翻不动的软卡（有档，但翻哪份都
    一样）、正常软卡（翻档能翻出新东西 —— 设计好的节奏，由调用方决定要不要列）。
    判决过渡场景不算：它们进来就结算。
    """
    engine = GameEngine(CONTENT, gates=TOPIC_GATES)
    engine.new_game()
    start = pack(engine.state)
    seen = {fingerprint(start)}
    stack = [start]
    hard: List[Tuple[str, str, int]] = []
    soft: List[Tuple[str, str, int, int]] = []
    stalled: List[Tuple[str, str, int, int]] = []
    moves = 0
    while stack and moves < budget:
        raw = stack[-1]
        engine.state = type(engine.state).from_save(raw, CONTENT)
        scene = engine.scene
        reads = sorted(_readable_unread(engine))
        if scene.kind != "ending" and not engine.at_verdict():
            # 门禁不开的选择不上桌：``options()`` 空了就是「这一屏没有可见选项」，
            # 挡住的那些在 ``hidden_options()`` 里 —— 它们**不算出口**。
            if not engine.options():
                if not reads:
                    hard.append((raw["scene"], scene.title, raw["turn"]))
                elif any(_flip_opens_something(raw, did, set(reads) - {did})
                         for did in reads):
                    soft.append((raw["scene"], scene.title, raw["turn"], len(reads)))
                else:
                    stalled.append((raw["scene"], scene.title, raw["turn"], len(reads)))
        steps = engine.options()
        advanced = False
        for kind, item in ([("opt", o) for o in steps] + [("read", d) for d in reads]):
            engine.state = type(engine.state).from_save(raw, CONTENT)
            if kind == "opt":
                item.action()
            else:
                engine.read_dossier(item)
            if engine.at_verdict() and not engine.state.ending:
                engine.finalize()
            moves += 1
            nxt = pack(engine.state)
            fp = fingerprint(nxt)
            if fp in seen:
                continue
            seen.add(fp)
            stack.append(nxt)
            advanced = True
            break
        if not advanced:
            stack.pop()

    hard_uniq: Dict[str, Tuple[str, int]] = {}
    for sid, title, turn in hard:
        if sid not in hard_uniq or turn < hard_uniq[sid][1]:
            hard_uniq[sid] = (title, turn)
    hard_out = [f"{sid} · {title}（最早出现在第 {turn} 回合，连档都没得读）"
                for sid, (title, turn) in sorted(hard_uniq.items())]
    soft_best: Dict[str, Tuple[str, int, int]] = {}
    for sid, title, turn, n in soft:
        if sid not in soft_best or turn < soft_best[sid][1]:
            soft_best[sid] = (title, turn, n)
    soft_out = [f"{sid} · {title}（最早第 {turn} 回合，尚有 {n} 份档可读）"
                for sid, (title, turn, n) in sorted(soft_best.items())]
    stalled_best: Dict[str, Tuple[str, int, int]] = {}
    for sid, title, turn, n in stalled:
        if sid not in stalled_best or turn < stalled_best[sid][1]:
            stalled_best[sid] = (title, turn, n)
    stalled_out = [f"{sid} · {title}（最早第 {turn} 回合，{n} 份档翻开也不改变任何东西）"
                   for sid, (title, turn, n) in sorted(stalled_best.items())]
    return hard_out, soft_out, stalled_out, len(seen)


# --------------------------------------------------------------------------
# 8. 可重复的选项带一次性收益（刷分 / 刷好感）
# --------------------------------------------------------------------------


def farmable_choices() -> List[str]:
    """可重复、而效果里带着分数／信任／线索／物证的选项。

    引擎对线索与物证去重，**分数和信任不去重** —— 这类选项连点就能刷。
    `acting()` 已经把这类动作默认设成不可重复，这里是闸门。
    """
    out: List[str] = []
    for sid, scene in sorted(CONTENT.scenes.items()):
        for ch in scene.choices:
            if not ch.repeatable:
                continue
            eff = ch.effect
            gains: List[str] = []
            if eff.score:
                gains.append(f"{eff.score} 分")
            if eff.trust:
                gains.append("信任")
            if eff.add_clues:
                gains.append("线索")
            if eff.add_items:
                gains.append("物证")
            if eff.add_dossiers:
                gains.append("档案")
            if gains:
                out.append(f"{sid} · {ch.label}（可重复，每次都给{'／'.join(gains)}）")
    return out


# --------------------------------------------------------------------------
# 9. 结局判定与结局屏对不对得上
# --------------------------------------------------------------------------


def ending_verdicts() -> Tuple[List[str], int]:
    """每条结局路线真走一遍，看判出来的是不是那条路线的结局。

    只有真跑一遍才看得出「走进辞官那屏、却被兜底判成查不出来」这类
    顺序错误 —— 路线本身走得通，屏幕上写的却是另一回事。
    """
    from gongwei.autoplay import ENDING_ROUTES, WalkError, play

    out: List[str] = []
    for eid in sorted(ENDING_ROUTES):
        engine = GameEngine(CONTENT, gates=TOPIC_GATES)
        engine.new_game()
        try:
            play(engine, ENDING_ROUTES[eid])
        except WalkError as exc:
            out.append(f"{eid} 的路线走不通：{exc}")
            continue
        got = engine.state.ending or engine.pick_ending()
        if got != eid:
            rule = next((e for e in CONTENT.endings if e.id == got), None)
            where = engine.state.scene
            out.append(f"{eid} 的路线判成了 {got}"
                       f"（{rule.title if rule else '?'}／{rule.rank if rule else '—'}）"
                       f"，停在 {where}")
    return out, len(ENDING_ROUTES)


# --------------------------------------------------------------------------
# 6. 锁而无提示
# --------------------------------------------------------------------------


def locks_without_hint() -> List[str]:
    """被 `locked_if` / `locked_by` 挡住、却没写 ``locked_hint`` 的选项。

    门禁改成「藏起来」之后，兜底的「条件不足」不再给玩家看，可这行字**审计与
    排障仍然要读**：`hidden_options()` 的原样输出、`audit_story.py` 的「从未解开过
    的门禁」都靠它认门禁。缺了它，被挡住的原因就只能回头翻剧本去猜。

    只查 `locked_if` / `locked_by`：`visible_if` 挡住的本来就不该给玩家提示
    （那是「还没到该看见它的时候」，不是「你缺什么」）。
    """
    out: List[str] = []
    for sid, scene in sorted(CONTENT.scenes.items()):
        for ch in scene.choices:
            if (ch.locked_if or ch.locked_by) and not ch.locked_hint:
                out.append(f"{sid} · {ch.label}")
    return out


# --------------------------------------------------------------------------
# 7. 问询退场归属
# --------------------------------------------------------------------------


def hall_mismatch() -> List[str]:
    out: List[str] = []
    for sid, scene in sorted(CONTENT.scenes.items()):
        if not scene.interlocutor:
            continue
        hall = scene.hall or CONTENT.interrogate_hall
        target = CONTENT.scenes.get(hall)
        if target is None:
            out.append(f"{sid} 的 hall 指向不存在的场景：{hall}")
            continue
        if scene.case and target.case and target.case != scene.case:
            out.append(f"{sid}（案{scene.case}）问完人回到 {hall}（案{target.case}）")
        elif scene.act and target.act and target.act != scene.act:
            out.append(f"{sid}（第{scene.act}幕）问完人回到 {hall}（第{target.act}幕）")
    return out


def main() -> int:
    budget = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else BUDGET
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    problems = 0

    print("== 1. 幕 / 案推进是否上锁 ==")
    bad = unlocked_progression()
    if bad:
        problems += len(bad)
        for line in bad:
            print(f"  ✗ {line}")
    else:
        print("  ✓ 每一条往后推进的选项都带着锁（读数不足就走不过去）")

    print("== 2. 开局剧透面（自拼档号就能打开的档案）==")
    open_now, later, cross = opening_surface()
    print(f"  开局可读 {len(open_now)} / {len(CONTENT.dossiers)} 份；"
          f"其中同一案后面幕的 {len(later) - len(cross)} 份（玩法内，允许）")
    if cross:
        problems += len(cross)
        for did in cross:
            d = CONTENT.dossiers[did]
            print(f"  ✗ {did}  第{d.act}幕  {d.title} —— 属于第 "
                  f"{GameEngine(CONTENT, gates=TOPIC_GATES).dossier_case(did)} 案，"
                  f"剧情锁没挡住")
    else:
        print("  ✓ 没有跨案的档案能在开局拼出来（剧情锁生效）")

    print("== 3. 选项 key 冲突 ==")
    bad3 = key_collisions()
    if bad3:
        problems += len(bad3)
        for line in bad3:
            print(f"  ✗ {line}")
    else:
        print("  ✓ 没有两个选项共用同一个 key")

    print("== 4. 结局兜底 ==")
    for line in ending_fallbacks():
        print(f"  {line}")
    bad4 = unconditional_rules()
    if bad4:
        problems += len(bad4)
        for line in bad4:
            print(f"  ✗ {line}")
    else:
        print("  ✓ 除兜底外，没有无条件成立的结局规则")

    print(f"== 5. 死胡同（预算 {budget} 步）==")
    bad5, soft5, stalled5, states = dead_ends(budget)
    if bad5:
        problems += len(bad5)
        for line in bad5:
            print(f"  ✗ {line}")
    else:
        print(f"  ✓ 展开 {states} 个状态，"
              f"没有任何「没有可见选项、连档也没得读」的硬死")
    if stalled5:
        problems += len(stalled5)
        for line in stalled5:
            print(f"  ✗ {line} —— 本状态没有可见选项，"
                  f"手上能翻的档翻开来也不改变任何东西")
    if soft5:
        print(f"  · 另有 {len(soft5)} 处「没有可见选项、但翻档能翻出新东西」的软卡"
              f"（翻档即解，正常节奏；{'明细：' if verbose else '加 -v 看明细'}）")
        if verbose:
            for line in soft5:
                print(f"      {line}")

    print("== 6. 门禁缺开发者可读的原因（locked_hint）==")
    bad6 = locks_without_hint()
    if bad6:
        problems += len(bad6)
        for line in bad6:
            print(f"  ✗ {line}")
    else:
        print("  ✓ 每道 locked_if / locked_by 门禁都写了 locked_hint"
              "（门禁不摆上桌，这行字只剩审计与排障在读）")

    print("== 7. 问询退场归属 ==")
    bad7 = hall_mismatch()
    if bad7:
        problems += len(bad7)
        for line in bad7:
            print(f"  ✗ {line}")
    else:
        print("  ✓ 每个问询场景都回到本案同一幕的前厅")

    print("== 8. 可重复而带一次性收益的选项（刷分 / 刷好感）==")
    bad8 = farmable_choices()
    if bad8:
        problems += len(bad8)
        for line in bad8:
            print(f"  ✗ {line}")
    else:
        print("  ✓ 带分数／信任／线索／物证的动作都只给一次")

    print("== 9. 结局判定与结局屏 ==")
    if "--no-routes" in sys.argv:
        print("  （--no-routes：跳过路线复跑）")
    else:
        bad9, total = ending_verdicts()
        if bad9:
            problems += len(bad9)
            for line in bad9:
                print(f"  ✗ {line}")
        else:
            print(f"  ✓ {total} 条结局路线，判出来的都是它自己那条")

    print()
    if problems:
        print(f"逻辑体检未通过：{problems} 处问题。")
        return 1
    print("逻辑体检通过：推进有锁、兜底不跑偏、没有死胡同。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
