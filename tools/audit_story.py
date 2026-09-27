"""剧本可达性体检：把「每个场景 / 每条线索 / 每个话题 / 每个结局是否都摸得到」查一遍。

做法是广度优先枚举**状态**（不是路径）：状态只由真正影响后续判定的东西组成 ——
当前场景、线索/物证集合、flags、已问话题、已访问场景、被指认者、**已阅档案**，
外加量化后的好感。这样既能穷尽分支，又不会组合爆炸。

**两件事必须一起枚举，否则体检会说谎**：

1. 选项（``engine.options()`` 里 enabled 的那些）；
2. **阅档**（``engine.can_read_dossier(did) and not state.dossier_read(did)``）。

第二件事是后加的：第一幕的出口挂着「必须先读过勘验总录」（``missing_dossier``），
只看选项的话，BFS 到不了侧殿，八个结局会全部报「未触达」——那是体检工具的
盲区，不是剧本死了。

**这是发现「门槛永远够不着」这类死锁的唯一可靠办法** —— 本项目已经靠它查出三处
（皇后线、小顺子线、指认未记录 accused）。

**枚举顺序**：每个状态只往下走**一条**没走过的分支（深度优先 + 栈），但按两种
顺序各跑一遍 —— 顺序枚举一头扎进「把能挖的都挖到手」的收集路线；逆序枚举把
``结案`` 这类动作排在前面试，专走「问两句就提笔」的岔路。两遍的并集才是结论。

**撒网之外还要走一遍现成的路线**（``route_sweep``）：``ENDING_ROUTES`` 里那
十三条路线是「有人真的这么玩过」的证据。案② 加进来之后，撒网的预算被摊薄，
一度把 ``ending_pressured`` / ``ending2_pressed`` 这两条**证据薄**的结局漏报成
死结局 —— 补上路线这一遍，它们就再也不会因为预算而误报。

用法::

    python tools/audit_story.py [预算步数] [--lint-only]

有任何一项没摸到（场景 / 档案 / 线索 / 话题 / 结局 / 路线），退出码是 1。
"""

from __future__ import annotations

import sys
from collections import deque
from typing import Callable, List, Tuple

sys.path.insert(0, ".")

from gongwei.data import CONTENT, TOPIC_GATES
from gongwei.game import GameEngine

BUDGET = 400000


def pack(state) -> dict:
    """把状态压成一个「重新计算一遍就等价」的最小字典。"""
    return {
        "scene": state.scene,
        "time": state.time,
        "place": state.place,
        "clues": list(state.clues),
        "items_owned": list(state.items_owned),
        "trust": dict(state.trust),
        "flags": sorted(state.flags),
        "visited": sorted(state.visited),
        "topics_asked": list(state.topics_asked),
        "accused": state.accused,
        "score": state.score,
        "turn": state.turn,
        # 与 ``GameState.to_save()`` 同形：did -> [read, guessed]。
        # 只留「读过或猜出来」的，指纹才不会被一堆 False 撑大。
        "dossiers": {did: [st.read, st.guessed]
                     for did, st in sorted(state.dossier_states.items())
                     if st.read or st.guessed},
    }


def fingerprint(raw: dict) -> tuple:
    trust = tuple(sorted((cid, v // 20) for cid, v in raw["trust"].items()))
    return (
        raw["scene"],
        tuple(sorted(raw["clues"])),
        tuple(sorted(raw["items_owned"])),
        tuple(raw["flags"]),
        tuple(sorted(raw["visited"])),
        tuple(sorted(raw["topics_asked"])),
        raw["accused"],
        tuple(sorted(raw["dossiers"])),
        trust,
    )


def lint() -> List[str]:
    """静态检查：档案引用的 id 是否存在、links 是否悬空。不需要跑引擎。"""
    problems: List[str] = []
    item_ids = set(CONTENT.items)
    char_ids = set(CONTENT.characters)
    known = set(CONTENT.dossiers)
    for did in sorted(known):
        dos = CONTENT.dossiers[did]
        for iid in dos.effect.add_clues:
            if iid not in item_ids:
                problems.append(f"{did} 的 clues 引用了未登记的 id：{iid}")
        for iid in dos.effect.add_items:
            if iid not in item_ids:
                problems.append(f"{did} 的 items 引用了未登记的 id：{iid}")
        for iid in dos.effect.add_dossiers:
            if iid not in known:
                problems.append(f"{did} 的 add_dossiers 引用了不存在的档案：{iid}")
        for cid, _delta in dos.effect.trust:
            if cid not in char_ids:
                problems.append(f"{did} 的 trust 引用了未登记的人物：{cid}")
        for link in dos.links:
            if link not in known:
                problems.append(f"{did} 的 links 悬空：{link}（没有这份档案）")
    # 档号形如 NN-XX-YYY：幕码必须和 Dossier.act 一致，否则档目会分错幕
    for did in sorted(known):
        dos = CONTENT.dossiers[did]
        head = did.split("-", 1)[0]
        if head.isdigit() and int(head) != dos.act:
            problems.append(f"{did} 的档号幕码 {head} 与 act={dos.act} 不一致")
    return problems


def search(budget: int, reverse: bool) -> dict:
    """深度优先枚举可达状态，返回摸到的东西。

    为什么要按**两种顺序**各跑一遍：剧本里有两种玩家。一种把能挖的都挖到手再
    结案；另一种问两句就提笔。深度优先只走一条路，顺序枚举时它一头扎进「收集
    路线」，等它想起来试「先收手」的岔路，预算已经用完了 —— 于是 `ending_pressured`
    / `ending_standard` 这两条只在**证据薄**的状态里成立的结局被漏报，看着像死结局。

    逆序那一遍把选项倒过来试（`结案` 之类排在最后的动作先试、阅档放最后），
    专走「少收证据」的岔路。两遍的并集才算体检结论。

    判决过渡场景（`verdict_*`）只在一瞬间存在：`finalize()` 一跑，场景就变成
    `ending_*`。所以必须先记场景再结算，否则它们永远报「未到达」。
    """
    engine = GameEngine(CONTENT, gates=TOPIC_GATES)
    engine.new_game()

    start = pack(engine.state)
    seen: set = {fingerprint(start)}
    found: dict = {k: set() for k in
                   ("scenes", "clues", "topics", "endings", "dossiers")}
    locked_counts: dict = {}
    open_labels: set = set()
    moves = 0
    max_depth = 0
    stack = [start]

    while stack and moves < budget:
        raw = stack[-1]
        max_depth = max(max_depth, len(stack))
        engine.state = type(engine.state).from_save(raw, CONTENT)
        found["scenes"].add(raw["scene"])
        found["clues"].update(raw["clues"])
        found["clues"].update(raw["items_owned"])
        found["topics"].update(raw["topics_asked"])
        found["dossiers"].update(raw["dossiers"])

        opts = engine.options()
        for opt in opts:
            if opt.enabled:
                open_labels.add(opt.label)
            else:
                locked_counts[opt.label] = locked_counts.get(opt.label, 0) + 1
        steps: List[Tuple[str, Callable[[], None]]] = [
            (o.label, o.action) for o in opts if o.enabled]
        reads: List[Tuple[str, Callable[[], None]]] = []
        for did in sorted(CONTENT.dossiers):
            if engine.state.dossier_read(did):
                continue
            if not engine.can_read_dossier(did):
                continue
            reads.append((f"阅档 #{did}", (lambda d=did: engine.read_dossier(d))))
        if reverse:
            steps.reverse()
            reads.reverse()
        move_list = steps + reads

        advanced = False
        for label, action in move_list:
            engine.state = type(engine.state).from_save(raw, CONTENT)
            action()
            found["scenes"].add(engine.state.scene)
            if engine.at_verdict() and not engine.state.ending:
                eid = engine.finalize()
                if eid:
                    found["endings"].add(eid)
            if engine.state.ending:
                found["endings"].add(engine.state.ending)
            moves += 1
            nxt = pack(engine.state)
            found["scenes"].add(nxt["scene"])
            found["clues"].update(nxt["clues"])
            found["clues"].update(nxt["items_owned"])
            found["topics"].update(nxt["topics_asked"])
            found["dossiers"].update(nxt["dossiers"])
            fp = fingerprint(nxt)
            if fp in seen:
                continue
            seen.add(fp)
            stack.append(nxt)
            advanced = True
            break
        if not advanced:
            stack.pop()

    found["seen"] = seen
    found["locked"] = locked_counts
    found["open"] = open_labels
    found["moves"] = moves
    found["states"] = len(seen)
    found["max_depth"] = max_depth
    return found


def route_sweep() -> Tuple[dict, List[str]]:
    """把剧本自带的十三条结局路线各走一遍，记录摸到的东西。

    搜索是「撒网」，这一步是「有人真的这么玩过」。已经成立的路线不该因为
    撒网的预算被分薄就报「未触达」——案② 加进来之后，深度优先就是这么把
    ``ending_pressured`` / ``ending2_pressed`` 这两条**证据薄**的结局漏掉的：
    它们要求「手上证据少就提笔」，而撒网总是先往证据多的深处走。

    返回 (摸到的东西, 走不通的路线说明)。
    """
    from gongwei.autoplay import ENDING_ROUTES, WalkError, play

    found: dict = {k: set() for k in
                   ("scenes", "clues", "topics", "endings", "dossiers")}
    broken: List[str] = []
    for eid, steps in ENDING_ROUTES.items():
        engine = GameEngine(CONTENT, gates=TOPIC_GATES)
        engine.new_game()
        try:
            engine, _ = play(engine, steps)
        except WalkError as exc:
            broken.append(f"{eid}：{exc}")
            continue
        state = engine.state
        found["scenes"].update(state.visited)
        found["scenes"].add(state.scene)
        found["clues"].update(state.clues)
        found["clues"].update(state.items_owned)
        found["topics"].update(state.topics_asked)
        if state.ending:
            found["endings"].add(state.ending)
        found["dossiers"].update(
            did for did, st in state.dossier_states.items() if st.read or st.guessed)
    return found, broken


def main() -> int:
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    lint_only = "--lint-only" in sys.argv
    budget = int(argv[0]) if argv else BUDGET

    problems = lint()
    print(f"[档案] {len(CONTENT.dossiers)} 份，"
          f"幕号 {CONTENT.act_numbers()}")
    if problems:
        print(f"   ✗ 静态问题 {len(problems)} 条")
        for line in problems:
            print(f"     · {line}")
    else:
        print("   ✓ 引用与链接全部有据（clues / items / trust / links / 幕码）")
    if lint_only:
        return 1 if problems else 0

    forward = search(budget, reverse=False)
    backward = search(budget, reverse=True)
    routes_found, broken = route_sweep()
    seen = forward["seen"] | backward["seen"]
    scenes = forward["scenes"] | backward["scenes"] | routes_found["scenes"]
    clues = forward["clues"] | backward["clues"] | routes_found["clues"]
    topics = forward["topics"] | backward["topics"] | routes_found["topics"]
    endings = forward["endings"] | backward["endings"] | routes_found["endings"]
    dossiers = forward["dossiers"] | backward["dossiers"] | routes_found["dossiers"]
    locked_counts: dict = {}
    open_labels: set = set()
    for tally in (forward, backward):
        for label, count in tally["locked"].items():
            locked_counts[label] = locked_counts.get(label, 0) + count
        open_labels |= tally["open"]
    moves = forward["moves"] + backward["moves"]
    max_depth = max(forward["max_depth"], backward["max_depth"])

    all_items = set(CONTENT.items)
    core_ids = {i.id for i in CONTENT.items.values() if i.core}
    from gongwei.autoplay import ENDING_ROUTES

    print(f"\n展开状态 {len(seen)} 个（两遍共走了 {moves} 步，每遍预算 {budget}，"
          f"最深 {max_depth} 层；"
          f"顺序 {forward['states']} / 逆序 {backward['states']} 个状态）")
    print(f"[路线] {len(ENDING_ROUTES)} 条结局路线", end="")
    if broken:
        print(f"，{len(broken)} 条走不通：")
        for line in broken:
            print(f"   ✗ {line}")
    else:
        print("全部走通（上面那些「摸到」里已经算进了它们走出来的东西）")

    # 覆盖不全就是问题：删掉一个选项、堵死一条路，都必须让体检红起来。
    missing = (
        len(set(CONTENT.scenes) - scenes)
        + len(set(CONTENT.dossiers) - dossiers)
        + len(all_items - clues)
        + len(set(CONTENT.topics) - topics)
        + len({e.id for e in CONTENT.endings} - endings)
        + len(broken)
    )

    print(f"\n[场景] 摸到 {len(scenes)} / {len(CONTENT.scenes)}")
    for sid in sorted(set(CONTENT.scenes) - scenes):
        print(f"   ✗ 未到达: {sid}  {CONTENT.scenes[sid].title}")

    print(f"\n[档案] 读到 {len(dossiers)} / {len(CONTENT.dossiers)}")
    for did in sorted(set(CONTENT.dossiers) - dossiers):
        dos = CONTENT.dossiers[did]
        print(f"   ✗ 未读到: {did}  {dos.title}（第{dos.act}幕）")

    print(f"\n[线索/物证] 摸到 {len(clues & all_items)} / {len(all_items)}"
          f"（核心 {len(clues & core_ids)} / {CONTENT.core_total()}）")
    for iid in sorted(all_items - clues):
        item = CONTENT.items[iid]
        print(f"   ✗ 未获得: {iid}  {item.name}{'  [核心]' if item.core else ''}")

    print(f"\n[话题] 问出 {len(topics)} / {len(CONTENT.topics)}")
    for tid in sorted(set(CONTENT.topics) - topics):
        print(f"   ✗ 未问出: {tid}  {CONTENT.topics[tid].label}")

    print(f"\n[结局] 触达 {len(endings)} / {len(CONTENT.endings)}")
    for e in CONTENT.endings:
        if e.id not in endings:
            print(f"   ✗ 未触达: {e.id}  {e.title}")

    # 只报「**任何状态下都没解开过**」的门禁。单纯被挡很多次不等于死锁：
    # 「已经验过了」「已经推演过了」这类不 repeatable 的动作，后半程每次都被挡，
    # 次数最高恰恰说明它成功过 —— 所以这里用 open_labels 把它们滤掉。
    never = {label: n for label, n in locked_counts.items()
             if label not in open_labels}
    if never:
        print("\n[从未解开过的门禁] 这些选项在任何状态下都没亮过")
        for label, count in sorted(never.items(), key=lambda kv: -kv[1]):
            print(f"   {count:>7} 次被挡  {label}")
    else:
        print("\n[从未解开过的门禁] 无 —— 每个被挡过的选项都至少亮过一次")

    if missing:
        print(f"\n体检未通过：有 {missing} 处东西没摸到 —— "
              f"删掉一个选项、堵死一条路，都要在这里现形。")
        return 1
    print("\n体检通过：场景 / 档案 / 线索 / 话题 / 结局全部摸得到。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
