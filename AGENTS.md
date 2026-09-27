# AGENTS.md · 给改这个仓库的 AI / 人

一个古风宫廷推理游戏：**三案十一幕**，终端版与网页版**共用同一份剧本、同一套判定**。
这份文件写的是「改动时必须守什么、改哪里、怎么验」，玩法与内容介绍见 `README.md`。

## 1. 硬规则（打破了就是事故）

1. **零第三方依赖**。Python 只用标准库（连 `curses` 都不用，终端层是自己写的）；
   网页版必须是**一个** HTML 文件、无 CDN、无外链、无外部字体。
   `tests/test_web.py` 会扫描产物里的 `http://` / `https://`。
2. **剧本只住在 `gongwei/data/story.py` 与 `gongwei/data/dossiers.py`**。
   `game/`、`tui/`、`web/src/` 里不许出现任何剧情硬编码（人物名、档号、案件事实）。
3. **两端同步**：改完剧本必须跑 `python tools/build_web.py`，
   否则 `test_disk_matches_sources` / `test_pack_file_parses` 会红（这不是 bug，是忘了打包）。
4. **门禁必须全绿**（§4）。任何一条红都先修，再谈别的。
5. **结局三方一致**：`CONTENT.endings` 的 id 集合 == `gongwei/autoplay.py` 里 `ENDING_ROUTES`
   的键集 == 路线扫出来的集合。加了结局就要加路线，`tests/test_audit.py` 会比对。
6. **选项标签（`Choice.label`）全局唯一**。引擎按 `::标签` 去重，重名会让两条路互相顶掉。
7. **档号一经发布就不要改**：`links=` / `requires=` / 正文里的交叉引用都按字符串写死。
   要加内容就加**新**档号。
8. `reference-gongwei-mizong.chatglm.html` 是只读参考原型，不要改、不要当数据源。

## 2. 目录地图（该改哪里）

| 路径 | 行数 | 什么时候动它 |
| --- | --- | --- |
| `gongwei/data/story.py` | ~2800 | 场景、选项、话题、结局规则、人物表、幕案映射 |
| `gongwei/data/dossiers.py` | ~2100 | 91 份档案的正文、幕标题 `ACT_TITLES`、勘验总录 |
| `gongwei/game/models.py` | 236 | 数据模型（字段不够用时才动） |
| `gongwei/game/engine.py` | 783 | 规则引擎：选项门禁、效果、阅档、结局判定、存档 |
| `gongwei/game/conditions.py` | 396 | 条件小语言（`clue:` / `flag:` / `trust:` …）+ AST |
| `gongwei/game/command.py` | 578 | 指令解析（档号、档目、检索、记事、存读档），两端同一套语义 |
| `gongwei/tui/terminal.py` | 850 | 零依赖终端层：CJK 双宽、禁则、ANSI、键盘、行编辑 |
| `gongwei/tui/app.py` | 1054 | 界面：分栏、阅读区、命令行、浮层、提示语 |
| `gongwei/web/pack.py` | 155 | 剧本 → 内容包（条件编译成 AST） |
| `gongwei/autoplay.py` | 425 | 脚本化通关原语 + `ENDING_ROUTES`（tools/ 与 tests/ 共用） |
| `web/src/game.js` | 786 | JS 侧引擎（必须与 `engine.py` 行为一致） |
| `web/src/ui.js` | 996 | 网页界面（分页、命令行、存读档、导出导入） |
| `web/src/style.css` | 458 | 网页版**断点都在这儿**（窄屏分页、宽屏三栏、480px）——`ui.js` 里没有宽度判断 |
| `web/src/driver.js` | 128 | node 下走路线，供 `audit_web.py` 调 |
| `tools/audit_*.py` | — | 四道体检闸门（§4） |
| `tests/` | — | 242 项；`tests/webui_harness.js` 在 node 里用最小 DOM 真跑 `web/src/ui.js` 与 `game.js` 的判决节拍；`tests/helpers.py` 只是转手 `autoplay` 的路线，**不要另抄一份** |

判断要点：**玩家的体验问题 → `story.py` / `dossiers.py`；行为不对 → `engine.py` + `web/src/game.js`
两边一起改；显示不对 → `tui/app.py` / `web/src/ui.js`（网页版的断点在 `web/src/style.css`）。**

## 3. 内容约定（写剧本照这个写）

**效果与动作**

- `E(text=…, clues=…, items=…, dossiers=…, trust=…, flags=…, time=…, scene=…, score=…, hurt=…)`：一次效果。
- `acting(scene, label, detail=…, text=…, clues=…, items=…, score=…, wants=…, locked_by=…, locked_hint=…, visible_if=…)`：
  **原地动作**（不换场景）。它内部靠一个元组判断「这个场景算不算原地」——
  **新加的场景 id 必须加进那个元组**（`story.py` 里 `here = scene in (...)`），
  否则动作会变成换场景。
- **`repeatable` 默认规则**：`acting()` 在带 `clues / items / dossiers / score / trust` 时
  自动设成「不可重复」。线索与物证引擎会去重，**分数与信任不会**——可重复就等于刷分。
  枢纽动作（回大厅、进子场景）不带效果，天然可重复。
- 场景上的 `act=` / `case=`：**0 表示「不改动当前幕号 / 案号」**，非 0 才会推进
  （`engine.go_to()` 里 `if scene.act:` / `if scene.case:`）。忘写就会顶栏不更新、
  结局串案。问询场景还要写 `hall=`（回哪个前厅，默认案① 的侧殿）。

**幕与案**

- 幕名表在 `dossiers.ACT_TITLES`（1~11）；**哪几幕属于哪一案只写在 `story.CASE_ACTS`**：
  `{1: (1,2,3,4,5), 2: (6,7,8), 3: (9,10,11)}` → 派生出 `Content.act_case` → 两端剧情锁与提示语。
  加一整案只改这一处，引擎与 JS 都不用动。
- **剧情锁**（`engine.can_read_dossier` / `game.js canReadDossier`）只看案号：
  「不在档目、`requires` 又不满足、且属于更靠后的案」→ 敲不开，提示「这份档属于第 N 案」。
  同一案里的旧档一律可翻——那是玩法。

**档案（`D(...)`）**

- `time_code` / `place_code` / `people` 不写就按档号拆（`09-JG-XYP` → 09 / JG / XYP）。
- `requires=` **只挡「自己拼档号」这一路**；一旦被 `links=` 收进档目就可读（`links` 不看 requires）。
  场景门槛要用 `missing_dossier(...)`（= 还没**读过**），不要手写一套。
- 幕标题加好后，把新幕的列表接进文件末尾的 `DOSSIERS = _ACT1 + … `。

**话题（问人）**

- `TOPIC_SPECS`：`(tid, owner, label, response, Effect, is_present, hint)`；`TOPIC_GATES`：`tid → (条件, 提示语)`。
- **跨案的话题不会摆上桌**：引擎按话题给出的档案算它属于哪一案（`engine.topic_case` /
  `game.js topicCase`），案号大于当前案就不显示——写话题时给 `E(dossiers=…)` 定好案号即可。
- 门禁只允许 `all_of / any_of / negate / has_clue / has_flag / trust_at_least / stamped / …` 这些
  **可序列化的条件对象**——写裸 `lambda` 会让内容包导不出去（`audit_web` / `pack` 会红）。
- 门槛高度必须低于「这个人信任实际能到的高度」（`audit_gates.py` 会算出可达上限，
  曾因门槛写在信任上限之上废掉两条支线）。

**结局**

- `_ending(eid, 标题, 正文)` 建结局屏；`_rule(eid, …, 判据, rank, case)` 登记规则；
  `_mk(...)` 从结局屏里取正文。**规则顺序就是优先级**，每案最后一条必须是
  「什么都没查出来」那一档的兜底（中下），不能兜出一个好结局——`audit_logic.py` 第 4 节会查。
- 每条规则的 `case=` 必须写对：案① 的判据（如 `accused_is("WDH")`）不加 `case`
  会把案② 的指认结果抢走。
- 加一条结局 = 加一条规则 + 一条 `ENDING_ROUTES` 路线 + 让 `audit_story` 扫得到。
- 判决屏是「进屏即结算」的中转站：正文跟场景一样进卷宗，标题由 `go_to()` 补记
  `【判决】…` 一行当节拍。指认去哪儿**不查那张表**，而是 `Engine.verdict_target()`
  按当前案号从指认选项里推（`content.verdicts` 一个嫌疑人只有一条，冯保与萧衍
  各在两案里出现）。`web/src/game.js` 的 `verdictTarget` 必须同形。

## 4. 门禁（改完按这个顺序跑）

```powershell
python tools/build_web.py --check        # 产物等于当前剧本打的包
python -m unittest discover -s tests -t .  # 242 项（含下面几道闸）
python tools/audit_gates.py              # 线索/物证登记一致性、门禁引用是否有据
python tools/audit_web.py                # 跨端差分：27 条路线逐字比对存档与选项表
python tools/audit_story.py 30000        # 可达性：枚举状态图 + 20 条结局路线（参数是预算步数）
python tools/audit_logic.py              # 逻辑体检：后门/剧透面/刷分/死胡同/结局判定
```

> **这六条本地不必默认全跑。** `audit_story.py` 是唯一吃内存的一条——它要在内存里
> 穷举整张状态图并给每个状态做指纹去重，步数预算越大驻留得越多。
> `.github/workflows/gates.yml` 已经每次 push 自动跑全套（Windows + Linux 两条腿），
> 本地按需单跑某一条就够，别默认全套。

预期输出（当前基线）：

- `Ran 242 tests … OK`
- `审计通过：门禁全部可达，引用全部有据。`
- `✓ 两端逐步一致：存档与选项表逐字相同，连报错都一致`
- `场景 64/64`、`档案 91/91`、`线索/物证 103/103（核心 65/65）`、`话题 44/44`、`结局 20/20`、
  `[从未解开过的门禁] 无`
- `audit_logic.py`：**九节全绿**（第 8 节的刷分口子已收；第 5 节会打印一处「还有档可翻」的软卡，
  那是案① 的节奏，不算死胡同）。

**两端的报错必须逐字一致**：Python 侧在 `gongwei/autoplay.py`，JS 侧在 `web/src/driver.js`，
`audit_web.py` 会把两侧的报错句子直接对比——改一边忘一边，门禁立刻红。

## 5. 加一幕 / 加一案的标准流程

1. `dossiers.py`：`ACT_TITLES` 加幕名 → 新写 `_ACT12 = [D(...), …]` → 接进 `DOSSIERS`。
2. `story.py`：写场景与选项（`Scene(..., act=12, case=4, hall=…)`）、话题、必要时加人物与线索。
3. 新案：只在 `CASE_ACTS` 加一行（`4: (12, 13, 14)`）。
4. 结局：`_ending` / `_rule`（顺序、`case`、兜底三件事）→ `autoplay.ENDING_ROUTES` 加路线。
5. `python tools/build_web.py` 重新打包。
6. 六道门禁 + `README.md` 里的数字（内容规模表、样例页脚、结局表）一起更新。
7. 发布级改动再手工跑一遍真实浏览器（两种视口 + 存档读回）。

## 6. 踩过的坑（省你一次）

- **PowerShell 不支持 heredoc**（`python - <<'PY'` 会 ParserError）；`python -c` 里嵌中文与引号
  也容易炸。要跑脚本就**写一个临时 `.py` 文件**再执行。
- 从 `%TEMP%` 之类的地方跑探针脚本，先 `$env:PYTHONPATH=$PWD.Path`，否则 `import gongwei` 失败。
- Windows 中文乱码：`$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"`。
- **同名函数会静默顶掉**（栽过两次：`web/src/ui.js` 里两个 `renderOptions()` 只剩右栏、
  `gongwei/tui/app.py` 里两个 `_draw_left()` 把带阅档功能的新版盖掉）。
  现在 `tests/test_structure.py` 扫 `main.py`、`gongwei/**/*.py`、`tools/*.py` 的重复定义，
  `tests/test_web.py` 另扫 `web/src/*.js` 的重复函数声明与产物外链。
- `web/src/ui.js` 里调 `game.xxx()` 前，先确认 `web/src/game.js` 真有这个方法（测试用 node 真跑）。
- 删/改档号会断 `links` 与正文引用；`audit_gates.py` 只查登记，不查叙事。
- 改完剧本忘了 `build_web.py` → 两条测试红，别去查引擎。
- 路线常量分「完整路线」与「尾段」：`OPENING_ROUTE` / `EVERYTHING_ROUTE` / `CASE3_ROUTE` 是完整的，
  `CASE2_ROUTE` 那些是尾段，必须接在 `CASE2_HEAD` 后面走。
- **撒网工具里那个「一步之后的世界」不能少字段**：`tools/audit_story.py` 的 `pack()` 直接
  用 `state.to_save()` 再摘掉三样纯显示键。历史上它手写字段表、漏了 `case`，于是恢复出来的
  状态永远停在第一案，报出「场景 61/63、档案 87/91」这种假缺口——**门禁红了先怀疑尺子**。
- **写死的规模数字有测试盯着**：界面文案里的案数与幕数由 `tests/test_presentation.py`
  与实际剧本比对（网页版的「关于」曾把总幕数写少过，这条教训自己也被它抓过一次）。

## 7. 交付前自检（DoD）

- [ ] 六道门禁 + 单元测试全绿，输出与 §4 的基线一致（数字变了就同步 README）。
- [ ] 新加的场景/档案/线索/话题/结局都出现在 `audit_story.py` 的 `N/N` 里。
- [ ] 新加的门禁都写了 `locked_hint`（玩家要知道缺什么）。
- [ ] 改动涉及界面 → 终端与网页两端都手工看过一眼（窄屏也要看）。
- [ ] 老存档读得回来（`GameState.from_save` 对缺字段要容错，别让版本升级废档）。
- [ ] `README.md` 的数字、结局表、目录结构与实际一致。
