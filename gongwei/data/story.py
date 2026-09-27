"""剧本：《宫闱迷踪 · 贤妃案》。

时间线（案发当夜）
------------------
戌时初   贤妃遣退近侍，独处凤仪殿（对外称「要静心抄经」）
戌时三刻 皇后萧氏私访凤仪殿（不合宫规，秘而不宣）
亥时初   王德海送安神茶入殿
亥时二刻 茶盏碎裂
亥时末   王德海再来，破门，报「贤妃薨」

真相
----
真凶是**太监总管王德海**。他以「苦杏仁油」（杏仁油，味似苦杏仁）下于安神茶中——
苦杏仁油含氰苷，是宫内取用方便而又不会被银针「明显验出」的慢性毒。
所谓香炉中的红色粉末是**朱砂**：朱砂入炉只会让人昏沉目眩，银针验不出、也不致死，
那是他事后布下的**障眼法**，用来把水搅浑。

动机有两层：
* 眼前——贤妃近日密查「内务府账目亏空」与一条**采薇杖毙**的旧案，已经查到王德海头上；
* 旧账——采薇当年是他手下的宫人，被杖毙的罪名是他伪造的，只为遮掩自己的亏空。

皇后有动机（贤妃手握太子之死的秘密）却被人拿住把柄；贵妃有动机（争宠）却只送了汤；
皇帝有隐情（天家骨肉）却只想把案子按下去——三人都不是凶手。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..game.conditions import (accused_in, accused_is, all_of, always, any_of,
                               at_least_clues, clue_absent, core_count_at_least,
                               has_clue, has_dossier, has_flag, missing_dossier,
                               negate, stamped, trust_at_least)
from ..game.models import (Character, Choice, Content, Effect, EndingRule, Item,
                           Scene, Topic)
from .dossiers import ACT_TITLES, FIRST_ACT_SUMMARY, build_dossiers

#: 每一案占哪几幕。**「哪几幕属于哪一案」的唯一事实源**：剧情锁按它算
#: （引擎与网页端同一张表 —— 后者由内容包带走）。
CASE_ACTS: Dict[int, Tuple[int, ...]] = {
    1: (1, 2, 3, 4, 5),      # 凤仪殿贤妃暴毙
    2: (6, 7, 8),            # 尚药局连环暴毙
    3: (9, 10, 11),          # 经卷阁 · 景和五年
}


def act_case_map() -> Dict[int, int]:
    """幕号 -> 案号（`Content.act_case` 的内容）。"""
    return {act: case for case, acts in CASE_ACTS.items() for act in acts}

# --------------------------------------------------------------------------
# 便捷构造
# --------------------------------------------------------------------------


def E(text: str = "", clues=(), items=(), dossiers=(), trust=(), flags=(),
      time: str = "", scene: str = "", score: int = 0, hurt: int = 0,
      to: str = "") -> Effect:
    return Effect(
        text=text or None,
        add_clues=tuple(clues),
        add_items=tuple(items),
        add_dossiers=tuple(dossiers),
        trust=tuple(trust),
        flags=tuple(flags),
        time=time or None,
        scene=scene or None,
        score=score,
        hurt=hurt,
    )


def missing_any_clue(ids) -> object:
    """只要还有任一条线索未入簿，动作就仍该显示（用于原地动作自动去重）。"""
    ids = tuple(ids)
    return stamped(["any", [["not", ["clue", cid]] for cid in ids]],
                   lambda state: any(cid not in state.clues
                                     and cid not in state.items_owned
                                     for cid in ids))


def acting(
    scene: str,
    label: str,
    detail: str = "",
    text: str = "",
    clues=(),
    items=(),
    dossiers=(),
    trust=(),
    flags=(),
    time: str = "",
    score: int = 0,
    wants: str = "",
    locked_by=None,
    locked_hint: str = "",
    visible_if=None,
    repeatable: Optional[bool] = None,
) -> Choice:
    """一个「去做某事」的选项。

    ``scene`` 传当前场景 id 表示「原地动作」（不跳场景）；传别的场景 id 才真的换场景。
    原地动作若已产出线索，应在 ``visible_if`` 里挂上 ``has_clue(...)``，做过就不再显示。

    ``repeatable`` 默认由效果决定：**带线索／物证／档案／评分／信任的动作做过一次
    就够了**（再点一遍只是把同一段文字重念一遍，而分数与信任却是照加的 —— 会被
    刷）。真正要反复走的枢纽动作（移步、传唤、结案）不带这些效果，天然可重复。
    """
    if repeatable is None:
        repeatable = not (clues or items or dossiers or score or trust)
    here = scene in ("crime_scene", "interrogate_hall", "pharmacy", "archive",
                     "talk_wdh", "talk_xse", "talk_hh", "talk_gf", "talk_hd",
                     # 案②：药库 / 值房 / 账房 / 前厅 / 灯下 / 四场问询
                     "case2_open", "drug_store", "night_room", "drug_office",
                     "case2_hall", "lamp_room", "talk_zzz", "talk_lq",
                     "talk_hxw", "talk_fb",
                     # 案③：阁前 / 丙字库 / 掌籍厅 / 内官监值房 / 阁前问人 / 四场问询
                     "case3_open", "jinghe_room", "scriptorium3", "key_room3",
                     "case3_hall", "talk_ca", "talk_lws", "talk_fb3", "talk_cc")
    if here and clues and visible_if is None:
        visible_if = missing_any_clue(clues)
    return Choice(
        label=label,
        to="" if here else scene,
        detail=detail,
        effect=E(text=text, clues=clues, items=items, dossiers=dossiers,
                 trust=trust, flags=flags,
                 time=time, score=score, scene=scene if not here else ""),
        wants=wants,
        locked_if=locked_by,
        locked_hint=locked_hint,
        visible_if=visible_if,
        repeatable=repeatable,
    )


# --------------------------------------------------------------------------
# 人物
# --------------------------------------------------------------------------

CHARACTERS: Dict[str, Character] = {
    "SMB": Character("SMB", "沈墨白", "大理寺仵作（你）", 0,
                     "验尸出身，惯于从死人身上找活人的破绽。", 999),
    "XF": Character("XF", "贤妃苏氏", "已故 · 六妃之一", 0,
                    "死者在凤仪殿榻上，嘴角黑色血迹。", 999),
    "WDH": Character("WDH", "王德海", "太监总管 · 掌凤仪殿起居", 45,
                     "圆滑、勤谨、话密。手里有整座后宫的钥匙。", 55),
    "HH": Character("HH", "皇后萧氏", "中宫之主", 30,
                    "端方寡言。看人的时候像在称你的分量。", 55),
    "GF": Character("GF", "贵妃柳氏", "四妃之首 · 掌协理六宫", 20,
                    "声高气盛，把「看不惯」写在脸上。", 30),
    "HD": Character("HD", "皇帝萧衍", "九五之尊", 50,
                     "疲倦，克制。谈起长兄时眼神会飘开。", 60),
    "XSE": Character("XSE", "小顺子", "御膳房小监 · 十五岁", 35,
                     "瘦小、机灵、怕事。袖口总是沾着炭灰。", 50),
    # ---------------- 案② 尚药局连环暴毙 ----------------
    "GYN": Character("GYN", "高延年", "尚药局典药 · 已故", 0,
                     "掌药库钥匙二十三年。认得出每一味药的斤两，也认得出谁的手不稳。", 999, case=(2,)),
    "ZZZ": Character("ZZZ", "郑守拙", "尚药局掌局太监", 35,
                     "谨慎到近乎迟钝。他从不自己写账，也从不自己开锁。", 999, case=(2,)),
    "LQ": Character("LQ", "柳青", "尚药局司药宫女 · 十九岁", 40,
                    "识药，手稳，黑里也摸得清附子和乌头。她的话比她的手脚慢半拍。", 55, case=(2,)),
    "HXW": Character("HXW", "贺小五", "药库值夜小监 · 十六岁", 30,
                     "瘦，怕黑，值夜要留一盏灯。他记得每一夜谁走过廊子。", 50, case=(2,)),
    "JJ": Character("JJ", "蒋九", "药库书吏 · 三十一岁", 25,
                    "抄了半辈子账。他的手认得出别人的字，比认人还准。", 999, case=(2,)),
    # 冯保是**跨案**的人：案② 他奉旨来收口，案③ 他手上多了一把钥匙。
    "FB": Character("FB", "冯保", "内官监少监 · 奉旨问案", 40,
                    "说话像在念公文。他来的那一夜，尚药局的灯全灭了一刻。", 50, case=(2, 3)),
    # ---------------- 案③ 经卷阁 · 景和旧案 ----------------
    "XYP": Character("XYP", "谢云屏", "经卷阁掌籍女史 · 已故", 0,
                     "在阁二十九年，认得出先帝的墨、今上的朱。死在丙字库里，门是从外封的。",
                     999, case=(3,)),
    "CC": Character("CC", "曹淳", "内官监掌印太监", 30,
                    "掌印二十一年。他说话从不超过两句，第一句是「奉旨」，第二句是「封存」。",
                    40, case=(3,)),
    "CA": Character("CA", "常安", "经卷阁看阁小监 · 十六岁", 30,
                    "去年才拨进阁里，认得的字不多。他记得谁在什么时候上了阁顶。",
                    45, case=(3,)),
    "LWS": Character("LWS", "陆文昭", "经卷阁候补书吏 · 二十二岁", 35,
                     "写得一手好字，抄书时手不抖。她师父昨夜让她抄的东西，她抄了三遍。",
                     50, case=(3,)),
    # 下面两个是**档号里在用的旧码**（档案的 people 字段），不是可问的人：
    # 档号 01-FY-XFE / 02-SY-TYS 是案① 一开始就写下的，改档号会连带动 links。
    # 在这里补上名字，只为让档目元信息印「贤妃苏氏」而不是一个生码。
    # trust=0 让它们不会出现在「人情」面板里（那一栏只列有信任度的人）。
    "XFE": Character("XFE", "贤妃苏氏", "已故 · 六妃之一", 0,
                     "死者在凤仪殿榻上，嘴角黑色血迹。", 999),
    "TYS": Character("TYS", "尚药局掌籍", "掌籍老太监 · 在本局四十年", 0,
                     "眼已花。说过一回「代签便无责可追」，被驳了，此后再没报过。",
                     999),
}

# --------------------------------------------------------------------------
# 线索与物证
# --------------------------------------------------------------------------

ITEMS_RAW: List[Tuple[str, str, str, bool, str]] = [
    # ---------------- 现场直接可得 ----------------
    ("si_needle", "银针验毒结果",
     "银针入指尖即黑；血色不凝、口鼻无沫，非即刻致命之毒。", True, "clue"),
    ("black_blood", "口角黑血",
     "黑血沿唇角流至耳下，说明中毒在两三个时辰之前。", True, "clue"),
    ("doors_bolted", "殿门由内反锁",
     "铁栓横死，窗插销完好——室内原本只有贤妃一人。", False, "clue"),
    ("window_scratch", "窗棂刮痕",
     "左窗棂上有一道新鲜撬痕，自外而内，刃口极薄。", True, "clue"),
    ("tea_almond", "残茶苦杏仁味",
     "茶已冷，凑近有淡淡苦杏仁味，非茶香。", True, "clue"),
    ("censer_red", "香炉红色粉末",
     "龙涎香灰尚温，灰中混着微红细末，指捻发涩。", True, "clue"),
    ("ground_print", "地面足迹",
     "青砖上一列湿脚印，自门至榻前，脚尖朝外——是退出去时踩的。", False, "clue"),
    ("pillow_letter", "枕下密信",
     "贤妃笔迹：「采薇之死，疑非杖毙。王德海经手，账目有亏。」未写完。", True, "clue"),
    # ---------------- 侧殿与尚药局 ----------------
    ("tea_set", "安神茶盏", "青瓷盏，盏底沉着一层薄白粉末，已干。", True, "item"),
    ("almond_oil", "苦杏仁油",
     "尚药局旧档：苦杏仁油入药可安神，过量则令人气绝；取用须记名。", True, "doc"),
    ("ledger_gap", "领用簿上的空档",
     "苦杏仁油三年内支取七次，记的名都是王德海，字迹却各不相同。", True, "doc"),
    ("cinnabar_note", "朱砂丸方",
     "朱砂入炉只令人昏沉目眩，不能致死，亦不为银针所验。", True, "clue"),
    ("old_record", "掖庭旧档 · 采薇案",
     "十二年前宫人采薇以「窃」杖毙，卷内证人供词与验伤单都是同一人手笔。", True, "doc"),
    # ---------------- 口供 ----------------
    ("timeline_testimony", "王德海供述的时间线",
     "戌时遣退宫人，亥时末送宵夜时「敲门不应」。", False, "testimony"),
    ("xse_testimony", "小顺子的证词",
     "亥时初他送茶入殿，门未上栓，听到贤妃问「你来做什么」。", True, "testimony"),
    ("xse_footprint", "小顺子的脚印",
     "他曾绕到殿后，在雪泥里留下半只草鞋印，比窗下的印小两寸。", False, "testimony"),
    ("dismissal_roll", "遣退宫人名录",
     "戌时初遣退九人，独留王德海在外殿值夜。", True, "doc"),
    ("silver_week", "银针变黑是七日积毒",
     "以茶汤浸针七日可令针黑；此毒非一回可致。", True, "clue"),
    ("empress_last_word", "皇后「来做什么」",
     "戌时三刻皇后私访，劝贤妃把东西交出来。", False, "testimony"),
    ("empress_motive", "皇后的把柄",
     "贤妃手中握有太子之死的物证，皇后忌她。", True, "testimony"),
    ("empress_ring", "先帝所赐玉扳指",
     "皇后手上戴着一枚不该在女子手上的先帝玉扳指——那是太子的遗物。", True, "clue"),
    ("consort_soup", "贵妃的汤",
     "贵妃送汤，贤妃未饮；汤碗当夜被收走，厨下已洗。", False, "testimony"),
    ("consort_leverage", "贵妃的把柄",
     "贵妃曾私换过贤妃的安胎药。她怕这件事被翻出来。", True, "testimony"),
    ("emperor_scold", "天颜难测",
     "皇帝只想把案子按下去。话说得太直，会先没命。", False, "testimony"),
    ("emperor_care", "皇帝的哀恸",
     "他问的不是「谁害了她」，是「她走时可疼」。", False, "testimony"),
    # ---------------- 结论性证据 ----------------
    ("contradiction", "供述矛盾",
     "王德海说亥时末破门才见尸体，却又说「娘娘面色如生，还饮着茶」。", True, "clue"),
    ("killer_knowledge", "只有凶手知晓之事",
     "他知道茶盏是碎的、知道裂纹的走向——那是在门内看过的。", True, "clue"),
    ("almond_habit", "贤妃的饮茶之习",
     "她惯饮武夷，茶味厚，能压住杏仁油气。", True, "clue"),
    ("caiwei_death", "采薇之死的隐情",
     "采薇为王德海手下宫人，因他伪造的罪名被杖毙。", True, "doc"),
    # ---------------- 对质录与结案（第三、四、五幕的卷面） ----------------
    # 这一批**刻意不是核心证据**：它们是「记录」，不是「推演」。
    # 核心证据必须由玩家在场景里的动作取得（见 dossiers.py 顶部的写作纪律）。
    ("wdh_slips", "王德海的三次改口",
     "三问三答，每一答都更往里一步；「面色如生，还饮着茶」是他自己说漏的。", False, "testimony"),
    ("hh_night_visit", "皇后夜访的时辰",
     "戌时三刻入殿，半刻即出；她说她是来「讨一样东西」的。", False, "doc"),
    ("gf_handstove", "手炉里的药渣",
     "贵妃托炉时露出的炉底灰里，有一层不是安胎药颜色的细白药渣。", False, "clue"),
    ("xse_fear_note", "小顺子抄过的那一页",
     "他抄过领用簿上的一页，随后那页纸被总管要走了。", False, "testimony"),
    ("hd_three_days", "三日的期限",
     "皇帝要的不是凶手，是一个能写进结案文书的名字。", False, "doc"),
    ("coroner_count", "仵作年记 · 四十七具",
     "沈墨白亲手填过的尸格：第七年已验四十七具，其中三具写着「杖毙」。", False, "doc"),
    ("smb_hand", "写在行刑单上的那一行",
     "「不足以致死，再杖」——笔锋起笔重、收笔轻，与沈墨白年记的字一样。", False, "doc"),
    ("yamen_draft", "结案陈词的底稿",
     "底稿不存档，写完即销；写下第一个名字，就没有回头路。", False, "doc"),
    ("eight_verdicts", "判决的八种写法",
     "同一个案子可以有八种收尾，都合法。只有一种是今夜该写的。", False, "doc"),
    # ---------------- 案② 尚药局连环暴毙 ----------------
    # 第六幕 · 药库现场
    ("gy_pupils", "瞳仁不散、口唇麻色",
     "死者口唇发麻色，瞳仁不收。这不是心疾，是药——而且是入口就麻的那种。", True, "clue"),
    ("gy_ink_finger", "指尖的墨",
     "高延年右手中指有墨痕，指腹还有纸灰。他死前在写字，可案上一张纸也没有。", False, "clue"),
    ("gy_cup", "半盏姜汤",
     "盏底有细砂，汤早凉透了，尸身也已僵冷——这盏汤不是死前喝的。", False, "clue"),
    ("aconite_smell", "匙上的白霜",
     "铜药匙上一层薄白霜，嗅之微辛，舌尖一沾就麻：附子。", True, "clue"),
    ("aconite_nature", "附子的药性",
     "附子入药须炮制。生用三钱即能致命：入口麻舌，一个时辰后心悸而亡，"
     "银针验不出，瞳仁也不散——与苦杏仁油正成一对。", True, "doc"),
    ("aconite_gap", "药柜第三层缺的三钱",
     "附子格里的余量比账面少三钱，缺口处的药粉印子是新的。", True, "clue"),
    ("gy_time", "尸冷与尸僵",
     "尸僵已过肩，尸温近砖。高延年死在子时之前——比值夜簿上他签的那一行早了一个更次。", True, "clue"),
    ("night_roster2", "值夜簿上的丑时初",
     "「丑时初，巡库。」字是他的。写下这一行的时候，他已经死了。", False, "doc"),
    ("bolt_thread", "门闩上的青丝线",
     "门闩栓槽里卡着一小截青丝线，线头是拉断的毛边：门是从外面拨上的。", True, "clue"),
    ("store_key", "铜药匙",
     "死者右手攥着药库的铜药匙，匙齿有新磨的痕——常被人拿去撬东西。", False, "item"),
    # 第六幕 · 账房与时间线
    ("seal_changed", "换封条的人",
     "药库封条是前一日换的，签名「高延年」，笔锋却不是他的。", True, "doc"),
    ("aconite_intake", "附子入库的日子",
     "附子入库的次日，正是苦杏仁油第七次被取用的那一天。", True, "doc"),
    ("two_cases_method", "同一种手法",
     "凤仪殿与药库是同一种做法：先下慢药，再从外面合上一道门。", True, "clue"),
    ("ledger_seventh", "第七次取用",
     "七次取用：前六次在景和五年到十二年之间，第七次在贤妃薨的前一日。", True, "doc"),
    # 第七幕 · 灯下人
    ("zzz_private", "掌局的私账",
     "一本私账，每笔只写四个字：「药出有主」。没有名字，只画押。", True, "doc"),
    ("lq_stain", "柳青指腹的药渍",
     "她指腹上的黄渍是附子粉染的，洗不掉。她说她没碰过附子。", True, "clue"),
    ("hxw_patrol", "贺小五的夜巡",
     "戌时末他巡到药库门口，门是从外面锁着的——那时屋里已经有人不喘气了。", True, "testimony"),
    ("jj_copy", "蒋九抄的那一页",
     "领用簿第七页的抄本，抄到一半断了笔，纸边有被人抽走的痕。", True, "doc"),
    ("jj_paper", "灯下的残纸",
     "蒋九手心里攥着一角纸，被水浸过，只剩半个字：「亻」。", False, "clue"),
    ("jj_corpse", "蒋九的尸格",
     "口唇麻色、瞳仁不散、无外伤，灯还亮着——与高延年同一味药。", True, "clue"),
    ("contradiction2", "两句供词对不上",
     "郑守拙说蒋九整夜在值房；柳青说戌时见他往药库去。", True, "testimony"),
    ("caiwei_hand", "十二年前的那支笔",
     "采薇案的口供与药局领用簿是同一个人写的：替人写字，写了十二年。", True, "doc"),
    ("jj_memory", "蒋九记得的事",
     "十二年前他还是药童，替人研过一味「安神的」药。研完，那人给了他一块糖。", True, "testimony"),
    ("fb_word", "内官监的口风",
     "冯保只说了一句：「内官监的意思是，写成暴病。」", True, "testimony"),
    ("zzz_pressure", "掌局的第一次改口",
     "先说高延年是心疾，改口说「也许是夜里受了寒」，第三次就不说话了。", False, "testimony"),
    # 第八幕 · 结案
    ("zzz_confession", "掌局的供述",
     "七次取用是他写的名，字是替人抄的。抄同一支笔，抄了十二年。", True, "testimony"),
    ("jinghe_seal", "景和五年的封泥",
     "药库旧档上一枚封泥，印的是经卷阁的印——药怎么会从经卷阁出？", True, "clue"),
    ("jinghe_leaf", "残账一页",
     "「景和五年，药出经卷阁，三取其二，余一入凤仪。」", True, "doc"),
    ("third_name", "被水浸过的名字",
     "残账背面只剩一横，看不清是谁。但那一横起笔很重。", False, "clue"),
    ("verdict2_draft", "第二份底稿",
     "第二份结案底稿。这一次，纸上有两个案子。", False, "doc"),
    # ---------------- 案③ · 第九幕 经卷阁勘验 ----------------
    ("xyp_livid", "樱红的尸斑",
     "尸斑不是紫的，是樱红的，按下去褪色又回红——炭气的记号。", True, "clue"),
    ("xyp_face", "口唇鲜红 · 十指不青",
     "唇色比活人还红，指甲不青不紫。她脸上没有半点痛色。", False, "clue"),
    ("needle_clean3", "银针不黑",
     "银针入喉、入心、入指尖，三次都不变色：这一回的凶手不是药。", True, "clue"),
    ("room_smell", "库里没有药味",
     "丙字库里只有陈纸、霉与炭气，没有一丝药的苦味。", False, "clue"),
    ("brazier_two", "两盆炭",
     "一盆烧成了白灰，另一盆是新添的，炭块还留着棱——有人在夜里添了火。", True, "clue"),
    ("ladder_wax", "书梯横档上的蜡痕",
     "书梯第三档上有一道黄蜡的印，人的鞋底踩不出这个形状。", False, "clue"),
    ("vent_wax", "气窗上的油纸与黄蜡",
     "气窗被人从里侧用油纸封住，纸角压着内官监封缄才用的黄蜡。", True, "clue"),
    ("seal_recast", "翻模的封泥",
     "封泥是旧的，泥胎却是新的：有人拿旧印翻了个模，重新盖了一枚。", True, "clue"),
    ("locked_outside3", "门是从外封的",
     "丙字库的门从外落锁、加封，钥匙在内官监——屋里的人自己出不来。", False, "clue"),
    ("key_ledger3", "领钥匙簿",
     "经卷阁的钥匙出入都要记。前日寅时那一行写着「内官监 · 领」，笔是冯保的手。", True, "doc"),
    ("cc_tone", "掌印的口风",
     "曹淳只说了一句：「炭气熏的。仵作这一句写在纸上，咱们都好过。」", False, "testimony"),
    ("burned_order", "炉灰里的半页令纸",
     "半页没烧尽的牒纸：「封存」两个字还在，纸角压着半个印。", False, "clue"),
    ("xyp_hand", "她手里攥着的半页",
     "她右手攥着半页纸，纸角有景和五年的年号，另一半被人抽走了。", True, "clue"),
    ("xyp_lastvisit", "她昨日查过景和五年",
     "调档单上，昨日午前她取过景和五年丙字第七函，登记的理由写着两个字：「对账」。", True, "doc"),
    ("xyp_note", "「十七行，不必问。」",
     "日课簿格子下面一行小字，是她的笔，写得很轻：「十七行，不必问。」", False, "doc"),
    ("shelf_gap", "架上少了一函",
     "丙字库第七架上空出一函的位置，灰印是新的——那一函昨夜还在这儿。", False, "clue"),
    ("char_footprint", "炭灰里的脚印",
     "炭灰里一枚脚印，五瓣花底，是女史的绣鞋。可她穿的是软底鞋。", False, "clue"),
    ("charcoal_source", "炭的来路",
     "那盆新炭是内官监的人送进阁的：阁里一冬的炭，都不走这条门。"
     "门前雪里的草鞋印，是搬炭的人留下的。", True, "doc"),
    # ---------------- 第十幕 对质 ----------------
    ("ca_words", "常安听到的那句话",
     "「姑姑夜里冷，把这两筐炭搬进去。」——常安说，那个人隔着窗吩咐，脸他没敢看。", True, "testimony"),
    ("ca_saw_fb", "上过阁顶的人",
     "常安说：昨夜有个人上了阁顶，下来时袖口沾着灰，他没敢抬头看脸。", True, "testimony"),
    ("lws_copy", "陆文昭抄的那一本",
     "她替师父抄过景和五年的抄没名录，抄了三遍。第三遍师父让她烧了。", True, "doc"),
    ("lws_tear", "抄本上少的那一行",
     "抄本中缺一行——正是名录第十七行，采薇那一行。", False, "clue"),
    ("cc_order", "掌印的令",
     "「封存，不开验。」——炉灰里半页烧剩的令纸上，压着半个掌印的印。", True, "doc"),
    ("cc_hand", "钥匙在冯保身上",
     "曹淳答得很慢：「钥匙？在冯保身上。」——封门要先开门，这是他的理。", True, "testimony"),
    ("fb_key3", "冯保领了钥匙",
     "前日寅时，领钥匙簿上是冯保的手笔。他说他前日不在宫里。", True, "doc"),
    ("fb_clean", "「上头要的是干净」",
     "「内官监办事，从来不问为什么。上头要的是干净。」", True, "testimony"),
    ("purge_names", "景和五年抄没名录",
     "景和五年冬，东宫旧人抄没名录：二十九人，死于狱、死于杖、死于「疾」。", True, "doc"),
    ("caiwei_row", "第十七行",
     "名录第十七行：采薇，女，年十五，掖庭，「疾」。那一行的墨比别行厚——描过一次。", False, "doc"),
    ("jinghe_orig", "景和五年原页",
     "「景和五年，药出经卷阁，三取其二，余一入凤仪」——下面是三字朱批。", True, "doc"),
    ("emperor_ink", "御笔三字",
     "原页末尾三个朱字，是今上的笔：「知道了。」", True, "clue"),
    ("third_name3", "那味药的名字",
     "原页上第一味药的名字被墨涂了，涂得很厚：写它的人不愿留名。", True, "doc"),
    ("three_line3", "三案一条线",
     "凤仪殿、尚药局、经卷阁：一剂慢药，一支笔，一枚印，三桩案。", True, "clue"),
    ("wax_match", "两处黄蜡是一块",
     "封泥上的蜡与气窗上的蜡，切口、色、气味都对得上：同一块蜡，同一个人。", True, "clue"),
    ("verdict3_draft", "第三份底稿",
     "第三份结案底稿。这一份写下去，纸上有三个案子、一个不能写的名字。", False, "doc"),
    ("road_out3", "出宫的路",
     "从经卷阁往南是宫门。你走过两回，两回都在天亮前。", False, "clue"),
]

ITEMS: Dict[str, Item] = {
    iid: Item(iid, name, desc, core, tag) for iid, name, desc, core, tag in ITEMS_RAW
}

# --------------------------------------------------------------------------
# 场景
# --------------------------------------------------------------------------

PROLOGUE = (
    "景和十七年，冬。\n"
    "子时三刻，凤仪殿。贤妃苏氏薨于榻上，口角黑血未干。\n"
    "宫门落锁，皇帝只留下一个人查这件事——大理寺仵作，沈墨白。\n"
    "「三日之内，给朕一个名字。」\n"
    "你抬头看见殿外的灯。三日之后，灯还亮着的，未必是你。"
)

TITLE_BODY = (
    "你是沈墨白，验尸出身，惯于从死人身上找活人的破绽。\n"
    "今夜，你只有三样东西：一副银针、一本记事簿，和三个时辰。"
)

CRIME_SCENE = Scene(
    id="crime_scene",
    act=1, case=1,
    title="第一幕 · 贤妃薨",
    place="凤仪殿",
    time="子时三刻",
    body=(
        "凤仪殿里还留着安神香的气味，甜得发闷。贤妃苏氏仰卧榻上，衣饰齐整，"
        "口角一道黑血已干成线条，沿下颌淌到耳下。\n"
        "殿门从里面锁死了，铁栓横在栓槽里。窗插销好好的。\n"
        "王德海跪在门槛外，额头抵着地面，肩膀一抽一抽；小顺子缩在他身后，"
        "袖口的炭灰还没拍干净。\n"
        "你蹲下来，先看死者，再看活人。\n"
        "（现场只能看个大概。要坐实这桩案子，得去调档——"
        "屏幕下沿的 › 后面可以敲档号或指令，敲「档目」看手里有些什么。）"
    ),
    choices=[
        acting("crime_scene", "俯身验尸 · 取银针探指尖",
               "最直接的死因",
               "你俯身检查贤妃遗体。面色青紫，嘴角残留黑色血迹，颈部无勒痕，胸口无外伤。"
               "你取出验尸银针，刺入遗体指尖——银针变黑。\n"
               "但你注意到：血色不凝、口鼻无沫、指甲未青。这不是鸩酒、砒霜那类即刻夺命之物，"
               "而是「慢慢地」、在两三个时辰里把人耗死的东西。",
               clues=("si_needle", "black_blood"), score=2, wants="SMB"),
        acting("crime_scene", "询问王德海 · 要一个准确的时间线",
               "现场供述",
               "你转向王德海，询问案发经过。王德海颤声说道：「今夜戌时，娘娘遣退了所有宫人，"
               "说要独自歇息。亥时末，老奴来送宵夜，敲门不应，方才……方才发现……」\n"
               "说到「亥时末」三个字时，他抬眼看了看你，又飞快地垂下去。",
               clues=("timeline_testimony",), trust=(("WDH", -5),), score=1, wants="WDH"),
        acting("crime_scene", "细查门窗 · 铁栓与插销",
               "现场封锁状况",
               "殿门从内侧以铁栓锁死，窗户亦从内侧插销闭合。\n"
               "但你蹲下细看：铁栓下方有一道新鲜的摩擦印，栓头不是自然落槽，"
               "倒像是从外面用薄刃拨进去的，再退出来时带出了木屑。\n"
               "左窗窗棂上另有一处细微刮痕，刃口极薄。窗下青砖上印着半只湿脚印，"
               "脚尖朝外——那人不是进来的，是退出去的。",
               clues=("doors_bolted", "window_scratch", "ground_print"), score=2),
        acting("crime_scene", "查看茶与香炉 · 嗅一嗅，捻一捻",
               "两处气味",
               "你走到案前，端起残茶凑近鼻端——一股苦杏仁味若有若无，被武夷茶的厚重压着。\n"
               "你又查看香炉，炉中龙涎香灰尚温，其中似混有不明粉末，色泽微红，指捻发涩。",
               clues=("tea_almond", "censer_red"), score=2),
        acting("crime_scene", "翻检塌上枕下",
               "死者最后在看什么",
               "枕下压着一张未写完的笺纸，是贤妃的笔迹，墨迹收尾处顿了一下：\n"
               "「采薇之死，疑非杖毙。王德海经手，账目有亏。」\n"
               "写到这里就断了。你把笺纸折起来，收进袖中。",
               clues=("pillow_letter",), score=3),
        # 这一幕真正的门槛：勘验格目齐全。
        # 「现场看完」只是看个大概；把现场看出来的号子顺下去、翻到第一幕的
        # 勘验总录（FIRST_ACT_SUMMARY），才算真的验透。那份总录自己还挂着
        # requires：尸格、门户格、炉格、枕下笺纸、值夜单、小顺子问供都得先读过。
        Choice(label="移步侧殿 · 布置问询与查证", to="interrogate_hall", tag="",
               detail="传唤宫人、调档、追查取用记录",
               locked_if=missing_dossier(FIRST_ACT_SUMMARY),
               locked_hint="勘验未毕：现场只看了个大概。请调阅档目，"
                           "顺着现场看出来的号子把第一幕的格目读全。"),
    ],
)

HALL = Scene(
    id="interrogate_hall",
    act=3, case=1,
    title="第三幕 · 侧殿问询",
    place="凤仪殿 · 侧殿",
    time="丑时",
    body=(
        "侧殿比正殿冷。你在案上摊开记事簿，把今夜要问的人一个个传进来。\n"
        "窗纸透出更鼓的影，你写下第一行字：「戌时遣人、亥时送茶、亥时末破门」。\n"
        "三个人有这个空档：掌殿起居的王德海、私访过凤仪殿的皇后、送过汤的贵妃。"
        "皇帝则在殿外站着，站了很久。\n"
        "（问对人、出示对证物，才能撬开他们的嘴。）"
    ),
    choices=[
        Choice(label="传唤 · 太监总管王德海", to="talk_wdh", wants="WDH", detail="最清楚凤仪殿今夜一切的人"),
        Choice(label="传唤 · 御膳房小监小顺子", to="talk_xse", wants="XSE", detail="今夜的茶是谁送进去的"),
        Choice(label="求见 · 中宫皇后萧氏", to="talk_hh", wants="HH", detail="戌时三刻她为什么在凤仪殿"),
        Choice(label="求见 · 贵妃柳氏", to="talk_gf", wants="GF", detail="她端来的那碗汤"),
        Choice(label="求见 · 皇帝萧衍", to="talk_hd", wants="HD", detail="他到底想要一个什么结果"),
        Choice(label="前往 · 尚药局账房", to="pharmacy", detail="查苦杏仁油与朱砂的领用记录"),
        Choice(label="前往 · 掖庭旧档库", to="archive", detail="翻十二年前那桩杖毙案", tag="",
               locked_by=all_of(clue_absent("pillow_letter"),
                                clue_absent("old_record")),
               locked_hint="你还不知道该翻哪一卷（需先发现「采薇」这条线）"),
        Choice(label="回到正殿 · 再验一遍现场", to="crime_scene", detail="有些东西要看过第二遍才认得"),
        Choice(label="整理证物 · 提笔结案", to="accuse_hall", tag="accuse",
               detail="写下那个名字。名字一出口，就再没有回头路"),
    ],
)

# --------------------------------------------------------------------------
# 审讯场景
# --------------------------------------------------------------------------

TALK_WDH = Scene(
    id="talk_wdh",
    act=3, case=1,
    title="问询 · 王德海",
    place="凤仪殿 · 侧殿",
    time="丑时",
    interlocutor="WDH",
    body=(
        "王德海进来的时候是侧着身子的，像怕碰倒什么。他跪下，双手叠在膝上。\n"
        "「大人问吧。老奴今晚哪儿也没去，就在外殿守着，一步没离。」"
    ),
)

TALK_XSE = Scene(
    id="talk_xse",
    act=3, case=1,
    title="问询 · 小顺子",
    place="凤仪殿 · 侧殿",
    time="丑时",
    interlocutor="XSE",
    body=(
        "小顺子一进门就跪下了，膝盖磕在砖上，声音很响。他飞快地瞟了一眼门外，"
        "压着嗓子说：「大人，小的……小的什么都不知道。」\n"
        "他袖口的炭灰，是御膳房炉膛里的灰。"
    ),
)

TALK_HH = Scene(
    id="talk_hh",
    act=3, case=1,
    title="问询 · 皇后萧氏",
    place="凤仪殿 · 西暖阁",
    time="丑时",
    interlocutor="HH",
    body=(
        "皇后没有坐。她站在灯影里，让你站在光里。\n"
        "「沈墨白。」她开口叫了你的名字，「大理寺的仵作，验过多少具尸首？」\n"
        "「四十七具。」\n"
        "「那你看得出什么样的人是被冤死的么。」她说这话时，左手拇指一直在转一枚玉扳指。"
    ),
)

TALK_GF = Scene(
    id="talk_gf",
    act=3, case=1,
    title="问询 · 贵妃柳氏",
    place="凤仪殿 · 东暖阁",
    time="丑时",
    interlocutor="GF",
    body=(
        "贵妃来得最快，进门先看了一圈案子上的东西，才把目光落到你身上。\n"
        "「你是仵作？那你别问本宫，去问死人。」她把手炉往上一托，"
        "「本宫今夜端了碗汤来，她没喝。她要是有胆子喝，本宫倒要看她能撑到几时。」"
    ),
)

TALK_HD = Scene(
    id="talk_hd",
    act=3, case=1,
    title="问询 · 皇帝萧衍",
    place="凤仪殿 · 廊下",
    time="丑时",
    interlocutor="HD",
    body=(
        "皇帝站在廊下，没有进殿。他背对着你，肩线绷得很直。\n"
        "「三日。」他说，「朕给了你三日。三日之后，无论你查出什么，"
        "这件事都要有个名字。」\n"
        "他停了一下，声音低下去：「她走的时候，可疼？」"
    ),
)

PHARMACY = Scene(
    id="pharmacy",
    act=2, case=1,
    title="查证 · 尚药局账房",
    place="尚药局",
    time="丑时二刻",
    body=(
        "尚药局的账房比别处都冷。掌籍老太监把三本簿子推到你面前，"
        "指节敲着最上面那本：「安神的、解毒的、丸散的，都在这儿。大人自己翻。」\n"
        "烛火晃，纸页发黄。"
    ),
)

ARCHIVE = Scene(
    id="archive",
    act=2, case=1,
    title="查证 · 掖庭旧档库",
    place="掖庭 · 旧档库",
    time="丑时二刻",
    body=(
        "旧档库在掖庭最里头，锁是坏的，灰有一指厚。\n"
        "十二年前的卷宗按年号捆着，最下一捆的绳结上还留着封泥。"
        "你抽出景和五年那一卷，指腹摸到一处被反复翻看的折痕。"
    ),
)

# --------------------------------------------------------------------------
# 结案：指认与判决
# --------------------------------------------------------------------------


def _accuse_choice(target: str, label: str, detail: str) -> Choice:
    return Choice(label=label, to="", detail=detail, tag="accuse", suspect=target,
                  effect=E(scene=f"verdict_{target}"))


ACCUSE_HALL = Scene(
    id="accuse_hall",
    title="第五幕 · 结案陈词",
    place="凤仪殿 · 正殿",
    time="寅时",
    act=5,
    case=1,
    body=(
        "你把记事簿摊在正殿的案上，一页页排开：银针、黑血、茶、香灰、"
        "脚印、窗棂上的刮痕、簿子里空着的名字。\n"
        "皇帝坐在上头。皇后在左，贵妃在右，王德海跪在中间，小顺子跪在他后面。\n"
        "「说吧。」皇帝说，「说出那个名字。」\n"
        "你开口之前，先在心里把所有的线头收成一句：这个人有什么手段、"
        "有什么动机、又是怎么进的殿。\n"
        "（核心证据越齐，你的话越难被驳倒。）"
    ),
    choices=[
        _accuse_choice("WDH", "「凶手是 —— 太监总管 王德海」", "以茶下毒，再以朱砂布下障眼法"),
        _accuse_choice("HH", "「凶手是 —— 中宫皇后 萧氏」", "戌时私访，为太子之死灭口"),
        _accuse_choice("GF", "「凶手是 —— 贵妃 柳氏」", "争宠下毒，送汤为饵"),
        _accuse_choice("HD", "「凶手是 —— 陛下」", "……这句话说出口，就没有回头路了"),
        # 「名字还没写下去」时的回头路。少了它，玩家一旦踏进结案厅而证据没备齐，
        # 案① 的九个枢纽（侧殿、正殿、药局、旧档库、五场问询）就再也回不去了
        # ——而「铁证如山」的三条判据（动机、玉扳指、亲口认罪）全都产在那里。
        Choice(label="「臣请再查。」· 回侧殿", to="interrogate_hall",
               detail="名字还没有写下去，卷宗还能翻"),
        Choice(label="「此案 —— 暂无确证，臣请再查」", to="",
               detail="承认查不出来，把案子从自己手里推出去",
               effect=E(flags=("gave_up",), scene="ending_bystander")),
        # 「辞官」结局的唯一入口：证据已经足够，但你选择不把名字说出来。
        # 需要一个门槛，否则开局直奔正殿就能辞官，结局会显得廉价。
        Choice(label="「臣 —— 验得出来，但臣不说。」", to="",
               detail="把簿子烧掉，解下腰牌（结局 · 辞官）",
               visible_if=at_least_clues(8),
               effect=E(flags=("resign",), scene="ending_quiet")),
        # 案① → 案② 的入口：尚药局当夜又死了一个人。
        # 门槛压得很低（勘验总录 + 八条核心证据），因为案② 不是惩罚线，是主线。
        Choice(label="「臣还有一事 —— 尚药局的药库，今夜也死了人。」", to="case2_open",
               tag="accuse",
               detail="先把第一案按下，去看第二具尸首（第六幕 · 药局寒夜）",
               locked_if=any_of(missing_dossier(FIRST_ACT_SUMMARY),
                                negate(core_count_at_least(8))),
               locked_hint="还需：先把凤仪殿这一案查到收手（读完「第一幕勘验总录」），"
                           "手里的核心证据也要够厚（核心证据 ≥ 8）",
               repeatable=False,   # 收益只有档案收录与 flag，都是幂等的
               effect=E(flags=("case2_entered",),
                        dossiers=("06-DL-SMB", "06-YK-GYN"),
                        scene="case2_open")),
    ],
)

VERDICT_SCENES: Dict[str, Scene] = {
    "verdict_WDH": Scene(
        id="verdict_WDH", act=5, case=1, title="判决 · 指认王德海", place="凤仪殿 · 正殿", time="寅时",
        kind="scene",
        body=(
            "你报出那三个字。殿里静了一息，然后王德海开始磕头，磕得很慢，一下一下。\n"
            "「老奴伺候娘娘十一年。」他说，「十一年。」\n"
            "皇帝没有看他，只看着你：「你说是他。把证据摆出来。」\n"
            "你把记事簿推到案前，退后一步。三日之后，结案文书从内廷发了下来。"
        ),
    ),
    "verdict_HH": Scene(
        id="verdict_HH", act=5, case=1, title="判决 · 指认皇后", place="凤仪殿 · 正殿", time="寅时",
        kind="scene",
        body=(
            "你报出「皇后萧氏」。西暖阁方向传来一声极轻的玉扳指碰在案沿上的声音。\n"
            "皇后没有回头，只问了一句：「仵作，你入宫几年了？」\n"
            "「三年。」你说。\n"
            "「三年。」她把这两个字在嘴里过了一遍，「那你不认得我。」\n"
            "皇帝把茶盏搁下，声音很平：「呈证。」"
        ),
    ),
    "verdict_GF": Scene(
        id="verdict_GF", act=5, case=1, title="判决 · 指认贵妃", place="凤仪殿 · 正殿", time="寅时",
        kind="scene",
        body=(
            "你报出「贵妃柳氏」。她先是笑了，然后把手炉摔在了地上。\n"
            "「一个验尸的，」她拍着手，「一个验尸的也敢指我。」\n"
            "炭火在金砖上滚开，殿里有人小步上前踩灭。皇帝从头到尾没有看那炉炭一眼，"
            "只看你：「理由。我要理由。」"
        ),
    ),
    "verdict_HD": Scene(
        id="verdict_HD", act=5, case=1, title="判决 · 指认陛下", place="凤仪殿 · 正殿", time="寅时",
        kind="scene",
        body=(
            "你说完那句话，殿上没有人动。连风都停了。\n"
            "皇帝看了你很久，久到你听见自己袖口里银针轻响。\n"
            "「沈墨白，」他终于开口，「你知道你现在站着的地方，是谁家的殿？」"
        ),
    ),
}

# --------------------------------------------------------------------------
# 案② · 尚药局连环暴毙（第六 ~ 八幕）
# --------------------------------------------------------------------------
# 入口在 accuse_hall：「臣还有一事 —— 尚药局的药库，今夜也死了人。」
# 案① 的八条结局不会被抢走：从案② 走回 accuse_hall 时 scene.case 会改回 1。

#: 第六幕「勘验总录」——案② 的档目门槛档（与案① 的 01-FY-END 同构）
CASE2_ACT6_SUMMARY = "06-YK-END"
#: 第七幕「问询总录」——开结案陈词的门槛档
CASE2_ACT7_SUMMARY = "07-DL-END"

CASE2_OPEN = Scene(
    id="case2_open",
    title="第六幕 · 药局寒夜",
    place="尚药局 · 药库前",
    time="丑时三刻",
    act=6,
    case=2,
    body=(
        "你从凤仪殿出来的时候，雪已经积到脚面。\n"
        "尚药局的灯亮着，门口站着两个人：一个捧灯的小监，一个穿内官监服色的少监。\n"
        "「沈仵作。」那人开口，声音平得像在念公文，「咱家冯保，奉旨问这一桩——"
        "药库里的高典药，半个时辰前没了。」\n"
        "他身后的门关着。门上只有一副闩，闩是从里头栓上的。\n"
        "「门没开过。」他说，「里头就他一个。」\n"
        "（案① 还摊在正殿的案上。你可以先看这一具尸首，也可以回去先把那个名字写上。）"
    ),
    choices=[
        Choice(label="推门进去 · 尸首还在药柜底下", to="drug_store",
               detail="先看死人，再看别的"),
        Choice(label="先去值房 · 今夜是谁值的夜", to="night_room",
               detail="值夜簿上写着谁的名字"),
        Choice(label="先去账房 · 附子是谁的方子", to="drug_office",
               detail="药出入库，账上都有日子"),
        Choice(label="回凤仪殿正殿 · 先把第一案的名字写上", to="accuse_hall",
               detail="把这一具先放下（回到案① 的结案陈词）"),
    ],
)

DRUG_STORE = Scene(
    id="drug_store",
    title="第六幕 · 药库",
    place="尚药局 · 药库",
    time="寅时",
    act=6,
    case=2,
    body=(
        "药库比外头还冷。药柜从地到梁，每一格都贴着签：人参、黄芪、半夏、附子。\n"
        "高延年靠在第三层柜脚下，右手攥着一把钥匙，左手摊着，像要去抓什么。\n"
        "案上一盏灯，柜上一盏灯，两盏都灭了。门闩在门内侧，栓槽里卡着一点东西。"
    ),
    choices=[
        acting("drug_store", "俯身验尸 · 看瞳仁与口唇", detail="最直接的死法",
               clues=("gy_pupils", "gy_ink_finger"),
               text="口唇是麻色，瞳仁不收。这不是心疾——心疾的人不会是这个样子。\n"
                    "他的右手中指有墨痕，指腹上还有纸灰。他死之前坐在案前写字，"
                    "可案上现在一张纸也没有。",
               score=3),
        acting("drug_store", "取铜药匙 · 就着灯嗅一嗅", detail="匙齿上有东西",
               clues=("aconite_smell", "store_key"),
               text="铜药匙上一层薄白霜，粉末细得像霜。你凑近嗅了一下，微辛；"
                    "用舌尖沾了一星——立刻麻到舌根。\n"
                    "附子。而且是没炮制过的生附子。",
               score=3),
        acting("drug_store", "拉开药柜第三层 · 附子格", detail="对一对账面余量",
               clues=("aconite_gap",),
               # 注意方向：``locked_if`` 是「满足就灰置」，不是「满足才亮」。
               # 这里要的是「先认出匙上那层白霜，才允许数格子」，所以用 visible_if。
               visible_if=all_of(has_clue("aconite_smell"), clue_absent("aconite_gap")),
               text="附子格里只剩小半格。你把药粉拨平，对着账页上昨日的余量看——"
                    "少了三钱，缺口处的粉印还是新的。\n"
                    "三钱。刚好是能让人死、又不至于立刻倒下的分量。",
               score=3),
        acting("drug_store", "验尸僵与尸温 · 推定死亡时辰", detail="他到底死在什么时候",
               clues=("gy_time", "night_roster2"),
               text="尸僵已经过了肩，尸温摸上去和地砖差不多。他死在子时之前。\n"
                    "你翻案上的值夜簿：末一行「丑时初，巡库」，签的是他自己的名。\n"
                    "写下这一行的时候，他已经死了。有人替他签了字，还比他本人写得像。",
               score=4),
        acting("drug_store", "查看门闩 · 栓槽里卡着什么", detail="门是怎么合上的",
               clues=("bolt_thread",),
               text="闩是好的，栓槽里卡着一小截青丝线，线头有拉断的毛边。\n"
                    "线从外头穿进来，套住闩尾一拉——门就在屋里没人的情况下，"
                    "从外面栓上了。\n"
                    "和凤仪殿那扇窗棂上的撬痕，是同一种手法。",
               score=4),
        Choice(label="前往 · 药局值房", to="night_room", detail="值夜的人在哪儿"),
        Choice(label="前往 · 尚药局账房", to="drug_office", detail="附子入库的日子"),
        Choice(label="移步 · 药局前厅", to="case2_hall",
               detail="把证物摊开，开始问人",
               locked_if=missing_dossier(CASE2_ACT6_SUMMARY),
               locked_hint="勘验未毕：请调阅档目，把第六幕的几份格目读全"
                           "（尸格、药匙、门闩、尸僵、领用簿）"),
        Choice(label="回凤仪殿正殿 · 先把第一案的名字写上", to="accuse_hall",
               detail="回到案① 的结案陈词"),
    ],
)

NIGHT_ROOM = Scene(
    id="night_room",
    title="第六幕 · 值房",
    place="尚药局 · 值房",
    time="寅时",
    act=6,
    case=2,
    body=(
        "值房一盆炭火，烧得只剩红心。板床上的被子叠得很齐——值夜的人今夜没睡。\n"
        "案上一本值夜簿，旁边半盏姜汤，汤面结了一层皮。"
    ),
    choices=[
        acting("night_room", "查看那半盏姜汤", detail="谁在什么时候喝的",
               clues=("gy_cup",),
               text="盏底有细砂，汤早凉透了。尸身也早僵了。\n"
                    "这盏汤不是他死前喝的那一盏——有人端了一盏新的来，"
                    "放在这儿，做出「他喝过汤、然后睡下」的样子。",
               score=2),
        acting("night_room", "查值夜簿上的签押", detail="字是活的，人是死的",
               clues=("night_roster2",),
               text="值夜簿上今夜两个人签押：贺小五，丑时初；高延年，丑时初。\n"
                    "高延年那一行的笔锋比他平时的字更「像」他——像是照着描的。",
               score=3),
        acting("night_room", "翻炭盆 · 一片没烧尽的纸角", detail="谁在烧纸",
               # 炭盆里那角纸只是「有人在烧东西」的旁证：给一面旗子，不给线索。
               # （正主是灯下那份抄到一半的抄本，见 lamp_room「收起他抄的那一页」。）
               flags=("jj_burned",),
               visible_if=negate(has_flag("jj_burned")),
               text="炭盆里翻出一角没烧透的纸。上面是半行账："
                    "「第七次取用，附子三钱，签——」，后面的名字烧掉了。\n"
                    "抄这页的人手很稳，抄到一半断了笔。",
               score=3),
        Choice(label="回到药库", to="drug_store", detail="再看一遍现场"),
        Choice(label="前往 · 尚药局账房", to="drug_office", detail="对账"),
        Choice(label="移步 · 药局前厅", to="case2_hall", detail="开始问人",
               locked_if=missing_dossier(CASE2_ACT6_SUMMARY),
               locked_hint="勘验未毕：请先读完第六幕的格目（尸格、药匙、门闩、尸僵、领用簿）"),
        Choice(label="回凤仪殿正殿 · 先把第一案的名字写上", to="accuse_hall",
               detail="回到案① 的结案陈词"),
    ],
)

DRUG_OFFICE = Scene(
    id="drug_office",
    title="第六幕 · 账房",
    place="尚药局 · 账房",
    time="寅时",
    act=6,
    case=2,
    body=(
        "账房三面都是柜，柜里全是簿。案上摊着今年的领用簿，墨还湿着——"
        "今夜有人在加班抄它。\n"
        "角落里堆着成捆的旧档，纸边发黄，捆绳上还压着封泥。"
    ),
    choices=[
        acting("drug_office", "翻《本草》 · 附子一味", detail="这味药到底怎么杀人",
               clues=("aconite_nature",),
               text="附子入药须炮制。生用三钱，入口麻舌，一个时辰后心悸而亡；"
                    "瞳仁不散、口唇麻色，银针验不出。\n"
                    "你在这页边上看到一行铅笔小字：「与杏仁油同法，不易验。」"
                    "——这是有人写给自己看的。",
               score=3),
        acting("drug_office", "核对附子入库的日子", detail="账上的日子会说话",
               clues=("aconite_intake",),
               text="附子入库的日子，是贤妃薨的前一日。\n"
                    "那一页的领用人写的是「尚药局公用」，签押却是空白。",
               score=4),
        acting("drug_office", "查苦杏仁油的七次取用", detail="第七次是谁来取的",
               clues=("ledger_seventh",),
               locked_by=missing_dossier(FIRST_ACT_SUMMARY),
               locked_hint="案① 的领用记录你还没读透（先读「第一幕勘验总录」）",
               text="苦杏仁油一共支取七次。前六次在景和五年到十二年之间，"
                    "间隔得很有规律——像是每年都要用一回。\n"
                    "第七次在贤妃薨的前一日，取用人写的是「王德海」，"
                    "字却不是王德海的。",
               score=4),
        acting("drug_office", "把两案的手法摆在一处", detail="门、药、时间",
               clues=("two_cases_method",),
               # 同上：这是「亮出来的条件」，不是「灰置的条件」。
               visible_if=all_of(has_clue("bolt_thread"), has_clue("ledger_seventh"),
                                 clue_absent("two_cases_method")),
               text="你把两张纸并排摊开。\n"
                    "凤仪殿：慢药入茶，再从外头拨上窗棂。\n"
                    "药库：生附子入汤，再从外头拉上门闩。\n"
                    "同一个人，同一种做法，连遮掩的门路都一样："
                    "让屋里看着像没人进过。",
               score=5),
        Choice(label="回到药库", to="drug_store", detail="再看一遍现场"),
        Choice(label="前往 · 药局值房", to="night_room", detail="值夜簿"),
        Choice(label="移步 · 药局前厅", to="case2_hall", detail="开始问人",
               locked_if=missing_dossier(CASE2_ACT6_SUMMARY),
               locked_hint="勘验未毕：请先读完第六幕的格目（尸格、药匙、门闩、尸僵、领用簿）"),
        Choice(label="回凤仪殿正殿 · 先把第一案的名字写上", to="accuse_hall",
               detail="回到案① 的结案陈词"),
    ],
)

CASE2_HALL = Scene(
    id="case2_hall",
    title="第七幕 · 灯下人",
    place="尚药局 · 前厅",
    time="寅时三刻",
    act=7,
    case=2,
    body=(
        "前厅的桌上排开你今夜拿到的东西：一把铜药匙、一截青丝线、半盏姜汤、几张账页。\n"
        "冯保站在门口，不进也不走，像一尊公文。\n"
        "天快亮了。尚药局今夜死了两个人——第二个是书吏蒋九，他死在灯下，"
        "灯芯烧得只剩一指。\n"
        "（问对人，出示对的东西，才能撬开他们的嘴。）"
    ),
    choices=[
        Choice(label="传唤 · 尚药局掌局郑守拙", to="talk_zzz", wants="ZZZ",
               detail="药出入库都要过他的手"),
        Choice(label="传唤 · 司药柳青", to="talk_lq", wants="LQ",
               detail="识药、手稳、黑里也摸得清附子"),
        Choice(label="传唤 · 值夜小监贺小五", to="talk_hxw", wants="HXW",
               detail="他记得每一夜谁走过廊子"),
        Choice(label="求见 · 内官监少监冯保", to="talk_fb", wants="FB",
               detail="他奉旨而来，为的是把话写成什么样"),
        Choice(label="前往 · 药库", to="drug_store", detail="再看一遍现场"),
        Choice(label="前往 · 值房", to="night_room", detail="值夜簿与姜汤"),
        Choice(label="前往 · 账房", to="drug_office", detail="附子与七次取用"),
        Choice(label="去书吏的灯下 · 第二具尸首", to="lamp_room",
               detail="蒋九还坐在案前，笔架上的笔没搁好"),
        Choice(label="整理证物 · 提笔结案", to="case2_accuse", tag="accuse",
               detail="把这一夜的收成写成第二份底稿",
               locked_if=missing_dossier(CASE2_ACT7_SUMMARY),
               locked_hint="问得还不够：蒋九的尸格、两句对不上的供词、"
                           "柳青的手、掌局的私账、十二年前那支笔，都还没有摆到案上"),
        Choice(label="回凤仪殿正殿 · 先把第一案的名字写上", to="accuse_hall",
               detail="回到案① 的结案陈词"),
    ],
)

LAMP_ROOM = Scene(
    id="lamp_room",
    title="第七幕 · 灯下人",
    place="尚药局 · 书吏值房",
    time="寅时三刻",
    act=7,
    case=2,
    body=(
        "书吏值房在药库西头。灯还亮着，灯芯只剩一指长。\n"
        "蒋九坐在案前，右手攥着东西，左手还搭在笔架上。脸上没有痛色，"
        "像是抄累了睡过去。\n"
        "案上摊着领用簿的抄本，抄到第七页，笔断了。"
    ),
    choices=[
        acting("lamp_room", "验蒋九的尸首", detail="第二具，同一味药",
               clues=("jj_corpse", "jj_paper"),
               text="口唇麻色，瞳仁不散，身上没有一处外伤。灯还亮着，人是凉的。\n"
                    "你掰开他右手，掌心里攥着一角纸，被水浸过，"
                    "只剩半个字：「亻」。\n"
                    "和高延年一样，是附子。下在他案上那碗夜里送来的汤里。",
               score=4),
        acting("lamp_room", "收起他抄的那一页", detail="他抄到一半的是什么",
               clues=("jj_copy",),
               text="领用簿第七页的抄本。抄的是七次取用，抄到第七次的名字时断了笔。\n"
                    "纸边有被人抽走的痕迹——有人想拿走完整的这一页，"
                    "只抽走了上半张。",
               score=4),
        Choice(label="回前厅", to="case2_hall", detail="接着问人"),
        Choice(label="前往 · 药库", to="drug_store", detail="第一具尸首"),
        Choice(label="回凤仪殿正殿 · 先把第一案的名字写上", to="accuse_hall",
               detail="回到案① 的结案陈词"),
    ],
)

TALK_ZZZ = Scene(
    id="talk_zzz",
    title="问询 · 郑守拙",
    place="尚药局 · 前厅",
    time="寅时三刻",
    act=7,
    case=2,
    interlocutor="ZZZ",
    hall="case2_hall",
    body=(
        "郑守拙进来的时候先理了理袖子，站定，又理了一次。\n"
        "「咱家是掌局。」他说，「药出入库，都要过咱家的手。"
        "可今夜的事，咱家真不知道。」\n"
        "他说「真不知道」的时候，看的是自己的鞋尖。"
    ),
)

TALK_LQ = Scene(
    id="talk_lq",
    title="问询 · 柳青",
    place="尚药局 · 前厅",
    time="寅时三刻",
    act=7,
    case=2,
    interlocutor="LQ",
    hall="case2_hall",
    body=(
        "柳青十九岁，站在案前，两只手垂着，指腹上有洗不掉的黄渍。\n"
        "「高典药出事，我知道。」她说，「药库的钥匙只有他和掌局有。」\n"
        "她说完就闭嘴了，像在等下一句该说什么。"
    ),
)

TALK_HXW = Scene(
    id="talk_hxw",
    title="问询 · 贺小五",
    place="尚药局 · 前厅",
    time="寅时三刻",
    act=7,
    case=2,
    interlocutor="HXW",
    hall="case2_hall",
    body=(
        "贺小五十六岁，进来时手里还攥着灯罩，像忘了放下。\n"
        "「我值夜。」他先说了这三个字，声音发抖，"
        "「灯我不熄的，我从来不熄灯。」\n"
        "他的鞋上全是雪，雪已经化了。"
    ),
)

TALK_FB = Scene(
    id="talk_fb",
    title="问询 · 冯保",
    place="尚药局 · 前厅",
    time="寅时三刻",
    act=7,
    case=2,
    interlocutor="FB",
    hall="case2_hall",
    body=(
        "冯保站在门口，没有坐。\n"
        "「沈仵作查案，咱家不拦。」他说，「内官监只等一句话："
        "这桩是暴病，还是别的。」\n"
        "他的官靴在门槛上蹭了一下，没进来。"
    ),
)

CASE2_ACCUSE = Scene(
    id="case2_accuse",
    title="第八幕 · 连环断",
    place="尚药局 · 前厅",
    time="卯时",
    act=8,
    case=2,
    body=(
        "第二份底稿摊在案上。这一份比上一份薄——你只有一夜。\n"
        "窗外开始发白，雪停了。冯保站在门外，等你报出一个名字，"
        "或者不报。\n"
        "「写在纸上的名字，」他说，「是要送去内官监的。」\n"
        "（指认谁，就写谁。也可以把两案并成一案来写。）"
    ),
    choices=[
        Choice(label="「凶手是 —— 尚药局掌局 郑守拙」", to="", tag="accuse",
               detail="替人写了十二年字的那个",
               suspect="ZZZ", effect=E(scene="verdict2_ZZZ")),
        Choice(label="「凶手是 —— 司药 柳青」", to="", tag="accuse",
               detail="她手上有附子粉",
               suspect="LQ", effect=E(scene="verdict2_LQ")),
        Choice(label="「凶手是 —— 值夜小监 贺小五」", to="", tag="accuse",
               detail="门是他锁的，灯是他留的",
               suspect="HXW", effect=E(scene="verdict2_HXW")),
        Choice(label="「凶手是 —— 内官监少监 冯保」", to="", tag="accuse",
               detail="……这一句说出口，比指认天子还险",
               suspect="FB", effect=E(scene="verdict2_FB")),
        # 案② → 案③ 的入口：药库旧档上那枚封泥，印的是经卷阁的印。
        # 门禁挂在「看见过那枚封泥」上——没看见的人，不知道还有第三桩。
        Choice(label="「臣还有一事 —— 经卷阁的封泥，也是景和五年的。」", to="case3_open",
               tag="accuse",
               detail="先把第二案按下，去看第三具尸首（第九幕 · 经卷阁）",
               locked_if=clue_absent("jinghe_seal"),
               locked_hint="还需：在第二案里见过那枚封泥（印着景和五年、被人重新封过的那一枚）",
               repeatable=False,   # 同上：收录与 flag 都幂等
               effect=E(flags=("case3_entered",),
                        dossiers=("09-DL-SMB", "09-JG-XYP"),
                        scene="case3_open")),
        # 同案①：结案厅里留一条回头路，否则掌局的供述与那页残账一旦漏掉，
        # 「两案同钉」就永远拿不到了。
        Choice(label="「臣请再查。」· 回尚药局前厅", to="case2_hall",
               detail="名字还没有写下去，卷宗还能翻"),
        Choice(label="「这两桩药局的死，臣只能写到这儿。」", to="",
               detail="两具尸首，一个不肯说的名字（结局 · 只写两个名字）",
               effect=E(flags=("gave_up2",), scene="ending2_quiet")),
        Choice(label="「臣要回凤仪殿 · 先把第一案的名字写上」", to="accuse_hall",
               detail="回到案① 的结案陈词"),
    ],
)

CASE2_VERDICT_SCENES: Dict[str, Scene] = {
    "verdict2_ZZZ": Scene(
        id="verdict2_ZZZ", title="判决 · 指认郑守拙", place="尚药局 · 前厅",
        time="卯时", act=8, case=2, kind="scene",
        body=(
            "你报出「尚药局掌局郑守拙」。\n"
            "他没有喊冤。他先把手里的茶盏放下，放得很轻，然后问了一句：\n"
            "「仵作，你写的是咱家的名，还是咱家的手？」\n"
            "「手。」你说。\n"
            "他点点头，像是终于有人替他把一件事说清了：「那就对了。"
            "咱家这辈子，只替人写字。」"
        ),
    ),
    "verdict2_LQ": Scene(
        id="verdict2_LQ", title="判决 · 指认柳青", place="尚药局 · 前厅",
        time="卯时", act=8, case=2, kind="scene",
        body=(
            "你报出「司药柳青」。\n"
            "她愣了很久，然后把手从袖子里抽出来，摊在案上——"
            "十指指腹都是黄的。\n"
            "「附子是我称的。」她说，「每日三钱，高典药让我称的。"
            "我没下过药，我连汤都没送过。」\n"
            "她说的可能是真的。可你手上只有她的手。"
        ),
    ),
    "verdict2_HXW": Scene(
        id="verdict2_HXW", title="判决 · 指认贺小五", place="尚药局 · 前厅",
        time="卯时", act=8, case=2, kind="scene",
        body=(
            "你报出「值夜小监贺小五」。\n"
            "他没有反驳，只是开始发抖，抖得灯罩在手里碰出细响。\n"
            "「我锁的门。」他说，「我真的锁了。锁的时候里头没人说话。」\n"
            "一个十六岁的孩子，一夜之间值出了两具尸首。他要为此赔上什么，"
            "那不是你能替他算的。"
        ),
    ),
    "verdict2_FB": Scene(
        id="verdict2_FB", title="判决 · 指认冯保", place="尚药局 · 前厅",
        time="卯时", act=8, case=2, kind="scene",
        body=(
            "你说出「内官监少监冯保」。\n"
            "他慢慢转过身来，脸上没有怒色，只有一点近乎惋惜的平静。\n"
            "「沈仵作。」他说，「你知道内官监管的是什么吗？」\n"
            "他往前走了半步，声音压低了些：「管的是："
            "哪一句话能写进档，哪一句话不能。」"
        ),
    ),
}

VERDICT_SCENES.update(CASE2_VERDICT_SCENES)

# --------------------------------------------------------------------------
# 案③ · 经卷阁 · 景和五年（第九 ~ 十一幕）
# --------------------------------------------------------------------------
# 入口在 case2_accuse：「臣还有一事 —— 经卷阁的封泥，也是景和五年的。」
# 玩家得先在案② 里看见那枚封泥（jinghe_seal），才摸得到第三桩。
#
# 三桩案子的死法是一次比一次「看不见」的：
#   案① 苦杏仁油：慢药入茶，血黑而银针不黑；
#   案② 生附子：麻舌、瞳仁不散，银针验不出；
#   案③ 炭气：银针不黑、血不黑、连药味都没有，只有一片樱红的尸斑。
# 真凶是奉内官监之命上阁顶添炭封窗的冯保，根子在景和五年那三个朱字。

#: 第九幕「勘验总录」——案③ 的档目门槛档
CASE3_ACT9_SUMMARY = "09-JG-END"
#: 第十幕「问询总录」——开第十一幕「提笔结案」的门槛档
CASE3_ACT10_SUMMARY = "10-DL-END"

CASE3_OPEN = Scene(
    id="case3_open",
    title="第九幕 · 经卷阁",
    place="经卷阁 · 阁前",
    time="卯时",
    act=9,
    case=3,
    body=(
        "你从尚药局出来的时候，天已经亮了一半。经卷阁在宫城西北角，"
        "三层砖石到顶，一层的窗都糊着纸。\n"
        "丙字库在阁后西头，门从外落锁，锁上又加了一道封。封泥上印的是"
        "「景和五年 · 经卷阁」——十二年前的印，泥胎却是新的。\n"
        "内官监掌印曹淳站在阶下，身上还是昨夜那件斗篷，靴底沾着炭灰。\n"
        "「炭气熏的。」他说，「阁里昨夜添了一盆炭，气窗也封了。"
        "仵作写一句炭气，这一桩就完了。」\n"
        "（他没说不能验。他只说了写什么。）"
    ),
    choices=[
        Choice(label="推门进去 · 尸首在书案边", to="jinghe_room",
               detail="先看这一具，再看别的"),
        Choice(label="去掌籍厅 · 她的案头", to="scriptorium3",
               detail="在阁二十九年的人，记的东西比谁都多"),
        Choice(label="去内官监值房 · 钥匙是从哪儿领的", to="key_room3",
               detail="阁门的钥匙出入都要登记"),
        Choice(label="回尚药局前厅 · 先把手上的名字写完", to="case2_hall",
               detail="回到案② 的问询"),
    ],
)

JINGHE_ROOM = Scene(
    id="jinghe_room",
    title="第九幕 · 丙字库",
    place="经卷阁 · 丙字库",
    time="卯时",
    act=9,
    case=3,
    body=(
        "丙字库不大，四面到顶都是架子，架上按年号排着档册，纸味压着霉味。\n"
        "谢云屏伏在书案与炭盆之间，右手攥着，左手伸向门口。"
        "她的脸朝着门——死之前，她听见有人进来。\n"
        "屋里两盆炭。气窗在北墙上，糊着一层新纸。门在你身后，锁在外面。"
    ),
    choices=[
        acting("jinghe_room", "俯身验尸 · 看尸斑的颜色", detail="先看她的脸",
               clues=("xyp_livid", "xyp_face"),
               text="你先把她的手摊平，再看她的脸。那不是活人的红，"
                    "也不是寻常尸首的青紫。\n"
                    "尸斑是一片樱红，从颈后一直铺到腰背，按下去褪色，抬手又回红。"
                    "口唇鲜红，十指不青，指甲底下干干净净。\n"
                    "她脸上没有半点挣扎过的样子——炭气走的人不挣扎，只是睡过去。",
               score=4),
        acting("jinghe_room", "取银针 · 三处入针", detail="先排掉「毒」这一条",
               clues=("needle_clean3",),
               text="银针入喉，不变；入心口，不变；入指尖，不变。\n"
                    "你把针就着门缝的天光照了照，还是银的。\n"
                    "案① 的贤妃是血里有毒，案② 的高典药是药里有毒。"
                    "这一回，凶器不在药里。",
               score=4),
        acting("jinghe_room", "数炭盆 · 一盆白灰，一盆新炭", detail="炭是谁添的",
               clues=("brazier_two", "charcoal_source"),
               text="东头那盆烧透了，只剩白灰，灰是凉的；西头这盆是新添的，"
                    "炭块还留着棱，边上搁着一把铜火箸。\n"
                    "丙字库是存旧档的屋子，冬天从不生火——炭气会返潮烂纸。"
                    "这两盆炭是有人特意送进来的，而且送了两次。",
               score=4),
        acting("jinghe_room", "搬书梯 · 查北墙的气窗", detail="屋里为什么没有风",
               clues=("vent_wax", "ladder_wax"),
               text="气窗开在北墙上，要踩书梯才够得着。\n"
                    "窗框上一圈新糊的油纸，纸角压着一块黄蜡，蜡上什么也没印——"
                    "不是封缄，是随手按上去的。窗缝里没有风，一丝也没有。\n"
                    "书梯第三档上，还有一道同样的黄蜡痕，扁圆，不是鞋底踩出来的形状。",
               score=4),
        acting("jinghe_room", "揭下封泥 · 对着天光看", detail="这道封是谁盖的",
               clues=("seal_recast", "locked_outside3"),
               text="你把封泥从门上揭下来，就着天光看印。\n"
                    "印文是「景和五年 · 经卷阁」，年号清清楚楚。可泥胎是新的："
                    "边缘还软，里头没有十二年的土气。\n"
                    "有人拿旧印翻了个模，重新盖了一枚——他要的不是封门，"
                    "是让人一眼看见年号。\n"
                    "门是从外头封的。屋里的人出不来。",
               score=4),
        acting("jinghe_room", "掰开她的右手", detail="她死前攥着什么",
               clues=("xyp_hand", "shelf_gap"),
               text="她攥得很紧。你一根一根掰开：半页纸。\n"
                    "纸上有景和五年的年号，边上是被撕开的毛茬——另外半页被人抽走了。\n"
                    "她左手撑在第七架的书边上。你抬头看那一架：中间空出一函的位置，"
                    "灰印是新的。那一函，昨夜还在这儿。",
               score=4),
        acting("jinghe_room", "拾起她脚边的调档单", detail="她昨天在查什么",
               clues=("xyp_lastvisit",),
               text="她脚边散着几张调档单，压在一只翻倒的砚台底下。\n"
                    "最上面那张写着：昨日午前，取「景和五年 丙字第七函」，"
                    "理由两个字——「对账」。\n"
                    "她昨日在查十二年前的东西。今天天亮前，她死在放那一函的库里。",
               score=4),
        acting("jinghe_room", "蹲下来 · 闻这屋子有什么味", detail="药味、香味，还是什么也没有",
               clues=("room_smell",),
               text="你蹲下来，闭上眼闻。陈纸、霉、炭气。\n"
                    "没有药味。一点也没有。\n"
                    "案① 殿里那盏茶有苦杏仁的甜，案② 药库里有附子的辛。"
                    "这一回，凶手连气味都省了。",
               score=2),
        acting("jinghe_room", "看炭灰里的脚印", detail="灰上这一枚太清楚了",
               clues=("char_footprint",),
               text="炭灰从盆沿漏出来，在地上铺了薄薄一层。灰上有一枚脚印，"
                    "五瓣花底，是女史的绣鞋。\n"
                    "可阁里当差的女史都穿软底鞋——软底踩不出这么深的花纹。\n"
                    "脚印的方向是从门口到书梯，深浅均匀，像是有人特意踩了一脚给人看。",
               score=3),
        Choice(label="回阁前 · 看看掌印还在不在", to="case3_open",
               detail="换个地方再看"),
        Choice(label="移步 · 阁前问人", to="case3_hall",
               detail="把常安、陆文昭、曹淳、冯保一个个叫来问",
               locked_if=missing_dossier(CASE3_ACT9_SUMMARY),
               locked_hint="勘验未毕：请调阅档目，把第九幕的格目读全"
                           "（尸格、银针、炭盆、气窗、封泥、领钥匙簿）"),
    ],
)

SCRIPTORIUM3 = Scene(
    id="scriptorium3",
    title="第九幕 · 掌籍厅",
    place="经卷阁 · 掌籍厅",
    time="卯时",
    act=9,
    case=3,
    body=(
        "掌籍厅在阁的东头，两张案子对着摆。她那一边收拾得极齐："
        "笔搁在笔架上，砚台里的墨已经干了。\n"
        "架上按年号排着档册，从景和元年一直排到今年。"
        "你一眼就看出少了一格——景和五年那一格是空的。"
    ),
    choices=[
        acting("scriptorium3", "翻她的日课簿 · 昨日写了什么", detail="掌籍每天都写字",
               dossiers=("09-JG-LAST",),
               text="日课簿一天一行，她写了二十九年，字越写越小。\n"
                    "最后写的一行是昨日：「取景和五年丙字第七函对账。"
                    "内官监来人文书二件，未登记。」\n"
                    "写完这一行，她把笔搁回了笔架——搁得很正。",
               score=4),
        acting("scriptorium3", "查景和五年那一格 · 空的", detail="那一函去哪儿了",
               dossiers=("09-JG-PURGE",),
               text="景和五年那一格只剩三本：一本是空的封皮，一本是抄没名录，"
                    "一本是年例开支。\n"
                    "名录是十二年前抄的，字迹潦草，一共二十九行，"
                    "死因栏上写的多半是「疾」与「杖」。\n"
                    "第十七行是个女子的名字：采薇。",
               score=4),
        acting("scriptorium3", "翻掌籍的交接簿 · 谁动过她的架", detail="钥匙领出去，没有还回来",
               dossiers=("09-JG-KEY",),
               text="交接簿上，丙字库的钥匙每月由掌籍向内官监领一次，"
                    "还钥匙要销号。\n"
                    "前日寅时那一行写着「内官监 · 领」，销号栏是空的——"
                    "钥匙到现在还没还。笔是冯保的手，押也是冯保的押。",
               score=4),
        Choice(label="回到丙字库", to="jinghe_room", detail="再看一遍尸首"),
        Choice(label="去内官监值房", to="key_room3", detail="钥匙与炭都从那儿出"),
        Choice(label="回阁前", to="case3_open", detail="看看掌印还在不在"),
        Choice(label="移步 · 阁前问人", to="case3_hall",
               detail="把常安、陆文昭、曹淳、冯保一个个叫来问",
               locked_if=missing_dossier(CASE3_ACT9_SUMMARY),
               locked_hint="勘验未毕：请调阅档目，把第九幕的格目读全"
                           "（尸格、银针、炭盆、气窗、封泥、领钥匙簿）"),
    ],
)

KEY_ROOM3 = Scene(
    id="key_room3",
    title="第九幕 · 内官监值房",
    place="内官监 · 值房",
    time="卯时",
    act=9,
    case=3,
    body=(
        "内官监的值房在阁外的东厢，一间屋子只摆一张案、一本簿、一炉火。\n"
        "案上摊着领钥匙簿，翻在前日那一页。火炉里烧的是新炭，"
        "炭盆边搁着两个空的炭筐——今夜有人从这里提过炭。\n"
        "看房的小太监不敢拦你，只说：「掌印吩咐过，仵作要看什么，就给他看。」"
    ),
    choices=[
        acting("key_room3", "翻领钥匙簿 · 前日寅时那一行", detail="谁领了阁门的钥匙",
               clues=("key_ledger3",),
               text="领钥匙簿上，前日寅时那一行写着「内官监 · 领」，"
                    "领用人的押是冯保。\n"
                    "可冯保说，那一日他不在阁里——他在尚药局当值。\n"
                    "要紧的不是谁领的，是这一行底下的销号是空的：钥匙没有还回来。",
               score=4),
        acting("key_room3", "点数炭筐 · 今夜提过几筐炭", detail="丙字库不生火",
               dossiers=("09-JG-COAL",),
               text="值房一夜的炭有定额，今日的账上多出两筐，签收人空着。\n"
                    "小太监说：前半夜有人来提过炭，穿内官监的靴子，"
                    "没让他跟着，自己搬的。\n"
                    "「往哪儿搬的？」\n"
                    "「往阁后头。」他说，「那儿冬天不生火的。」",
               score=4),
        acting("key_room3", "看看掌印的火炉 · 炉边有什么", detail="他昨夜一直在这儿么",
               clues=("burned_order", "cc_tone"),
               text="炉边的灰里埋着一角纸，烧剩半边，上面有「封存」两个字，"
                    "是内官监的牍式。纸角还压着半个印——"
                    "该封存的东西，他先烧了一半。\n"
                    "你直起身，看见曹淳站在门口。他没进来，只说了一句：\n"
                    "「炭气熏的。仵作这一句写在纸上，咱们都好过。」",
               score=3),
        Choice(label="回到丙字库", to="jinghe_room", detail="再看一遍尸首"),
        Choice(label="去掌籍厅", to="scriptorium3", detail="她的案头"),
        Choice(label="回阁前", to="case3_open", detail="看看掌印还在不在"),
        Choice(label="移步 · 阁前问人", to="case3_hall",
               detail="把常安、陆文昭、曹淳、冯保一个个叫来问",
               locked_if=missing_dossier(CASE3_ACT9_SUMMARY),
               locked_hint="勘验未毕：请调阅档目，把第九幕的格目读全"
                           "（尸格、银针、炭盆、气窗、封泥、领钥匙簿）"),
    ],
)

CASE3_HALL = Scene(
    id="case3_hall",
    title="第十幕 · 阁前人",
    place="经卷阁 · 阁前",
    time="辰时",
    act=10,
    case=3,
    body=(
        "天已经全亮了。阁前的砖地上，两个小监抬着炭筐从你身边过去，"
        "谁也不敢往丙字库那边看。\n"
        "曹淳坐在阶上，手里一直捏着那枚封泥，捏得指节发白。"
        "冯保站在他后面一步，像影子一样贴着。\n"
        "（这一回要问的是活人：看阁的、抄书的、掌印的，还有昨夜上过阁顶的那一个。）"
    ),
    choices=[
        Choice(label="传唤 · 看阁小监常安", to="talk_ca", wants="CA",
               detail="十六岁，记得谁在什么时候上了阁顶"),
        Choice(label="传唤 · 候补书吏陆文昭", to="talk_lws", wants="LWS",
               detail="她替师父抄过景和五年的原页"),
        Choice(label="求见 · 内官监掌印曹淳", to="talk_cc", wants="CC",
               detail="「写一句炭气，就完了」"),
        Choice(label="求见 · 内官监少监冯保", to="talk_fb3", wants="FB",
               detail="领钥匙簿上有他的手笔"),
        Choice(label="前往 · 丙字库", to="jinghe_room", detail="再看一遍现场"),
        Choice(label="前往 · 掌籍厅", to="scriptorium3", detail="景和五年那一格"),
        Choice(label="前往 · 内官监值房", to="key_room3", detail="领钥匙簿与炭筐"),
        Choice(label="整理证物 · 提笔结案", to="case3_accuse", tag="accuse",
               detail="把三桩案子写成第三份底稿",
               locked_if=missing_dossier(CASE3_ACT10_SUMMARY),
               locked_hint="问得还不够：看阁小监、候补书吏、掌印、少监，"
                           "四个人的话都还没有摆到案上"),
        Choice(label="回尚药局前厅 · 先把第二案的名字写上", to="case2_hall",
               detail="回到案② 的问询"),
    ],
)

TALK_CA = Scene(
    id="talk_ca",
    title="问询 · 常安",
    place="经卷阁 · 阁前",
    time="辰时",
    act=10,
    case=3,
    interlocutor="CA",
    hall="case3_hall",
    body=(
        "常安十六岁，去年才拨进阁里，认得的字不多。他站得笔直，"
        "手在袖子里绞着，肩膀一抖一抖。\n"
        "「掌籍姑姑教我认字。」他先说了这一句，"
        "「她说认了字，才守得住这些东西。」"
    ),
)

TALK_LWS = Scene(
    id="talk_lws",
    title="问询 · 陆文昭",
    place="经卷阁 · 阁前",
    time="辰时",
    act=10,
    case=3,
    interlocutor="LWS",
    hall="case3_hall",
    body=(
        "陆文昭二十二岁，候补书吏，写得一手好字。她进来的时候手里还握着笔，"
        "像是忘了放下。\n"
        "「师父昨夜让我抄东西。」她说，「抄三遍。」\n"
        "她的下眼圈发青，指甲修得很短。"
    ),
)

TALK_CC = Scene(
    id="talk_cc",
    title="问询 · 曹淳",
    place="经卷阁 · 阁前",
    time="辰时",
    act=10,
    case=3,
    interlocutor="CC",
    hall="case3_hall",
    body=(
        "曹淳坐在阶上，让你站着说话。他掌印二十一年，"
        "手上的封泥一直没放下。\n"
        "「仵作问吧。」他说，「内官监的差事，答得了的咱家都答。」\n"
        "（答得了的。）"
    ),
)

TALK_FB3 = Scene(
    id="talk_fb3",
    title="问询 · 冯保",
    place="经卷阁 · 阁前",
    time="辰时",
    act=10,
    case=3,
    interlocutor="FB",
    hall="case3_hall",
    body=(
        "冯保站在曹淳身后一步，从进阁到此刻没有坐下过。\n"
        "「沈仵作。」他先开口，「尚药局那一夜，你写的名字是郑守拙。"
        "内官监认了。」\n"
        "他顿了顿：「这一回，你打算写谁？」"
    ),
)

CASE3_ACCUSE = Scene(
    id="case3_accuse",
    title="第十一幕 · 卷终",
    place="经卷阁 · 阁前",
    time="巳时",
    act=11,
    case=3,
    body=(
        "第三份底稿摊在阶前的砖地上。这一份最薄：三桩案子，三层纸，"
        "底下压着三个朱字。\n"
        "阁门还封着，封泥上的年号对着日头，红得刺眼。\n"
        "曹淳站在左边，冯保在右边，常安与陆文昭跪在阶下。\n"
        "你提笔。这一回写下去的名字，会比前两份都重——"
        "重到可能没有人敢接。\n"
        "（指认谁，就写谁。也可以把三桩案子并成一桩来写；"
        "也可以什么都不写。）"
    ),
    choices=[
        Choice(label="「凶手是 —— 内官监掌印 曹淳」", to="", tag="accuse",
               detail="令是他下的，封是他盖的，钥匙是他领的",
               suspect="CC", effect=E(scene="verdict3_CC")),
        Choice(label="「凶手是 —— 内官监少监 冯保」", to="", tag="accuse",
               detail="炭是他搬的，气窗是他封的，钥匙在他手里",
               suspect="FB", effect=E(scene="verdict3_FB")),
        Choice(label="「凶手是 —— 候补书吏 陆文昭」", to="", tag="accuse",
               detail="炭灰里那枚五瓣花底的鞋印是女史的",
               suspect="LWS", effect=E(scene="verdict3_LWS")),
        Choice(label="「凶手是 —— 看阁小监 常安」", to="", tag="accuse",
               detail="丙字库的炭，是他一趟一趟搬进去的",
               suspect="CA", effect=E(scene="verdict3_CA")),
        Choice(label="「凶手是 —— 陛下」", to="", tag="accuse",
               detail="……景和五年那三个朱字，是今上的笔",
               visible_if=has_clue("emperor_ink"),
               suspect="HD", effect=E(scene="verdict3_HD")),
        Choice(label="「臣请再查。」· 回阁前问人", to="case3_hall",
               detail="名字还没有写下去，卷宗还能翻"),
        Choice(label="「这三桩案子 —— 臣只能写到这儿。」", to="",
               detail="把底稿收进袖子（结局 · 合上卷宗）",
               effect=E(flags=("gave_up3",), scene="ending3_quiet")),
        Choice(label="「臣要回尚药局前厅 · 把第二案的名字写完」", to="case2_hall",
               detail="回到案② 的问询"),
    ],
)

CASE3_VERDICT_SCENES: Dict[str, Scene] = {
    "verdict3_CC": Scene(
        id="verdict3_CC", title="判决 · 指认曹淳", place="经卷阁 · 阁前",
        time="巳时", act=11, case=3, kind="scene",
        body=(
            "你报出「内官监掌印曹淳」。\n"
            "他把封泥放在砖地上，放得很正，印文朝上。\n"
            "「咱家掌印二十一年。」他说，「领钥匙、送炭、盖封，"
            "都是咱家的手。仵作写得不错。」\n"
            "「是谁的令？」你问。\n"
            "他抬眼看你，第一次笑了一下：「内官监的令，从来不写在纸上。」"
        ),
    ),
    "verdict3_FB": Scene(
        id="verdict3_FB", title="判决 · 指认冯保", place="经卷阁 · 阁前",
        time="巳时", act=11, case=3, kind="scene",
        body=(
            "你说出「内官监少监冯保」。\n"
            "他没有看你，看着阁顶。三层之上是瓦，瓦上昨夜落了霜。\n"
            "「炭是咱家搬的，窗是咱家封的。」他说得很平，"
            "「那个孩子只当是给掌籍姑姑添一盆火。」\n"
            "「你上去的时候，她知道吗？」\n"
            "「她知道。」他说，「她抬头看了咱家一眼，说了一句："
            "『那一页你已经拿走了。』」"
        ),
    ),
    "verdict3_LWS": Scene(
        id="verdict3_LWS", title="判决 · 指认陆文昭", place="经卷阁 · 阁前",
        time="巳时", act=11, case=3, kind="scene",
        body=(
            "你报出「候补书吏陆文昭」。\n"
            "她先是没有懂，然后懂了，笔从手里掉下去，滚到砖缝里。\n"
            "「我抄过那一页。」她说，「师父让我抄三遍，第三遍让我烧了。"
            "我留了一张。」\n"
            "她把手伸进袖子里，掏出一张折了四折的纸：「这个……算不算证据？」\n"
            "算。可它不是杀人的证据。它只证明，炭灰里那枚鞋印，"
            "是一个从来没有上过阁顶的人的。"
        ),
    ),
    "verdict3_CA": Scene(
        id="verdict3_CA", title="判决 · 指认常安", place="经卷阁 · 阁前",
        time="巳时", act=11, case=3, kind="scene",
        body=(
            "你报出「看阁小监常安」。\n"
            "他愣了很久，然后开始哭，哭得没有声音，肩膀一抖一抖，"
            "像他一直站在阶下那样。\n"
            "「是我搬的炭。」他说，「那个人说，姑姑夜里冷。」\n"
            "「他还给了你一块蜡。」你说，「让你把气窗糊上。」\n"
            "「他说糊上就不冷了。」\n"
            "十六岁。他认得几个字，认得姑姑教他的那些字。"
            "他不认得「炭气」这两个字。"
        ),
    ),
    "verdict3_HD": Scene(
        id="verdict3_HD", title="判决 · 指认陛下", place="经卷阁 · 阁前",
        time="巳时", act=11, case=3, kind="scene",
        body=(
            "你说出那两个字，把手里的原页摊开在阶上，三个朱字朝着天。\n"
            "阁前没有一个人动。曹淳慢慢地跪了下去，冯保跟着跪。\n"
            "「仵作。」曹淳说，声音终于不像公文了，「你知道你在念什么吗？」\n"
            "「臣在念一页账。」你说，「十二年前，二十九个人，一剂药。」\n"
            "当日午后，内官监来收走了那半页原页。你没有被问话，也没有被升官——"
            "只是从那天起，经卷阁的丙字库，再也不许仵作进去了。"
        ),
    ),
}

VERDICT_SCENES.update(CASE3_VERDICT_SCENES)

# --------------------------------------------------------------------------
# 结局
# --------------------------------------------------------------------------

ENDING_SCENES: Dict[str, Scene] = {}


def _ending(eid: str, title: str, body: str, case: int = 1, act: int = 5) -> Scene:
    scene = Scene(id=eid, title=title, place="结案", time="卯时", kind="ending",
                  body=body, case=case, act=act)
    ENDING_SCENES[eid] = scene
    return scene


_ending("ending_restitution", "结局 · 铁证如山", (
    "你把每一件都摆了出来：银针变黑是七日积毒而非即刻鸩杀；香炉里的朱砂只会叫人昏沉，"
    "那是布给你看的障眼法；窗棂上的撬痕、栓下的木屑，说明门是从外头拨上的；"
    "尚药局簿上七次支取苦杏仁油，记的都是王德海的名，字迹却各不相同——有人替他写，"
    "那笔迹和十二年前采薇案卷里的供词一模一样。\n"
    "最后你念出贤妃那张没写完的笺纸，念到「王德海经手，账目有亏」时，"
    "王德海的肩膀塌了下去。\n"
    "「她……她查了三个月。」他说，「她要翻十二年前的事。老奴这条命，是从那时候活到现在的。」\n"
    "他又抬起头，眼睛红着：「皇后娘娘也恨她。可是娘娘没动手。是老奴动的手。"
    "茶是亥时初送的，她喝了半盏，问老奴为什么手抖。」\n"
    "皇帝没有立刻说话。他先问：「她走的时候，疼么。」\n"
    "「不疼。」你说，「苦杏仁油是慢慢走的，人会先睡过去。」\n"
    "那句话像一块石头落进水里。皇帝闭了一下眼，才开口：「杖毙。同罪者，一并查。」\n"
    "——同罪者。你抬起头，看见皇后在手心里攥紧了那枚玉扳指。\n"
    "三个月后，掖庭重修名册，采薇的名字被添回了一笔。"
    "你升了大理寺丞，从此再没人敢在你验尸的时候说话。\n"
    "「真相大白，且未曾被任何人按下。」"
))

_ending("ending_standard", "结局 · 尘埃落定", (
    "你摆出了茶盏、苦杏仁油、香炉灰与窗棂上的刮痕，把王德海按在了案上。\n"
    "他招了：茶是亥时初送的，他本来只想让她昏睡几日，好把账目上的窟窿填平。"
    "可他没算准分量——或者说，他算准了。\n"
    "「杖毙。」皇帝说。\n"
    "王德海被拖出去的时候，回头看了你一眼，像是要说什么，最后什么也没说。\n"
    "案子结了，结得很干净。只是你总觉得，还有些东西没有摆到案上——"
    "比如那枚不该出现在皇后手上的玉扳指，比如采薇。\n"
    "皇帝赏了你二十两银、一件狐裘，还有一句话：「此案，不必再提。」\n"
    "「凶手伏法，但水面下的东西，你没有捞完。」"
))

_ending("ending_dangerous", "结局 · 玉扳指", (
    "你报了皇后的名字，然后把那枚玉扳指的事端了出来——先帝所赐，本该在太子手上。\n"
    "皇后的脸在灯下白了一层。她看着皇帝，一个字都没说。\n"
    "殿上安静了很久。皇帝说：「沈墨白，你查的是贤妃的死。」\n"
    "「臣查的是贤妃的死因。」你说，「她死前见的是皇后娘娘。」\n"
    "然后你被请了出去。当晚你被挪进大理寺的值房，门口多了一个人守着。\n"
    "三日后结案：太监总管王德海「因账目亏空、谋害主位」，杖毙——是皇帝自己下的旨。"
    "你知道那是对的，也知道那不是全部。\n"
    "你保住了命，保住了官，也从此被记在了那本不该记的册子上。\n"
    "「你说出了更危险的那半截真相。它没有杀死你，但也再没有第二个人听见。」"
))

_ending("ending_pressured", "结局 · 按下", (
    "皇帝在你开口之前先开了口。\n"
    "「贤妃久病，痰壅气绝。」他说，「仵作验过了。」\n"
    "你验过了。你验出的是一根变黑的银针、一盏有苦杏仁味的冷茶，和一张没写完的笺纸。"
    "这些话在你喉咙里滚了一圈，最后你低头：「……是。」\n"
    "案子就这样收了。王德海被调去守陵，三日后在陵上自缢。"
    "皇后那枚玉扳指没人再提。采薇的名字依旧不在名册上。\n"
    "你走出宫门的时候天亮了。你把记事簿收进袖子，觉得它比来时重。\n"
    "「你活着，且升了官。只是从此以后，你再没有验过一具宫里的尸首。」"
))

_ending("ending_false", "结局 · 替罪的人", (
    "你报出的名字，不是那个把茶端进去的人。\n"
    "证据被一条条驳了回来。贵妃当堂冷笑：「汤碗还在厨下，大人不妨去验；"
    "倒是那盏茶——是谁端进去的？」\n"
    "皇帝看着你，看了很久，然后说：「沈墨白，你验了四十七具尸首，"
    "今日这一具，你验坏了。」\n"
    "结案如你所请。三日后，那人被处死。\n"
    "又过了七日，御膳房的小顺子在掖庭的井里被捞了上来。"
    "仵作验的是溺水——你去看过那个井口，井沿上有一道新鲜的血痕。\n"
    "你从此不再接宫里的差事。夜里偶尔会想起王德海跪在门槛外那副肩膀一抽一抽的样子，"
    "然后想起他抬头看你的那一眼。\n"
    "「错的人死了，对的人还在。这桩案子从此没有人再敢查。」"
))

_ending("ending_treason", "结局 · 天子无案", (
    "「陛下。」\n"
    "这两个字在殿上落地的时候，你就已经知道后面会发生什么了。\n"
    "皇帝没有怒。他只是很轻地叹了口气，像是终于等到一件早知道会来的事。\n"
    "「沈墨白，你验尸验得久了，把活人也当成了死物。」\n"
    "当夜，大理寺的档案房走水，烧了三间屋。仵作沈墨白「殉于火」。\n"
    "贤妃以「薨于旧疾」入陵。王德海守陵三年，未死。"
    "小顺子后来补进了尚药局，做事很稳，只是从不碰茶。\n"
    "「在这座宫里，天子没有案子。」"
))

_ending("ending_bystander", "结局 · 查不出来", (
    "你把记事簿合上：「此案暂无确证，臣请再查。」\n"
    "皇帝没有让你再查。他让你把簿子留下。\n"
    "贤妃以「薨于旧疾」下葬，丧仪如制。王德海照旧当他的总管，"
    "只是从此见了你便绕道走。三个月后，小顺子被调去了皇陵，说是「他自己求的」。\n"
    "你在记事簿的最后一页写过一句话，交上去之前，你把它撕了下来，"
    "投进了烛火里：「我知道是谁。我知道我为什么不说。」\n"
    "「你交出了簿子。这座宫城照旧运转，一点声音也没有。」"
))

_ending("ending_quiet", "结局 · 辞官", (
    "你把簿子放进火盆，看着它烧完，然后解了腰牌。\n"
    "「臣验不出来。」你说，「臣请辞。」\n"
    "皇帝盯着你看了很久，最后摆了摆手。\n"
    "三个月后，京城西市开了一家小药铺，掌柜的姓沈，验尸的手艺改成了看脉。"
    "偶尔有官差上门求验伤，他都推了。\n"
    "只有一个夜里，一个裹着斗篷的女人来买安神的药，"
    "付钱时掉出一枚玉扳指，骨碌碌滚到柜台底下。\n"
    "「客官的东西。」\n"
    "「不是我的。」她说，「扔了吧。」\n"
    "「你把扳指扔进了井里。从此再没有谁提起贤妃。」"
))


# --------------------------------------------------------------------------
# 选项：正殿重验
# --------------------------------------------------------------------------

CRIME_SCENE.choices.append(
    acting("crime_scene", "再验一次 · 用记事簿对着看",
           "第二遍才认得出的东西",
           "你把记事簿摊在膝上，一条一条对着现场看。\n"
           "看到「茶」那条时，你忽然想起一件事：一个惯饮武夷的人，"
           "茶味那样厚，怎么会在半盏之内就尝出苦杏仁味、却又照喝不误？"
           "——除非她已经喝了不止一天。\n"
           "银针上的黑，不是这一夜的毒，是七日的积毒。这一夜那盏茶，"
           "只是把已经走到尽头的东西推了最后一把。",
           clues=("silver_week", "almond_habit"), score=3,
           visible_if=all_of(has_clue("si_needle"), has_clue("tea_almond")))
    # 原有一对 `locked_by=has_clue("silver_week")` / `locked_hint="已经推演过了"`：
    # 这条动作产出线索 ⇒ `acting()` 自动 `repeatable=False`，做过就被 `seen_choices`
    # 滤掉，而这两枚线索只有它一个来源 ⇒ 灰态与那句提示永远不会出现（死文案）。
)

# 侧殿查证：茶盏
HALL.choices.insert(7, acting(
    "interrogate_hall", "检查 · 正殿案上的安神茶盏",
    "盏底的粉末",
    "你把那盏残茶端到灯下，倒出盏底。\n"
    "盏底沉着薄薄一层白粉，已经干了，边缘有一圈水痕——那不是茶叶沉渣，"
    "是有人「先放粉，再注水」。茶盏是青瓷，盏托底下没有款识，"
    "说明它不属于凤仪殿的器皿，是另外带进来的。",
    items=("tea_set",), score=2,
    visible_if=has_clue("tea_almond"),
    # 同上：`items=` 让它自动不可重复，茶盏也只有这一个来源 ⇒ 原来的
    # `locked_by=all_of(has_clue("tea_set"))` / `"已经验过了"` 是死门禁、死文案。
))

# --------------------------------------------------------------------------
# 尚药局：选项
# --------------------------------------------------------------------------

# 这五条是**直接写 Choice** 的：绕过了 `acting()` 的
# `repeatable = not (clues or items or dossiers or score or trust)` 自动规则，
# 所以必须显式写 `repeatable=False`。否则线索虽然只给一次（引擎去重），
# `score` 却每点一次就加一次 —— 实测连点五次 +10 分，且无上限。
PHARMACY.choices = [
    Choice(label="翻查安神类药材领用簿", to="pharmacy",
           detail="苦杏仁油去了哪里", repeatable=False,
           effect=E(
               text="你翻到「安神」那一册。苦杏仁油在册上是个不起眼的小条目："
                    "「苦杏仁油，安神定惊，入汤剂，一钱至一钱半。多服令人气绝。」\n"
                    "小字注得很清楚，只是这一行下面被朱笔勾过两次。",
               clues=("almond_oil",), score=2)),
    Choice(label="核对取用记录与签押", to="pharmacy",
           detail="谁取的、谁写的", repeatable=False,
           effect=E(
               text="取用记录三年七次，记的名都是「王德海」。\n"
                    "你把这七处签押排在一起看：第一笔和第二笔是一样的，"
                    "第三笔开始就换了个人——横竖都更硬，收笔带着钩。"
                    "一个人不会在三年里把自己的名字写成两种写法。",
               clues=("ledger_gap",), score=3)),
    Choice(label="问掌籍 · 朱砂入炉会怎样", to="pharmacy",
           detail="红粉是不是毒", repeatable=False,
           effect=E(
               text="掌籍老太监听完就摇头：「朱砂入炉？那是方士的把戏。"
                    "闻久了头昏、目眩、心里发慌，可它毒不死人，银针也验不出来。」\n"
                    "他顿了一下，补了一句：「所以要拿它下毒的人，图的不是毒——图的是让验的人看错地方。」",
               clues=("cinnabar_note",), score=3)),
    Choice(label="回侧殿", to="interrogate_hall", detail="继续问询与查证"),
]

# --------------------------------------------------------------------------
# 掖庭旧档：选项
# --------------------------------------------------------------------------

# 同上：直接写 Choice，收益给一次，必须显式关掉重复。
ARCHIVE.choices = [
    Choice(label="调阅景和五年「采薇案」卷宗", to="archive",
           detail="那张笺纸上写的名字", repeatable=False,
           effect=E(
               text="卷宗很薄。景和五年，宫人采薇「窃内帑金饰」，杖八十，毙于掖庭。\n"
                    "你翻到验伤单，又翻到证人供词——两份的字迹是同一个人写的："
                    "横竖更硬，收笔带钩。正是你在尚药局领用簿第三笔上见过的那个手笔。\n"
                    "更奇的是，两份纸上都写着「供认不讳」，可采薇是哑的——"
                    "掖庭名册里，她的名字旁边标注着「哑」字。",
               clues=("old_record",), flags=("knows_caiwei",), score=4)),
    Choice(label="查采薇其人的旧档与经手人", to="archive",
           detail="谁办的这桩案子", repeatable=False,
           visible_if=has_flag("knows_caiwei"),
           effect=E(
               text="景和五年的掖庭管事名录上，采薇的顶头管事写着三个字：王德海。\n"
                    "那一年他刚升管事，第二年就调进了凤仪殿。\n"
                    "卷宗最后夹着一页便签，是内务府的字迹：「采薇名下亏空已补，案结。」\n"
                    "「已补」两个字下面，被人用指甲划了一道。",
               clues=("caiwei_death",), score=3)),
    Choice(label="回侧殿", to="interrogate_hall", detail="继续问询与查证"),
]

# ---------------- 案② 的六个收尾（第八幕） ----------------

_ending("ending2_truth", "结局 · 两案同钉", (
    "你把两案的纸摊在同一张案上。\n"
    "左边是凤仪殿：半盏安神茶、一炉朱砂、窗棂上的撬痕。"
    "右边是药库：三钱生附子、一截青丝线、值夜簿上描出来的那一行字。\n"
    "然后你摆出第三样东西：一本私账，每笔只写四个字——「药出有主」。"
    "七次取用，前六次在景和五年到十二年之间，第七次在贤妃薨的前一日。\n"
    "「同一个人写的字。」你说，「都是照着别人的手描的。"
    "凤仪殿的茶是一支，尚药局的附子是一支，写字的只有一支。」\n"
    "郑守拙跪下了。他说的第一句话不是求饶：「咱家十二岁进宫，"
    "认字是别人教的。教咱家写字的人说：你这一手字，能换一条命。」\n"
    "「换了几条？」你问。\n"
    "「三条。」他说，「采薇一条。高延年一条。蒋九一条。」\n"
    "他还说了第四件事：景和五年，药是从经卷阁出的，"
    "经手的人里有一个名字被水浸过，谁也看不清——但那一横起笔很重。\n"
    "冯保在门外站了很久。天亮的时候，他进来把两份底稿都收走了，"
    "一句话没说。\n"
    "三个月后你听说，经卷阁闭了。又过了半年，东宫废址的墙塌了一角，"
    "有人在里面挖出半箱账册。\n"
    "「两案并作一案：药是同一双手下的，名字也写在同一页纸上。」"
), case=2, act=8)

_ending("ending2_thin", "结局 · 一页之差", (
    "你把郑守拙的话原样誊了下来。\n"
    "他承认字是他描的，承认七次取用里有三次是他签的押——"
    "可他始终没说那页纸是从哪儿来的。\n"
    "「药出有主。」你把私账翻到最后一页，「主是谁？」\n"
    "他抬眼看你，没有答。\n"
    "内官监当天就把底稿收走了。冯保读得比上一回慢，"
    "读到「描」字的时候停了一下，什么也没改。\n"
    "结案文书上写的是：尚药局掌局郑守拙，私刻药引、伪造簿册，"
    "两案并发，拟定绞。\n"
    "「药是同一双手下的」——这一句你没写进去。"
    "写不进去：你手上没有那一页。\n"
    "三个月后经卷阁封了。你托人问过那半箱账册，"
    "回话是「搬运时落水，字都泡了」。\n"
    "只有你自己还记得：那一横，起笔很重。"
), case=2, act=8)

_ending("ending2_pressed", "结局 · 又是暴病", (
    "你报了郑守拙的名字，把青丝线、值夜簿和那本私账摆上案。\n"
    "他没有喊冤。他只是一直看着冯保。\n"
    "冯保接过底稿，从头到尾读了一遍，读到「附子三钱」四个字的时候停了一下，"
    "然后拿起笔，把「附子」改成了「寒疾」。\n"
    "「两具尸首，一个典药、一个书吏，一夜之间。」他说，"
    "「写出去，尚药局从上到下都要换人。这不合内官监的意思。」\n"
    "你想说什么，他先抬手拦住了：「沈仵作，你的名字咱家会写上去，"
    "功劳是你的。」\n"
    "底稿发下来的时候，你看了很久。上面写着：尚药局典药高延年、书吏蒋九，"
    "俱因寒疾暴卒。\n"
    "「你写的名字是真的，可送出去的纸是假的。」"
), case=2, act=8)

_ending("ending2_wrong", "结局 · 错的药方", (
    "你报了那个手上有黄渍的姑娘，或者那个十六岁、不肯熄灯的小监。\n"
    "结案文书发得很快，快到你都来不及再问一句。\n"
    "柳青被送进掖庭的时候，把自己称过的附子一笔一笔报给了记档的人："
    "「每日三钱，一共四十七两六钱。你们可以称。」\n"
    "四十七两六钱，分毫不差。\n"
    "贺小五什么也没说。他只是把灯罩留在了值房——那是他娘留给他的东西。\n"
    "案子结了，你升了。尚药局换了掌局，药库换了封条。\n"
    "第二年冬天，又有一位娘娘在夜里薨了，口角有黑血。\n"
    "「你报了一个方便的名字，真正的写字人还坐在案前。」"
), case=2, act=8)

_ending("ending2_lightout", "结局 · 灯灭", (
    "你说出「内官监少监冯保」。\n"
    "他没有生气，甚至笑了一下，然后做了一件你没想到的事："
    "他转身走到廊下，把前厅的灯一盏一盏吹灭了。\n"
    "天还没亮透。黑暗里你听见他的声音，很近：\n"
    "「沈仵作，你查的是两具尸首。内官监管的是——谁的名字能留在纸上。」\n"
    "灯重新点起来的时候，他还在原地。底稿不见了。\n"
    "当日的文书写的是一场雪，冻死了两个当值的。\n"
    "三个月后，大理寺的档架少了一格。你被调去管义庄，"
    "在那里你验的每一具尸首，都没有名字。\n"
    "「你说出了最该说的那句话，然后就没有然后了。」"
), case=2, act=8)

_ending("ending2_quiet", "结局 · 只写两个名字", (
    "你把笔搁下，没有写凶手。你写的是两行事实：\n"
    "尚药局典药高延年，卒于药库，口唇麻色；"
    "书吏蒋九，卒于值房，口唇麻色。\n"
    "附子三钱，值夜簿一行，门闩上的一截线。\n"
    "「臣只能写到这儿。」你说，「再往下的名字，臣没有证据。」\n"
    "冯保看了很久，然后把底稿折起来收进袖里。\n"
    "「这也是一份结案。」他说，「只可惜——不知是谁以后要替它写下去。」\n"
    "开春以后，尚药局换了新的封条，药库的钥匙换了人拿。\n"
    "蒋九案上那盏灯，没有人再去点。\n"
    "「两具尸首，一个不肯说的名字。」"
), case=2, act=8)

# ---------------- 案③ 的六条收尾 ----------------
_ending("ending3_orig", "结局 · 原页", (
    "你把那张折了四折的纸摊在案上，连同翻模的封泥、气窗上的蜡。\n"
    "景和五年，经卷阁领炭一千二百斤，收炭一千二百斤。账目平整。"
    "唯有末尾三个朱字，写得极随意：知道了。\n"
    "「这一页是抄本。」你说，「原页在丙字库，抄本在她袖子里。"
    "抄本上少了第十七行——因为第十七行上有一个人。」\n"
    "「名录上的采薇，是后来入宫的贤妃。景和五年，她被从这一页上抹掉，"
    "本该死在掖庭——十二年后，这一页上那剂苦杏仁油，送回了凤仪殿。」\n"
    "「封门的是冯保，教他封门的人在内官监。"
    "臣要写的那个名字写不出来——臣只写这三个字。」\n"
    "天子伸出手指，在「知道了」上按了很久。\n"
    "「烧了。」他说，「连抄本一起。」\n"
    "殿前点起火盆。三桩案子的底稿一份一份送进去，"
    "纸上的字先亮起来，然后暗下去。\n"
    "——只是那天夜里，经卷阁的书案上多了一本日课簿，"
    "皮面写着景和五年，翻开那一格，字还在。"
), case=3, act=11)

_ending("ending3_byorder", "结局 · 奉旨", (
    "「凶手是内官监掌印曹淳。」你说，「他封的库，他写的档。」\n"
    "曹淳没有辩。他跪下来，把袖中的封泥模子放在阶上。\n"
    "「是咱家封的门。」他说，「内官监的规矩，先封后验。」\n"
    "「炭是谁添的？」\n"
    "「咱家不知道。」他答得极稳，「咱家只知道有一扇窗要糊。」\n"
    "案子结了。写进档的是：内官监掌印曹淳，擅封宫库，"
    "致掌籍女史谢云屏毙于炭气。\n"
    "半个月后，冯保升了掌印。\n"
    "经卷阁丙字库换了新锁，钥匙收在内官监值房，"
    "领钥匙簿上从此不再出现空的销号。\n"
    "「奉旨」两个字，写得下一切。"
), case=3, act=11)

_ending("ending3_sealed", "结局 · 留中", (
    "「凶手是内官监少监冯保。」你说，「他领的钥匙，他糊的窗。」\n"
    "你把领钥匙簿呈上去：前日寅时，钥匙领出去了，没有还。\n"
    "冯保跪在阶下，一句话没说。天子看完了案卷，搁下笔。\n"
    "「留中。」\n"
    "留中的意思是：不发，不抄，不议。\n"
    "案卷被收进内廷，从此没有人再见过它。\n"
    "你回到经卷阁时，丙字库的门开着：炭盆、气窗、封泥都收拾干净了。\n"
    "门上新换了一道封条，封泥是今年的年号，按得规规矩矩。\n"
    "那一枚翻模的旧印，从此谁也没有再提起。\n"
    "「名字是真的，纸是留中的。」"
), case=3, act=11)

_ending("ending3_wrong", "结局 · 替罪的人", (
    "「是陆文昭。」你说，「她抄的最后一页，她袖子里那张纸。」\n"
    "「是常安。」你说，「他搬的炭，他糊的窗。」\n"
    "审问那天，常安才十六岁。他一直在抖，说不清是听了谁的话去糊窗。\n"
    "陆文昭把袖子翻过来给你看：里面空了——那张纸她烧了，"
    "火盆里还剩一角没烧尽的边。\n"
    "结案文书上写的是：候补书吏陆文昭，因争掌籍之职，谋害其师。"
    "或者是：看阁小监常安，失职致人死亡。\n"
    "三日后，常安被送去做苦役。九日后，他在工地上死了，仵作说是摔的。\n"
    "经卷阁照着旧例换了封条。丙字库的钥匙，还是内官监的人拿。\n"
    "你写完最后一行，墨还没干。"
), case=3, act=11)

_ending("ending3_unspeakable", "结局 · 不可说", (
    "「臣要对质的是——」你抬起头，「御笔。」\n"
    "阶上没有人说话。曹淳闭上了眼，冯保把额头贴在地上。\n"
    "天子看着你，看了很久，然后笑了一下。\n"
    "「知道了。」他说，「你退下吧。」\n"
    "第二天，你被调去管义庄。第三年，你的名字从刑部的名册上消失了。\n"
    "有说你在任上病死的，有说你夜半出城往南去了的。\n"
    "景和五年那一页还在经卷阁的书案上，末尾三个字是今上的笔。\n"
    "它没有被人抄过，也没有被人烧过。\n"
    "它只是没有被人念出来。"
), case=3, act=11)

_ending("ending3_quiet", "结局 · 合上卷宗", (
    "你把笔搁下。\n"
    "案上摊着三桩案子：凤仪殿的茶，尚药局的附子，经卷阁的炭。"
    "三具尸首，三个说法。\n"
    "你写下的只有事实：经卷阁掌籍女史谢云屏，卒于丙字库，"
    "尸斑樱红，银针不黑；门从外锁，封泥为翻模；气窗有蜡。\n"
    "「臣只能写到这儿。」你说，「再往下，臣要写一个不能写的名字。」\n"
    "天子把那三页纸收起来，放进一个木匣。\n"
    "「合上吧。」他说。\n"
    "你合上卷宗，退出去。经卷阁的书案上，日课簿还摊在景和五年那一格——\n"
    "这一格，以后再没有人添过字。\n"
    "——三桩案子，一个不肯说的名字。"
), case=3, act=11)

# --------------------------------------------------------------------------
# 审讯话题
# --------------------------------------------------------------------------

TOPIC_SPECS: List[Tuple[str, str, str, str, Effect, bool, str]] = [
    # id, owner, label, response, effect, is_present, gate-hint
    # ---------------- 王德海 ----------------
    ("wdh_again", "WDH", "再问一遍 · 今夜你几时进的殿",
     "「亥时末。」他答得很快，「老奴敲门，敲了七八声，里头没动静，"
     "才唤人一起把门撞开。门是从里头栓着的，撞开的时候铁栓'啪'一声弹到地上。」\n"
     "你把这句记下来。撞开的门栓，那栓槽里该有新茬——可你白天看的那根栓，栓头是圆的。",
     E(clues=("contradiction",), trust=(("WDH", -5),), score=2), False, ""),

    ("wdh_tea", "WDH", "追问 · 那盏茶是谁送进去的",
     "他顿了一下：「是老奴。娘娘夜里要饮安神茶，都是老奴送。」\n"
     "「茶是什么茶？」\n"
     "「武夷。娘娘惯饮武夷。」他答完这句，像是想起了什么，喉咙动了一下。",
     E(clues=("almond_habit",), trust=(("WDH", -5),), score=2), False, ""),

    ("wdh_inside", "WDH", "逼问 · 你进过殿内",
     "「没有！」他抬起头，声音一下高了，随即又压下去，「老奴一步没进去过，"
     "只在门外看了一眼——娘娘面色如生，还饮着茶，那茶盏就搁在手边。」\n"
     "「手边的茶盏，是碎的。」你说。\n"
     "他的话卡在喉咙里。",
     E(clues=("killer_knowledge",), flags=("wdh_cracked",), trust=(("WDH", -10),), score=4),
     False, "需先在正殿发现「残茶苦杏仁味」与「殿门由内反锁」"),

    ("wdh_ledger", "WDH", "出示 · 尚药局领用簿上的七次取用",
     "你把领用簿摊在他面前：「七次苦杏仁油，都记的你的名。第三笔起，"
     "就不是你写的了——你自己看。」\n"
     "他盯着那几行字，盯了很久，忽然笑了一下：「大人好眼力。"
     "老奴的字是那样写的吗？那都是底下人代笔，帐上不清不楚的地方多了。」\n"
     "「帐上不清不楚的地方，」你说，「包括采薇那一笔么。」\n"
     "他这回没有立刻答。他的手指在膝上收紧了。",
     E(clues=("ledger_gap",), flags=("wdh_shaken",), trust=(("WDH", -8),), score=4),
     True, "需先取得「领用簿上的空档」"),

    ("wdh_caiwei", "WDH", "摊牌 · 采薇是被你办的",
     "「十二年前，掖庭宫人采薇，罪名是窃，验伤单和供词出自同一个人的手。"
     "她是个哑的，可她『供认不讳』。」你把卷宗推过去，「王总管，你写完了她，"
     "第二年就进了凤仪殿。你补的是哪一笔亏空？」\n"
     "王德海的手开始抖。他忽然伏下去，额头抵着地，很久没有起来。\n"
     "「她……她查了三个月。」他终于开口，声音是从地缝里出来的，"
     "「贤妃娘娘要翻这件事。她要翻，老奴这条命就是从那时候捡回来的，"
     "十二年了，老奴天天想着这一天。」\n"
     "他抬起头，眼睛红着：「茶是老奴送的。」",
     E(text="王德海交代了十二年前的旧账，也认下了那盏茶。",
       flags=("wdh_confessed",), trust=(("WDH", 10),), score=8),
     False, "需持有「掖庭旧档 · 采薇案」与「领用簿上的空档」，且王德海已被问破一次"),

    ("wdh_why", "WDH", "问他 · 为什么是她",
     "「娘娘待老奴不薄。」他说，「可是她查到了采薇的名字。"
     "她把那张纸写给谁看？写给陛下。写给陛下，老奴就活不到开春。」\n"
     "「所以你连她的死法都布好了。」\n"
     "「朱砂是给大人看的。」他小声说，「大人验尸的，见了红粉，总要往毒上想。」",
     E(clues=("cinnabar_note",), score=3),
     False, "需先让王德海认罪"),

    # ---------------- 小顺子 ----------------
    ("xse_tea", "XSE", "轻声问 · 今夜的茶是你送的吗",
     "「是……是老奴……不，是小的。」他咽了口唾沫，"
     "「亥时初，总管让小的把安神茶送进殿里。小的进去的时候，门没上栓，"
     "娘娘坐在案后，问了小的一句话。」\n"
     "「她问你什么？」\n"
     "「她问『你来做什么』。」小顺子说，「小的说送茶，她就让小的放下了。"
     "她的声音……不太对，像隔着一层东西。」",
     E(clues=("xse_testimony",), trust=(("XSE", 8),), score=3),
     False, ""),

    ("xse_track", "XSE", "问他 · 你在殿后做什么",
     "小顺子的脸一下白了：「小的……小的听见窗棂那边有动静，"
     "绕到殿后看了一眼，雪泥里滑了一跤，鞋是小的自己踩的。」\n"
     "「看到了什么？」\n"
     "「没看清。」他很快地说，「就一个影子，穿着……穿着长的。」\n"
     "你看了一眼他的鞋。他在雪泥里留下的印，比窗下那半只印小两寸。",
     E(clues=("xse_footprint",), trust=(("XSE", 5),), score=2),
     False, "需先取得「窗棂刮痕」"),

    ("xse_roll", "XSE", "问 · 今夜戌时谁被遣退了",
     "「九个人。」他掰着指头数，「扫洒的、看炉的、值夜的，还有两个尚衣局的。"
     "总管说娘娘要静心抄经，都遣了。就他一个留在外殿值夜。」\n"
     "「你呢？」\n"
     "「小的在御膳房候着。」他小声说，「总管本来也让小的走，"
     "后来又叫人把小的喊回来送茶。」",
     E(clues=("dismissal_roll",), trust=(("XSE", 5),), score=3),
     False, ""),

    ("xse_fear", "XSE", "问他 · 你在怕谁",
     "他跪着往后缩了半寸：「大人，小的不敢说。」\n"
     "「你说了，我记在簿子上。」\n"
     "「……小的怕总管。」他说得很快，「今夜他把小的喊回来的时候，"
     "手上有股味道，甜的，像苦杏仁。他说那是药。」",
     E(clues=("almond_oil",), flags=("xse_told",), trust=(("XSE", 10),), score=5),
     False, "需先取得王德海的「供述矛盾」，或小顺子已愿意开口（好感 ≥ 45）"),

    ("xse_caiwei", "XSE", "把采薇的名字念给他听",
     "「采薇？」小顺子愣了愣，「小的进宫晚，没听过这个名字。"
     "不过掖庭的老人说过，有个宫人埋在西角门外的荒地里，是个哑的，"
     "牌位上没有字。」\n"
     "他低头想了想，又补了一句：「西角门的封土，是总管每年差人去添的。」",
     E(clues=("caiwei_death",), score=3),
     False, "需先得知「采薇」这条线"),

    # ---------------- 皇后 ----------------
    ("hh_visit", "HH", "直问 · 戌时三刻您在凤仪殿",
     "她没有否认：「本宫来过。」\n"
     "「本宫劝她把东西交出来。」她说得很平，「她手里有一样东西，"
     "是十二年前从太子宫里流出去的。本宫要她交出来，她不肯。」\n"
     "「什么东西？」\n"
     "「与你无关。」她终于转了一下那枚玉扳指，「本宫走的时候，她还活着，"
     "端着茶，说她明日就去见陛下。本宫信了。」",
     E(clues=("empress_last_word",), trust=(("HH", 5),), score=4),
     False, "需先取得现场铁证（银针验毒与门窗痕迹），否则皇后根本不会承认她来过"),

    ("hh_motive", "HH", "问她 · 太子之死与您有什么关系",
     "灯影里的人停了很久。\n"
     "「景和十三年，太子暴卒。」她说，「太医说是急症。本宫的儿子不是急症死的，"
     "本宫知道。本宫查了三年，只查到一样东西——一个匣子，"
     "被人从太子宫里抬出去，抬进了凤仪殿。」\n"
     "「贤妃娘娘知道匣子里是什么？」\n"
     "「她知道。」皇后说，「她拿它换了六妃的位置。所以本宫恨她。"
     "本宫恨了她五年，恨得有理有据。」\n"
     "她终于看向你：「可她死的那一夜，本宫只是想要那个匣子。」",
     E(clues=("empress_motive",), flags=("hh_opened",), trust=(("HH", 10),), score=6),
     False, "皇后好感需 ≥ 55（对质她最痛的地方，好感不够她会中止问询）"),

    ("hh_ring", "HH", "问 · 您手上那枚玉扳指",
     "她把左手往袖子里收了收，随即又停住，摊开。\n"
     "「先帝赐给太子的。」她说，「太子死的时候，这枚扳指在他手里。"
     "本宫从死人手上取下来的东西，本宫戴了四年。」\n"
     "「贤妃娘娘知道您戴着它。」\n"
     "「她知道。」皇后说，「所以她才敢让本宫去凤仪殿。」",
     E(clues=("empress_ring",), trust=(("HH", 8),), score=5),
     False, "需先问出「皇后的把柄」，且好感 ≥ 55"),

    ("hh_ask", "HH", "问她 · 本官该报谁的名字",
     "「你该报那个把茶端进去的人。」皇后说。\n"
     "你抬头。\n"
     "「本宫的孩子死在四年前，本宫查了三年，什么也没查到；"
     "王德海在宫里四十七年，从管事做到总管，手里进出过多少东西，没人算得清。」\n"
     "她顿了一下：「你要证据，本宫没有。本宫只有一件事想告诉你——"
     "贤妃死的时候，手上没有那枚匣子的钥匙。钥匙在她枕头底下。」\n"
     "你想起那张没写完的笺纸。",
     E(flags=("hh_hint",), trust=(("HH", 10),), score=5),
     False, "需先问出「皇后的把柄」"),

    # ---------------- 贵妃 ----------------
    ("gf_soup", "GF", "问 · 您送的那碗汤",
     "「黑豆鲫鱼汤。」她说得理直气壮，「本宫端到殿门口，她连门都没让本宫进，"
     "隔着门说'放着吧'。本宫把汤搁在阶上就走了。」\n"
     "「汤呢？」\n"
     "「不知道。」她顿了顿，气短了半截，「第二天早上本宫叫人去取，碗没了。"
     "厨下说收去洗了。」",
     E(clues=("consort_soup",), trust=(("GF", 5),), score=2),
     False, ""),

    ("gf_poison", "GF", "问她 · 您手里的安胎药",
     "贵妃的脸沉了：「谁跟你说的。」\n"
     "「大人是仵作，不该管这个。」\n"
     "「本官管的是死因。」\n"
     "她咬着牙坐了一会儿，最后把手炉撂下：「本宫换过她的药，换成温补的，"
     "不是毒。她那年怀的那个孩子，本来也留不住——本宫是不想让她把账算到本宫头上。」\n"
     "「这话您该对陛下说。」\n"
     "「本宫说了，陛下会信吗？」她笑了一下，「所以你查你的案子，别查本宫。"
     "本宫今夜真没进那道门。」",
     E(clues=("consort_leverage",), trust=(("GF", -5),), score=3),
     False, "需先取得「贵妃的汤」这条口供"),

    ("gf_who", "GF", "问她 · 今夜还有谁在凤仪殿",
     "「本宫在殿外站了一刻。」她说，「先是皇后进去了，待了半刻就走了，"
     "走的时候脚步很急。再后来王德海端着托盘进去。」\n"
     "「他进去多久？」\n"
     "「……挺久的。」贵妃皱眉，「本宫不耐烦等，就先回了。"
     "灯还亮着，本宫还以为她真在抄经。」",
     E(flags=("gf_timeline",), trust=(("GF", 5),), score=4),
     False, "需先问过「您送的那碗汤」，且已知「戌时三刻皇后私访」"),

    # ---------------- 皇帝 ----------------
    ("hd_ask", "HD", "问 · 陛下想听什么",
     "他背对着你站了一会儿。\n"
     "「朕想听一个名字。」他说，「一个能写在结案文书上的名字，"
     "一个能让这件事到此为止的名字。」\n"
     "「若那个名字不好写呢。」\n"
     "「那就写在朕这儿。」他终于转过身，「沈墨白，朕不是在跟你做买卖。"
     "三日之后，无论你查不查得出，这件事都要有个名字。」",
     E(clues=("emperor_scold",), score=2),
     False, ""),

    ("hd_grief", "HD", "问 · 娘娘走的时候疼不疼",
     "他沉默了很久才开口，声音比刚才低。\n"
     "「她十七岁进宫，是朕亲自挑的，从掖庭底下挑上来的。」他说，"
     "「第一个冬天她手上有冻疮，还跟朕说，她不冷。」\n"
     "「她这两年不跟朕说话了。朕以为她是不想，后来才知道她是在算账。」\n"
     "他停了一下：「她死的时候，疼么。」\n"
     "「慢性之毒，先睡过去，再走。」你说，「不疼。」\n"
     "「好。」他说。就这一个字。",
     E(clues=("emperor_care",), flags=("hd_softened",), trust=(("HD", 10),), score=4),
     False, "需先取得「口角黑血」，说明死亡并非即刻"),

    # ---------------- 案② · 掌局郑守拙 ----------------
    ("zzz_first", "ZZZ", "问 · 高延年几时巡的库",
     "「丑时初。」郑守拙答得很快，「簿子上有他的押，咱家是看簿子才知道的。」\n"
     "「您看的是哪一本簿子？」\n"
     "他愣了一下：「值夜簿。就压在他案上那一本。」\n"
     "案上那一本你已经翻过了：那一行的字是描的。他答得太快——"
     "快得像早就想过这个问题。",
     E(flags=("zzz_said_night",), trust=(("ZZZ", -5),), score=3),
     False, ""),

    ("zzz_ledger", "ZZZ", "出示 · 私账上的四个字",
     "你把那本私账推过去。每笔只写四个字：「药出有主」。\n"
     "郑守拙的手停在账面上，没有翻。\n"
     "「这不是咱家的。」他说。\n"
     "「四个字的收笔，」你说，「和领用簿上「王德海」那三个字一样。」\n"
     "他慢慢把手收回去，放进袖子里：「仵作，咱家只是个掌局的。」",
     E(flags=("zzz_shaken",), trust=(("ZZZ", -8),), score=4),
     False, "需先取得「掌局的私账」"),

    ("zzz_caiwei", "ZZZ", "摊牌 · 十二年前那支笔",
     "你把两张纸并排铺开：一张是十二年前采薇案的口供，一张是尚药局的领用簿。\n"
     "「同一个人的字。」你说，「十二年，你替人写了多少张？」\n"
     "郑守拙看了很久。然后他伸出手，指腹抹了一下案上的封泥——"
     "药库旧档的封泥，印记还在。\n"
     "「旧档里有景和五年的东西。」他说，「大人要看，就自己去看。」",
     E(clues=("jinghe_seal",), flags=("zzz_named_jinghe",), score=5),
     False, "需先取得「十二年前的那支笔」"),

    ("zzz_press", "ZZZ", "逼问 · 领用簿上的字是谁写的",
     "「第七次取用，签的是王德海。」你说，「字是你的。」\n"
     "「王德海是凤仪殿的人。」\n"
     "「你替他写，因为他管不着尚药局。」你把私账拍在案上，「你替谁写，"
     "谁就替你兜着。十二年前你替人写了一份供词，十二年后你替人取了一味药。"
     "写字的人从来不知道药是给谁喝的——是不是？」\n"
     "郑守拙站起来，又坐下，膝盖碰在案沿上。\n"
     "「他给了咱家一块糖。」他说，声音很小，「十二年前咱家十二岁，"
     "教写字的人说，写完了有糖吃。」\n"
     "「谁？」\n"
     "「……咱家只认得那支笔。」他说，「笔杆上刻着一片叶子。」",
     E(clues=("zzz_confession",), flags=("zzz_confessed",), score=8),
     False, "需先问破他一次，且握有「两句供词对不上」"),

    # ---------------- 案② · 司药柳青 ----------------
    ("lq_hands", "LQ", "问 · 你手上的黄渍",
     "她把手往袖子里收了一下，又停住，摊开给你看。\n"
     "「附子粉。染上就洗不掉。」她说，「这个月我称了四十七两六钱。」\n"
     "「谁让你称的？」\n"
     "「高典药。」她想了想，「不，是掌局传的话——每日三钱，连称了半个月。」\n"
     "半个月。你心里算了一下日子：正好从贤妃开始查账那天起。",
     E(clues=("lq_stain",), trust=(("LQ", 5),), score=3),
     False, ""),

    ("lq_night", "LQ", "问她 · 戌时你在哪儿",
     "「在配药房。」她说，「掌局让我把附子格的药筛一遍，说受了潮。」\n"
     "「筛出来的药呢？」\n"
     "「掌局收走了。」她低下头，「他说要送去焙一遍。」\n"
     "送去焙一遍的药，最后进了高延年的汤里。",
     E(flags=("lq_helped",), trust=(("LQ", 5),), score=3),
     False, "需先看见「柳青指腹的药渍」"),

    ("lq_jj", "LQ", "问她 · 蒋九今夜找过你吗",
     "「找过。」她说，「戌时前后，他拿着抄本来问我，"
     "问第七次取用的附子是谁签的名。我说我不知道。」\n"
     "「你怎么答他的？」\n"
     "「我说——」她抬眼看了看门口，「我说掌局今夜一直在值房，你去找他。"
     "他后来去了哪儿，我不知道。」\n"
     "可你问郑守拙的时候，他说的是：蒋九整夜都在值房抄账。\n"
     "两句供词，对不上。",
     E(clues=("contradiction2",), score=4),
     False, "需先验过「蒋九的尸格」"),

    # ---------------- 案② · 值夜小监贺小五 ----------------
    ("hxw_night", "HXW", "问他 · 你巡到药库是几时",
     "「戌时末。」他攥着灯罩，「我巡到药库门口，门是从外面锁着的。"
     "我拿钥匙试了一下，没开——链子在外面扣着。」\n"
     "「那时候屋里有动静吗？」\n"
     "「没有。」他说，「一点声都没有。我以为高典药早睡了。」\n"
     "戌时末。那时候高延年已经出不了声了。",
     E(clues=("hxw_patrol",), trust=(("HXW", 5),), score=3),
     False, ""),

    ("hxw_lock", "HXW", "问他 · 锁门的时候闩是里栓还是外锁",
     "「外锁。」他说得很肯定，「链子在我手里，闩在里头，我够不着。」\n"
     "「那你第二次开库是什么时候？」\n"
     "「丑时。」他说，「掌局来叫我，说高典药巡库巡得太久了，让我去看看。"
     "门还是外锁的，我开的锁；闩是里栓的——我推门的时候，闩自己掉下来了。」",
     E(flags=("hxw_trusts",), trust=(("HXW", 5),), score=3),
     False, "需先看清「门闩上的青丝线」"),

    # 标签必须全局唯一：玩家问过的话题记在 seen_choices 里，键是「::标签」，
    # 所以两个人物用同一句话就会被当成「已经问过了」而收起来（案① 的小顺子
    # 已经占了「问他 · 你在怕谁」）。
    ("hxw_fear", "HXW", "问他 · 这几天你躲着谁",
     "他先看门口，又看灯，才小声说：「内官监的人今夜来过值房。」\n"
     "「什么时候？」\n"
     "「蒋九死之前。」他说，「那位少监站了一会儿，说了一句："
     "『今夜的事，写成暴病就是了。』说完就走，灯他也没让点。」\n"
     "「你怕他？」\n"
     "「我怕他记住我的脸。」",
     E(clues=("fb_word",), score=5),
     False, "需先让贺小五信你（好感 ≥ 40）"),

    # ---------------- 案② · 内官监少监冯保 ----------------
    ("fb_order", "FB", "问 · 您是奉谁的旨来的",
     "「内官监的差事，不问旨。」他说，「问的是：这一夜的账，"
     "该往哪本簿子上记。」\n"
     "「哪一本？」\n"
     "「大人写哪一本，咱家就记哪一本。」他看着你，「只要那一本，"
     "看上去是干干净净的。」",
     E(trust=(("FB", 5),), score=2),
     False, ""),

    ("fb_press", "FB", "把七次取用与掌局的供述摆给他看",
     "你把两页纸放在他面前：一张是七次取用，一张是郑守拙的供述。\n"
     "冯保看完，把两张并齐，边缘对得很准。\n"
     "「沈仵作，」他说，「你知道这一页纸送上去，要动多少人吗？」\n"
     "「我不知道。」你说，「我只知道上面有两个人的死法。」\n"
     "他沉默了一会儿：「内官监的意思是——写成暴病。」",
     E(clues=("fb_word",), flags=("fb_warned",), score=5),
     False, "需先握有「第七次取用」与「掌局的供述」"),

    ("fb_meaning", "FB", "问 · 「写成暴病」是什么意思",
     "「意思就是：」他说，「这一页纸上只写得出两个名字。"
     "一个是死人的，一个是查案的。」\n"
     "「第三个名字写不上去？」\n"
     "「写上去的人，」他终于看了你一眼，「第二年会去管义庄。」",
     E(flags=("fb_warned",), trust=(("FB", -5),), score=3),
     False, "需先听到「内官监的口风」"),

    # ---------------- 案③ · 看阁小监常安 ----------------
    ("ca_night", "CA", "问他 · 昨夜你在哪儿值夜",
     "「我在阁里值夜。」他说，「姑姑让我守着前厅那盏灯，说灯不能灭。」\n"
     "「你听见什么了？」\n"
     "「有人上阁顶。」他咽了一下，「从东边的梯子上去，来回两趟。"
     "脚步很轻，可是瓦响。」\n"
     "东边的梯子。丙字库在西头——那个人上去的时候，不必经过她。",
     E(trust=(("CA", 5),), score=3),
     False, ""),

    ("ca_words", "CA", "问他 · 炭是谁让你添的",
     "「后半夜有人敲窗。」他说，「他让我把两筐炭搬到丙字库，"
     "说姑姑夜里冷。还给我一块蜡，让我把气窗糊上。」\n"
     "「你为什么要糊窗？」\n"
     "「他说糊上才暖。」常安的声音低下去，「我不知道会……」",
     E(clues=("ca_words",), dossiers=("10-DL-CA",), trust=(("CA", 5),), score=4),
     False, ""),

    ("ca_top", "CA", "问他 · 你看见那个人的靴子了吗",
     "常安咬着嘴唇，好一会儿才点头：「他下来的时候我在檐下，"
     "袖口沾着灰。他戴着帽子，我没敢抬头看脸。」\n"
     "「靴子呢？」\n"
     "「靴子我认得。」他说，「内官监的靴子，靴底是硬的，踩在砖上有声。"
     "我在值房门口听过一万回。」",
     E(clues=("ca_saw_fb",), trust=(("CA", 5),), score=5),
     False, "需先让常安信你（好感 ≥ 40：先问值夜、再问添炭）"),

    # ---------------- 案③ · 候补书吏陆文昭 ----------------
    ("lws_copy", "LWS", "问她 · 师父昨夜让你抄什么",
     "「景和五年的名录。」她说，「二十九行的那一本，抄三遍。"
     "第一遍她对着看，第二遍让我念出声，第三遍她说：烧了。」\n"
     "「你念的时候，她说什么了？」\n"
     "「我念到第十七行，她让我停。」陆文昭说，「她说那一行不要念。」",
     E(clues=("lws_copy",), dossiers=("10-DL-LWS",), trust=(("LWS", 5),), score=4),
     False, ""),

    ("lws_tear", "LWS", "问她 · 少的那一行是哪一行",
     "「名录第十七行，采薇。」她说，「师父说那一行上有人。我问她是谁，"
     "她说不必知道，抄完就烧。」\n"
     "「那你为什么记得是第十七行？」\n"
     "「因为第一遍抄的时候，师父在那一行上停了很久，笔尖都干了。」",
     E(clues=("lws_tear",), trust=(("LWS", 5),), score=4),
     False, "需先问过「师父昨夜让你抄什么」"),

    ("lws_three", "LWS", "问她 · 三遍都烧了吗",
     "陆文昭没有立刻答。她把手伸进袖子里，掏出两张纸。\n"
     "「第三遍我没烧。」她说，「我想，万一有人来问。」\n"
     "抄本上二十九行都在，只有第十七行空着。另一张更旧，边上缺了一角：\n"
     "「师父让我把它夹在抄本里带出去。」\n"
     "那是原页——账目、数量、年份。末尾三个朱字笔画很轻，像是随手一勾。",
     E(dossiers=("10-JG-ORIG",), trust=(("LWS", 5),), score=5),
     False, "需先问出「抄本上少的那一行」"),

    # ---------------- 案③ · 内官监掌印曹淳 ----------------
    ("cc_order", "CC", "问 · 封存是你下的令",
     "你把半页烧剩的令纸放在他面前，纸角那半个印朝上。\n"
     "「内官监的规矩：宫里死了人，先封后验。」曹淳说，"
     "「封条、封泥、封门，都是咱家的事。」\n"
     "「烧了的东西，也是规矩？」\n"
     "「烧了的东西，不算档。」\n"
     "「炭气这一句，也是规矩？」\n"
     "「仵作。」他终于抬头看你，「一句能写进档的话，比十句真话省事。」",
     E(clues=("cc_order",), dossiers=("10-DL-CC",), trust=(("CC", 5),), score=4),
     False, ""),

    ("cc_hand", "CC", "问 · 领钥匙簿上的销号为什么是空的",
     "你把簿子摊在他面前：「前日寅时，钥匙领出去了，没有还。」\n"
     "曹淳看了很久，答得很慢：「在冯保身上。」\n"
     "「你让他去开丙字库的门？」\n"
     "「咱家让他去封丙字库的门。」他说，「封门要先开门——这个理，仵作懂。」",
     E(clues=("cc_hand",), trust=(("CC", 5),), score=5),
     False, "需先看见「领钥匙簿」上那一行"),

    ("cc_last", "CC", "问 · 那一页上还有谁的字",
     "阶上安静了一息。曹淳把封泥翻了个面，印文朝下。\n"
     "「有字。」他说，「朱的。」\n"
     "「谁的字？」\n"
     "「仵作，」他声音很平，「你在宫里当差三年，见过今上的朱批没有？」\n"
     "见过。结案文书上一句「知道了」，就是这个写法。",
     E(clues=("emperor_ink", "three_line3"), trust=(("CC", -5),), score=5),
     False, "需先让曹淳肯答（好感 ≥ 40：先问封存、再问钥匙）"),

    # ---------------- 案③ · 内官监少监冯保 ----------------
    ("fb3_key", "FB", "问 · 前日寅时你在哪儿",
     "「在尚药局。」他说，「仵作见过的。」\n"
     "「领钥匙簿上有你的押。」你把簿子推过去，「前日寅时，"
     "经卷阁丙字库的钥匙，是你领的。」\n"
     "他低头看那一行，看了一会儿：「手是咱家的手。」",
     E(clues=("fb_key3",), dossiers=("10-DL-FB",), trust=(("FB", 5),), score=4),
     False, ""),

    ("fb3_clean", "FB", "把封泥与气窗上的蜡摆在他面前",
     "你把两样东西并排放在阶上：翻模的封泥，气窗上那块黄蜡。\n"
     "「同一块蜡。」你说，「切口、颜色、气味都对得上。"
     "封门的人和封窗的人，是同一个。」\n"
     "冯保看了很久。\n"
     "「上头要的是干净。」他说，「干净的意思，仵作知道吗？」\n"
     "「没有人追问。」\n"
     "「没有人追问。」他重复了一遍，声音里第一次有了点人味。",
     E(clues=("fb_clean", "wax_match"), flags=("fb_cracked3",),
       trust=(("FB", -5),), score=5),
     False, "需先握有「翻模的封泥」与「气窗上的油纸与黄蜡」"),
]


def build_topics() -> Dict[str, Topic]:
    topics: Dict[str, Topic] = {}
    for tid, owner, label, response, effect, present, _hint in TOPIC_SPECS:
        # 回话**只**放在 `Topic.response` 上，不要同时挂到 `effect.text`：
        # `GameEngine.choose()` 已经按 `response` 写了一条旁白，`apply_effect()`
        # 又会把 `effect.text` 写一条，同一段回话会在卷宗里连着出现两遍
        # （曾实测 44/44 条话题全部重复）。两端对称，改这里一处即可。
        eff = Effect(
            add_clues=effect.add_clues,
            add_items=effect.add_items,
            add_dossiers=effect.add_dossiers,
            trust=effect.trust,
            flags=effect.flags,
            time=effect.time,
            scene=effect.scene,
            score=effect.score,
            hurt=effect.hurt,
        )
        topics[tid] = Topic(id=tid, owner=owner, label=label, response=response,
                            effect=eff, present=present)
    return topics


# 话题解锁条件（剧本知道剧情，引擎负责判定）
TOPIC_GATES: Dict[str, Tuple[object, str]] = {
    "wdh_again": (always, ""),
    "wdh_tea": (always, ""),
    "wdh_inside": (
        all_of(has_clue("tea_almond"), has_clue("doors_bolted")),
        "需先在正殿发现「残茶苦杏仁味」，并看清「殿门由内反锁」的破绽",
    ),
    "wdh_ledger": (
        has_clue("ledger_gap"),
        "需先取得「领用簿上的空档」（尚药局 · 核对取用记录与签押）",
    ),
    "wdh_caiwei": (
        all_of(has_clue("old_record"), has_clue("ledger_gap"),
               has_flag("wdh_cracked")),
        "需持有「掖庭旧档 · 采薇案」与「领用簿上的空档」，并先问破他一次",
    ),
    "wdh_why": (
        has_flag("wdh_confessed"),
        "需先让王德海认罪",
    ),
    "xse_tea": (always, ""),
    "xse_track": (
        has_clue("window_scratch"),
        "需先取得「窗棂刮痕」",
    ),
    "xse_roll": (always, ""),
    "xse_fear": (
        # 小顺子初始好感 35；能加好感的只有本话题（xse_testimony +8、xse_footprint +5），
        # 门槛若定 55 就永远够不着 —— 定 45，即「先问过两条话、他觉得你靠得住」。
        any_of(has_clue("contradiction"), trust_at_least("XSE", 45)),
        "需先问出王德海的「供述矛盾」，或小顺子已经信你（好感 ≥ 45）",
    ),
    "xse_caiwei": (
        any_of(has_clue("pillow_letter"), has_flag("knows_caiwei")),
        "需先得知「采薇」这条线（枕下密信或掖庭旧档）",
    ),
    "hh_visit": (
        all_of(has_clue("si_needle"), has_clue("window_scratch")),
        "皇后不会空口承认：需先握有银针验毒与门窗痕迹两项铁证",
    ),
    "hh_motive": (
        # 注意：初始好感 30，仅靠本次问询最多 +15（visit +5、ring/ask 需要先过本关），
        # 因此这里不能拿「≥55」当门槛，否则永远问不出来 —— 门槛改成「已经问出她最在意的时辰」。
        has_clue("empress_last_word"),
        "需先问出「戌时三刻您在凤仪殿」，她才会谈太子的事",
    ),
    "hh_ring": (
        all_of(has_clue("empress_motive"), trust_at_least("HH", 50)),
        "需先问出「皇后的把柄」，且她的好感 ≥ 50（再多问几句她肯听的）",
    ),
    "hh_ask": (
        has_clue("empress_motive"),
        "需先问出「皇后的把柄」",
    ),
    "gf_soup": (always, ""),
    "gf_poison": (
        has_clue("consort_soup"),
        "需先取得「贵妃的汤」这条口供",
    ),
    "gf_who": (
        # 她是被人捧着长大的，只有顺着毛问才肯说 —— 所以门槛里要有「问过那碗汤」
        # 这件事本身，而不只是「信任够高」。
        # 信任下限取 20 而不是 25：贵妃信任的全部来源只有 gf_soup 的 +5
        # （gf_poison 是 -5，初始 20），按 25 写就是零余量 —— 先问了安胎药的人
        # 会永久锁死这条线，而界面上看不出原因。
        all_of(trust_at_least("GF", 20),
               has_clue("consort_soup"),
               has_clue("empress_last_word")),
        "需先问过「您送的那碗汤」，且已知「戌时三刻皇后私访」",
    ),
    "hd_ask": (always, ""),
    "hd_grief": (
        has_clue("black_blood"),
        "需先取得「口角黑血」，才有话头谈她走得疼不疼",
    ),
    # ---------------- 案② 的问询门禁 ----------------
    "zzz_first": (always, ""),
    "zzz_ledger": (
        has_clue("zzz_private"),
        "需先取得「掌局的私账」（药库旧档 / 值房抽屉）",
    ),
    "zzz_caiwei": (
        has_clue("caiwei_hand"),
        "需先比对出「十二年前的那支笔」",
    ),
    "zzz_press": (
        # 郑守拙初始 35、上限 55；本条 -8、上一条 -5，好感只会往下走，
        # 所以门槛不能挂在好心上，只能挂「你手上有没有那两样东西」。
        all_of(has_flag("zzz_shaken"), has_clue("contradiction2")),
        "需先问破他一次（私账），且握有「两句供词对不上」",
    ),
    "lq_hands": (always, ""),
    "lq_night": (
        has_clue("lq_stain"),
        "需先看见「柳青指腹的药渍」",
    ),
    "lq_jj": (
        has_clue("jj_corpse"),
        "需先验过「蒋九的尸格」",
    ),
    "hxw_night": (always, ""),
    "hxw_lock": (
        has_clue("bolt_thread"),
        "需先看清「门闩上的青丝线」",
    ),
    "hxw_fear": (
        # 贺小五初始 30、上限 50：本话题是唯一的大门槛，
        # 两条前置各 +5（hxw_night / hxw_lock），40 正好够得着。
        trust_at_least("HXW", 40),
        "需先让贺小五信你（好感 ≥ 40：先问夜巡、再对门闩）",
    ),
    "fb_order": (always, ""),
    "fb_press": (
        all_of(has_clue("ledger_seventh"), has_clue("zzz_confession")),
        "需先握有「第七次取用」与「掌局的供述」",
    ),
    "fb_meaning": (
        has_clue("fb_word"),
        "需先听到「内官监的口风」",
    ),

    # ---------------- 案③ ----------------
    "ca_night": (always, ""),
    "ca_words": (always, ""),
    "ca_top": (
        trust_at_least("CA", 40),
        "需先让常安信你（好感 ≥ 40：先问值夜、再问添炭）",
    ),
    "lws_copy": (always, ""),
    "lws_tear": (
        has_clue("lws_copy"),
        "需先问过「师父昨夜让你抄什么」",
    ),
    "lws_three": (
        has_clue("lws_tear"),
        "需先问出「抄本上少的那一行」",
    ),
    "cc_order": (always, ""),
    "cc_hand": (
        has_clue("key_ledger3"),
        "需先看见「领钥匙簿」上那一行",
    ),
    "cc_last": (
        trust_at_least("CC", 40),
        "需先让曹淳肯答（好感 ≥ 40：先问封存、再问钥匙）",
    ),
    "fb3_key": (always, ""),
    "fb3_clean": (
        all_of(has_clue("seal_recast"), has_clue("vent_wax")),
        "需先握有「翻模的封泥」与「气窗上的油纸与黄蜡」",
    ),
}

# --------------------------------------------------------------------------
# 结局判定
# --------------------------------------------------------------------------

ENDINGS: List[EndingRule] = []


def _rule(eid: str, title: str, subtitle: str, body: str, rule, rank: str = "",
          case: int = 1) -> EndingRule:
    r = EndingRule(id=eid, title=title, subtitle=subtitle, body=body, rule=rule,
                   rank=rank, case=case)
    ENDINGS.append(r)
    return r


_END = {s.id: s for s in ENDING_SCENES.values()}


def _mk(eid: str, title: str, subtitle: str, rule, rank: str,
        case: int = 1) -> EndingRule:
    scene = _END[eid]
    return _rule(eid, title, subtitle, scene.body, rule, rank, case=case)


_mk("ending_treason", "结局 · 天子无案", "你指认了天子",
    accused_is("HD"), "不可说")
_mk("ending_restitution", "结局 · 铁证如山", "真凶伏法，且无人能将此案按下",
    all_of(accused_is("WDH"), core_count_at_least(10),
           has_clue("empress_motive"), has_clue("empress_ring"),
           has_flag("wdh_confessed")),
    "上上")
_mk("ending_standard", "结局 · 尘埃落定", "真凶伏法，但水下还有东西",
    all_of(accused_is("WDH"), core_count_at_least(6),
           has_clue("killer_knowledge")),
    "上")
_mk("ending_dangerous", "结局 · 玉扳指", "你说出了更危险的那半截真相",
    accused_is("HH"), "存疑")
_mk("ending_false", "结局 · 替罪的人", "你报错了名字",
    accused_in("GF"), "下下")
# 「辞官」必须排在下一条兜底之前：辞官那条路不指认任何人，`accused` 一直是空的，
# 只要兜底规则（`accused_is("")`）排在它前面，辞官就永远被判成「查不出来」。
_mk("ending_quiet", "结局 · 辞官", "你烧了簿子",
    has_flag("resign"), "退")
# 「按下」是「王德海被指认了，但你手上没有能钉死他的东西」这一格的收口，
# 必须排在 standard 之后兜住。
#
# 判据从「core_count() < 6」改成「没有 killer_knowledge」：第一幕的门槛
# 本身就送来 10 条以上核心，条数门槛在这条路上永远不成立，「按下」曾是
# 一条走不到的结局。三条判据现在是一条台阶——
#   指认王德海但拿不出只有凶手才知道的事 → 按下（案子被按下去）
#   拿得出，核心 ≥ 6                        → 尘埃落定
#   再加上动机、玉扳指、口供                → 铁证如山
_mk("ending_pressured", "结局 · 按下", "真凶未受审，案子被按了下去",
    all_of(accused_is("WDH"), has_flag("accused"),
           clue_absent("killer_knowledge")),
    "中")
# 案① 的最后一条必须是兜底：`pick_ending()` 全不命中时虽然会退回
# `ending_bystander`，但那是引擎里的常数，不是这里的顺序；兜底排在中途，
# 后面那条「按下」就永远收不到自己的那一格。
_mk("ending_bystander", "结局 · 查不出来", "你没有写下任何名字",
    any_of(has_flag("gave_up"), accused_is("")), "中下")

# ---------------- 案② 的六条收尾（判定顺序即优先级） ----------------
# 案① 的规则都带 case=1，案② 带 case=2；pick_ending() 只在本案的规则里挑，
# 所以两案的结局不会互相抢（案② 里 accused_is("WDH") 永远不成立）。
_mk("ending2_lightout", "结局 · 灯灭", "你说出了最该说的那句话，然后就没有然后了",
    accused_is("FB"), "不可说", case=2)
_mk("ending2_truth", "结局 · 两案同钉", "药是同一双手下的，名字写在同一页纸上",
    all_of(accused_is("ZZZ"), core_count_at_least(12),
           has_clue("zzz_confession"), has_clue("jinghe_leaf")),
    "上上", case=2)
# 同样是「一条台阶」（与案① 的「按下 → 尘埃落定 → 铁证如山」同形）：
#   指认郑守拙，却拿不出他的口供            → 又是暴病（纸被人改过）
#   拿得到口供，手上却没有景和五年那页残账   → 一页之差（案子结了，线头断了）
#   口供与残账都在                          → 两案同钉
# 少了中间这一级时，「口供到手但残页缺失」会掉进兜底 ending2_quiet
# （「只写两个名字」），与「根本没查出来」同奖。
_mk("ending2_thin", "结局 · 一页之差", "供述到手了，那一页还在别人手里",
    all_of(accused_is("ZZZ"), has_flag("accused"),
           has_clue("zzz_confession")),
    "中上", case=2)
_mk("ending2_pressed", "结局 · 又是暴病", "你写的名字是真的，送出去的纸是假的",
    all_of(accused_is("ZZZ"), has_flag("accused"),
           clue_absent("zzz_confession")),
    "中", case=2)
_mk("ending2_wrong", "结局 · 错的药方", "你报了一个方便的名字",
    accused_in("LQ", "HXW"), "下下", case=2)
_mk("ending2_quiet", "结局 · 只写两个名字", "两具尸首，一个不肯说的名字",
    any_of(has_flag("gave_up2"), accused_is("")), "中下", case=2)

# ---------------- 案③ 的六条收尾（判定顺序即优先级） ----------------
# 同样是「一条台阶」：名字指对了还分两级——手上有没有那一页与那三个字，
# 决定纸是被烧掉（原页）还是被留中（留中）。
_mk("ending3_unspeakable", "结局 · 不可说", "你说出了那个写在纸上的名字",
    accused_is("HD"), "不可说", case=3)
_mk("ending3_orig", "结局 · 原页", "原页、供述、翻模的封泥，一齐摆到了案上",
    all_of(accused_is("FB"), has_clue("jinghe_orig"), has_clue("emperor_ink"),
           has_flag("fb_cracked3")),
    "上上", case=3)
_mk("ending3_byorder", "结局 · 奉旨", "你指认了那个奉旨办事的人",
    accused_is("CC"), "中", case=3)
_mk("ending3_sealed", "结局 · 留中", "名字是真的，纸是留中的",
    all_of(accused_is("FB"), has_flag("accused")),
    "中", case=3)
_mk("ending3_wrong", "结局 · 替罪的人", "你报了一个方便的名字",
    accused_in("LWS", "CA"), "下下", case=3)
_mk("ending3_quiet", "结局 · 合上卷宗", "三桩案子，一个不肯说的名字",
    any_of(has_flag("gave_up3"), accused_is("")), "中下", case=3)

# --------------------------------------------------------------------------
# 组装
# --------------------------------------------------------------------------


def build_content() -> Content:
    scenes: Dict[str, Scene] = {
        "crime_scene": CRIME_SCENE,
        "interrogate_hall": HALL,
        "talk_wdh": TALK_WDH,
        "talk_xse": TALK_XSE,
        "talk_hh": TALK_HH,
        "talk_gf": TALK_GF,
        "talk_hd": TALK_HD,
        "pharmacy": PHARMACY,
        "archive": ARCHIVE,
        "accuse_hall": ACCUSE_HALL,
        # 案②
        "case2_open": CASE2_OPEN,
        "drug_store": DRUG_STORE,
        "night_room": NIGHT_ROOM,
        "drug_office": DRUG_OFFICE,
        "case2_hall": CASE2_HALL,
        "lamp_room": LAMP_ROOM,
        "talk_zzz": TALK_ZZZ,
        "talk_lq": TALK_LQ,
        "talk_hxw": TALK_HXW,
        "talk_fb": TALK_FB,
        "case2_accuse": CASE2_ACCUSE,
        # 案③
        "case3_open": CASE3_OPEN,
        "jinghe_room": JINGHE_ROOM,
        "scriptorium3": SCRIPTORIUM3,
        "key_room3": KEY_ROOM3,
        "case3_hall": CASE3_HALL,
        "talk_ca": TALK_CA,
        "talk_lws": TALK_LWS,
        "talk_cc": TALK_CC,
        "talk_fb3": TALK_FB3,
        "case3_accuse": CASE3_ACCUSE,
    }
    scenes.update(VERDICT_SCENES)
    scenes.update(ENDING_SCENES)

    # 审讯场景的后半段：回侧殿
    for sid in ("talk_wdh", "talk_xse", "talk_hh", "talk_gf", "talk_hd",
                "talk_zzz", "talk_lq", "talk_hxw", "talk_fb",
                "talk_ca", "talk_lws", "talk_cc", "talk_fb3"):
        scenes[sid].choices = []

    verdicts = {
        "WDH": ("verdict_WDH", "太监总管王德海"),
        "HH": ("verdict_HH", "中宫皇后萧氏"),
        "GF": ("verdict_GF", "贵妃柳氏"),
        "HD": ("verdict_HD", "皇帝萧衍"),
        # 案②
        "ZZZ": ("verdict2_ZZZ", "尚药局掌局郑守拙"),
        "LQ": ("verdict2_LQ", "司药柳青"),
        "HXW": ("verdict2_HXW", "值夜小监贺小五"),
        "FB": ("verdict2_FB", "内官监少监冯保"),
        # 案③（FB 的第三案判决屏由 Choice.suspect + effect.scene 指定，
        # 这里仍指向案② 那一屏，与案① 的 HD 用法一致）
        "CC": ("verdict3_CC", "内官监掌印曹淳"),
        "LWS": ("verdict3_LWS", "候补书吏陆文昭"),
        "CA": ("verdict3_CA", "看阁小监常安"),
    }

    return Content(
        items=ITEMS,
        characters=CHARACTERS,
        scenes=scenes,
        topics=build_topics(),
        endings=ENDINGS,
        start_scene="crime_scene",
        verdict_scene="accuse_hall",
        interrogate_hall="interrogate_hall",
        verdict_scenes=tuple(VERDICT_SCENES.keys()),
        verdicts=verdicts,
        title="宫闱迷踪",
        subtitle="古风宫廷推理 · 终端探案",
        prologue=PROLOGUE,
        dossiers=build_dossiers(),
        starter_dossiers=STARTER_DOSSIERS,
        act_titles=ACT_TITLES,
        act_case=act_case_map(),
    )


from .dossiers import ACT_TITLES, FIRST_ACT_SUMMARY, build_dossiers

#: 开场就插在档目里的两份：一份讲怎么阅档，一份是问案底册。
#: 玩家不必先学会「查档」才能开始查案——第一份档案本身就教了这件事。
STARTER_DOSSIERS = ("01-DL-SMB", "01-FY-XFE")

CONTENT: Content = build_content()
