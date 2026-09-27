"""脚本化通关：按给定的选项顺序走一遍，打印每步状态。

用法::

    python tools/walk.py "俯身验尸" "细查门窗" "@0f" ...

记号见 ``gongwei/autoplay.py``：``前缀`` 唯一匹配标签、``@N`` 取第 N 个可用项、
``@Nf`` 只数没做过的、``!前缀`` 断言不可见。不给参数则跑默认的「真结局」路线。
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from gongwei.autoplay import TRUE_ENDING as _TRUE_ENDING, WalkError, play
from gongwei.data import CONTENT, TOPIC_GATES
from gongwei.game import GameEngine

#: 默认路线：拿满案① 的 21 条核心线索 → 指认王德海 → 真结局「铁证如山」。
#:
#: 不在这里另抄一份：路线定义在 ``gongwei/autoplay.py``，测试与
#: ``tools/audit_web.py`` 取的是同一份常量（抄一份出去，门槛一调整
#: 那份就会悄悄开始说谎）。想连案② 一起走，用
#: ``gongwei.autoplay.EVERYTHING_ROUTE``。
TRUE_ENDING = list(_TRUE_ENDING)


def main(argv) -> int:
    engine = GameEngine(CONTENT, gates=TOPIC_GATES)
    engine.new_game()
    print(f"开局 {engine.state.scene} · {engine.scene.title}")
    lines: list = []

    def note(_engine, _choice, _upd) -> None:
        pass

    try:
        engine, lines = play(engine, argv or TRUE_ENDING, on_step=note)
    except WalkError as exc:
        for line in lines:
            print(line)
        state = engine.state
        print(f"!! 第 {len(lines) + 1} 步 {exc}")
        print("   当前场景:", state.scene, f"（{engine.scene.title}）")
        for opt in engine.options():
            flag = " " if opt.enabled else "x"
            print(f"   {flag} {opt.index}. {opt.label}"
                  + (f"   [{opt.hint}]" if opt.hint else ""))
        return 1
    for line in lines:
        print(line)
    state = engine.state
    print("\n场景:", state.scene, f"（{engine.scene.title}）")
    print("结局:", state.ending or "（未结算）")
    print("核心:", state.core_count(), "/", CONTENT.core_total())
    print("线索:", len(state.clues), "行囊:", len(state.items_owned),
          "回合:", state.turn, "评分:", state.score)
    print("flags:", sorted(state.flags))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
