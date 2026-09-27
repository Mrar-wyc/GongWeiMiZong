"""把 Python 侧的剧本导出成网页端能读的内容包（JSON）。

网页端没有 Python，所以「剧本」必须以数据形式交出去。这里导出的是**全部**
剧本数据，包括条件与结局规则 —— 但不是函数，而是它们背后的 AST
（见 `gongwei/game/conditions.py` 的 `stamped()`）。JS 侧只实现一棵小求值器，
判定语义因此只有一份定义。

`tools/build_web.py` 用它生成单文件网页；`tools/audit_web.py` 用它做两端逐字比对。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..game.command import HELP_SECTIONS
from ..game.conditions import TIME_ORDER, ast_of
from ..game.models import Choice, Content, Dossier, Effect, Scene, Topic


def _effect(eff: Optional[Effect]) -> Dict[str, Any]:
    if eff is None:
        return {
            "text": None, "add_clues": [], "add_items": [], "add_dossiers": [],
            "trust": [], "flags": [], "time": None, "scene": None,
            "unlock": None, "score": 0, "hurt": 0,
        }
    return {
        "text": eff.text,
        "add_clues": list(eff.add_clues),
        "add_items": list(eff.add_items),
        "add_dossiers": list(eff.add_dossiers),
        "trust": [[cid, delta] for cid, delta in eff.trust],
        "flags": list(eff.flags),
        "time": eff.time,
        "scene": eff.scene,
        "unlock": eff.unlock,
        "score": eff.score,
        "hurt": eff.hurt,
    }


def _choice(ch: Choice) -> Dict[str, Any]:
    return {
        "key": ch.key,
        "label": ch.label,
        "to": ch.to,
        "detail": ch.detail,
        "effect": _effect(ch.effect),
        "visible_if": ast_of(ch.visible_if),
        "locked_if": ast_of(ch.locked_if or ch.locked_by),
        "locked_hint": ch.locked_hint,
        "repeatable": ch.repeatable,
        "wants": ch.wants,
        "tag": ch.tag,
        "suspect": ch.suspect,
    }


def _scene(sc: Scene) -> Dict[str, Any]:
    return {
        "id": sc.id,
        "title": sc.title,
        "place": sc.place,
        "time": sc.time,
        "body": sc.body,
        "kind": sc.kind,
        "interlocutor": sc.interlocutor,
        "hall": sc.hall,
        "case": sc.case,
        "act": sc.act,
        "on_enter": _effect(sc.on_enter),
        "choices": [_choice(c) for c in sc.choices],
    }


def _topic(tp: Topic, gates: Dict[str, Any]) -> Dict[str, Any]:
    gate, hint = gates.get(tp.id, (None, ""))
    return {
        "id": tp.id,
        "owner": tp.owner,
        "label": tp.label,
        "response": tp.response,
        "present": tp.present,
        "effect": _effect(tp.effect),
        "gate": ast_of(gate) if gate is not None else None,
        "gate_hint": hint or "",
    }


def _dossier(d: Dossier) -> Dict[str, Any]:
    return {
        "id": d.id,
        "title": d.title,
        "act": d.act,
        "time_code": d.time_code,
        "place_code": d.place_code,
        "people": list(d.people),
        "body": d.body,
        "links": list(d.links),
        "requires": ast_of(d.requires),
        "effect": _effect(d.effect),
        "found_msg": d.found_msg,
    }


def content_pack(content: Content,
                 gates: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """导出整个内容包（纯 JSON 可序列化的 dict）。"""
    gates = gates or {}
    return {
        "title": content.title,
        "subtitle": content.subtitle,
        "prologue": content.prologue,
        "version": content.version,
        "start_scene": content.start_scene,
        "verdict_scene": content.verdict_scene,
        "interrogate_hall": content.interrogate_hall,
        "verdict_scenes": list(content.verdict_scenes),
        "verdicts": {k: [v[0], v[1]] for k, v in content.verdicts.items()},
        "time_order": list(TIME_ORDER),
        "items": {
            iid: {"name": it.name, "desc": it.desc, "core": it.core, "tag": it.tag}
            for iid, it in content.items.items()
        },
        "characters": {
            cid: {"name": ch.name, "role": ch.role, "trust": ch.trust,
                  "desc": ch.desc, "confide_at": ch.confide_at,
                  "case": list(ch.case)}
            for cid, ch in content.characters.items()
        },
        "scenes": {sid: _scene(sc) for sid, sc in content.scenes.items()},
        "topics": [_topic(tp, gates) for tp in content.topics.values()],
        "endings": [
            {"id": e.id, "title": e.title, "subtitle": e.subtitle,
             "body": e.body, "rank": e.rank, "case": e.case, "rule": ast_of(e.rule)}
            for e in content.endings
        ],
        "dossiers": {did: _dossier(d) for did, d in content.dossiers.items()},
        "starter_dossiers": list(content.starter_dossiers),
        "act_titles": {str(k): v for k, v in sorted(content.act_titles.items())},
        "act_case": {str(k): v for k, v in sorted(content.act_case.items())},
        "act_numbers": content.act_numbers(),
        "core_total": content.core_total(),
        "help_sections": [
            {"title": title, "rows": [[name, text] for name, text in rows]}
            for title, rows in HELP_SECTIONS
        ],
    }


def pack_json(content: Content, gates: Optional[Dict[str, Any]] = None) -> str:
    """内容包的 JSON 文本（网页里内联的那一份）。"""
    return json.dumps(content_pack(content, gates), ensure_ascii=False,
                      sort_keys=True, separators=(",", ":"))
