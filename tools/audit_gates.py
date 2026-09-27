"""闸门可达性审计：证明每一道门禁都真的够得着。

`tools/audit_story.py` 走的是「一条路线」式审计——它只能证明走得到，
不能证明「某道门禁在该路线之外还有解」。本工具补的是另一件事：

1. **未知引用的线索 id**——剧本里 `add_clues("xxx")` 写了一个不在
   `ITEMS` 里的名字。这类错误在终端里表现为卷宗直接显示内部代号
   （`clue_name()` 找不到就原样返回 id），玩家会看到一串英文标识符。
2. **条件里引用错的 id**——`has_clue("silver_weekk")`、`visited("drgu_store")`
   这类错别字不会报错，只会让那道门禁永远不开。条件现在都贴着 AST
   （见 `gongwei/game/conditions.py`），所以这里直接走 AST 取字面量，
   不再靠正则扫源码——案② 的话题门禁改用 `trust_at_least()` 之后，
   旧的正则写法就再也扫不到东西了（静默失效）。
3. **够不着的信任门槛**——某道门禁要求 `trust_of(X) >= N`，但全剧本
   影响 X 信任的效果加起来都到不了 N，那条话题就永远解不开。
   旧版本真抓到过两处：`hh_motive`（门槛 55，实际最多 45）与
   `gf_who`（门槛 35，实际最多 20）。

用法：python tools/audit_gates.py
"""

from __future__ import annotations

import os
import sys
from typing import Dict, Iterator, List, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gongwei.data.story import CONTENT, ITEMS, TOPIC_GATES  # noqa: E402
from gongwei.game.conditions import ast_of  # noqa: E402

#: 条件里代表「线索 id 列表」的指令
_CLUE_LIST_OPS = ("clues_at_least", "clues_count_in")
#: 条件里代表「档案 id」的指令
_DOSSIER_OPS = ("dossier", "missing_dossier")
#: 条件里代表「角色 id」的指令
_CHARACTER_OPS = ("suspect", "suspect_in")


def _iter_nodes(node) -> Iterator[list]:
    """深度遍历条件 AST（``all`` / ``any`` / ``not`` 都可以嵌套）。"""
    if not isinstance(node, list) or not node:
        return
    yield node
    head = node[0]
    if head in ("all", "any"):
        for child in node[1]:
            yield from _iter_nodes(child)
    elif head == "not":
        yield from _iter_nodes(node[1])


def _literals(node, ops: Tuple[str, ...]) -> List[str]:
    """取出 AST 里这些指令引用的字面量 id。"""
    out: List[str] = []
    for item in _iter_nodes(node):
        if item[0] not in ops:
            continue
        if isinstance(item[1], (list, tuple)):
            out.extend(str(x) for x in item[1])
        else:
            out.append(str(item[1]))
    # `["suspect", ""]` 是「谁都没指认」的哨兵值，不是角色 id
    return [cid for cid in out if cid]


def condition_sources() -> List[Tuple[str, object]]:
    """全剧本里所有带条件的对象：(出处, 条件)。

    覆盖场景选项的三个条件字段、话题门禁（`TOPIC_GATES`）、
    档案的 ``requires``、以及结局规则。AST 已经贴在条件函数上，
    所以这里拿到的都是同一个来源。
    """
    out: List[Tuple[str, object]] = []
    for scene in CONTENT.scenes.values():
        for choice in scene.choices:
            label = f"{scene.id} · {choice.label}"
            for attr, cond in (("visible_if", choice.visible_if),
                               ("locked_if", choice.locked_if),
                               ("locked_by", choice.locked_by)):
                if cond is not None:
                    out.append((f"{label}（{attr}）", cond))
    for tid, pair in TOPIC_GATES.items():
        cond = pair[0] if isinstance(pair, (tuple, list)) else pair
        out.append((f"话题门禁 {tid}", cond))
    for did, dossier in CONTENT.dossiers.items():
        if dossier.requires is not None:
            out.append((f"{did} 的 requires", dossier.requires))
    for ending in CONTENT.endings:
        out.append((f"{ending.id} 的结局规则", ending.rule))
    return out


def unknown_clue_refs() -> List[Tuple[str, str]]:
    """找出被引用、却没有在 ITEMS 里登记过的 id（效果里的增删）。"""
    known: Set[str] = set(ITEMS)
    bad: List[Tuple[str, str]] = []
    for scene in CONTENT.scenes.values():
        for eff in [scene.on_enter] + [c.effect for c in scene.choices]:
            for cid in list(eff.add_clues) + list(eff.add_items):
                if cid not in known:
                    bad.append((scene.id, cid))
    for tid, topic in CONTENT.topics.items():
        for cid in list(topic.effect.add_clues) + list(topic.effect.add_items):
            if cid not in known:
                bad.append((f"topic:{tid}", cid))
    return bad


def unknown_ids_in_conditions() -> List[str]:
    """条件表达式里引用、却没有登记的 id。

    不写死某一类 id：线索、档案、场景、角色都查一遍——
    写错一个字母的门禁不会报错，只会永远不开。
    """
    known = {
        "线索": set(ITEMS),
        "档案": set(CONTENT.dossiers),
        "场景": set(CONTENT.scenes),
        "角色": set(CONTENT.characters),
    }
    bad: List[str] = []
    for where, cond in condition_sources():
        ast = ast_of(cond)
        if ast is None:            # 裸 lambda：生成器会在别处报错
            continue
        for kind, ops in (("线索", ("clue",) + _CLUE_LIST_OPS),
                          ("档案", _DOSSIER_OPS),
                          ("场景", ("visited",)),
                          ("角色", _CHARACTER_OPS)):
            for cid in _literals(ast, ops):
                if cid not in known[kind]:
                    bad.append(f"{where} 引用了不存在的{kind}：{cid}")
    return bad


def reachable_trust(target: str) -> Dict[str, int]:
    """统计全剧本里影响 target 信任的每一处增减。"""
    delta = {"start": CONTENT.characters[target].trust if target in CONTENT.characters else 0,
             "gain": 0, "loss": 0}
    for scene in CONTENT.scenes.values():
        for choice in scene.choices:
            for cid, val in choice.effect.trust:
                if cid == target:
                    delta["gain" if val > 0 else "loss"] += val
    for topic in CONTENT.topics.values():
        for cid, val in topic.effect.trust:
            if cid == target:
                delta["gain" if val > 0 else "loss"] += val
    for scene in CONTENT.scenes.values():
        for cid, val in scene.on_enter.trust:
            if cid == target:
                delta["gain" if val > 0 else "loss"] += val
    return delta


def gate_requirements() -> List[Tuple[str, str, int]]:
    """把「信任 ≥ N」这类门槛抠出来：(出处, 人物, 门槛)。"""
    out: List[Tuple[str, str, int]] = []
    for where, cond in condition_sources():
        ast = ast_of(cond)
        if ast is None:
            continue
        for item in _iter_nodes(ast):
            if item[0] != "trust":
                continue
            who, op, need = str(item[1]), str(item[2]), item[3]
            if op in (">=", ">") and isinstance(need, int):
                out.append((where, who, need))
    return out


def main() -> int:
    problems = 0

    bad = unknown_clue_refs()
    print("== 未登记的线索引用 ==")
    if bad:
        problems += len(bad)
        for where, cid in bad:
            print(f"  ✗ {where} 引用了不存在的 id：{cid}")
    else:
        print("  ✓ 全部线索都在 ITEMS 里登记过")

    bad2 = unknown_ids_in_conditions()
    print("== 条件里的未登记 id ==")
    if bad2:
        problems += len(bad2)
        for line in bad2:
            print(f"  ✗ {line}")
    else:
        print("  ✓ 条件里引用的 id 全部已登记")

    print("== 信任门槛可达性 ==")
    checked = 0
    for where, who, need in gate_requirements():
        d = reachable_trust(who)
        ceiling = d["start"] + d["gain"]
        checked += 1
        if ceiling < need:
            problems += 1
            print(f"  ✗ {where}：要求 {who} 信任 ≥ {need}，"
                  f"但初始 {d['start']} + 全部正向 {d['gain']} = 上限 {ceiling}")
        else:
            print(f"  ✓ {where}：要求 {who} 信任 ≥ {need}，上限 {ceiling}")
    if not checked:
        print("  （没扫到显式的信任门槛）")

    print()
    if problems:
        print(f"审计未通过：{problems} 处问题。")
        return 1
    print("审计通过：门禁全部可达，引用全部有据。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
