# 逻辑与 bug 复检（S9）

这一轮的目标是「确保没有大的逻辑错误和 bug，确保能正常运行」。做法是**先钉基线、
再对抗式审查、每条发现都要有能红能绿的回归测试**，最后六道门禁 + 两端目视。

- 代码基线：`Ran 352 tests … OK`（1 skip）、`web/gongwei-mizong.html` 459994 字节、
  `web/gongwei-pack.json` 353698 字节。
- 审查方式：三路只读审查（引擎/JS 镜像、网页端、终端端），一律不改仓库，产出
  `file:line + 证据 + 严重度`；我（主控）逐条复现后才动手，每条配回归测试。
- 审查脚本留在 `%TEMP%\gw-audit3\`（临时目录，不入库）。结论：**没有 blocker**。

## 一、五条发现（都已修，都有回归测试）

### 1（中危）终端版按 L 键会把游戏打崩

- 位置：`gongwei/tui/app.py:1207-1213`（`_draw_confirm`）。
- 症状：`self.store.summary().describe() if self.store.exists() else ''` —— `summary()`
  在存档读不动时按约定返回 `None`（`gongwei/game/save.py` 开头写明「绝不因为一个坏档让游戏
  起不来」），于是标题屏一按 `L` 就 `AttributeError: 'NoneType' object has no attribute 'describe'`，
  整个 TUI 跟着崩。
- 修法：先算出 `info`，`None` 时改用 `self.store.last_error`（**故意不调**模块级
  `describe(content, path)`——那个认默认路径，会跟显式路径打架）。
- 回归：`tests/test_tui.py` 的 `SaveKeyTest.test_a_broken_save_does_not_take_the_title_screen_down`
  （4 种坏档：`v:2` ⇒「太新」、`state:"x"` ⇒「格式不对」、`v:"一"` ⇒「不是数字」、
  `turn:"abc"` ⇒ 摘要照给；断言按 `l` 后确认框进得去、`self.screen(100, 30)` 画得出）。

### 2（中危）坏档能带着 `AttributeError` 穿出存档层

- 位置：`gongwei/game/save.py:163`（`load()` 的捕获名单）与 `summary()` 的两处取值。
- 症状：`{"v": 1, "state": "x"}` 会让引擎拿到字符串再 `.get`，抛
  `AttributeError: 'str' object has no attribute 'get'`；原名单只有
  `(KeyError, ValueError, TypeError)`，于是异常一路穿到界面。同族的还有 `state` 里某个值是
  数字、`turn` 是 `"abc"` 这类形状。
- 修法：捕获名单补 `AttributeError`；`summary()` 里 `state` 不是对象 ⇒ 记 `last_error` 并返回
  `None`；`turn` 走安全转换。
- 回归：`tests/test_engine.py` 的 `SaveTest.test_a_misshapen_save_never_raises`（8 种形状）
  与 `SaveTest.test_summary_refuses_a_state_that_is_not_an_object`（4 种）。
  注：`{"v": None, "state": {}}` 是**被接受**的（`v` 缺失按当前版本处理），别把它写进「必拒」清单。

### 3（低危）网页端不校验存档版本号

- 位置：`web/src/ui.js:116-126`（新增 `SAVE_VERSION` 与 `saveVersionError`），调用点 `:329`
  与 `:1166`（导入面板）。
- 症状：终端版拒读 `v:2` 的档，网页端却静默载入——同一份存档两端行为不一致。
- 修法：照 `gongwei/game/save.py` 的口径补上版本检查，报「读档失败：存档版本 2 太新，本版本读不了」。
- 回归：`tests/webui_harness.js` 的「坏档：版本太新、档案状态不成对，两端都读不进来」
  （先种坏档，再点「续前案（读档）」，断言 toast 里出现「太新」且没有 `#reading-body`）。

### 4（低危）JS 侧把不成对的档案状态悄悄读成「未读」

- 位置：`web/src/game.js:277`。
- 症状：`{"01-FY-01": true}` 这种形状，Python 那边整档拒收，JS 这边却按
  `!!pair[0]` 读成 `[false, false]`——「读过的档」倒回未读，是**静默丢数据**。
- 修法：形状不对就 `throw new Error("存档里的档案状态不成对：" + did)`（与 Python 同口径）。
  `fromSave` 中途抛不会写坏 `this.state`（末尾才赋值），所以这条路是安全的。
- 回归：同上那条 harness 检查（断言 toast 里出现「不成对」）。

### 5（低危）`hidden_options()` 的 docstring 与代码不符

- 位置：`gongwei/game/engine.py:513`。
- 症状：注释说「问过就不再出现的话题不算隐藏」，但门禁会重新关上的话题（好感会降）
  仍会进清单。行为是对的，文档是错的——这种不一致最容易被后人「按注释改坏代码」。
- 修法：只改注释，行为不动。

## 二、审查认为「无事」的部分（附证据，便于下次少查一遍）

- **两端逐步一致**：可见选项表 + 隐藏清单（label + hint）+ `to_save()` 逐步比对，随机走
  10 个种子（每次 ≤300 步）共 **12705 次比对，0 不一致**。
- **全场景扫描**：64 个场景 × 5 种状态（裸态 / 全线索全好感全旗标 / 案② / 案③ / 全部问过）
  共 320 例，`vis` / `hid` / `save` 三项 0 不一致。
- **门禁理由不外泄**：`web/src/ui.js` 全库不调 `hiddenOptions()`（只有 `web/src/driver.js:121`
  为审计拿它），终端版的选项直接来自 `engine.options()`；这一轮还顺手删掉了
  `gongwei/tui/app.py` 里两处会把 `locked_hint` 念给玩家的死分支。
- **`Option.enabled` / `hint` 的不变量**（恒 `true` / `""`）在三个构造点都对得上：
  `gongwei/game/engine.py:497`、`:533`、`gongwei/autoplay.py:361`。
- `tools/audit_web.py` 的 27 条路线含案②③ 与 4 条负例，全绿。
- **审查自己点名的盲区**（记录下来，别当已经查过）：随机走只覆盖案①；没有驱动真 UI；
  坏档只试了 16 种形状。这一轮补的是「两端真 UI 读坏档」2 条 + 引擎层 12 种形状。

## 三、有意不动的东西

- 剧本、20 条结局、刚验收的 UI 形制：不动。
- `.locked` / `.lock-chip` 的 CSS：门禁改成「不显示」后它们已无节点，但
  `tests/test_web_tokens.py` 的选择器清单钉着它们，删了反而要改合约——留着，作为「整条不显示」
  之前的痕迹。
- `.col-right` 的独立滚动条（`web/src/style.css` 宽屏分支）：有意为之，宽屏右栏是对齐
  三栏网格的独立栏。
- 四条依赖真存档规模的 harness 检查（28 线索 / 19 人 / 3 人可深谈 / 90–91 条记录）：
  种档是测试夹具，规模变了本来就该一起改，记录在案不改。

## 四、怎么复跑

```powershell
python -m unittest discover -s tests -t .   # 352 项（含 harness 33 项、CSS 合约 15 项）
python tools/audit_gates.py
python tools/audit_web.py
python tools/audit_story.py 30000
python tools/audit_logic.py -v
python tools/build_web.py --check
python tools/build_android.py --check
```
