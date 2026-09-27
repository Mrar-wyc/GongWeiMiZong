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
  var app = makeNode("div");
  app.id = "app";
  body.appendChild(app);           // web/shell.html 里 body 只有一个 <div id="app">
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
var win = {
  __GONGWEI_PACK__: pack,
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

  check("点「新案」进第一幕", function () {
    clickButton("新案");
    need(byId("reading-body"), "开局后没有 #reading-body（阅读区没渲染）");
    var body = String(START_SCENE.body).slice(0, 12);
    need(paneText("reading-body").indexOf(body) >= 0,
      "卷宗里没有开场正文；应有「" + body + "」，实得「" + brief(byId("reading-body")) + "」");
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
  }
}

// ---------------------------------------------------------------------------

var failed = 0;
RESULTS.forEach(function (r) {
  if (r.ok) { console.log("OK " + r.name); }
  else { failed += 1; console.log("FAIL " + r.name + " :: " + r.detail); }
});
console.log("CHECKS " + RESULTS.length + " " + failed);
process.exit(failed ? 1 : 0);
