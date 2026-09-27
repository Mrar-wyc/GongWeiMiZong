"""条件表达式：把剧本里的可读字符串编译成 ``state -> bool`` 的纯函数。

支持的小语言（大小写不敏感）::

    clue:si_needle                      拥有某条线索
    clues:si_needle,tea_residue>=2      至少拥有其中 N 条
    flag:forced_entry                   某个剧情标记已置位
    !flag:x                             取反
    trust:WDH>=60                       好感度比较（>= > <= < == !=）
    min_trust:WH=50,GW=35               多名角色同时达标
    suspect:WDH                         已指认的嫌疑人
    evidence:core>=4                    核心证据数量
    evidence:total>=8                   线索总数
    time_at:丑时                         当前时辰（含之后）
    visited:interrogate_hall            到过某场景

组合：``a and b``、``a or b``、``(a or b) and !c``
"""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Sequence

from .models import Condition

# --------------------------------------------------------------------------
# 时辰顺序（推进时间线用）
# --------------------------------------------------------------------------

TIME_ORDER: Sequence[str] = ("子时三刻", "丑时", "丑时二刻", "寅时", "寅时三刻", "卯时")


def time_index(t: str) -> int:
    try:
        return list(TIME_ORDER).index(t)
    except ValueError:
        return 0


# --------------------------------------------------------------------------
# 原子条件
#
# 每个条件函数都贴着一个可序列化的 AST（``fn.ast``，就是上面那种嵌套列表）。
# 这不是装饰：网页前端跑的是同一份剧本，但它没有 Python，只能拿到 JSON。
# 生成器 `tools/build_web.py` 把 AST 写进内容包，JS 侧用一棵等价的小求值器
# 解释它 —— 于是「什么条件下这个选项可点」这件事只有一份定义，
# 两边不可能各自漂移。`tests/test_web.py` 会核对「AST 与 Python 判断逐态一致」。
# --------------------------------------------------------------------------

Node = List[object]


def stamped(node: Node, fn: Condition) -> Condition:
    """给条件函数贴上 AST。"""
    fn.ast = node  # type: ignore[attr-defined]
    return fn


def ast_of(cond: Optional[Condition]) -> Optional[Node]:
    """取条件的 AST；没有 AST 的自造 lambda 返回 ``None``（生成器会报错）。"""
    if cond is None:
        return None
    return getattr(cond, "ast", None)


def has_clue(cid: str) -> Condition:
    """是否已入手某条证据。

    线索与物证一起算 —— 核心证据 `tea_set 安神茶盏` 就是入行囊的物证，
    只查 ``state.clues`` 会让 ``has_clue("tea_set")`` 永远是假。
    """
    return stamped(["clue", cid],
                   lambda state: cid in state.clues or cid in state.items_owned)


def clue_absent(cid: str) -> Condition:
    """手上还没有某条线索（「按下」那类结局要用）。"""
    return stamped(["not", ["clue", cid]], lambda state: not has_clue(cid)(state))


def has_flag(flag: str) -> Condition:
    return stamped(["flag", flag], lambda state: flag in state.flags)


def has_dossier(did: str) -> Condition:
    """是否已经**阅过**某份档案。

    判「读过」而不是「在档目里」：档目里躺着一份没打开的档案，等于不知道里面的
    事情。门禁若要的是「你已经知道」，就该用这个。
    """
    return stamped(["dossier", did], lambda state: state.dossier_read(did))


def dossiers_read_at_least(n: int) -> Condition:
    """已阅档案数至少 n 份。"""
    return stamped(["dossiers_count", ">=", n],
                   lambda state: sum(1 for did in state.dossier_states
                                     if state.dossier_read(did)) >= n)


def missing_dossier(did: str) -> Condition:
    """还没阅过某份档案——给 ``locked_if`` 用的写法。

    ``locked_if`` 的语义是「这个条件成立时，选项上锁」。所以「你必须先读过
    X 才能往下走」应当写成 ``locked_if=missing_dossier("X")``，
    而不是 ``locked_if=has_dossier("X")``（那会反过来：读过之后才锁上）。
    """
    return stamped(["missing_dossier", did],
                   lambda state: not state.dossier_read(did))


def trust_at_least(cid: str, value: int) -> Condition:
    return stamped(["trust", cid, ">=", value],
                   lambda state: state.trust_of(cid) >= value)


def trust_compare(cid: str, op: str, value: int) -> Condition:
    """好感度比较（``op`` 取 ``>= <= == != > <``）。"""
    import operator as _op

    cmp = {">=": _op.ge, "<=": _op.le, "==": _op.eq,
           "!=": _op.ne, ">": _op.gt, "<": _op.lt}[op]
    return stamped(["trust", cid, op, value],
                   lambda state: cmp(state.trust_of(cid), value))


def clue_count_at_least(n: int) -> Condition:
    """线索总数（含物证）至少 n 条。"""
    return stamped(["clues_count", ">=", n],
                   lambda state: len(state.clues) + len(state.items_owned) >= n)


def core_count_at_least(n: int) -> Condition:
    return stamped(["core_count", ">=", n], lambda state: state.core_count() >= n)


def all_clues(*ids: str) -> Condition:
    return stamped(["all", [["clue", i] for i in ids]],
                   lambda state: all(i in state.clues or i in state.items_owned
                                     for i in ids))


def any_clues(*ids: str) -> Condition:
    return stamped(["any", [["clue", i] for i in ids]],
                   lambda state: any(i in state.clues or i in state.items_owned
                                     for i in ids))


def at_least_clues(n: int, *ids: str) -> Condition:
    """在给定 id 里至少满足 n 条；不给 id 时表示「线索总数至少 n 条」。"""
    if not ids:
        return clue_count_at_least(n)
    return stamped(["clues_at_least", list(ids), n],
                   lambda state: sum(1 for i in ids
                                     if i in state.clues
                                     or i in state.items_owned) >= n)


def accused_is(cid: str) -> Condition:
    """被指认者是谁（结局规则要用）。"""
    return stamped(["suspect", cid], lambda state: state.accused == cid)


def accused_in(*ids: str) -> Condition:
    return stamped(["suspect_in", list(ids)], lambda state: state.accused in ids)


def visited(scene_id: str) -> Condition:
    return stamped(["visited", scene_id], lambda state: scene_id in state.visited)


def always(state) -> bool:  # noqa: ANN001
    return True


def never(state) -> bool:  # noqa: ANN001
    return False


always.ast = ["always"]  # type: ignore[attr-defined]
never.ast = ["never"]  # type: ignore[attr-defined]


def all_of(*conds: Optional[Condition]) -> Condition:
    real = [c for c in conds if c is not None]
    return stamped(["all", [ast_of(c) for c in real]],
                   lambda state: all(c(state) for c in real))


def any_of(*conds: Optional[Condition]) -> Condition:
    real = [c for c in conds if c is not None]
    return stamped(["any", [ast_of(c) for c in real]],
                   lambda state: any(c(state) for c in real))


def negate(cond: Optional[Condition]) -> Condition:
    inner = cond or always
    return stamped(["not", ast_of(inner)], lambda state: not inner(state))


# --------------------------------------------------------------------------
# 小语言解析
# --------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"\s*(\(|\)|,|>=|<=|==|!=|>|<|!|[\w\u4e00-\u9fff:.\-]+)")


class ConditionSyntaxError(ValueError):
    """剧本里的条件写错了。"""


def _tokenize(expr: str) -> List[str]:
    tokens: List[str] = []
    pos = 0
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if not m:
            if expr[pos:].strip() == "":
                break
            raise ConditionSyntaxError(f"无法解析条件片段: {expr[pos:]!r} (完整: {expr!r})")
        tokens.append(m.group(1))
        pos = m.end()
    return tokens


class _Parser:
    def __init__(self, tokens: Sequence[str], expr: str) -> None:
        self.tokens = list(tokens)
        self.pos = 0
        self.expr = expr

    def peek(self) -> Optional[str]:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def next(self) -> Optional[str]:
        tok = self.peek()
        if tok is not None:
            self.pos += 1
        return tok

    def parse(self) -> Condition:
        cond = self.parse_or()
        if self.peek() is not None:
            raise ConditionSyntaxError(f"多余的内容 {self.peek()!r} (完整: {self.expr!r})")
        return cond

    def parse_or(self) -> Condition:
        left = self.parse_and()
        while self.peek() is not None and self.peek().lower() == "or":
            self.next()
            right = self.parse_and()
            left = any_of(left, right)
        return left

    def parse_and(self) -> Condition:
        left = self.parse_unary()
        while self.peek() is not None and self.peek().lower() == "and":
            self.next()
            right = self.parse_unary()
            left = all_of(left, right)
        return left

    def parse_unary(self) -> Condition:
        tok = self.peek()
        if tok == "!" or (tok is not None and tok.lower() == "not"):
            self.next()
            return negate(self.parse_unary())
        if tok == "(":
            self.next()
            inner = self.parse_or()
            if self.next() != ")":
                raise ConditionSyntaxError(f"括号未闭合 (完整: {self.expr!r})")
            return inner
        return self.parse_atom()

    def parse_atom(self) -> Condition:
        tok = self.next()
        if tok is None:
            raise ConditionSyntaxError(f"条件不完整 (完整: {self.expr!r})")
        key, _, value = tok.partition(":")
        key = key.lower()

        # ``clues:`` / ``min_trust:`` 的值是逗号列表；``clue:`` / ``flag:`` 的值
        # 是一个标识符。分词器会在逗号处切开，这里统一把「同一字段」的后续片段粘回来。
        if key in ("clues", "min_trust", "clue", "flag", "dossier", "dossiers",
                   "suspect", "visited"):
            while self.peek() == ",":
                self.next()
                nxt = self.next()
                if nxt is None or nxt.startswith((">", "<", "=", "!")):
                    raise ConditionSyntaxError(f"{key} 的取值不完整 (完整: {self.expr!r})")
                value += "," + nxt
        if key == "clue":
            return has_clue(value)
        if key == "flag":
            return has_flag(value)
        if key == "dossier":
            return has_dossier(value)
        if key == "suspect":
            return accused_is(value)
        if key == "visited":
            return visited(value)
        if key == "time_at":
            return stamped(["time_at", value],
                           lambda state: time_index(state.time) >= time_index(value))
        if key in ("clues", "evidence", "dossiers", "trust", "min_trust"):
            op = self.next()
            if op not in (">=", "<=", "==", "!=", ">", "<"):
                raise ConditionSyntaxError(f"{key} 后缺少比较运算符 (完整: {self.expr!r})")
            num_tok = self.next()
            if num_tok is None or not num_tok.lstrip("-").isdigit():
                raise ConditionSyntaxError(f"{key} 后缺少数字 (完整: {self.expr!r})")
            return self._build_number_cond(key, value, op, int(num_tok))
        raise ConditionSyntaxError(f"未知条件关键字 {key!r} (完整: {self.expr!r})")

    def _build_number_cond(self, key: str, value: str, op: str, num: int) -> Condition:
        import operator as _op

        cmp = {
            ">=": _op.ge, "<=": _op.le, "==": _op.eq,
            "!=": _op.ne, ">": _op.gt, "<": _op.lt,
        }[op]

        if key == "trust":
            cid = value
            return stamped(["trust", cid, op, num],
                           lambda state: cmp(state.trust_of(cid), num))

        if key == "min_trust":
            pairs = [p for p in value.split(",") if p]
            if not pairs:
                raise ConditionSyntaxError("min_trust 缺少角色")
            return stamped(["all", [["trust", cid, op, num] for cid in pairs]],
                           lambda state: all(cmp(state.trust_of(cid), num)
                                             for cid in pairs))

        if key == "clues":
            ids = [c for c in value.split(",") if c]
            if ids:
                return stamped(["clues_count_in", ids, op, num],
                               lambda state: cmp(sum(1 for i in ids
                                                     if i in state.clues), num))
            return stamped(["clues_count", op, num],
                           lambda state: cmp(len(state.clues), num))

        if key == "evidence":
            if value in ("", "total"):
                return stamped(["clues_count", op, num],
                               lambda state: cmp(len(state.clues), num))
            if value == "core":
                return stamped(["core_count", op, num],
                               lambda state: cmp(state.core_count(), num))
            if value == "item":
                return stamped(["items_count", op, num],
                               lambda state: cmp(len(state.items_owned), num))
            raise ConditionSyntaxError(f"evidence 的范围只支持 core/total/item，收到 {value!r}")

        if key == "dossiers":
            # `dossiers: >= 6` —— 已阅档案数。用 0 表示不限范围。
            return stamped(["dossiers_count", op, num],
                           lambda state: cmp(
                               sum(1 for did in state.dossier_states
                                   if state.dossier_read(did)), num))
        raise ConditionSyntaxError(f"未知数值条件 {key!r}")


_CACHE: Dict[str, Condition] = {}


def parse_condition(expr: Optional[str]) -> Optional[Condition]:
    """把条件字符串编译成函数；``None``/空串表示无条件。"""
    if expr is None:
        return None
    text = expr.strip()
    if not text:
        return None
    if text in _CACHE:
        return _CACHE[text]
    cond = _Parser(_tokenize(text), text).parse()
    _CACHE[text] = cond
    return cond


def as_condition(spec) -> Optional[Condition]:  # noqa: ANN001
    """接受 ``None`` / ``str`` / 可调用对象，统一成条件函数。"""
    if spec is None:
        return None
    if callable(spec):
        return spec
    return parse_condition(str(spec))
