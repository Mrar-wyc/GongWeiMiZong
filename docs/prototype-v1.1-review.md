# 《宫闱迷踪 v1.1 插画版》拆解：取其精华，去其糟粕

对第三方原型 `宫闱迷踪 v1.1 插画版.html`（698,661 字节，sha256 `133b480f…b7d2c`）的逐段拆解，
以及**已经落在本仓库**的借用清单。原型只读，不进本仓库、不做数据源（见 `AGENTS.md` §1 第 8 条）。

---

## 0. 一句话

它把「氛围」做对了方向（**景与声靠代码现生成、状态里记「玩家怎么想」**），
也把「一份文件」的代价全暴露了（**77% 的字节是插画、两处函数/键名静默重名、没有一条测试**）。
我们偷它的**做法**，不偷它的**载体**：同样 64 屏的图景，我们用 11 KB 的 CSS 换来，
它用 497 KB 的 base64 换来（43.7 倍）。

---

## 1. 实测体量（不是印象，是数出来的）

| 项 | v1.1 插画版 | 本项目（当前 HEAD） |
| --- | --- | --- |
| 单文件 | 698,661 B / 645,057 字符 / 3,342 行 | 400,882 B（`web/gongwei-mizong.html`） |
| 图片 | 8 张 base64 JPEG = **497,288 字符 = 77.1%**；另 9 处 inline SVG | **0 张**（`tests/test_web.py` 扫外链，`tests/test_art.py` 扫图中断） |
| 图景成本 | 497,288 字符（8 屏） | 11,391 B / 302 行 CSS（`web/src/static.css`，覆盖 64 屏） |
| 剧情节点 | 95 个（9 段 `Object.assign(NODES, {…})`） | 64 场景 + 20 结局屏；91 份档案、103 线索/物证、44 话题 |
| 结局 | 5 | 20 |
| 成就 | 11 条 | 不做（有幕册 / 结局册） |
| 存档键 | 7 个 localStorage 键 | 3 个（`gongwei_save` / `gongwei_marks` / `gongwei_settings`） |
| 两端一致 | 只有一份 JS 实现 | Python 引擎 + JS 引擎，`tools/audit_web.py` 27 条路线逐字比对 |
| 测试 | 0 | 293 项 + 六道闸 |

原型的引擎自己分成 40 个小节（`/* ===== 效果 ===== */` 那种），骨架是清楚的：
`NODES`（593）剧情 → `META`（1687）名册 → `G`（616）状态 + `freshState()`（625）→ `meetReq()`（662）
判门禁 → `applyEffects()`（876）结算 → `enterNode()`（1280）进屏 → `renderStory()/renderChoices()`（1019/1085）出屏。
这份骨架值得我们承认：**一个 3,300 行的单文件，靠分节注释和大写常量表，仍然是能读的**。

---

## 2. 精华：六条真的值得偷

### ① 报幕不靠图，靠「名字」——但我们把图换成了 CSS

- 它的做法：`showChapterSplash(n)`（955-972）取 `META.chapters[n-1]` 的卷名、副题、题记，
  `CN_NUM[n]` 转中文数字，插 `ART[n]` 那张图，敲一声 `bell`，5 秒后自动关（点一下早退）；
  另有 `showDreamSplash`（1348-1359）给幻章，顺手给 `body` 加 `dreaming` 类，让整页换一种气。
- 值得偷的是**结构**：`幕号 → 幕名 → 地点 → 时辰` 四件事在任何一屏都能被一眼看到，
  而且这四件事都是**数据驱动的名字**，不是手画的图。
- 我们怎么落：`gongwei/web/art.py`（177 行，一张纯名字台账：地点→色调、时辰→明暗、标签→字形）
  + `web/src/static.css`（302 行，宫墙／药柜／书架／藻井全是渐变与形状）
  + `web/src/ui.js` 的 `#stage` 层与 `.stage-card` 报幕卡。**7 种色调 × 3 种明暗**覆盖全部 64 屏，
  而 `tests/test_art.py` 会拿真剧本查「有没有哪个地点没登记」。
- 有意不学的部分：**5 秒阻塞**（见糟粕 ⑥）。

### ② 说话人是数据，不是正文里的冒号

- 它的做法：段落可以是 `{t: '…', sp: 'wang'}` 对象（996-1018），`sp` 命中 `META.chars` 才出名牌，
  名牌用 `.dlg` 样式点色、逐段淡入；正文里因此**不需要**任何「名字：」的约定。
- 这比我们的处境干净。我们落地时受两条约束：剧本（91 份档案 / 285,679 字节内容包）已经发布，
  而 `AGENTS.md` §1 第 9 条禁止给 `Content` 加字段（`tools/audit_web.py` 要逐字比对两端的存档与选项表）。
  所以走的是**启发式 + 真名表校验**：`web/src/ui.js` 的 `SPEAKERS`（从 `PACK.characters` 现建，
  不硬编码任何名字）+ `saidLine()`；TUI 侧是 `gongwei/tui/app.py` 的 `_speaker_of()` / `_dialogue_rows()`。
- 关键口径（两端**同一套**）：允许前导空白。全库实测只有 **3 行**以真名开头，全在档案 `07-DL-TWO`：
  顶格 1 行（郑守拙）+ 六格缩进 2 行（柳青、贺小五）。顶格-only 会漏掉三分之二，
  所以 `_speaker_of()` 先切出 `lead`、只在 `rest` 上匹配；网页侧 `saidLine()` 同形。
  两端现在都恰好点亮这 3 个名字（TUI：`DossierSpeakerPlateTest`；网页：harness 的 `.said-name` 恰好 3 个）。

### ③ 音效「现吹」，不放音频文件

- 它的做法：`Audio2`（686-787）——正弦 + 三角波（`pluck`，走一个 2200 Hz 低通）、
  噪声爆破（`noiseBurst`，衰减随机数过带通）、闷响（`thud`，150→60 Hz 下滑），
  再加 9 个命名音（click / clue / item / trust / page / stamp / bell / fail / win）
  和一段**程序化 BGM**：`bgmMood()` 按 `state.chapter` 分 calm / tense / storm，
  `bgmStep()` 从对应音阶里随机挑音、按概率排下一次 `setTimeout`，自己给自己续拍。
  `startBGM()` 会在用户手势后 `resume()` 被浏览器挂起的上下文——这个细节是对的。
- 我们怎么落：`web/src/ui.js`（1161-1210 区）只取「事件音」这一半：`CUES` 5 条
  （scene / clue / dossier / verdict / ending，音高、延迟、时长、增益、波形都写在一张表里），
  `cueFor(upd)` 按 `upd` 的字段决定吹哪一声，`settings.sfx` + `settings.volume` 控制，
  没有 WebAudio 的环境（老浏览器、node 测试沙箱）**一律静默跳过**。
  有意不学 BGM：一段随机续拍的背景音需要「暂停/恢复/失焦」三处生命周期处理，
  成本远超收益，而且纯文字推理游戏里它会和阅读打架。

### ④ 元进度收集页（幕册 / 结局册 / 图鉴 / 成就）

- 它的做法：`openChaptersUI()`（1422-1452）按 `getMaxCh()` 决定哪几卷能看到名字（其余显示「？？」）、
  `openEndingsUI()`（1453-1468）把未得结局的标题也遮成「？？」但**留着 hint**、
  `openLoreUI()` / `openAchUI()` 再开两页。三个键各自持久化（`gw_maxch` / `gw_endings` / `gw_ach`）。
- 值得偷的是**信息设计**：未到的东西不藏得干干净净，而是「名字遮住、提示留着」——
  玩家知道还有东西在，也知道该往哪个方向找。
- 我们怎么落：网页第 5 页「案外」（`ui.js` 的 `renderCollection()`）：**幕册 / 结局册 / 行囊 / 音画设定**，
  记录写在 `gongwei_marks`（`{acts: […], endings: […]}`）。
  harness 里有一条检查专门盯这件事：**未到过的幕名一个字都不许泄露**（`未至` 占位），
  同时 `结局册` 保留 `未至` 行数——和原型「遮名留 hint」是同一手。

### ⑤ 门禁声明式化（标量或数组，全部 AND）

- 它的做法：`meetReq(req)`（662-683）认 `visited / clue / item / flag / noflag / trust` 六个键，
  每个键都接受「一个值或一组值」，语义统一是 AND，`trust` 还支持 `{角色: 阈值}` 逐项比。
  整套判定短到能一眼看完，这是它最漂亮的地方。
- 我们怎么落：没有直接搬代码——我们的 `gongwei/game/conditions.py`（396 行）是它的加强版：
  条件编译成**可序列化的 AST**（`all_of / any_of / negate / has_clue / has_flag / trust_at_least / stamped / …`），
  每个门禁都带 `locked_hint`（玩家要知道缺什么），两端共用同一套语义，
  `tools/audit_gates.py` 还会算「这个信任门槛在整局里够不够得着」。
  原型那句「写裸 lambda 会怎样」在它自己的代码里就有答案——见糟粕 ④。

### ⑥ 结算与状态卫生

- 它的做法：`applyEffects(fx)`（876-927）里几处小气度——信任 `clamp(0, 100)`；
  线索**记下是在第几卷知道的**（`s.clues[c] = s.chapter`）；多条增益先攒进 `msgs`；
  `checkAch()`（842-854）对已解锁成就直接 `return`，每个 `check()` 还包在 `try/catch` 里。
  结局屏给一张复盘条（1336-1344）：线索 x/25 · 推演成 n 失 m · 抉择 n 次 · 历时约 n 分钟 · 心如恻隐/刀锋/秋水。
- 我们怎么落：结案复盘与结局印章（TUI 结局印章、网页 `.ending-seal`）、
  开局与结案的规模统计（网页「关于」页那一栏）、以及 `GameState.from_save` 的**缺字段容错**。
- 没偷但值得记一笔的：「心绪三轴」（`mood: {cold, warm, sharp}`）——它把玩家的**态度**也存进状态，
  结局屏据此加一句题外话（1330-1334）。我们的状态里有 `hurt` 与 `score`，但没有态度轴；
  将来若要加，做法应当是**只设不读的 flag 登记进 `BREADCRUMB_FLAGS`**，而不是往状态里塞函数。

---

## 3. 糟粕：七条明确不学

### ① 77% 的字节是插画

497,288 个字符（8 张 base64 JPEG）压在一个必须「双击就能开」的单文件里，
换来的是**8 屏**（每卷一张）的视觉，而 95 个节点里的绝大多数仍然是纯文字屏。
首次解析、缓存、diff、以及「换一张图就得重打整包」全都要为这 77% 买单。
我们的选择是把它换成**规则**：地点→色调、时辰→明暗、标签→字形，
一张 177 行的台账 + 302 行 CSS，覆盖全部 64 屏，产物只涨了 13 KB。

### ② 静默重名（活体事故两处）

- `Audio2` 里 `thud: function` 定义了**两次**（725 与 751），后一个覆盖前一个：
  `sfx('stamp')`（741）想敲的那声闷响其实永远是死代码。
- `META.clues.c_codetail` 定义了**两次**（1725 与 1727）：后者覆盖前者，
  前一条（含 `type: '文'`、`ch: 6` 字段的那条）从没被任何代码看到过。
- 这类事故**不报错、不崩、不提示**，只是悄悄少一个音、少一版描述。
  这正是 `tests/test_structure.py`（Python 侧）与 `tests/test_web.py`（`web/src/*.js`）现在盯着的事——
  我们自己在这个坑里栽过两次，教训写进了 `AGENTS.md` §6。

### ③ 规模数字三处不一致

注释写「线索（24）」、`clueTotal: 25`、实测唯一键 **26** 个；物品注释写「12」、实测 **14** 个。
写死的规模数字没有任何东西盯着，于是三份数字各说各话。
我们的对策是让测试当尺子（`README.md` / `AGENTS.md` 里那句「写死的规模数字有测试盯着」）。

### ④ 状态里塞函数

`COMPUTED`（647-659）是一张**函数表**（`chain_perfect` / `win_path` / `wrong_path` / `die_path`…），
`META.ach[*].check` 也是函数。后果有三：
不能打包成可 diff 的数据、不能被审计工具静态分析、不能用非 JS 的实现重跑。
更别扭的是 `ach_allend` 的 `check` 直接 `return false`，真正的解锁逻辑藏在 `checkAch()`（851-853）
那段特例代码里——**数据说「不可能」，代码偷偷开后门**。
我们的条件语言是 AST（可序列化），审计工具因此能反问「这条门禁在整局里够不够得着」。

### ⑤ 可无限重试的推演

`openDeduce()`（1211-1277）失败只做两件事：`G.state.ded.fail += 1`、显示 `o.fb`。
没有代价、没有冷却、没有锁选项——**玩家最优策略永远是把每个选项点一遍**。
（它的池子倒是取对了：只列你已经拿到的线索，`if (!G.state.clues[cid]) return`。）
我们的 `tools/audit_logic.py` §8 专门查这类「可重复 + 一次性收益」的口子，
§5 还会按「翻档到底改不改变什么」分档看软卡——就是不让「点一遍」变成唯一解。

### ⑥ 5 秒阻塞过场

`showChapterSplash()` 自动 5 秒关闭，还先敲一声 `bell`；
阅读是连续动作，被一张必须等的过场卡打断 5 秒，是拿玩家的耐心换仪式感。
我们保留了报幕的信息（幕号、幕名、地点·时辰），但让它**不阻塞**：
`.stage-card` 淡入 420 ms、随剧情自然退场，动效还能一键关掉。

### ⑦ 存档碎片化 + 没有迁移

7 个 localStorage 键（`gw_save_0` 自动、`gw_save_1..3` 手记、`gw_settings`、`gw_ach`、`gw_endings`、
`gw_maxch`、`gw_preend`），每处各自 `try/catch` + 各自 `JSON.parse`；
`state.ver: '1.0.0'` 记下来了却**没有任何代码读它**，版本升级靠 `flags.restored = true` 打补丁
（`loadFrom` 943）。`gw_preend` 是「结局前快照」（`savePreEnd()` 951），思路很好，
可界面上没有显式入口，玩家永远不会知道自己有一张后悔药。

我们的做法：`{v: 1, state: {…}}` 信封 + `GameState.from_save` 对缺字段容错（老存档要读得回来，§7 DoD），
加 `gongwei_marks` / `gongwei_settings` 两个纯展示用键。

### ⑧ 手抄的章节 preset

`META.chapters[*].preset`（1756-1763）把每一章的 `clues` / `items` / `trust` / `flags` /
`ded` **又抄了一遍**（8 章 × 20+ 条线索），供「章节回廊」直接跳进某一卷。
一改内容就会漂移，而且没有任何东西盯着这份副本。
我们的幕册只记「到过哪几幕」，不回放状态——省掉一整类漂移风险。

### ⑨ 只有一份实现，也没有测试

原型是单份 JS，没有对端可差分，没有 `tests/`，没有门禁。
于是上面这些事故只能靠人读代码发现。我们这条路走的是另一头：
Python 引擎 + JS 引擎两份实现，`tools/audit_web.py` 用 27 条路线把**存档与选项表逐字比对**，
连报错句子都必须一模一样——多一份实现的成本，换的是「两端不一致会在 CI 里红」。

---

## 4. 落地对照（偷了什么 → 落在哪 → 谁盯着）

| 偷来的做法 | 落点 | 盯着它的测试/闸门 |
| --- | --- | --- |
| 景是名字（地点→色调 / 时辰→明暗 / 标签→字形） | `gongwei/web/art.py`、`web/src/static.css`、`ui.js` 的 `#stage` | `tests/test_art.py`（19 项：台账、真剧本、CSS、产物四方对账） |
| 报幕卡（幕号 · 幕名 · 地点·时辰） | `ui.js` 的 `.stage-card`、`shell.html` 的 `__ART_SLOT__` | harness「进场报幕」检查 |
| 说话人名牌 | `ui.js` 的 `SPEAKERS`/`saidLine()`；`gongwei/tui/app.py` 的 `_speaker_of()`/`_dialogue_rows()` | `DossierSpeakerPlateTest`（TUI）+ harness「说话人名牌」检查（恰好 3 个名字） |
| 音效现吹（事件音 5 条） | `ui.js` 的 `CUES`/`audioCue()`/`cueFor()` | harness「各条指令都不炸」（无 WebAudio 时静默） |
| 元进度收集页 | 「案外」页：幕册 / 结局册 / 行囊 / 音画设定 | harness「案外」与「音画设定」两条检查（未到的幕名一个字不许泄） |
| 结局印章 / 结案复盘 | TUI 结局印章、网页 `.ending-seal`；「关于」页统计栏 | `tests/test_audit.py` 20 条结局路线、`audit_logic` §9 |
| 深谈门槛的可见性 | TUI 人情栏金 `●`（`CONFIDE_MARK`，`confide_at == 999` 永不亮） | `TrustCeilingTest` + `audit_gates.py` 的门槛可达性 |
| 设置项「过场停留 / 音效 / 音量」 | `ui.js` 的 `renderSettings()`（4 行）+ `gongwei_settings` | harness「音画设定：点一下当场生效，也写进本机」 |

原型的**教训**也一并落进了文档：`AGENTS.md` §1 第 9 条（图景是名字，不是图片）、§2 地图里的 `art.py` /
`static.css` 两行、§6「同名函数会静默顶掉」、§7 新增的「新地点/时辰/标签要登记」条目。

---

## 5. 记下来、但这轮没做

1. **结构化说话人**（`{t, sp}` 那种）：更干净，但要给 `Content` 加字段，
   会破坏 `tools/audit_web.py` 的逐字比对契约。若将来重写剧本，这是首选形态。
2. **「回到结局前」的显式入口**：原型的 `gw_preend` 证明这个需求真实存在
   （结案后若没有手动存档，玩家只能重来）。做它要同时动 Python/JS 两侧的存档与状态字段，
   属于一次独立的小改动，不适合搭在这次表现层工作里。
3. **心绪三轴**：把玩家的态度记进状态、让结局屏多说一句话。
   以我们的规矩，只能落成 flag + `BREADCRUMB_FLAGS` 登记，不能落成状态里的函数。

---

## 6. 复验（当前 HEAD 的六道门禁）

```text
python tools/build_web.py --check     ✓ 408829 / 353698 字节，与剧本一致
python -m unittest discover -s tests -t .   Ran 293 tests … OK
python tools/audit_gates.py          审计通过：门禁全部可达，引用全部有据。
python tools/audit_web.py            ✓ 两端逐步一致：存档与选项表逐字相同，连报错都一致
python tools/audit_story.py 30000    场景 64/64 · 档案 91/91 · 线索/物证 103/103（核心 65/65）
                                     · 话题 44/44 · 结局 20/20 · [从未解开过的门禁] 无
python tools/audit_logic.py          九节全绿（§5 另有 1 处「翻档即解」的软卡，案① 开局的正常节奏）
```
