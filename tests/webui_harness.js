"use strict";
/*
 * 在 node 里把 web/src/ui.js 真跑一遍。
 *
 * 为什么要有这个文件：`web/src/ui.js`（近千行）是仓库里唯一没有任何测试执行过的部分 ——
 * `tests/test_web.py` 只用正则扫重名函数、只用 node 验证 `game.X` 调用名存在，
 * 没有任何一条断言「点下去、敲进去，屏幕上真的出现东西」。
 * 网页版「读档」被正则吃成「阅 档」、about 里的幕数写少，都是从这个盲区溜过去的。
 *
 * 玩法：手写一个刚好够用的假 DOM（零依赖，也不许引 jsdom），把 ui.js 当脚本执行，
 * 然后用「点按钮 / 往 #cmd 里敲指令再回车」这样的真动作走一遍主要界面。
 * 只用到 ui.js 实际用到的那些 DOM 能力，见下。
 *
 * 输出：
 *   OK <检查名>
 *   FAIL <检查名> :: <原因>
 *   CHECKS <总数> <失败数>
 * 有失败就 exit 1。tests/test_webui.py 读这些行。
 *
 * 环境变量（只有测试自检用得上）：
 *   GONGWEI_UI_SRC     改跑另一份 ui.js（用来证明这套检查真能抓到坏掉的界面）
 *   GONGWEI_PACK_FILE  改读另一个内容包（默认 web/gongwei-pack.json）
 *   GONGWEI_SEED_SAVE  一份真存档（Python 引擎写出来的），用来验证「读回结案存档」
 */

var fs = require("fs");
var path = require("path");

var ROOT = path.join(__dirname, "..");
var UI_FILE = process.env.GONGWEI_UI_SRC || path.join(ROOT, "web", "src", "ui.js");
var PACK_FILE = process.env.GONGWEI_PACK_FILE || path.join(ROOT, "web", "gongwei-pack.json");
var SEED_SAVE = process.env.GONGWEI_SEED_SAVE || "";

function noop() {}

// ---------------------------------------------------------------------------
// 假 DOM：ui.js 用到的全部能力都在这里
//   建树：createElement / createTextNode / appendChild / removeChild
//   查找：getElementById（按 id 走树）/ querySelectorAll（只支持「.a .b」与「.a」）
//   属性：className / textContent / title / value / id / scrollTop / scrollHeight
//   事件：addEventListener / dispatch / click / focus
//   文档：body / body.setAttribute / body.appendChild / addEventListener
// 没有 classList、没有 style、没有 dataset、没有 innerHTML（ui.js 只在「内容包没带上」
// 那条错误分支里用过一次 innerHTML）。
// ---------------------------------------------------------------------------

function makeNode(tag) {
  var node = {
    tagName: String(tag == null ? "div" : tag).toUpperCase(),
    id: "",
    className: "",
    textContent: "",
    title: "",
    value: "",
    scrollTop: 0,
    scrollHeight: 0,
    type: "",
    placeholder: "",
    focused: false,
    children: [],
    listeners: {},
    parent: null,
    appendChild: function (child) {
      child.parent = this;
      this.children.push(child);
      return child;
    },
    removeChild: function (child) {
      var i = this.children.indexOf(child);
      if (i >= 0) { this.children.splice(i, 1); }
      return child;
    },
    remove: function () {                       // ui.js:787 关浮层时用
      if (this.parent) { this.parent.removeChild(this); }
    },
    setAttribute: function (key, value) {
      if (key === "id") { this.id = String(value); }
      this[key] = value;
    },
    getAttribute: function (key) { return this[key]; },
    addEventListener: function (kind, fn) {
      (this.listeners[kind] = this.listeners[kind] || []).push(fn);
    },
    dispatch: function (kind, ev) {
      var fns = this.listeners[kind] || [];
      for (var i = 0; i < fns.length; i += 1) { fns[i](ev); }
    },
    focus: function () { this.focused = true; },
    click: function () {
      this.dispatch("click", { target: this, preventDefault: noop, stopPropagation: noop });
    },
    querySelectorAll: function (sel) { return query(this, sel); }
  };
  Object.defineProperty(node, "firstChild", {
    get: function () { return this.children.length ? this.children[0] : null; }
  });
  return node;
}

function descendants(root) {
  var out = [];
  (function walk(node) {
    node.children.forEach(function (child) { out.push(child); walk(child); });
  })(root);
  return out;
}

function matchesToken(node, token) {
  if (token.charAt(0) === ".") {
    return (" " + node.className + " ").indexOf(" " + token.slice(1) + " ") >= 0;
  }
  return node.tagName === token.toUpperCase();
}

function query(root, sel) {
  var tokens = String(sel).trim().split(/\s+/).filter(function (t) { return t.length > 0; });
  if (!tokens.length) { return []; }
  var last = tokens[tokens.length - 1];
  var hits = descendants(root).filter(function (n) { return matchesToken(n, last); });
  if (tokens.length > 1) {
    var chain = tokens.slice(0, -1);
    hits = hits.filter(function (node) {
      var i = chain.length - 1;
      var p = node.parent;
      while (p && i >= 0) {
        if (matchesToken(p, chain[i])) { i -= 1; }
        p = p.parent;
      }
      return i < 0;
    });
  }
  return hits;
}

function textOf(node) {
  if (!node) { return ""; }
  var out = node.textContent ? String(node.textContent) : "";
  node.children.forEach(function (child) { out += textOf(child); });
  return out;
}

function makeDocument() {
  var body = makeNode("body");
  var stage = makeNode("div");
  stage.id = "stage";
  var card = makeNode("div");
  card.id = "stage-card";
  card.className = "stage-card";
  stage.appendChild(card);
  // 与 web/shell.html 里那段标记一样：图景槽自带默认色调/明暗/幕次
  stage.setAttribute("data-tone", "hall");
  stage.setAttribute("data-light", "day");
  stage.setAttribute("data-act", "0");
  var app = makeNode("div");
  app.id = "app";
  // web/shell.html 里 body 是「图景 + <div id="app">」：#stage 在 #app 之外，
  // ui.js 每次 clear(#app) 都清不到它 —— 这正是图景不被重画打断的原因。
  body.appendChild(stage);
  body.appendChild(app);
  var doc = {
    body: body,
    documentElement: makeNode("html"),
    listeners: {},
    createElement: function (tag) { return makeNode(tag); },
    createTextNode: function (text) {
      var n = makeNode("#text");
      n.textContent = String(text);
      return n;
    },
    getElementById: function (id) {
      if (body.id === id) { return body; }
      var hits = descendants(body).filter(function (n) { return n.id === id; });
      return hits.length ? hits[0] : null;
    },
    addEventListener: function (kind, fn) {
      (doc.listeners[kind] = doc.listeners[kind] || []).push(fn);
    },
    dispatch: function (kind, ev) {
      var fns = doc.listeners[kind] || [];
      for (var i = 0; i < fns.length; i += 1) { fns[i](ev); }
    }
  };
  return doc;
}

function makeStorage() {
  var store = {};
  return {
    getItem: function (k) {
      return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null;
    },
    setItem: function (k, v) { store[k] = String(v); },
    removeItem: function (k) { delete store[k]; },
    key: function (i) { return Object.keys(store)[i]; },
    clear: function () { store = {}; }
  };
}

// ---------------------------------------------------------------------------
// 检查框架
// ---------------------------------------------------------------------------

var RESULTS = [];

function check(name, fn) {
  try {
    fn();
    RESULTS.push({ name: name, ok: true, detail: "" });
  } catch (err) {
    RESULTS.push({ name: name, ok: false, detail: (err && err.message) || String(err) });
  }
}

function need(cond, msg) { if (!cond) { throw new Error(msg); } }

function brief(node, limit) {
  var t = textOf(node).replace(/\s+/g, " ").trim();
  var cap = limit || 90;
  return t.length > cap ? t.slice(0, cap) + "…" : t;
}

// ---------------------------------------------------------------------------
// 起手：装 DOM、装内容包、跑 ui.js
// ---------------------------------------------------------------------------

var pack = JSON.parse(fs.readFileSync(PACK_FILE, "utf8"));
var doc = makeDocument();
var storage = makeStorage();
// 图景台账由 tests/test_webui.py 从 gongwei/web/art.py 导出（与页面上 #art 块同一份
// JSON），没给就留空 —— ui.js 必须能空着手跑，所以这也算一条隐性检查。
var art = null;
if (process.env.GONGWEI_ART_FILE) {
  art = JSON.parse(fs.readFileSync(process.env.GONGWEI_ART_FILE, "utf8"));
}
var win = {
  __GONGWEI_PACK__: pack,
  __GONGWEI_ART__: art,
  localStorage: storage,
  sessionStorage: storage,
  addEventListener: noop,
  removeEventListener: noop,
  location: { href: "file:///gongwei-mizong.html" }
};
win.GongweiGame = require(path.join(ROOT, "web", "src", "game.js"));
global.window = win;
global.document = doc;
global.localStorage = storage;

var booted = true;
try {
  require(UI_FILE);                                   // ui.js 末尾会自己 render() 一次
} catch (err) {
  booted = false;
  console.log("FAIL 加载并渲染" + " :: " + ((err && err.stack) || err));
}

function app() { return doc.getElementById("app"); }
function byId(id) { return doc.getElementById(id); }
function appText() { return textOf(app()); }
function paneText(id) { var n = byId(id); return n ? textOf(n) : ""; }

function cmd(text) {
  var input = byId("cmd");
  need(input, "没有 #cmd：命令输入框没渲染出来（当前屏：" + brief(app(), 60) + "）");
  input.value = text;
  input.dispatch("keydown", { key: "Enter", preventDefault: noop, target: input });
}

function esc() {
  doc.dispatch("keydown", { key: "Escape", target: doc.body, preventDefault: noop });
}

// 给某个节点派发一次按键（如命令行里的 ↑ ↓）。
function keyOn(node, key) {
  node.dispatch("keydown", { key: key, preventDefault: noop, target: node });
}

function buttons(scope, word) {
  var host = scope || app();
  var all = query(host, "button");      // 选项是 .opt、浮层里是 .btn，都按标签找
  if (word === undefined) { return all; }
  return all.filter(function (b) { return textOf(b).indexOf(word) >= 0; });
}

function clickButton(word) {
  var hits = buttons(app(), word);
  need(hits.length === 1, "屏幕上找不到唯一的「" + word + "」按钮（找到 " + hits.length + " 个）");
  hits[0].click();
}

var START = pack.start_scene;
var START_SCENE = pack.scenes[START];

// ---------------------------------------------------------------------------

if (booted) {

  check("开屏是标题屏", function () {
    var t = appText();
    need(t.indexOf(pack.title) >= 0, "标题屏上找不到作品名「" + pack.title + "」");
    need(t.indexOf("新案") >= 0, "标题屏上找不到「新案」入口");
    need(t.indexOf(String(pack.prologue).slice(0, 10)) >= 0, "标题屏上找不到序章引文");
  });

  // 图景槽是一层画在 #app 外面的景：ui.js 每次重画都会 clear(#app)，景要是放进去
  // 就会被连根拔掉，所以这条检查同时钉住「它在 body 之下」这件事。
  check("图景槽在标题屏上是默认景，且落在 #app 外面", function () {
    var stage = byId("stage");
    need(stage, "页面上没有 #stage：web/shell.html 的图景槽没接上");
    need(stage.parent === doc.body, "#stage 被放进了 #app 里，每次重画都会被清掉");
    need(String(stage.getAttribute("data-tone")).length > 0, "#stage 没有 data-tone");
    need(String(stage.getAttribute("data-light")).length > 0, "#stage 没有 data-light");
    need(stage.getAttribute("data-act") === "0",
      "标题屏该是第 0 幕，实得「" + stage.getAttribute("data-act") + "」");
    if (art) {
      need(stage.getAttribute("data-tone") === art.default_tone,
        "标题屏色调是「" + stage.getAttribute("data-tone") + "」，台账里默认是「" + art.default_tone + "」");
      need(stage.getAttribute("data-light") === art.default_light,
        "标题屏明暗是「" + stage.getAttribute("data-light") + "」，台账里默认是「" + art.default_light + "」");
    }
  });

  check("点「新案」进第一幕", function () {
    clickButton("新案");
    need(byId("reading-body"), "开局后没有 #reading-body（阅读区没渲染）");
    var body = String(START_SCENE.body).slice(0, 12);
    need(paneText("reading-body").indexOf(body) >= 0,
      "卷宗里没有开场正文；应有「" + body + "」，实得「" + brief(byId("reading-body")) + "」");
  });

  check("进场报幕：幕次、幕名、地点色调都跟着走", function () {
    var stage = byId("stage");
    need(stage, "进游戏后 #stage 不见了");
    need(stage.getAttribute("data-act") === "1",
      "已经进了第一幕，图景还写着第 " + stage.getAttribute("data-act") + " 幕");
    var card = byId("stage-card");
    need(card && (" " + card.className + " ").indexOf(" on ") >= 0, "换幕没有报幕卡片");
    var title = String(pack.act_titles["1"]);
    need(textOf(card).indexOf(title) >= 0,
      "报幕卡片上没有第一幕的幕名「" + title + "」：" + brief(card));
    var place = String(START_SCENE.place);
    if (art) {
      // 地点必须在台账里登记过：漏一个就会静默退回默认景，画面对不上文字
      need(art.place_tone[place],
        "起点地点「" + place + "」不在图景台账里（gongwei/web/art.py 的 PLACE_TONES）");
      need(stage.getAttribute("data-tone") === art.place_tone[place],
        "在「" + place + "」，色调却是「" + stage.getAttribute("data-tone") + "」");
      var lights = Object.keys(art.time_light).map(function (k) { return art.time_light[k]; });
      lights.push(art.default_light);
      need(lights.indexOf(stage.getAttribute("data-light")) >= 0,
        "明暗「" + stage.getAttribute("data-light") + "」不在台账里");
    }
  });

  check("选项区列出可选动作", function () {
    var label = START_SCENE.choices[0].label;
    need(paneText("options-body").indexOf(label) >= 0,
      "选项区里没有「" + label + "」；实得「" + brief(byId("options-body")) + "」");
  });

  check("敲档号能阅档", function () {
    var did = pack.starter_dossiers[0];
    var title = pack.dossiers[did].title;
    cmd(did);
    need(paneText("reading-body").indexOf(title) >= 0,
      "敲 " + did + " 后阅读区没有出现「" + title + "」；实得「" + brief(byId("reading-body")) + "」");
  });

  check("「档目」列出幕次", function () {
    cmd("档目");
    var act = pack.act_titles[String(pack.act_numbers[0])];
    need(appText().indexOf(act) >= 0, "档目里没有「" + act + "」");
  });

  check("「查」能检索已读档案", function () {
    var term = pack.dossiers[pack.starter_dossiers[0]].title.slice(0, 2);
    cmd("查 " + term);
    need(appText().indexOf(term) >= 0, "检索「" + term + "」后屏幕上找不到这个词");
    need(appText().indexOf("没有") < 0 || appText().indexOf("已阅的档案里没有") < 0,
      "检索「" + term + "」报「已阅的档案里没有」——说明刚才那份档其实没被读过");
  });

  check("「记」写进记事簿", function () {
    cmd("记 冒烟测试用的一句话");
    need(appText().indexOf("冒烟测试用的一句话") >= 0, "记事簿里没有刚写下的那句话");
  });

  check("「帮助」出浮层、Esc 关掉", function () {
    cmd("帮助");
    var overlay = byId("overlay");
    need(overlay, "敲「帮助」后没有浮层");
    need(textOf(overlay).indexOf("阅档") >= 0, "帮助浮层里没有「阅档」一节");
    esc();
    need(!byId("overlay"), "按 Esc 之后浮层还在");
  });

  check("「存档」写进本机存档", function () {
    cmd("存档");
    var raw = storage.getItem("gongwei_save");
    need(raw, "敲「存档」后本机没有 gongwei_save");
    var data = JSON.parse(raw);
    need(data.v === 1, "存档版本号应为 1，实为 " + JSON.stringify(data.v));
    need(data.state && data.state.scene, "存档里没有 state.scene");
  });

  check("「读档」开存读面板，点「读本机存档」不出错", function () {
    cmd("读档");
    var overlay = byId("overlay");
    need(overlay, "敲「读档」后没有开存读面板");
    var back = buttons(overlay, "读本机存档");
    need(back.length === 1, "存读面板里找不到唯一的「读本机存档」按钮（找到 " + back.length + " 个）");
    back[0].click();
    var toasts = paneText("toasts");
    need(toasts.indexOf("还不能调阅") < 0 && toasts.indexOf("读档失败") < 0,
      "读档报错：「" + brief(byId("toasts")) + "」");
    need(appText().indexOf(String(START_SCENE.body).slice(0, 12)) >= 0,
      "读档后卷宗回到了别的地方");
  });

  check("各条指令都不炸", function () {
    var cmds = ["帮助", "关于", "档目", "记事", "检索", "搜 银针", "查 尸格",
      "记 再记一句", "改 1 改过的", "删 1", "冒烟", "123", "没见过的指令"];
    cmds.forEach(function (text) {
      cmd(text);
      esc();
    });
    // 折腾完之后回到游戏屏，后面的检查才有输入框可用
    if (buttons(app(), "新案").length === 1) { clickButton("新案"); }
    need(byId("cmd"), "折腾一圈之后回不到游戏屏（没有 #cmd）");
  });

  check("帮助里列的那些敲法，网页自己真的都认", function () {
    // 表在 ui.js 里是硬编码的，所以直接读源码把行首那几格刮出来；
    // 表改了而这里没跟上，下面的两条断言就会红。
    var src = fs.readFileSync(UI_FILE, "utf8");
    var head = src.indexOf('if (kind === "help")');
    need(head >= 0, "ui.js 里找不到帮助浮层的分支");
    var tail = src.indexOf('} else if (kind === "about")', head);
    need(tail > head, "帮助浮层与「关于」之间那段代码不见了");
    var block = src.slice(head, tail);
    var rows = [];
    var re = /\["((?:[^"\\]|\\.)*)",\s*"/g;
    var m;
    while ((m = re.exec(block)) !== null) { rows.push(m[1]); }
    need(rows.length >= 8, "帮助表只刮出 " + rows.length + " 行，正则或表结构变了");

    // 每一行都要有交代：要么给出「照它敲什么」的样例，要么登记成非指令的说明行。
    var SAMPLES = {
      "01-FY-XFE": "01-FY-XFE",
      "档目": "档目",
      "搜 银针": "搜 银针",
      "记 皇后在说谎": "记 皇后在说谎",
      "删 2": "删 2",
      "存档 / 读档": "存档",
      "重来 / 离开": "重来",
      "直接敲选项上的字": "",
      "数字 1-9": "",
      "↑ ↓（行里有字时）": ""
    };
    rows.forEach(function (key) {
      need(Object.prototype.hasOwnProperty.call(SAMPLES, key),
        "帮助表里多了一行「" + key + "」，测试没跟上：给它一个能敲的样例，或登记成非指令行");
    });
    Object.keys(SAMPLES).forEach(function (key) {
      need(rows.indexOf(key) >= 0, "帮助表里少了「" + key + "」这一行");
    });

    var bad = [];
    Object.keys(SAMPLES).forEach(function (key) {
      var sample = SAMPLES[key];
      if (!sample) { return; }
      cmd(sample);
      var screen = appText() + " " + paneText("toasts");
      if (screen.indexOf("看不明白：「" + sample + "」") >= 0) { bad.push(sample); }
      esc();                              // 关掉可能开着的浮层（读档 / 重来）
    });
    need(bad.length === 0, "帮助里写了、网页却敲不通：" + bad.join(" / "));
    need(byId("cmd"), "走完这一圈回不到游戏屏（没有 #cmd）");
  });

  check("判决屏节拍与跨案指认（JS 侧与 Python 一致）", function () {
    var GAME = win.GongweiGame;
    var third = new GAME.Game(pack);
    third.newGame();
    third.state.case = 3;
    need(third.verdictTarget("HD") === "verdict3_HD",
      "案③ 里指认陛下被送到「" + third.verdictTarget("HD") + "」");
    third.goTo("verdict3_HD");
    var beats = third.state.log.filter(function (row) {
      return row[0] === "scene" && String(row[1]).indexOf("【判决】") === 0;
    });
    need(beats.length === 1, "判决屏标题记进卷宗的次数是 " + beats.length);
    need(beats[0][1] === "【判决】" + pack.scenes.verdict3_HD.title,
      "卷宗里的判决标题是「" + beats[0][1] + "」");

    var first = new GAME.Game(pack);
    first.newGame();
    first.state.case = 1;
    need(first.verdictTarget("HD") === "verdict_HD",
      "案① 里指认陛下被送到「" + first.verdictTarget("HD") + "」");
  });

  check("网页的命令行也认 ↑ ↓ 翻指令历史（与终端一致）", function () {
    cmd("档目");                       // 先提交一条真指令进历史
    var input = byId("cmd");
    need(input, "敲完「档目」后命令行不见了");
    input.value = "银";
    keyOn(input, "ArrowUp");           // 行里有字 → 翻历史，不是挪光标
    need(input.value === "档目", "↑ 之后行里变成了「" + input.value + "」");
    keyOn(input, "ArrowDown");         // 再按回来 = 回到还没提交的草稿
    need(input.value === "银", "↓ 之后行里变成了「" + input.value + "」");
    keyOn(input, "Escape");            // 收尾：清空草稿，别把状态漏给后面的检查
    need(input.value === "", "Escape 没清掉命令行");
  });

  check("「案外」页：幕册 / 结局册 / 行囊 / 音画设定", function () {
    var tabs = buttons(app(), "案外");
    need(tabs.length === 1, "找不到「案外」页签（找到 " + tabs.length + " 个）");
    tabs[0].click();
    var text = appText();
    ["幕册", "结局册", "行囊", "音画设定"].forEach(function (word) {
      need(text.indexOf(word) >= 0, "「案外」页里没有「" + word + "」这一节");
    });
    need(text.indexOf("未至") >= 0, "还没到过的幕没有标「未至」");
    // 收集册只记「到过哪儿」：没到过的幕，连幕名都不许先漏出来
    var raw = storage.getItem("gongwei_marks");
    need(raw, "「案外」没把进度写进本机（gongwei_marks）：" + String(raw));
    var marks = JSON.parse(raw);
    need(marks.acts && marks.acts.length >= 1, "marks.acts 里没有已至的幕：" + raw);
    Object.keys(pack.act_titles).forEach(function (key) {
      var title = String(pack.act_titles[key]);
      if (title.length < 3 || marks.acts.indexOf(Number(key)) >= 0) { return; }
      need(text.indexOf(title) < 0,
        "第 " + key + " 幕还没到过，「案外」却把幕名「" + title + "」写出来了");
    });
    buttons(app(), "卷宗")[0].click();          // 收尾：别把页签状态漏给后面的检查
  });

  check("音画设定：点一下当场生效，也写进本机", function () {
    buttons(app(), "案外")[0].click();
    var rows = query(app(), ".setting-row");
    need(rows.length === 4, "音画设定该是四行，实得 " + rows.length + " 行");
    need(brief(rows[0]).indexOf("动效") >= 0, "第一行不是「动效」：" + brief(rows[0]));
    var off = buttons(rows[0], "关");
    need(off.length === 1, "「动效」行里找不到唯一的「关」按钮（找到 " + off.length + " 个）");
    off[0].click();
    var saved = JSON.parse(storage.getItem("gongwei_settings") || "null");
    need(saved && saved.motion === "off",
      "点了「关」之后本机设定是 " + String(storage.getItem("gongwei_settings")));
    need(doc.body.getAttribute("data-motion") === "off",
      "body 上的 data-motion 还是「" + doc.body.getAttribute("data-motion") + "」，动效没当场关掉");
    var back = buttons(query(app(), ".setting-row")[0], "开");
    need(back.length === 1, "「动效」行里找不到唯一的「开」按钮（找到 " + back.length + " 个）");
    back[0].click();
    need(JSON.parse(storage.getItem("gongwei_settings")).motion === "on", "动效开不回来了");
    buttons(app(), "卷宗")[0].click();
  });

  check("顶栏分主次：四项读数带 meta-extra，窄屏交给 CSS 收", function () {
    // 收不收是 CSS 的事（@media max-width:899px），这里只管两件事：
    // 该收的那四项真的带了记号，该留的「幕 / 时辰 / 所在」没被一起收走。
    var extra = query(app(), ".meta-extra");
    var words = ["回合", "评分", "行囊", "线索"];
    need(extra.length === words.length,
      "顶栏该有 " + words.length + " 项读数带 meta-extra，实得 " + extra.length + " 项");
    var text = extra.map(function (node) { return textOf(node); }).join(" ");
    words.forEach(function (word) {
      need(text.indexOf(word) >= 0, "带 meta-extra 的读数里少了「" + word + "」：" + text);
    });
    var head = appText();
    ["幕 ", "时辰 ", "所在 "].forEach(function (word) {
      need(head.indexOf(word) >= 0, "顶栏把「" + word.trim() + "」也收起来了：" + brief(app()));
    });
  });

  check("浮层的出口：顶上「收起」当场合上，body 上记着有没有遮罩", function () {
    cmd("帮助");
    var overlay = byId("overlay");
    need(overlay, "敲「帮助」后没有开帮助浮层");
    need(doc.body.getAttribute("data-overlay") === "1",
      "开着浮层时 body 上没有 data-overlay=1（实为「" +
      doc.body.getAttribute("data-overlay") + "」）");
    var top = query(overlay, ".sheet-top");
    need(top.length === 1, "浮层顶上没有那条常驻出口（找到 " + top.length + " 条）");
    need(textOf(top[0]).indexOf("Esc 可合上") >= 0, "顶上那条不是按键提示：" + brief(top[0]));
    var shut = buttons(top[0], "收起");
    need(shut.length === 1, "顶上找不到唯一的「收起」按钮（找到 " + shut.length + " 个）");
    shut[0].click();
    need(!byId("overlay"), "点了「收起」浮层还在");
    need(doc.body.getAttribute("data-overlay") !== "1",
      "合上浮层之后 body 上还留着 data-overlay=1");
  });

  if (SEED_SAVE) {
    check("读回一份结案存档", function () {
      var data = JSON.parse(fs.readFileSync(SEED_SAVE, "utf8"));
      storage.setItem("gongwei_save", JSON.stringify(data));
      var eid = data.state.ending;
      need(eid && pack.scenes[eid], "存档里的 ending「" + eid + "」不在内容包里");
      cmd("读档");
      var overlay = byId("overlay");
      need(overlay, "敲「读档」后没有开存读面板");
      var back = buttons(overlay, "读本机存档");
      need(back.length === 1, "存读面板里找不到唯一的「读本机存档」按钮");
      back[0].click();
      need(appText().indexOf("已结案") >= 0, "读回结案存档后顶栏没写「已结案」");
      var body = String(pack.scenes[eid].body).slice(0, 12);
      need(appText().indexOf(body) >= 0,
        "结局屏上没有结局正文「" + body + "」；实得「" + brief(app()) + "」");
    });

    // 全篇真正带人名的话只有 07-DL-TWO 里的三行供词（郑守拙 / 柳青 / 贺小五），
    // 同一份档案里还躺着两行「……：」的旁白——名牌与旁白必须分得开。
    check("说话人名牌：名字真在人物表里才点金", function () {
      var data = JSON.parse(fs.readFileSync(SEED_SAVE, "utf8"));
      data.state.dossiers["07-DL-TWO"] = [true, false];
      storage.setItem("gongwei_save", JSON.stringify(data));
      cmd("读档");
      var overlay = byId("overlay");
      need(overlay, "敲「读档」后没有开存读面板");
      var back = buttons(overlay, "读本机存档");
      need(back.length === 1, "存读面板里找不到唯一的「读本机存档」按钮");
      back[0].click();
      cmd("07-DL-TWO");
      var pane = byId("reading-body");
      need(pane, "阅档后阅读区不见了");
      var names = query(pane, ".said-name").map(function (n) { return textOf(n); });
      need(names.length === 3, "07-DL-TWO 里该有三行名牌，实得 " + names.length + " 个：" + names.join(" / "));
      ["郑守拙：", "柳青：", "贺小五："].forEach(function (who) {
        need(names.indexOf(who) >= 0, "名牌里少了「" + who + "」，实得 " + names.join(" / "));
      });
      var text = paneText("reading-body");
      need(text.indexOf("三句放在一起：") >= 0 && text.indexOf("只有一种可能：") >= 0,
        "旁白里的冒号被当成名牌、正文也被拆坏了：" + brief(pane));
      need(text.indexOf("郑守拙：蒋九整夜都在值房抄账，咱家没见他出去。") >= 0,
        "套上名牌之后那一行改动了：" + brief(pane));
    });

    // 档案正文里有以 // 开头的旁注行（01-FY-XFE 的尸格里两处）：整行降一档、
    // 只把开头的 // 点金——但 pane 文本必须与从前逐字相同（终端版也是原样印的）。
    check("档案里的 // 旁注行：淡墨点金，字一个不改", function () {
      var data = JSON.parse(fs.readFileSync(SEED_SAVE, "utf8"));
      data.state.dossiers["01-FY-XFE"] = [true, false];
      storage.setItem("gongwei_save", JSON.stringify(data));
      cmd("读档");
      var overlay = byId("overlay");
      need(overlay, "敲「读档」后没有开存读面板");
      var back = buttons(overlay, "读本机存档");
      need(back.length === 1, "存读面板里找不到唯一的「读本机存档」按钮");
      back[0].click();
      cmd("01-FY-XFE");
      var pane = byId("reading-body");
      need(pane, "阅档后阅读区不见了");
      var notes = query(pane, ".note-line");
      need(notes.length === 2 || notes.length === 3,
        "01-FY-XFE 的尸格里该有两三行旁注，实得 " + notes.length + " 行：" + brief(pane, 200));
      var text = paneText("reading-body");
      need(text.indexOf("//另有一事记在尸格末尾") >= 0,
        "第一处旁注的字被改动了：" + brief(pane, 300));
      need(text.indexOf("//份档号：01-FY-XFE-2、01-FY-WDH") >= 0,
        "档号那行旁注的字被改动了：" + brief(pane, 300));
      query(pane, ".note-mark").forEach(function (mark) {
        need(textOf(mark) === "//", "旁注行的 // 被换成了「" + textOf(mark) + "」");
      });
      need(text.indexOf("苏氏，年二十有七，六妃之一，居凤仪殿。") >= 0,
        "旁注样式把正文也一起吞了：" + brief(pane, 300));
    });
  }
}

// ---------------------------------------------------------------------------
// 原型 v1.1 的插画形制：只许加 class 与节点，文字口径一字不改
// ---------------------------------------------------------------------------

if (booted) {
  function titleOf(node) {
    return node ? String(node.title || node.getAttribute("title") || "") : "";
  }
  function topAction(word) {
    return query(app(), ".top-actions button").filter(function (b) { return titleOf(b) === word; });
  }
  function splashOn() {
    var s = byId("splash");
    return !!(s && (" " + s.className + " ").indexOf(" on ") >= 0);
  }
  function panelButton(word) {
    return query(app(), ".panel-head button").filter(function (b) { return textOf(b) === word; });
  }
  function backToTitle() {
    var home = topAction("回到标题");
    need(home.length === 1, "顶栏上找不到唯一的「回到标题」图标键（找到 " + home.length + " 个）");
    home[0].click();
  }
  function loadSeed(mutate) {
    var data = JSON.parse(fs.readFileSync(SEED_SAVE, "utf8"));
    mutate(data);
    storage.setItem("gongwei_save", JSON.stringify(data));
    cmd("读档");
    var overlay = byId("overlay");
    need(overlay, "敲「读档」后没有开存读面板");
    var back = buttons(overlay, "读本机存档");
    need(back.length === 1, "存读面板里找不到唯一的「读本机存档」按钮");
    back[0].click();
    return data;
  }

  if (SEED_SAVE) {
    // 全篇真正带人名的话只有 07-DL-TWO 里的三行供词（郑守拙 / 柳青 / 贺小五）：
    // 把档记成「在册、未读」再读一次，正文才会整段进卷宗。
    check("对话行新皮：说话人点金，正文一字不改", function () {
      loadSeed(function (data) { data.state.dossiers["07-DL-TWO"] = [false, false]; });
      cmd("07-DL-TWO");
      var pane = byId("reading-body");
      need(pane, "阅档后阅读区不见了");
      var body = String((pack.dossiers["07-DL-TWO"] || {}).body || "");
      need(body.length > 40, "内容包里 07-DL-TWO 没有正文，这条检查会空转");
      need(paneText("reading-body").indexOf("三句放在一起：") >= 0,
        "阅档时旁白被拆坏了：" + brief(pane, 120));
      var shut = panelButton("收档");
      need(shut.length === 1, "档案读开后找不到唯一的「收档」按钮（找到 " + shut.length + " 个）");
      shut[0].click();
      var rows = query(app(), ".log-entry").filter(function (n) {
        return (" " + n.className + " ").indexOf(" dlg ") >= 0;
      });
      need(rows.length === 1, "07-DL-TWO 该有且只有一条对话行，实得 " + rows.length + " 条");
      var cls = " " + rows[0].className + " ";
      need(cls.indexOf(" log-entry ") >= 0 && cls.indexOf(" dlg ") >= 0,
        "对话行少了 log-entry / dlg 记号：" + rows[0].className);
      var names = query(rows[0], ".said-name").map(function (n) { return textOf(n); });
      need(names.length === 3, "对话行里该有三个名牌，实得 " + names.length + " 个：" + names.join(" / "));
      ["郑守拙：", "柳青：", "贺小五："].forEach(function (who) {
        need(names.indexOf(who) >= 0, "名牌里少了「" + who + "」，实得 " + names.join(" / "));
      });
      need(textOf(rows[0]) === body, "套上名牌之后正文被改动了：卷宗里 " + textOf(rows[0]).length +
        " 字 / 档案原文 " + body.length + " 字 —— " + brief(rows[0], 120));
      var text = paneText("reading-body");
      ["三句放在一起：", "只有一种可能：", "郑守拙：蒋九整夜都在值房抄账，咱家没见他出去。",
        "柳青：戌时前后，蒋九拿着抄本来问我，我说你去问掌局，他就走了。"].forEach(function (line) {
        need(text.indexOf(line) >= 0, "卷宗里少了那句「" + line + "」");
      });
    });

    check("【线索】/【物证】的记号只包前缀，整行一字不改", function () {
      var pane = byId("reading-body");
      need(pane, "现在不在卷宗页上，读不到线索行");
      var rows = query(pane, ".kv-line");
      need(rows.length >= 20, "卷宗页里的 【线索】/【物证】 行只剩 " + rows.length + " 条，这条检查会空转");
      var kvs = query(pane, ".kv");
      var marked = query(pane, ".kv-line .kv");
      need(kvs.length === marked.length,
        "有 " + (kvs.length - marked.length) + " 个 .kv 记号没长在 【线索】/【物证】 行里");
      var wuyi = 0;
      rows.forEach(function (row) {
        var marks = query(row, ".kv");
        need(marks.length === 1, "一行里套了 " + marks.length + " 个记号：" + brief(row, 60));
        var mark = textOf(marks[0]);
        need(mark === "【线索】" || mark === "【物证】", "记号里包的不只是前缀：「" + mark + "」");
        if (mark === "【物证】") { wuyi += 1; }
        var whole = textOf(row).replace(/^\s+/, "");
        need(whole.indexOf(mark) === 0, "整行不是以记号开头的：" + brief(row, 60));
        need(whole.length > mark.length + 3, "记号之后没有正文了：" + brief(row, 60));
      });
      need(wuyi >= 1, "卷宗里一条 【物证】 行都没有，这条检查会空转");
      need(paneText("reading-body").indexOf("【线索】银针验毒结果 —— ") >= 0,
        "线索行的字被改动了：" + paneText("reading-body").slice(0, 100));
    });

    // 坏档：Python 那边（gongwei/game/save.py）拒收的形状，网页版也必须拒收 ——
    // 同一份档两端给相反的答案最坑人。两条：`v` 太新（ui.js 的 saveVersionError）
    // 与 `dossiers` 的值不成对（game.js 的 fromSave 抛错，以前会静默读成 [false,false]）。
    check("坏档：版本太新、档案状态不成对，两端都读不进来", function () {
      var cases = [
        { what: "版本太新", word: "太新",
          mutate: function (d) { d.v = 2; } },
        { what: "档案状态不成对", word: "不成对",
          mutate: function (d) { d.state.dossiers["01-FY-01"] = true; } }
      ];
      cases.forEach(function (item) {
        var data = JSON.parse(fs.readFileSync(SEED_SAVE, "utf8"));
        item.mutate(data);
        storage.setItem("gongwei_save", JSON.stringify(data));
        // 第一轮从游戏屏回标题屏；第二轮本来就站在标题屏上（上一轮没读进去）。
        if (query(app(), ".top-actions").length === 1) { backToTitle(); }
        need(!byId("reading-body"), item.what + "：没回到标题屏 —— " + brief(app(), 60));
        var entry = buttons(app(), "续前案");
        need(entry.length === 1,
          item.what + "：标题屏上找不到唯一的「续前案（读档）」入口（找到 " + entry.length + " 个）");
        entry[0].click();
        var told = paneText("toasts");
        need(told.indexOf(item.word) >= 0,
          item.what + "：读不进来却没说清原因（toasts 里是「" + brief(byId("toasts"), 120) + "」）");
        need(!byId("reading-body"),
          item.what + "：坏档居然读进去了 —— " + brief(app(), 120));
      });
      // 把状态还给后面的检查：先「新案」回到轴上，再读一份正规存档。
      var fresh = buttons(app(), "新案");
      need(fresh.length === 1,
        "标题屏上找不到唯一的「新案」入口（找到 " + fresh.length + " 个）");
      fresh[0].click();
      loadSeed(function () {});
      need(byId("reading-body"), "做完坏档检查之后，正规存档也读不回来了");
    });

    check("行动记录折叠条：aria 跟着开合走，条数与卷宗对得上", function () {
      var bars = query(app(), ".log-bar");
      need(bars.length === 1, "卷宗页上该有一条行动记录折叠条，实得 " + bars.length + " 条");
      var btn = query(bars[0], ".log-toggle")[0];
      need(btn, "折叠条上没有那个按钮");
      need(query(btn, ".caret").length === 1, "折叠条上没有右侧箭头");
      var pane = byId("reading-body");
      need(pane, "卷宗页不见了");
      var total = query(pane, ".log-entry").length;
      need(total > 20, "卷宗里只有 " + total + " 条记录，这条检查会空转");
      need(btn.getAttribute("aria-expanded") === "true",
        "展开时 aria-expanded 是「" + btn.getAttribute("aria-expanded") + "」");
      var count = query(bars[0], ".count");
      need(count.length === 1, "折叠条右边没有条数");
      need(textOf(count[0]) === total + " 则",
        "条数写的是「" + textOf(count[0]) + "」，卷宗里却有 " + total + " 条");
      btn.click();
      need(query(byId("reading-body"), ".log-entry").length === 0, "折起来之后记录还留在正文里");
      need(query(byId("reading-body"), ".log-bar").length === 1, "折起来之后连折叠条也一起没了");
      need(query(app(), ".log-toggle")[0].getAttribute("aria-expanded") === "false",
        "折起来之后 aria-expanded 没跟着变成 false");
      query(app(), ".log-toggle")[0].click();
      need(query(byId("reading-body"), ".log-entry").length === total,
        "再点回来记录变了：" + query(byId("reading-body"), ".log-entry").length + " 条");
      need(query(app(), ".log-toggle")[0].getAttribute("aria-expanded") === "true",
        "再点回来 aria-expanded 没回到 true");
    });

    check("右栏四张仪表卡：信任条按 confide_at 折算，到线才点金", function () {
      // 先退回存档那一刻：上一条检查读过一份档案，会把存档里的线索数顶高一枚。
      loadSeed(function () {});
      var cards = query(app(), ".rail-card");
      need(cards.length === 4, "右栏该有四张仪表卡，实得 " + cards.length + " 张");
      var heads = cards.map(function (c) { return brief(query(c, ".panel-head")[0], 30); });
      ["进度", "人物心意", "线索囊", "随身之物"].forEach(function (word, i) {
        need(heads[i].indexOf(word) >= 0, "第 " + (i + 1) + " 张卡不是「" + word + "」：" + heads[i]);
      });
      var stats = query(cards[0], ".rail-stat");
      need(stats.length === 3, "进度卡该有三行读数，实得 " + stats.length + " 行");
      stats.forEach(function (s) {
        need(query(s, ".rail-label").length === 1 && query(s, ".rail-num").length === 1,
          "读数行没有拆成「标签 + 数字」：" + brief(s, 30));
      });
      var data = JSON.parse(fs.readFileSync(SEED_SAVE, "utf8"));
      var chars = pack.characters || {};
      var ids = Object.keys(chars);
      var rows = query(app(), ".trust-row");
      need(rows.length === ids.length, "人物心意该有 " + ids.length +
        " 行（与人物表同数），实得 " + rows.length + " 行");
      need(rows.length >= 10, "人物表只有 " + rows.length + " 人，这条检查会空转");
      var bars = 0;
      var candie = 0;
      var forever = 0;
      ids.forEach(function (cid, i) {
        var ch = chars[cid] || {};
        var name = ch.name || cid;
        var now = Number((data.state.trust || {})[cid] || 0);
        var at = Number(ch.confide_at);
        if (!isFinite(at) || at <= 0) { at = 999; }
        var row = rows[i];
        var label = query(row, ".trust-name");
        need(label.length === 1, "「" + name + "」那行没有名字");
        need(textOf(label[0]) === name, "第 " + (i + 1) + " 行该是「" + name + "」，写的是「" +
          textOf(label[0]) + "」");
        var num = query(row, ".trust-num");
        need(num.length === 1 && textOf(num[0]) === String(now),
          "「" + name + "」那行的当前心意该是 " + now + "，写的是「" +
          (num.length ? textOf(num[0]) : "没有") + "」");
        var fills = query(row, ".trust-fill");
        if (at === 999) {
          need(fills.length === 0, "「" + name + "」的 confide_at 是 999，却还画了一条信任条");
          forever += 1;
        } else {
          need(fills.length === 1, "「" + name + "」该有一条信任条，实得 " + fills.length + " 条");
          bars += 1;
          var style = String(fills[0].getAttribute("style") || "");
          need(style.indexOf("width:") === 0 && /%$/.test(style),
            "「" + name + "」的信任条宽度不是按 confide_at 折算的：" + style);
        }
        var dots = query(row, ".trust-candie").length;
        var want = at !== 999 && now >= at ? 1 : 0;
        need(dots === want, "「" + name + "」的心意 " + now + " / 深谈线 " + at + "，金点该是 " +
          want + " 枚，实得 " + dots + " 枚");
        candie += dots;
      });
      need(forever >= 1, "人物表里没有 confide_at=999 的人，这条检查会空转");
      need(bars >= 1, "人物表里没有一个能画条的人，这条检查会空转");
      need(candie >= 1, "没有一个到线的人，这条检查会空转");
      need(heads[1].indexOf(candie + " 人可深谈") >= 0,
        "「人物心意」的计数该是 " + candie + " 人可深谈，写的是「" + heads[1] + "」");
      need(brief(cards[0], 60).indexOf(data.state.clues.length + "/" + pack.core_total) >= 0,
        "进度卡的线索数没跟着存档走：" + brief(cards[0], 60));
      var clues = data.state.clues.length;
      need(clues >= 5, "存档里的线索只有 " + clues + " 条，这条检查会空转");
      need(query(app(), ".clue-chip").length === Math.min(5, clues),
        "线索囊该摆最近五条（" + Math.min(5, clues) + " 枚），实得 " + query(app(), ".clue-chip").length + " 枚");
      need(query(app(), ".item-chip").length === data.state.items_owned.length,
        "随身之物该有 " + data.state.items_owned.length + " 枚，实得 " + query(app(), ".item-chip").length + " 枚");
    });
  }

  check("标题屏的落花与印章只做样子，一个字都不吐", function () {
    backToTitle();
    need(query(app(), ".title-screen").length === 1, "没回到标题屏：" + brief(app(), 60));
    var petals = query(app(), ".petal");
    need(petals.length === 10, "落花该有 10 片，实得 " + petals.length + " 片");
    var wrap = query(app(), ".petals");
    need(wrap.length === 1, "落花外面没有那一层容器（找到 " + wrap.length + " 个）");
    need(wrap[0].getAttribute("aria-hidden") === "true", "落花那一层没标 aria-hidden");
    petals.forEach(function (p, i) {
      need(textOf(p) === "", "第 " + (i + 1) + " 片花瓣里塞了字：「" + textOf(p) + "」");
      need(p.children.length === 0, "第 " + (i + 1) + " 片花瓣里还挂了 " + p.children.length + " 个节点");
      need(p.parent === wrap[0], "有一片花瓣没长在落花那一层里");
    });
    var badge = query(app(), ".seal-badge");
    need(badge.length === 1, "标题屏上没有印章（找到 " + badge.length + " 个）");
    need(query(badge[0], "svg").length >= 1, "印章里没有 svg 图形");
    var credit = query(app(), ".credit");
    need(credit.length === 1 && brief(credit[0], 40).length > 0, "标题屏页脚那行小字不见了");
    // 装饰不许伪造正文容器：标题屏上根本没有 #reading-body，落花也就无处落进正文。
    need(byId("reading-body") === null, "标题屏上冒出了 #reading-body");
    need(paneText("reading-body") === "", "标题屏的正文口径不是空的：" + paneText("reading-body"));
  });

  check("卷首过场：点「新案」起幕帘，Esc 与轻触都能落下", function () {
    clickButton("新案");
    need(splashOn(), "点「新案」后没有出现卷首过场");
    var sp = byId("splash");
    var seal = brief(query(app(), ".seal")[0], 16);
    var m = /第\s*(\d+)\s*幕/.exec(seal);
    need(m, "顶栏上读不出当前是第几幕：" + seal);
    var want = String(pack.act_titles[m[1]]);
    need(textOf(query(sp, ".splash-title")[0]) === want,
      "过场上的幕名是「" + textOf(query(sp, ".splash-title")[0]) + "」，第 " + m[1] + " 幕叫「" + want + "」");
    [".splash-veil", ".splash-card", ".splash-art", ".splash-num", ".splash-title",
      ".splash-quote", ".seal-stamp", ".splash-hint"].forEach(function (sel) {
      need(query(sp, sel).length === 1, "过场里少了 " + sel);
    });
    esc();
    need(!splashOn(), "按 Esc 之后幕帘还挂着");
    need(byId("reading-body"), "落下幕帘之后没回到游戏屏");
    backToTitle();
    clickButton("新案");
    need(splashOn(), "第二次点「新案」没有过场");
    // 假 DOM 不冒泡：轻触幕帘本身（真浏览器里点卡片也浮到这一层）
    byId("splash").click();
    need(!splashOn(), "轻触幕帘之后它没落下");
    need(byId("reading-body"), "落下幕帘之后没进游戏屏");
  });

  check("游戏屏顶栏：图标键只带 aria/title，不跟文字按钮抢名字", function () {
    var bar = query(app(), ".topbar");
    need(bar.length === 1, "游戏屏上没有 .topbar（找到 " + bar.length + " 个）");
    var head = textOf(bar[0]);
    need(head.indexOf(pack.title) >= 0, "顶栏上没有剧名「" + pack.title + "」");
    need(/第\s*\d+\s*幕/.test(head), "顶栏上没有「第 N 幕」：" + brief(bar[0], 60));
    var chips = query(app(), ".hud-chip");
    need(chips.length >= 4, "顶栏读数只挂了 " + chips.length + " 枚");
    var actions = query(app(), ".top-actions");
    need(actions.length === 1, "顶栏上没有那排图标键（找到 " + actions.length + " 排）");
    var icons = query(actions[0], "button");
    need(icons.length === 5, "图标键该有 5 枚，实得 " + icons.length + " 枚");
    icons.forEach(function (b, i) {
      need(textOf(b) === "", "第 " + (i + 1) + " 枚图标键带了文字「" + textOf(b) +
        "」，会跟文字按钮抢名字");
      need(String(b.getAttribute("aria-label") || "").length > 0, "第 " + (i + 1) + " 枚图标键没写 aria-label");
      need(titleOf(b).length > 0, "第 " + (i + 1) + " 枚图标键没写 title");
    });
    need(buttons(app(), "案外").length === 1, "「案外」按钮变成了 " + buttons(app(), "案外").length +
      " 个（图标键抢了名字？）");
    need(buttons(app(), "新案").length === 0, "游戏屏上冒出了 " + buttons(app(), "新案").length + " 个「新案」按钮");
  });

  check("选项卡：序号与标签分家，没开的选项整条不出现", function () {
    var cards = query(app(), ".choice-card");
    need(cards.length >= 2, "选项区只有 " + cards.length + " 张卡，这条检查会空转");
    cards.forEach(function (card, i) {
      var nums = query(card, ".choice-num");
      need(nums.length === 1, "第 " + (i + 1) + " 张卡上找不到序号");
      need(textOf(nums[0]) === String(i + 1), "第 " + (i + 1) + " 张卡的序号写的是「" + textOf(nums[0]) + "」");
      need(query(card, ".choice-label").length === 1, "第 " + (i + 1) + " 张卡上找不到标签");
      // 门禁不摆在桌上（硬规则 11）：桌上只有真能做的事，没有「灰置 + 条件不足」
      // 那一档 —— 卡上既不该带 locked 记号，也不该挂 .lock-chip。
      need((" " + card.className + " ").indexOf(" locked ") < 0,
        "第 " + (i + 1) + " 张卡还带着 locked 记号：" + card.className);
      need(query(card, ".lock-chip").length === 0,
        "第 " + (i + 1) + " 张卡上还挂着锁定提示：" + brief(card, 60));
      need(textOf(card).indexOf("条件不足") < 0, "第 " + (i + 1) + " 张卡上写着「条件不足」");
    });
    need(appText().indexOf("条件不足") < 0,
      "页面上还留着「条件不足」四个字：" + brief(app(), 200));
    var pick = cards[0];
    need(pick, "开局一张选项卡都没有");
    var labelNode = query(pick, ".choice-label")[0];
    // 卡面上标签与细节（.detail）同住 label 这一层，卷宗里只记标签那一截。
    var label = textOf(labelNode);
    query(labelNode, ".detail").forEach(function (n) {
      label = label.replace(textOf(n), "");
    });
    need(label.length > 0, "这张卡上没有标签：" + brief(pick, 40));
    var before = paneText("reading-body");
    pick.click();
    var after = paneText("reading-body");
    need(after.length > before.length, "点了一项之后卷宗没有接着记");
    // 换了场景之后，旧条目的幕名会跟着改写（那是既有口径），所以按期望串做包含判断。
    need(after.indexOf(String(START_SCENE.body).slice(0, 12)) >= 0,
      "点了一项之后开局那段正文被改掉了：" + brief(byId("reading-body"), 80));
    var choices = query(app(), ".log-choice");
    need(choices.length >= 1, "答话那行没进卷宗（找不到 .log-choice）");
    need(textOf(choices[choices.length - 1]) === label,
      "卷宗里记的是「" + textOf(choices[choices.length - 1]) + "」，按钮上写的是「" + label + "」");
  });

  check("种一份审讯存档：被门禁挡住的话题整条不出现，理由也不许露出来", function () {
    // 固定存档 + 固定改写：把结案存档倒回「案① 审讯王德海、这一案什么都还没查出」
    // 的那一刻。这一刻的选项表是**确定**的（同一份存档在 Python 侧算出来是同样三枚，
    // audit_web.py 逐字比对两端的选项表）：三枚能问、四枚被门禁挡着。挡住的那几枚
    // 整条都不该出现 —— 连它们的 locked_hint（写给审计排障看的理由）也不许飘到页面上。
    loadSeed(function (data) {
      var s = data.state;
      s.scene = "talk_wdh";
      s.ending = "";
      s.chapter = 1;
      s.case = 1;
      s.turn = 16;
      s.interrogating = "WDH";
      s.clues = [];
      s.items_owned = [];
      s.flags = [];
      s.topics_asked = [];
      s.seen_choices = [];
      s.log = [];
      s.open_dossier = "";
    });
    var dealt = ["再问一遍 · 今夜你几时进的殿",
                 "追问 · 那盏茶是谁送进去的",
                 "作揖告退 · 结束对「王德海」的问询"];
    var gated = ["逼问 · 你进过殿内",
                 "出示 · 尚药局领用簿上的七次取用",
                 "摊牌 · 采薇是被你办的",
                 "问他 · 为什么是她"];
    var cards = query(app(), ".choice-card");
    need(cards.length === dealt.length,
      "这一屏该摆 " + dealt.length + " 枚选项，实得 " + cards.length + " 枚：" + brief(app(), 200));
    var page = appText();
    dealt.forEach(function (label, i) {
      need(textOf(cards[i]).indexOf(label) >= 0,
        "第 " + (i + 1) + " 张卡该是「" + label + "」，写的是「" + brief(cards[i], 40) + "」");
    });
    gated.forEach(function (label) {
      need(page.indexOf(label) < 0, "被门禁挡住的「" + label + "」还摆在桌上");
    });
    need(page.indexOf("条件不足") < 0, "页面上还留着「条件不足」四个字");
    need(query(app(), ".lock-chip").length === 0, "页面上还挂着锁定提示");
  });
}
// ---------------------------------------------------------------------------

var failed = 0;
RESULTS.forEach(function (r) {
  if (r.ok) { console.log("OK " + r.name); }
  else { failed += 1; console.log("FAIL " + r.name + " :: " + r.detail); }
});
console.log("CHECKS " + RESULTS.length + " " + failed);
process.exit(failed ? 1 : 0);
