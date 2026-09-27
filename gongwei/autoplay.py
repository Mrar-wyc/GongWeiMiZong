"""自动通关：给一串「选项标签前缀」，替玩家把游戏走一遍。

这是本项目的核心诊断原语 —— `tools/walk.py`（命令行通关）、
`tools/probe_story.py`（场景图勘探）和 `tests/`（回归测试）都建立在它之上。

记号
----
* ``前缀``   —— 选项标签前缀，必须唯一匹配
* ``@N``     —— 当前可用选项里第 N 个（从 0 计）
* ``@Nf``    —— 只数「还没做过」的选项
* ``!前缀``  —— 断言该选项此刻**不可见**
* ``#档号``  —— 像玩家那样在命令行里敲档号阅档（如 ``#01-FY-XFE``）

``#`` 记号是为了让「阅档」也进入脚本化通关：v2 的门禁是「你有没有读过某份
档案」，只走选项已经不足以证明主线可达。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .data.dossiers import ACT1_READING_ORDER, FIRST_ACT_SUMMARY
from .game import GameEngine

# --------------------------------------------------------------------------
# 通用前奏：从开局走到「刚站进侧殿」为止
# --------------------------------------------------------------------------
#
# 第一幕是有真门槛的（见 ``data/story.py`` 的 ``CRIME_SCENE``）：现场看完还
# 不算完，得把勘验格目读全，出口才解锁；而「勘验总录」自己又挂着 ``requires``。
#
# ``tools/walk.py`` 与 ``tests/helpers.py`` 都从这里取，**别在别处另抄一份**：
# 门槛一调整，抄出去的那份就会悄悄开始说谎。

#: 现场**四**处勘验。这里刻意不含「再验一次」：那一动作在侧殿里还有一个
#: 入口（「回到正殿 · 再验一遍现场」），两边是同一个动作，做过一次就锁。
#: 前奏里做掉，脚本回到正殿时那一步就已经是「已经推演过了」。
SCENE_SWEEP: List[str] = [
    "俯身验尸", "细查门窗", "查看茶与香炉", "翻检塌上枕下",
]

#: 过第一幕门槛所需的阅读序。总录必须最后读——它的 ``requires`` 要前面那些格目。
#: 其中几份档号没有前向链接，只能自己敲出来，这正是「查案」的玩法本身。
ACT1_GATE_READS: List[str] = [f"#{did}" for did in ACT1_READING_ORDER]
ACT1_GATE_READS.append(f"#{FIRST_ACT_SUMMARY}")

#: 从开局到**刚站进侧殿**为止。末尾那一步不能省：门槛就卡在「移步侧殿」上。
#: ``helpers.preface`` 会把调用方重复写的那一步吃掉。
OPENING_ROUTE: List[str] = SCENE_SWEEP + ACT1_GATE_READS + ["移步侧殿"]

#: 只走到门槛前一步（还留在凤仪殿，出口刚亮起来）。
OPENING_AT_GATE: List[str] = SCENE_SWEEP + ACT1_GATE_READS

#: ``OPENING_ROUTE`` 之后的那一步（写在这里，免得两边各写一遍）。
OPENING_NEXT: str = "移步侧殿"


# --------------------------------------------------------------------------
# 案① 后半程 / 真结局
# --------------------------------------------------------------------------
#
# 这一段原来是 ``tools/walk.py`` 与 ``tests/test_story.py`` 各抄一份的。
# 案② 要在「结案陈词」这一屏上进门，两边都得跟着改，所以收到这里来。

#: 案① 后半程：三处查证、五个人问遍、回正殿复看，**收尾停在「结案陈词」那一屏**。
#: 停在这里是有意的：案② 的入口（``CASE2_ENTRY``）就长在这一屏上。
ACT1_SWEEP_TAIL: List[str] = [
    "前往 · 尚药局", "@0f", "@0f", "@0f",
    "回侧殿", "检查 · 正殿案上的安神茶盏",
    "传唤 · 御膳房", "@0f", "@0f", "@0f", "@0f", "@0f", "作揖告退",
    "前往 · 掖庭", "@0f", "@0f", "回侧殿",
    "传唤 · 太监总管", "@0f", "@0f", "@0f", "@0f", "@0f", "@0f", "作揖告退",
    "求见 · 中宫", "@0f", "@0f", "@0f", "@0f", "作揖告退",
    # 贵妃三问按**信任算术**排：送汤 +5 → 25；「还有谁在凤仪殿」要 ≥ 25，问完 =30；
    # 安胎药 −5。顺序一颠倒，最后那一问就永远灰着（案① 二十条话题里就它最难碰到，
    # 旧写法用 ``@0f`` 顺手先问了安胎药，于是这条话题从来没被问出来过）。
    "求见 · 贵妃",
    "问 · 您送的那碗汤", "问她 · 今夜还有谁在凤仪殿", "问她 · 您手里的安胎药",
    "作揖告退",
    "求见 · 皇帝", "@0f", "@0f", "作揖告退",
    "回到正殿", "再验一次", "移步侧殿",
    "整理证物",
]

#: 案① 真结局（「铁证如山」）：拿满案① 的核心线索，指认王德海。
TRUE_ENDING: List[str] = OPENING_ROUTE + ACT1_SWEEP_TAIL + ["「凶手是 —— 太监总管"]


# --------------------------------------------------------------------------
# 案② · 尚药局连环暴毙（第六 ~ 八幕）
# --------------------------------------------------------------------------
#
# 案② 的门槛与案① 同构：勘验收手要读全第六幕格目（``06-YK-END``），
# 问询收手要读全第七幕（``07-DL-END``），两份总录自己又挂着 ``requires``。
# 所以下面这串读档不是「把能读的都读一遍」，而是**照着门禁链走**——
# 顺序换了就读不出来，这正是案② 的玩法。

#: 从案① 的结案陈词进案② 的那一步（门槛：勘验总录 + 八条核心证据）。
CASE2_ENTRY: str = "「臣还有一事"

#: 第六幕 · 药局寒夜：三处勘验全做掉，第六幕格目按门禁链读全，再移步前厅。
CASE2_ACT6: List[str] = [
    # 药库门口那一步（案② 的开场屏）。
    "推门进去",
    # 药库：一口气做五件事，五件都换成线索。
    "俯身验尸", "取铜药匙", "拉开药柜第三层", "验尸僵与尸温", "查看门闩",
    # 值房与账房：两处的原地动作。
    # （值房「查值夜簿上的签押」与药库「验尸僵」给的是同一条线索 ``night_roster2``，
    #   前一步已经拿了，这里就不再点它——非重复动作会自动从选项表里收起。）
    "前往 · 药局值房", "查看那半盏姜汤", "翻炭盆",
    "前往 · 尚药局账房", "翻《本草》", "核对附子入库的日子",
    "查苦杏仁油的七次取用", "把两案的手法摆在一处",
    # 第六幕格目：每一份的 requires 都被上一步喂饱了。
    "#06-DL-SMB", "#06-YK-GYN", "#06-YK-KEY", "#06-YK-DOR", "#06-YK-TIME",
    "#06-SY-ZZZ", "#06-ZF-HXW", "#06-SY-SEAL", "#06-SY-LEDGER",
    "#06-DL-PAIR", "#06-ZF-JJ", "#06-YK-END",
    # 勘验总录读过之后，去前厅那一步才亮。
    "移步 · 药局前厅",
]

#: 第七幕 · 灯下人：第二具尸首、四场问询（话题门禁按依赖顺序点）、第七幕格目。
CASE2_ACT7: List[str] = [
    "去书吏的灯下", "验蒋九的尸首", "收起他抄的那一页", "回前厅",
    "#07-DL-JJ", "#07-DL-PAPER", "#07-SY-LQ", "#07-SY-ZZZ2", "#07-SY-FB",
    "#07-ZF-HXW2", "#07-DL-TWO", "#07-JG-OLD", "#07-DL-HAND", "#07-DL-END",
    # 郑守拙：先问、再出示私账、摊牌十二年前那支笔，最后逼问。
    "传唤 · 尚药局掌局",
    "问 · 高延年几时巡的库", "出示 · 私账上的四个字",
    "摊牌 · 十二年前那支笔", "逼问 · 领用簿上的字是谁写的", "作揖告退",
    # 柳青：手、戌时在哪儿、蒋九找没找过她。
    "传唤 · 司药柳青",
    "问 · 你手上的黄渍", "问她 · 戌时你在哪儿", "问她 · 蒋九今夜找过你吗", "作揖告退",
    # 贺小五：三问（第三问要好感 40，前面两问加上档目正好够）。
    "传唤 · 值夜小监贺小五",
    "问他 · 你巡到药库是几时", "问他 · 锁门的时候闩是里栓还是外锁",
    "问他 · 这几天你躲着谁", "作揖告退",
    # 冯保：他的第三问要掌局的供述先到手，所以排在最后。
    "求见 · 内官监少监冯保",
    "问 · 您是奉谁的旨来的", "把七次取用与掌局的供述摆给他看",
    "问 · 「写成暴病」是什么意思", "作揖告退",
    # 问询总录读过之后，提笔结案才亮。
    "整理证物 · 提笔结案",
]

#: 第七幕的**最小**走法：只把「问询总录」（07-DL-END）的门禁喂饱，
#: 不问掌局那一句「逼问」（那句会给 ``zzz_confession``，把真结局抢走）。
#: 四条错过型的案② 结局都从这条线分叉。
CASE2_ACT7_MIN: List[str] = [
    "去书吏的灯下", "验蒋九的尸首", "收起他抄的那一页", "回前厅",
    # 先把手上的格目读掉：「出示 · 私账上的四个字」这一问要你先读过掌局的私账。
    "#07-DL-JJ", "#07-DL-PAPER", "#07-SY-LQ", "#07-SY-ZZZ2",
    # 柳青的手与掌局的私账：这两份格目是 07-DL-TWO / 07-DL-HAND 的前置。
    "传唤 · 司药柳青", "问 · 你手上的黄渍", "作揖告退",
    "传唤 · 尚药局掌局", "问 · 高延年几时巡的库", "出示 · 私账上的四个字",
    "作揖告退",
    "#07-DL-TWO", "#07-DL-HAND", "#07-DL-END",
    "整理证物 · 提笔结案",
]

#: 案② 的短走法：站在第八幕的结案厅里，但手上没有掌局的供述。
CASE2_SHORT_ROUTE: List[str] = CASE2_ACT6 + CASE2_ACT7_MIN

#: 第八幕 · 连环断：结案陈词这一屏上能把第二份底稿与那条线读齐。
#: （读档与指认不冲突：站在结案厅里照样可以调档。）
CASE2_ACT8: List[str] = [
    "#08-CE-END", "#08-DL-LEAF", "#08-DL-NAME", "#08-SY-CONF",
    "#08-DL-LINK", "#08-DL-VERDICT", "#08-JG-ROAD", "#08-DL-SMB",
]

#: 案② 的完整走法，**收尾停在第八幕的结案厅**（还没指认）。
CASE2_ROUTE: List[str] = CASE2_ACT6 + CASE2_ACT7 + CASE2_ACT8

#: 案② 的真结局（「两案同钉」）：指认郑守拙。
CASE2_TRUE_ROUTE: List[str] = CASE2_ROUTE + ["「凶手是 —— 尚药局掌局"]

#: 两案连打：案① 查到手 → 进案② → 查到手 → 指认郑守拙。
#: 这是「玩家把这部作品玩到底」的那条线，也是唯一能拿满 43 条核心线索的走法。
EVERYTHING_ROUTE: List[str] = (
    OPENING_ROUTE + ACT1_SWEEP_TAIL + [CASE2_ENTRY] + CASE2_TRUE_ROUTE
)

#: 案① 走到结案厅门口（够门槛进案②）的那一段，四条错过型的案② 路线都用它当起手。
CASE2_HEAD: List[str] = OPENING_ROUTE + ACT1_SWEEP_TAIL + [CASE2_ENTRY]

#: 只把第八幕的结案厅走到的短路线（手上没有掌局的供述）。
CASE2_SHORT_HEAD: List[str] = CASE2_HEAD + CASE2_SHORT_ROUTE


# --------------------------------------------------------------------------
# 案③ · 经卷阁 · 景和五年（第九 ~ 十一幕）
# --------------------------------------------------------------------------
#
# 案③ 的门槛与案①/② 同构，但**证据链是「顺着格子读」**：第九幕的格目彼此
# 挂着前向链接，总录（``09-JG-END``）自己又要六份格目全读过。所以下面这串
# 读档不是「把能读的都读一遍」，顺序换了就读不出来。

#: 从案② 的结案陈词进案③ 的那一步（门槛：``07-JG-OLD`` 上的旧封泥线索
#: ``jinghe_seal``；那条线索只在案② 的**完整**走法里拿得到，短走法拿不到）。
CASE3_ENTRY: str = "「臣还有一事 —— 经卷阁"

#: 第九幕 · 经卷阁：丙字库九处勘验、掌籍厅三份、内官监值房三处，
#: 再把第九幕格目按链接链读全，最后移步阁前问人。
CASE3_ACT9: List[str] = [
    # 阁前那张开场屏 → 丙字库（尸首在书梯下）。
    "推门进去",
    # 丙字库九处：每一处换一组线索，一处也不重复。
    "俯身验尸", "取银针", "数炭盆", "搬书梯", "揭下封泥", "掰开她的右手",
    "拾起她脚边的调档单", "蹲下来", "看炭灰里的脚印",
    # 回阁前 → 掌籍厅：日课簿、景和五年那一格、交接簿（三份档案）。
    "回阁前", "去掌籍厅",
    "翻她的日课簿", "查景和五年那一格", "翻掌籍的交接簿",
    # 内官监值房：领钥匙簿、炭筐、掌印的火炉。
    "去内官监值房",
    "翻领钥匙簿", "点数炭筐", "看看掌印的火炉",
    # 第九幕格目：照链接链读全（总录必须最后读，它要前面六份）。
    "#09-DL-SMB", "#09-JG-YARD", "#09-JG-XYP", "#09-JG-NDL", "#09-JG-HAND",
    "#09-JG-COAL", "#09-JG-VNT", "#09-JG-SEAL", "#09-JG-KEY", "#09-JG-LAST",
    "#09-JG-PURGE", "#09-JG-FOOT", "#09-JG-END",
    # 总录读过之后，问人那一步才亮。
    "移步 · 阁前问人",
]

#: 第十幕 · 阁前人：四场问询（话题门禁按依赖顺序点）+ 第十幕格目 + 提笔结案。
#: 好感算术：常安 30 →（值夜 +5、添炭 +5）= 40，第三问要 ≥ 40；
#: 曹淳 30 →（封存 +5、钥匙 +5）= 40，第三问要 ≥ 40；冯保 40，跨案不变。
CASE3_ACT10: List[str] = [
    # 常安：值夜 → 添炭 → 靴子。
    "传唤 · 看阁小监常安",
    "问他 · 昨夜你在哪儿值夜", "问他 · 炭是谁让你添的",
    "问他 · 你看见那个人的靴子了吗", "作揖告退",
    # 陆文昭：抄什么 → 少的那一行 → 三遍都烧了吗（三问靠线索串，不靠好感）。
    "传唤 · 候补书吏陆文昭",
    "问她 · 师父昨夜让你抄什么", "问她 · 少的那一行是哪一行",
    "问她 · 三遍都烧了吗", "作揖告退",
    # 曹淳：封存 → 销号 → 御笔（第三问 −5，问完掉回 35，后面不再用他）。
    "求见 · 内官监掌印曹淳",
    "问 · 封存是你下的令", "问 · 领钥匙簿上的销号为什么是空的",
    "问 · 那一页上还有谁的字", "作揖告退",
    # 冯保：寅时在哪儿 → 封泥与蜡摆在他面前（后者是「灯下灭口」那条心的开关）。
    "求见 · 内官监少监冯保",
    "问 · 前日寅时你在哪儿", "把封泥与气窗上的蜡摆在他面前", "作揖告退",
    # 第十幕格目：四份问询录 + 原页 + 总录（总录要四录全读过）。
    "#10-DL-SMB", "#10-DL-CA", "#10-DL-LWS", "#10-DL-CC", "#10-DL-FB",
    "#10-JG-ORIG", "#10-DL-END",
    # 总录读过之后，结案那一步才亮。
    "整理证物 · 提笔结案",
]

#: 第十幕的**最小**走法：不摆封泥与蜡（``fb_cracked3`` 不点），
#: 于是「指认冯保」只能落到「留中」。错过型的案③ 结局从这条线分叉。
CASE3_ACT10_MIN: List[str] = [
    s for s in CASE3_ACT10 if s != "把封泥与气窗上的蜡摆在他面前"
]

#: 案② 走到底、**收尾停在案② 的结案屏**（案③ 的入口就长在这一屏上）。
CASE3_HEAD: List[str] = CASE2_HEAD + CASE2_ROUTE

#: 案③ 的完整走法，**收尾停在第十一幕的结案屏**（还没指认）。
CASE3_ROUTE: List[str] = (
    CASE3_HEAD + [CASE3_ENTRY] + CASE3_ACT9 + CASE3_ACT10
)

#: 手上有原页与御笔、但没有点破冯保那层心的走法。
CASE3_ROUTE_MIN: List[str] = (
    CASE3_HEAD + [CASE3_ENTRY] + CASE3_ACT9 + CASE3_ACT10_MIN
)


# --------------------------------------------------------------------------
# 十九条结局路线：每个结局各一条「真的能走到」的路线
# --------------------------------------------------------------------------
#
# 这张表是**唯一**一份。三个地方都从这里取：
#
# * ``tests/test_story.py`` —— 逐条断言「这条路线确实落到这个结局」；
# * ``tests/test_tui.py``   —— 每种结局屏都渲染一遍、量一遍宽度；
# * ``tools/audit_story.py`` —— 可达性体检的起手式（撒网搜索有预算上限，
#   案② 加进来之后它就曾把「证据薄」的两条结局漏报成死结局）。
#
# 抄一份出去，剧本一动就会有一边开始说谎。

#: 结局 id -> 能走到它的路线。案① 八条、案② 五条、案③ 六条。
ENDING_ROUTES: Dict[str, List[str]] = {
    "ending_restitution": TRUE_ENDING,
    # 指认王德海却拿不出决定性证据 → 被按下
    "ending_pressured": OPENING_ROUTE + ["整理证物", "「凶手是 —— 太监总管"],
    # 有决定性证据但只够「尘埃落定」
    "ending_standard": OPENING_ROUTE + [
        "传唤 · 太监总管", "@0f", "@0f", "@0f", "@0f", "@0f", "@0f", "作揖告退",
        "整理证物", "「凶手是 —— 太监总管"],
    # 指认皇后 → 玉扳指
    "ending_dangerous": OPENING_ROUTE + [
        "传唤 · 太监总管", "@0f", "@0f", "作揖告退",
        "整理证物", "「凶手是 —— 中宫"],
    # 空手指认贵妃 → 替罪的人
    "ending_false": OPENING_ROUTE + ["整理证物", "「凶手是 —— 贵妃"],
    # 不指认任何人 → 查不出来
    "ending_bystander": OPENING_ROUTE + ["整理证物", "「此案 —— 暂无确证"],
    # 证据够了但选择缄口 → 辞官
    "ending_quiet": OPENING_ROUTE + [
        "传唤 · 太监总管", "@0f", "@0f", "@0f", "@0f", "@0f", "@0f", "作揖告退",
        "整理证物", "「臣 —— 验得出来"],
    # 指认皇帝 → 天子无案
    "ending_treason": OPENING_ROUTE + [
        "前往 · 尚药局", "@0f", "@0f", "@0f", "回侧殿",
        "检查 · 正殿案上的安神茶盏",
        "传唤 · 太监总管", "@0f", "@0f", "@0f", "@0f", "@0f", "@0f", "作揖告退",
        "整理证物", "「凶手是 —— 陛下"],
    # —— 案② 的五条：短走法（手上没有掌局的供述）上分叉 ——
    # 两案连打到底 → 两案同钉（唯一拿满 43 条核心线索的走法）
    "ending2_truth": EVERYTHING_ROUTE,
    # 手上没有供述就指认掌局 → 又是暴病
    "ending2_pressed": CASE2_SHORT_HEAD + ["「凶手是 —— 尚药局掌局"],
    # 指认柳青 / 贺小五 → 错的药方
    "ending2_wrong": CASE2_SHORT_HEAD + ["「凶手是 —— 司药"],
    # 指认冯保 → 灯灭
    "ending2_lightout": CASE2_SHORT_HEAD + ["「凶手是 —— 内官监"],
    # 只写两个名字就走 → 只写两个名字
    "ending2_quiet": CASE2_SHORT_HEAD + ["「这两桩药局的死"],
    # —— 案③ 的六条：完整走法（手上有原页与御笔）上分叉 ——
    # 原页 + 御笔 + 点破冯保那层心 → 原页（上上）
    "ending3_orig": CASE3_ROUTE + ["「凶手是 —— 内官监少监 冯保」"],
    # 指认冯保却没能点破他那层心 → 留中
    "ending3_sealed": CASE3_ROUTE_MIN + ["「凶手是 —— 内官监少监 冯保」"],
    # 指认掌印曹淳 → 奉旨（半个月后冯保升掌印）
    "ending3_byorder": CASE3_ROUTE + ["「凶手是 —— 内官监掌印 曹淳」"],
    # 指认常安 / 陆文昭 → 替罪的人
    "ending3_wrong": CASE3_ROUTE + ["「凶手是 —— 看阁小监 常安」"],
    # 指认御笔 → 不可说（那一步要先有 ``emperor_ink``）
    "ending3_unspeakable": CASE3_ROUTE + ["「凶手是 —— 陛下」"],
    # 只写事实、不写凶手 → 合上卷宗
    "ending3_quiet": CASE3_ROUTE + ["「这三桩案子"],
}



class WalkError(RuntimeError):
    """脚本与剧本对不上时抛出。"""


class _ReadStep:
    """把「敲档号」伪装成一个选项，好让 ``play()`` 不需要分叉。"""

    def __init__(self, engine: GameEngine, did: str) -> None:
        self.did = did
        self.label = f"阅档 #{did}"
        self.detail = ""
        self.enabled = True
        self.hint = ""
        self.asked = False
        self._engine = engine

    def action(self):
        return self._engine.read_dossier(self.did)


def resolve(engine: GameEngine, step: str) -> Optional[object]:
    """把一个记号解析成 Option；``!`` 断言返回 None。"""
    opts = engine.options()
    if step.startswith("#"):
        did = step[1:].strip()
        if not engine.dossier_exists(did):
            raise WalkError(f"剧本里没有档案 {did}")
        if not engine.can_read_dossier(did):
            case = engine.dossier_case(did)
            if case > engine.state.case:
                raise WalkError(f"档案 {did} 属于第 {case} 案，还没走到")
            raise WalkError(f"档案 {did} 此时还读不到（requires 未满足）")
        return _ReadStep(engine, did)
    if step.startswith("@"):
        raw = step[1:]
        fresh = raw.endswith("f")
        idx = int(raw[:-1] if fresh else raw)
        pool = [o for o in opts if o.enabled and (not fresh or not o.asked)]
        if idx >= len(pool):
            raise WalkError(f"{step} 越界：当前只有 {len(pool)} 个可用选项")
        chosen = pool[idx]
    elif step.startswith("!"):
        hits = [o for o in opts if o.label.startswith(step[1:])]
        if hits:
            raise WalkError(f"断言失败：{step[1:]} 本来不该出现")
        return None
    else:
        hits = [o for o in opts if o.label.startswith(step)]
        if len(hits) != 1:
            names = " / ".join(f"{o.index}.{o.label}" for o in opts)
            raise WalkError(f"「{step}」匹配到 {len(hits)} 项（当前：{names}）")
        chosen = hits[0]
    if not chosen.enabled:
        raise WalkError(f"「{chosen.label}」被锁住：{chosen.hint}")
    return chosen


def play(engine: GameEngine, steps: List[str],
         on_step=None) -> Tuple[GameEngine, List[str]]:
    """按脚本走完；返回引擎与「每步一行」的记录。"""
    lines: List[str] = []
    for i, step in enumerate(steps, 1):
        chosen = resolve(engine, step)
        if chosen is None:
            lines.append(f"{i:>3}. 断言 {step[1:]}")
            continue
        before = engine.state.scene
        upd = chosen.action()
        if engine.at_verdict() and not engine.state.ending:
            engine.finalize()
        line = (f"{i:>3}. [{before}] {chosen.label[:34]:<36} → "
                f"{engine.state.scene:<16} 线索+{len(upd.new_clues)} "
                f"核心={engine.state.core_count()}")
        lines.append(line)
        if on_step is not None:
            on_step(engine, chosen, upd)
    return engine, lines
