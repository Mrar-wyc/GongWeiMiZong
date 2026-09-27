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

**从哪儿开始撒网**：只从 ``new_game()`` 出发时，深度优先会在案② 之前耗尽预算
（实测 400000 步、三十万个状态，最深只到第六幕），案② 后半与案③ 的内容全靠
那十九条路线兜着 —— 路线没读的档、没走的判决屏就会报「未触达」。所以这里用
剧本自带的路线前缀造几个**深水起点**（案② 药局前厅 / 案② 结案厅 / 案③ 阁前 /
案③ 结案厅），每个起点再撒一遍网：从案③ 结案厅往外摸，才摸得到卷尾那四份
总录，也才走得到「指认贺小五」「指认陆文昭」这两张没人写路线的判决屏。

**「从未解开过的门禁」按 ``(场景, 选项文本)`` 计数**：同一个文本在三个场景里
各写一遍（`移步 · 药局前厅` 就是），只按文本计数会把「这三个里有一个亮过」
错当成「每个场景都亮过」，于是漏报。

用法::

    python tools/audit_story.py [预算步数] [--lint-only]

有任何一项没摸到（场景 / 档案 / 线索 / 话题 / 结局 / 路线），退出码是 1。
"""

from __future__ import annotations

import sys
from collections import deque
from typing import Callable, List, Optional, Tuple

sys.path.insert(0, ".")

from gongwei.data import CONTENT, TOPIC_GATES
from gongwei.game import GameEngine

BUDGET = 400000


def pack(state) -> dict:
    """把状态压成一个「重新计算一遍就等价」的字典。

    直接取 ``GameState.to_save()``，只摘掉三样纯显示用的东西（卷宗、档名缓存、
    幕名缓存）——它们不影响任何判定，却会让栈里的每一格都拖着几百行正文。

    **不能少字段**：这个字典就是撒网里「一步之后的世界」。少了 ``case``、
    ``ending``、``seen_choices``，恢复出来的状态就会和玩家真到的那一格不一样，
    撒网走出来的结论也就不再作数（历史上 61/63、87/91 的假缺口正是这么来的）。
    """
    raw = state.to_save()
    for key in ("log", "dossier_titles", "act_titles"):
        raw.pop(key, None)
    return raw


def fingerprint(raw: dict) -> tuple:
    trust = tuple(sorted((cid, v // 20) for cid, v in raw["trust"].items()))
    return (
        raw["scene"],
        raw["case"],
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


def search(budget: int, reverse: bool, seed: Optional[dict] = None) -> dict:
    """深度优先枚举可达状态，返回摸到的东西。

    ``seed`` 是 ``pack()`` 出来的一份状态：给了它就从那儿往外摸，而不是从开局。
    只从开局出发时，深度优先会被案① 的分支吃光预算（实测最深只到第六幕），
    案② 后半与案③ 全靠路线兜着 —— 深水起点就是给撒网补上这一段。

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
    if seed is not None:
        engine.state = type(engine.state).from_save(seed, CONTENT)

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
            spot = (raw["scene"], opt.label)
            if opt.enabled:
                open_labels.add(spot)
            else:
                locked_counts[spot] = locked_counts.get(spot, 0) + 1
        steps: List[Tuple[str, Callable[[], None]]] = [
            (o.label, o.action) for o in opts if o.enabled]
        reads: List[Tuple[str, Callable[[], None]]] = []
        # 结局屏与判决屏上不再枚举阅档：玩家已经走到头，能读的档在进这一屏之前就
        # 读得到（``can_read_dossier`` 既不看 ``ending`` 也不看判决屏），在这儿枚举
        # 只会把预算烧在「先读哪一份」的排列上 —— 实测 4005 步里有 4004 步耗在同一
        # 个结局屏里，后面的判决屏反而排不上队。撤掉之后撒网既快又能走到最后一个案。
        if not engine.state.ending and not engine.at_verdict():
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
    opened: set = set()
    for eid, steps in ENDING_ROUTES.items():
        opened.update(s for s in steps if s[:1] not in ("#", "@", "!"))
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
    found["open"] = opened
    return found, broken


def seed_states() -> List[dict]:
    """造几个「已经走到后半程」的起点，给撒网当第二、第三批根。

    用的都是剧本自带的路线前缀 —— 走一遍就等于「有个玩家真做到了这一步」，
    于是从那份状态出发的撒网不必再从头把案① 的分支摸一遍。没有这一步，
    案③ 结案厅之外的分支（比如把卷尾那四份总录一份份读完）永远轮不到预算。
    """
    from gongwei.autoplay import (CASE2_ACT6, CASE2_HEAD, CASE2_ROUTE,
                                  CASE3_ACT9, CASE3_ACT10, CASE3_ENTRY,
                                  CASE3_HEAD, WalkError, play)

    prefixes = [
        ("案② 药局前厅", CASE2_HEAD + CASE2_ACT6),
        ("案② 结案厅", CASE2_HEAD + CASE2_ROUTE),
        ("案③ 阁前", CASE3_HEAD + [CASE3_ENTRY] + CASE3_ACT9),
        ("案③ 结案厅", CASE3_HEAD + [CASE3_ENTRY] + CASE3_ACT9 + CASE3_ACT10),
    ]
    seeds: List[dict] = []
    for _name, steps in prefixes:
        engine = GameEngine(CONTENT, gates=TOPIC_GATES)
        engine.new_game()
        try:
            engine, _ = play(engine, steps)
        except WalkError:
            continue
        seeds.append(pack(engine.state))
    return seeds


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

    seed_budget = max(budget // 2, 1)
    forward = search(budget, reverse=False)
    backward = search(budget, reverse=True)
    seeds = seed_states()
    seeded = [search(seed_budget, reverse=False, seed=s) for s in seeds]
    routes_found, broken = route_sweep()

    runs = [forward, backward] + seeded
    seen = set().union(*(r["seen"] for r in runs))
    scenes = set().union(*(r["scenes"] for r in runs)) | routes_found["scenes"]
    clues = set().union(*(r["clues"] for r in runs)) | routes_found["clues"]
    topics = set().union(*(r["topics"] for r in runs)) | routes_found["topics"]
    endings = set().union(*(r["endings"] for r in runs)) | routes_found["endings"]
    dossiers = set().union(*(r["dossiers"] for r in runs)) | routes_found["dossiers"]
    locked_counts: dict = {}
    open_labels: set = set()
    for tally in runs:
        for spot, count in tally["locked"].items():
            locked_counts[spot] = locked_counts.get(spot, 0) + count
        open_labels |= tally["open"]
    open_labels |= routes_found["open"]
    moves = sum(r["moves"] for r in runs)
    max_depth = max(r["max_depth"] for r in runs)

    all_items = set(CONTENT.items)
    core_ids = {i.id for i in CONTENT.items.values() if i.core}
    from gongwei.autoplay import ENDING_ROUTES

    print(f"\n展开状态 {len(seen)} 个（{len(runs)} 遍共走了 {moves} 步，"
          f"最深 {max_depth} 层；开局两遍各 {budget} 步、"
          f"{len(seeds)} 口深井各 {seed_budget} 步，"
          f"另有 {len(ENDING_ROUTES)} 条路线）")
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
    # 键是 ``(场景, 选项文本)``：同一个文本在三个场景里各写一遍时（药局前厅那条
    # 门禁就是），只按文本算会把「一处亮过」当成「处处亮过」。路线里真点过的
    # 选项也算亮过 —— 那是有玩家真的走通了。
    route_labels = routes_found["open"]
    never = {spot: n for spot, n in locked_counts.items()
             if spot not in open_labels and spot[1] not in route_labels}
    if never:
        print("\n[从未解开过的门禁] 这些选项在任何状态下都没亮过")
        for (scene_id, label), count in sorted(never.items(), key=lambda kv: -kv[1]):
            print(f"   {count:>7} 次被挡  {scene_id} · {label}")
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
