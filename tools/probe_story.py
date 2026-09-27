"""遍历探测：把剧情的可达结构与线索产出打印出来（一次性诊断工具）。"""

from __future__ import annotations

import sys
from collections import deque

sys.path.insert(0, ".")

from gongwei.data import CONTENT, TOPIC_GATES
from gongwei.game import GameEngine
from gongwei.game.engine import LogEntry
from gongwei.game.models import Choice


def fresh() -> GameEngine:
    return GameEngine(CONTENT, gates=TOPIC_GATES)


def label(choice: Choice) -> str:
    return choice.label


def explore() -> None:
    seen_scenes = set()
    queue: deque[str] = deque([CONTENT.start_scene])
    while queue:
        sid = queue.popleft()
        if sid in seen_scenes:
            continue
        seen_scenes.add(sid)
        scene = CONTENT.scenes[sid]
        outs = [c for c in scene.choices]
        outs += [Choice(label=f"<topic:{t.id}>", to="")
                 for t in CONTENT.topics.values() if t.owner == scene.interlocutor]
        print(f"[{sid}] {scene.title}  kind={scene.kind}  opts={len(outs)}")
        for c in outs:
            target = c.effect.scene or c.to
            if target:
                print(f"    -> {label(c)[:28]:<30} => {target}")
                queue.append(target)
    print("\n可达场景:", len(seen_scenes), sorted(seen_scenes))


def greedy_walk(max_steps: int = 200) -> None:
    """贪心：每次挑「能带来新线索/物证」的选项，否则挑第一个未做过的。"""
    eng = fresh()
    steps = 0
    while not eng.state.ending and steps < max_steps:
        opts = eng.options()
        if not opts:
            print("!! 无选项，场景:", eng.state.scene, eng.scene.title)
            break
        best = None
        for opt in opts:
            if not opt.enabled:
                continue
            upd = opt.action()          # 试探执行
            gained = len(upd.new_clues) + len(upd.new_items)
            # 回滚：用存档快照恢复
            snap = eng.save()
            eng.load(snap)
            if gained and best is None:
                best = opt
        if eng.at_verdict():
            eng.finalize()
            break
        target = best or next((o for o in opts if o.enabled), None)
        if target is None:
            print("!! 全部选项不可用:", [o.label for o in opts])
            break
        label_text = target.label
        upd = target.action()
        steps += 1
        print(f"{steps:>3}. [{eng.state.scene}] {label_text[:34]:<36} "
              f"线索+{len(upd.new_clues)} 物证+{len(upd.new_items)} 核心={eng.state.core_count()}")
        if eng.at_verdict() and not eng.state.ending:
            eng.finalize()
    print("\n结束场景:", eng.state.scene, "结局:", eng.state.ending,
          "核心:", eng.state.core_count(), "/", CONTENT.core_total(),
          "线索:", len(eng.state.clues), "回合:", eng.state.turn)
    print("flags:", sorted(eng.state.flags))


def full_sweep() -> None:
    """穷举式：把当前场景所有可用选项依次做完，再前进。"""
    eng = fresh()
    guard = 0
    while not eng.state.ending and guard < 400:
        guard += 1
        opts = [o for o in eng.options() if o.enabled]
        if not opts:
            print("!! 卡住:", eng.state.scene)
            break
        progress = False
        for opt in opts:
            if opt.tag == "accuse":
                continue
            before = (len(eng.state.clues), len(eng.state.items_owned), eng.state.scene)
            upd = opt.action()
            if eng.at_verdict():
                eng.finalize()
                progress = True
                break
            after = (len(eng.state.clues), len(eng.state.items_owned), eng.state.scene)
            if after != before or upd.narration:
                progress = True
            if eng.state.ending:
                break
            if len(eng.state.log) > 0 and eng.state.scene != before[2]:
                break
        if eng.state.ending:
            break
        if not progress:
            # 只能靠移动场景推进
            movers = [o for o in eng.options() if o.enabled and o.tag != "accuse"]
            if not movers:
                break
            movers[-1].action()
    print("sweep 结束:", eng.state.scene, "核心", eng.state.core_count(),
          "线索", len(eng.state.clues), "回合", eng.state.turn)


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "explore"
    if what == "explore":
        explore()
    elif what == "greedy":
        greedy_walk()
    else:
        full_sweep()
