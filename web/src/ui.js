/* 宫闱迷踪 · 网页端界面
 *
 * 两种操作方式**并存**（与终端版同一套设计）：
 *   1. 在 › 后面敲档号或指令 —— 「查案」的主要动作（阅档、检索、记事）
 *   2. 点/选下面的动作列表 —— 对话与抉择
 *
 * 手机上按「卷宗 / 档目 / 记事 / 检索」分页；宽屏自动三栏铺开（纯 CSS 判断）。
 * 存档写 localStorage，形状与终端版逐字相同，可「导出/导入」在两端之间搬。
 */
"use strict";

(function () {
  var PACK = window.__GONGWEI_PACK__;
  if (!PACK) {
    document.body.innerHTML = "<p style='padding:20px'>内容包没带上：请用 tools/build_web.py 重新生成。</p>";
    return;
  }

  var SAVE_KEY = "gongwei_save";
  var Engine = window.GongweiGame;
  var game = new Engine.Game(PACK);

  var ui = {
    screen: "title",        // title | game
    read: "log",            // log | dossier | index | search
    dossier: "",            // 正在看的档号（read === "dossier" 时有意义）
    searchTerm: "",
    hits: [],
    cursor: 0,
    toasts: [],
    overlay: null,          // null | {kind:"help"|"save"|"load"|"restart"|"about"}
    tab: "log",
    history: [],
    histAt: -1,
    draft: ""
  };

  // ------------------------------------------------------------------
  // 小工具
  // ------------------------------------------------------------------

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) { node.className = cls; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  }

  function clear(node) { while (node.firstChild) { node.removeChild(node.firstChild); } }

  function esc(text) { return text === undefined || text === null ? "" : String(text); }

  function toast(message, kind) {
    ui.toasts.push({ text: message, kind: kind || "" });
    while (ui.toasts.length > 3) { ui.toasts.shift(); }
    renderToasts();
    setTimeout(function () {
      ui.toasts.shift();
      renderToasts();
    }, 2400);
  }

  function nowStamp() {
    var d = new Date();
    function p(n) { return (n < 10 ? "0" : "") + n; }
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) +
      " " + p(d.getHours()) + ":" + p(d.getMinutes());
  }

  function hasSave() {
    try { return !!window.localStorage.getItem(SAVE_KEY); } catch (e) { return false; }
  }

  function readSave() {
    try {
      var raw = window.localStorage.getItem(SAVE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }

  function writeSave() {
    try {
      var payload = game.save();
      payload.stamp = nowStamp();
      window.localStorage.setItem(SAVE_KEY, JSON.stringify(payload));
      return true;
    } catch (e) {
      toast("存档写不进去：" + e.message, "error");
      return false;
    }
  }

  // ------------------------------------------------------------------
  // 命令行
  // ------------------------------------------------------------------

  var DOSSIER_RE = /^\d{2}-[A-Za-z]{2,4}(?:-[A-Za-z0-9]+)*$/;

  function canonDossier(text) {
    // 与终端侧的 `command.py: canon_dossier_id` 对齐：NFKC 折全角（０１－ＦＹ）、
    // 各种分隔符一律折成连字符（01_fy_wdh）、合并连续连字符、去掉首尾连字符。
    return String(text).normalize("NFKC").toUpperCase()
      .replace(/[-_—–~·\s]+/g, "-")
      .replace(/-{2,}/g, "-")
      .replace(/^-+|-+$/g, "");
  }

  function looksLikeDossier(text) {
    if (DOSSIER_RE.test(canonDossier(text))) { return true; }
    return game.dossierExists(canonDossier(text));
  }

  /** 网页端支持的敲法（终端版还多几样，见「关于」里的说明）。 */
  function runCommand(raw) {
    var text = raw.trim();
    if (!text) { return; }
    ui.history.push(text);
    if (ui.history.length > 100) { ui.history.shift(); }
    ui.histAt = -1;

    if (/^\d+$/.test(text)) {          // 纯数字 = 选第 N 项
      var n = parseInt(text, 10);
      var opts = game.options();
      if (n >= 1 && n <= opts.length) { runOption(opts[n - 1]); return; }
      toast("没有第 " + n + " 项。", "error");
      return;
    }

    if (looksLikeDossier(text)) { readDossier(canonDossier(text)); return; }

    // 系统指令必须排在「阅档」正则**之前**：`读档` / `读取` 都以读取动词开头，
    // 先跑 READ 就会被吃成「阅 档」→ readDossier("档")，网页端读档入口直接废掉。
    // 终端侧的 command.py 一向按「长别名优先」匹配，所以只有网页中招。
    if (/^(档目|目录|档案|卷宗|目|list|ls)$/i.test(text)) { showIndex(); return; }
    if (/^(帮助|说明|help|\?|？)$/i.test(text)) { ui.overlay = { kind: "help" }; renderOverlay(); return; }
    if (/^(关于|about)$/i.test(text)) { ui.overlay = { kind: "about" }; renderOverlay(); return; }
    if (/^(存档|保存|save|s)$/i.test(text)) { doSave(); return; }
    if (/^(读档|读取|load|l)$/i.test(text)) { ui.overlay = { kind: "save" }; renderOverlay(); return; }
    if (/^(重来|重开|重新开始|restart)$/i.test(text)) { ui.overlay = { kind: "restart" }; renderOverlay(); return; }
    if (/^(离开|退出|返回标题|quit|q)$/i.test(text)) { backToTitle(); return; }

    var m = /^(?:读|看|阅|调阅|打开|启|read|open|cat)\s*(.+)$/i.exec(text);
    if (m) { readDossier(canonDossier(m[1])); return; }

    m = /^(?:搜|查|找|检索|search)\s*(.+)$/i.exec(text);
    if (m) { doSearch(m[1]); return; }

    m = /^(?:记|记事|写下|note)\s*(.+)$/i.exec(text);
    if (m) {
      game.state.notes.push(m[1].trim());
      toast("已记下。");
      ui.tab = "notes";
      render();
      return;
    }

    m = /^(?:改|修改|改写|edit)\s*(\d+)\s+(.+)$/i.exec(text);
    if (m) {
      var ei = parseInt(m[1], 10) - 1;
      if (ei >= 0 && ei < game.state.notes.length) {
        game.state.notes[ei] = m[2].trim();
        toast("改好了。");
        ui.tab = "notes";
        render();
      } else {
        toast("记事簿上没有第 " + m[1] + " 条。", "error");
      }
      return;
    }

    m = /^(?:删|划掉|del)\s*(\d+)$/i.exec(text);
    if (m) {
      var idx = parseInt(m[1], 10) - 1;
      if (idx >= 0 && idx < game.state.notes.length) {
        game.state.notes.splice(idx, 1);
        toast("划掉了。");
        render();
      } else {
        toast("记事簿上没有第 " + m[1] + " 条。", "error");
      }
      return;
    }

    // 最后退到「敲选项」：与脚本化通关同一套前缀匹配规则
    var hits = game.options().filter(function (o) {
      return o.label.indexOf(text) === 0;
    });
    if (hits.length === 1) { runOption(hits[0]); return; }
    if (hits.length > 1) {
      toast("「" + text + "」对上好几项，再多写两个字。", "error");
      return;
    }
    toast("看不明白：「" + text + "」。敲「帮助」看能敲什么。", "error");
  }

  function readDossier(did) {
    if (!game.dossierExists(did)) {
      var near = suggest(did);
      toast(near.length
        ? "档目里没有 " + did + "。相近的档号：" + near.join("、")
        : "档目里没有 " + did + "。", "error");
      return;
    }
    if (!game.canReadDossier(did)) {
      var lockedCase = game.dossierCase(did);
      toast(lockedCase > game.state.case
        ? did + " 是第 " + lockedCase + " 案的档 —— 你还没走到那一案。"
        : did + " 还没到能看的时候。", "error");
      return;
    }
    try {
      var upd = game.readDossier(did);
    } catch (err) {
      toast("读不了这份档：" + err.message, "error");
      return;
    }
    ui.read = "dossier";
    ui.dossier = did;
    ui.tab = "log";
    toastUpd(upd);
    render();
    scrollReading(0);
  }

  /** 近似档号提示：先找同前缀，再按编辑距离。 */
  function suggest(text, limit) {
    limit = limit || 3;
    var ids = Object.keys(PACK.dossiers);
    var near = ids.filter(function (id) {
      return id.indexOf(text.slice(0, 5)) === 0 && id !== text;
    });
    if (near.length) { return near.slice(0, limit); }
    function dist(a, b) {
      var m = a.length, n = b.length, prev = [], cur = [], i, j;
      for (j = 0; j <= n; j++) { prev[j] = j; }
      for (i = 1; i <= m; i++) {
        cur[0] = i;
        for (j = 1; j <= n; j++) {
          cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1,
                            prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
        }
        prev = cur.slice();
      }
      return prev[n];
    }
    return ids.filter(function (id) { return dist(id, text) <= 3; }).slice(0, limit);
  }

  function toastUpd(upd) {
    (upd.toasts || []).forEach(function (t, i) {
      setTimeout(function () { toast(t, /^\/\//.test(t) ? "dossier" : ""); }, i * 260);
    });
  }

  function showIndex() {
    ui.read = "index";
    ui.tab = "index";
    render();
  }

  function doSearch(term) {
    var t = (term || "").trim();
    if (!t) { toast("要搜什么？写成「搜 银针」这样。", "error"); return; }
    ui.searchTerm = t;
    ui.hits = game.searchDossiers(t, 40);
    ui.read = "search";
    ui.tab = "search";
    if (!ui.hits.length) { toast("已阅的档案里没有「" + t + "」。", ""); }
    render();
  }

  function doSave() {
    if (writeSave()) { toast("已存入本机（存于 " + nowStamp() + "）。"); }
  }

  function doLoad() {
    var data = readSave();
    if (!data) { toast("本机没有存档。", "error"); return; }
    try {
      game.fromSave(data);
    } catch (err) {
      toast("读档失败：" + err.message, "error");
      return;
    }
    if (game.atVerdict() && !game.state.ending) { game.finalize(); }
    ui.screen = "game";
    ui.read = "log";
    ui.dossier = "";
    ui.cursor = 0;
    toast("读档完成（存于 " + (data.stamp || "——") + "）。");
    render();
  }

  function backToTitle() {
    ui.screen = "title";
    ui.overlay = null;
    ui.read = "log";
    ui.dossier = "";
    render();
  }

  // ------------------------------------------------------------------
  // 动作
  // ------------------------------------------------------------------

  function runOption(opt) {
    if (!opt) { return; }
    if (!opt.enabled) {
      toast("「" + opt.label + "」现在做不了：" + (opt.hint || "条件不足"), "error");
      return;
    }
    var upd = opt.choice
      ? game.choose(opt.choice, opt.topic_id)
      : { toasts: [], new_clues: [], new_items: [], new_dossiers: [] };
    if (game.atVerdict() && !game.state.ending) { game.finalize(); }
    ui.read = "log";
    ui.dossier = "";
    toastUpd(upd);
    var opts = game.options();
    ui.cursor = Math.min(ui.cursor, Math.max(0, opts.length - 1));
    render();
    scrollReading(1e9);
  }

  function moveCursor(step) {
    var opts = game.options();
    if (!opts.length) { return; }
    ui.cursor = (ui.cursor + step + opts.length) % opts.length;
    refreshOptions();
  }

  function scrollReading(where) {
    var body = document.getElementById("reading-body");
    if (!body) { return; }
    body.scrollTop = where > 1000 ? body.scrollHeight : where;
  }

  // ------------------------------------------------------------------
  // 渲染
  // ------------------------------------------------------------------

  var root = document.getElementById("app");

  function render() {
    document.body.setAttribute("data-tab", ui.tab);
    clear(root);
    if (ui.screen === "title") { renderTitle(); }
    else { renderGame(); }
    renderOverlay();
    renderToasts();
  }

  function renderTitle() {
    var box = el("div", "center-screen");
    box.appendChild(el("div", "brand", PACK.title));
    box.appendChild(el("div", "brand-sub", PACK.subtitle + " · 网页版"));
    box.appendChild(el("div", "rule"));
    var quote = el("div", "quote", PACK.prologue);
    box.appendChild(quote);

    var menu = el("div", "menu");
    var entries = [["新案", function () {
      game.newGame();
      ui.screen = "game";
      ui.read = "log";
      ui.cursor = 0;
      toast("//新案开卷——" + PACK.title + "//", "dossier");
      render();
      scrollReading(0);
    }]];
    if (hasSave()) {
      entries.push(["续前案（读档）", doLoad]);
    }
    entries.push(["玩法说明", function () { ui.overlay = { kind: "help" }; renderOverlay(); }]);
    entries.push(["关于本作", function () { ui.overlay = { kind: "about" }; renderOverlay(); }]);

    entries.forEach(function (pair, i) {
      var btn = el("button", "opt");
      btn.appendChild(el("span", "num", String(i + 1)));
      btn.appendChild(el("span", "label", pair[0]));
      btn.addEventListener("click", pair[1]);
      menu.appendChild(btn);
    });
    box.appendChild(menu);
    root.appendChild(box);
    renderFooter(root);
  }

  function renderGame() {
    var st = game.state;

    // -- 顶栏
    var top = el("div", "topbar");
    var row = el("div", "topbar-row");
    row.appendChild(el("span", "brand", PACK.title));
    row.appendChild(el("span", "brand-sub", PACK.subtitle));
    var seal = el("span", "seal", st.ending ? "已结案" : "第 " + st.chapter + " 幕");
    row.appendChild(seal);
    top.appendChild(row);

    var meta = el("div", "topbar-meta");
    // 「幕」跟着**眼前这一屏**走：正在读某份档案时印那份档案的幕（读第二幕的账目
    // 时别让人以为还在第一幕），否则印当前进度。不能直接看 st.open_dossier ——
    // 那是引擎替存档记着的「上次读到哪儿」，读完退回卷宗、或读一份旧存档之后
    // 它仍然指着旧档，顶栏就会印错幕（案① 已结案、人站在第六幕，却写着第一幕）。
    var headAct = game.headAct(ui.read === "dossier" ? ui.dossier : "");
    [["幕", game.actTitleOf(headAct)],
     ["时辰", st.time], ["所在", st.place], ["回合", String(st.turn)],
     ["评分", String(st.score)], ["行囊", String(st.items_owned.length)],
     ["线索", st.clues.length + "/" + Object.keys(PACK.items).filter(function (k) { return PACK.items[k].core; }).length]
    ].forEach(function (pair) {
      var span = el("span");
      span.appendChild(document.createTextNode(pair[0] + " "));
      span.appendChild(el("b", null, esc(pair[1])));
      meta.appendChild(span);
    });
    if (st.hurt) {
      var hurt = el("span");
      hurt.appendChild(document.createTextNode("心绪 "));
      hurt.appendChild(el("b", null, String(st.hurt)));
      meta.appendChild(hurt);
    }
    top.appendChild(meta);

    var tabs = el("div", "tabs");
    [["log", "卷宗"], ["index", "档目"], ["notes", "记事"], ["search", "检索"]].forEach(function (pair) {
      var b = el("button", "tab" + (ui.tab === pair[0] ? " on" : ""), pair[1]);
      b.addEventListener("click", function () {
        ui.tab = pair[0];
        if (pair[0] === "index") { ui.read = "index"; }
        if (pair[0] === "log") { ui.read = ui.dossier ? "dossier" : "log"; }
        render();
      });
      tabs.appendChild(b);
    });
    top.appendChild(tabs);
    root.appendChild(top);

    var main = el("div", "main");
    var left = el("div", "col-left");
    var right = el("div", "col-right");

    left.appendChild(renderReading());
    if (!game.state.ending) { left.appendChild(renderOptions()); }
    left.appendChild(renderCommand());

    // 窄屏靠分页切：宽屏时左栏已经在显示档目/检索的话，右栏那份由 CSS 收起来
    right.appendChild(renderIndex());
    right.appendChild(renderNotes());
    right.appendChild(renderSearchHits());
    right.appendChild(renderButtons());
    main.appendChild(left);
    main.appendChild(right);
    root.appendChild(main);
    renderFooter(root);
  }

  function renderReading() {
    var panel = el("div", "panel reading page page-log");
    var head = el("div", "panel-head");
    var titles = { log: "卷宗", dossier: "档案", index: "档目", search: "检索" };
    head.appendChild(el("span", null, titles[ui.read] || "卷宗"));
    var acts = el("span", "count");
    if (ui.read === "dossier" && ui.dossier) {
      acts.textContent = ui.dossier;
      var close = el("button", "btn small bare", "收档");
      close.addEventListener("click", function () {
        game.closeDossier();
        ui.dossier = "";
        ui.read = "log";
        render();
      });
      head.appendChild(close);
    } else {
      acts.textContent = "已收 " + game.knownDossiers().length + " 份";
    }
    panel.appendChild(head);

    var body = el("div", "panel-body");
    body.id = "reading-body";

    if (ui.read === "dossier" && ui.dossier) {
      body.appendChild(dossierCard(ui.dossier));
    } else if (ui.read === "index") {
      body.appendChild(indexTree());
    } else if (ui.read === "search") {
      body.appendChild(hitList());
    } else {
      body.appendChild(logList());
    }
    panel.appendChild(body);
    return panel;
  }

  /** 档案正文排几列：中文一格算两列，量不到就用窗口宽度估。 */
  function dossierColumns() {
    var host = document.getElementById("reading-body");
    var em = 16;
    var w = Math.min(window.innerWidth - 40, 48 * 16);
    if (host && host.clientWidth > 60) {
      em = parseFloat(window.getComputedStyle(host).fontSize) || 16;
      w = Math.min(host.clientWidth, 48 * em) - 28;
    }
    return Math.max(24, Math.floor(w / (em / 2)));
  }

  function dossierCard(did) {
    var card = el("div", "dossier-card");
    var d = PACK.dossiers[did];
    card.appendChild(el("div", "doc-head", did + " · " + game.titleOfDossier(did)));
    var meta = game.dossierMeta(d);
    if (meta) { card.appendChild(el("div", "doc-meta", meta)); }
    var body = el("pre");
    // 与终端版同一套排版：把卡片宽度折成「列数」，中文按两格算
    body.textContent = game.dossierView(did, dossierColumns()).slice(2).join("\n");
    card.appendChild(body);
    var links = (d.links || []).filter(function (x) { return PACK.dossiers[x]; });
    if (links.length) {
      var row = el("div", "doc-hint");
      row.appendChild(document.createTextNode("顺链可查："));
      links.forEach(function (x, i) {
        if (i) { row.appendChild(document.createTextNode("　")); }
        var b = el("button", "btn small bare", x);
        b.title = game.titleOfDossier(x) + (game.state.dossiers[x] ? "" : "（未收集）");
        b.addEventListener("click", function () { readDossier(x); });
        row.appendChild(b);
      });
      card.appendChild(row);
    }
    return card;
  }

  function logList() {
    var wrap = el("div");
    var entries = game.state.log;
    if (!entries.length) {
      wrap.appendChild(el("p", "empty", "案上还空着。先在 › 后面敲「档目」看看手上有哪些卷宗。"));
      return wrap;
    }
    var limit = entries.length > 120 ? entries.slice(-120) : entries;
    limit.forEach(function (entry) {
      var kind = entry[0], text = entry[1];
      var box = el("div", "log-entry log-" + kind);
      if (kind === "scene") {
        var scene = PACK.scenes[game.state.scene];
        if (scene) { box.appendChild(el("span", "scene-title", scene.title + " · " + scene.place)); }
      }
      box.appendChild(el("p", null, text));
      wrap.appendChild(box);
    });
    return wrap;
  }

  function indexTree() {
    var wrap = el("div");
    var groups = game.dossierIndex();
    if (!groups.length) {
      wrap.appendChild(el("p", "empty", "档目还空着。"));
      return wrap;
    }
    groups.forEach(function (pair) {
      var act = pair[0], rows = pair[1];
      var box = el("div", "index-act");
      box.appendChild(el("h4", null, game.actTitleOf(act)));
      rows.forEach(function (row) {
        var did = row[0], title = row[1], hint = row[2], read = row[3];
        var b = el("button", "doc-row" + (read ? "" : " unread"));
        b.appendChild(el("span", "did", did));
        b.appendChild(el("span", "title", title));
        if (hint) { b.appendChild(el("span", "hint", "还牵着 " + hint + " 份")); }
        b.addEventListener("click", function () { readDossier(did); });
        box.appendChild(b);
      });
      wrap.appendChild(box);
    });
    return wrap;
  }

  function hitList() {
    var wrap = el("div", "hits");
    if (!ui.hits.length) {
      wrap.appendChild(el("p", "empty",
        "已阅的档案里没找到「" + ui.searchTerm + "」。"));
      return wrap;
    }
    ui.hits.forEach(function (hit) {
      var b = el("button", "hit");
      b.appendChild(el("span", "did", hit[0] + " · " + hit[1]));
      b.appendChild(el("span", "snippet", hit[2]));
      b.addEventListener("click", function () { readDossier(hit[0]); });
      wrap.appendChild(b);
    });
    return wrap;
  }

  function renderOptions() {
    var panel = el("div", "panel options page page-log");
    var head = el("div", "panel-head");
    head.appendChild(el("span", null, "可以做的事"));
    head.appendChild(el("span", "count", "↑↓ 移动 · 回车确认 · 也可直接敲下面的字"));
    panel.appendChild(head);
    var body = el("div", "panel-body");
    body.id = "options-body";
    panel.appendChild(body);
    fillOptions(body);
    return panel;
  }

  function fillOptions(body) {
    var opts = game.options();
    if (!opts.length) {
      body.appendChild(el("p", "empty", "此刻没有可做的事。"));
      return;
    }
    opts.forEach(function (opt, i) {
      var b = el("button", "opt" + (opt.enabled ? "" : " locked") +
        (i === ui.cursor ? " focus" : ""));
      b.appendChild(el("span", "num", String(opt.index)));
      var label = el("span", "label", opt.label);
      if (opt.detail) { label.appendChild(el("span", "detail", opt.detail)); }
      if (!opt.enabled && opt.hint) { label.appendChild(el("span", "hint", "条件不足：" + opt.hint)); }
      if (opt.asked) { label.appendChild(el("span", "asked", "（已经问过）")); }
      b.appendChild(label);
      b.addEventListener("click", function () { runOption(opt); });
      body.appendChild(b);
    });
  }

  /** 只重画选项区（移动光标时用，免得整页重排把输入框的焦点弄丢）。 */
  function refreshOptions() {
    var body = document.getElementById("options-body");
    if (!body) { return; }
    clear(body);
    fillOptions(body);
  }

  function renderCommand() {
    var panel = el("div", "panel page page-log");
    var body = el("div", "panel-body command");
    body.appendChild(el("span", "prompt", "›"));
    var input = el("input");
    input.id = "cmd";
    input.type = "text";
    input.autocomplete = "off";
    input.autocapitalize = "off";
    input.spellcheck = false;
    input.placeholder = "输入档号或指令（如 01-FY-XFE / 档目 / 搜 银针 / 记 一句话）";
    input.value = ui.draft;
    input.addEventListener("input", function () { ui.draft = input.value; });
    input.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") {
        ev.preventDefault();
        var text = input.value;
        ui.draft = "";
        input.value = "";
        runCommand(text);
      } else if (ev.key === "Escape") {
        ui.draft = "";
        input.value = "";
      } else if (ev.key === "ArrowUp") {
        ev.preventDefault();
        if (!ui.history.length) { return; }
        if (ui.histAt < 0) { ui.draft = input.value; ui.histAt = ui.history.length; }
        ui.histAt = Math.max(0, ui.histAt - 1);
        input.value = ui.history[ui.histAt] || "";
      } else if (ev.key === "ArrowDown") {
        ev.preventDefault();
        if (ui.histAt < 0) { return; }
        ui.histAt += 1;
        if (ui.histAt >= ui.history.length) { ui.histAt = -1; input.value = ui.draft; }
        else { input.value = ui.history[ui.histAt] || ""; }
      }
    });
    body.appendChild(input);
    var go = el("button", "btn", "执行");
    go.addEventListener("click", function () {
      var text = input.value;
      ui.draft = "";
      input.value = "";
      runCommand(text);
      input.focus();
    });
    body.appendChild(go);
    var head = el("div", "panel-head");
    head.appendChild(el("span", null, "案前问话"));
    head.appendChild(el("span", "count", "回车执行"));
    panel.appendChild(head);
    panel.appendChild(body);
    return panel;
  }

  function renderIndex() {
    var panel = el("div", "panel page page-index" + (ui.read === "index" ? " mirror" : ""));
    var head = el("div", "panel-head");
    head.appendChild(el("span", null, "档目"));
    head.appendChild(el("span", "count", game.knownDossiers().length + " / " + Object.keys(PACK.dossiers).length));
    panel.appendChild(head);
    var body = el("div", "panel-body");
    body.appendChild(indexTree());
    panel.appendChild(body);
    return panel;
  }

  function renderNotes() {
    var panel = el("div", "panel notes page page-notes");
    var head = el("div", "panel-head");
    head.appendChild(el("span", null, "记事簿"));
    head.appendChild(el("span", "count", game.state.notes.length + " 条"));
    panel.appendChild(head);
    var body = el("div", "panel-body");
    if (!game.state.notes.length) {
      body.appendChild(el("p", "empty", "用「记 一句话」把想到的写下来。"));
    } else {
      var list = el("ul");
      game.state.notes.forEach(function (note, i) {
        var li = el("li");
        li.appendChild(el("span", null, (i + 1) + ". " + note));
        var del = el("button", "btn small bare del", "划掉");
        del.addEventListener("click", function () {
          game.state.notes.splice(i, 1);
          render();
        });
        li.appendChild(del);
        list.appendChild(li);
      });
      body.appendChild(list);
    }
    panel.appendChild(body);
    return panel;
  }

  function renderSearchHits() {
    var panel = el("div", "panel page page-search" + (ui.read === "search" ? " mirror" : ""));
    var head = el("div", "panel-head");
    head.appendChild(el("span", null, "检索已阅档案"));
    head.appendChild(el("span", "count", ui.searchTerm ? "「" + ui.searchTerm + "」" : ""));
    panel.appendChild(head);
    var body = el("div", "panel-body");
    if (!ui.searchTerm) {
      body.appendChild(el("p", "empty", "用「搜 银针」这样找已读过的档案。"));
    } else {
      body.appendChild(hitList());
    }
    panel.appendChild(body);
    return panel;
  }

  function renderButtons() {
    var panel = el("div", "panel page page-index page-notes page-search");
    var body = el("div", "panel-body");
    var row = el("div", "tabs");
    [["存档", doSave], ["读档/搬档", function () { ui.overlay = { kind: "save" }; renderOverlay(); }],
     ["帮助", function () { ui.overlay = { kind: "help" }; renderOverlay(); }],
     ["重来", function () { ui.overlay = { kind: "restart" }; renderOverlay(); }],
     ["回到标题", backToTitle]].forEach(function (pair) {
      var b = el("button", "btn small", pair[0]);
      b.addEventListener("click", pair[1]);
      row.appendChild(b);
    });
    body.appendChild(row);
    var info = el("p", "empty");
    info.textContent = "存档写在本机浏览器里，形状与终端版完全一样；" +
      "用「读档/搬档」把 JSON 抄出来贴到另一台机器（或 " +
      "%USERPROFILE%\\.gongwei\\save.json）就接着玩。";
    body.appendChild(info);
    panel.appendChild(body);
    return panel;
  }

  function renderFooter(target) {
    var foot = el("div", "footer");
    [["1-9", "选项"], ["↑↓", "移动"], ["回车", "确认"], ["Esc", "清空"]].forEach(function (pair, i) {
      if (i) { foot.appendChild(document.createTextNode(" · ")); }
      foot.appendChild(el("kbd", null, pair[0]));
      foot.appendChild(document.createTextNode(" " + pair[1]));
    });
    foot.appendChild(el("span", "only-narrow", "　点选项、敲档号即可。"));
    target.appendChild(foot);
  }

  // ------------------------------------------------------------------
  // 浮层与提示
  // ------------------------------------------------------------------

  function renderOverlay() {
    var old = document.getElementById("overlay");
    if (old) { old.remove(); }
    if (!ui.overlay) { return; }
    var wrap = el("div", "overlay");
    wrap.id = "overlay";
    var sheet = el("div", "sheet");
    var kind = ui.overlay.kind;

    function closeRow(extra) {
      var row = el("div", "sheet-actions");
      if (extra) { row.appendChild(extra); }
      var b = el("button", "btn", "合上");
      b.addEventListener("click", function () { ui.overlay = null; renderOverlay(); });
      row.appendChild(b);
      return row;
    }

    if (kind === "help") {
      sheet.appendChild(el("h3", null, "怎么玩"));
      sheet.appendChild(el("p", null, "这是一桩宫里的案子。你是仵作沈墨白。" +
        "查案靠两件事：在现场与侧殿里做事（点下面的动作列表，或敲它的字），" +
        "以及调阅档案（在 › 后面敲档号，如 01-FY-XFE）。"));
      sheet.appendChild(el("p", null, "档号的样子是「幕码-地点码-在场人」，" +
        "例如 01-FY-XFE 就是第一幕、凤仪殿、贤妃的尸格。" +
        "手上有的档在「档目」里，读完一份，它牵着的下一份会自动进档目——" +
        "但有几份没写在前面的档里，要你自己把号子拼出来。"));
      sheet.appendChild(el("div", "rule"));
      sheet.appendChild(el("h4", null, "网页版可以敲的"));
      var table = el("table");
      [["01-FY-XFE", "敲档号阅档（也可以敲 读 01-FY-XFE）"],
       ["档目", "列出已收的档案与各自还牵着几份"],
       ["搜 银针", "在已读过的档案里找字"],
       ["记 皇后在说谎", "在记事簿上记一条"],
       ["删 2", "划掉记事簿第 2 条"],
       ["存档 / 读档", "存到本机 / 读回本机（也可搬档）"],
       ["重来 / 离开", "重开一卷 / 回到标题"],
       ["直接敲选项上的字", "与点它一样；敲「移步」就能迈步"],
       ["数字 1-9", "选第 N 项动作"]].forEach(function (pair) {
        var tr = el("tr");
        tr.appendChild(el("td", "k", pair[0]));
        tr.appendChild(el("td", null, pair[1]));
        table.appendChild(tr);
      });
      sheet.appendChild(table);
      sheet.appendChild(el("div", "rule"));
      sheet.appendChild(el("h4", null, "终端版还多这些敲法"));
      (PACK.help_sections || []).forEach(function (sec) {
        sheet.appendChild(el("h4", null, "【" + sec.title + "】"));
        var t = el("table");
        (sec.rows || []).forEach(function (row) {
          var tr = el("tr");
          tr.appendChild(el("td", "k", row[0]));
          tr.appendChild(el("td", null, row[1]));
          t.appendChild(tr);
        });
        sheet.appendChild(t);
      });
      sheet.appendChild(closeRow());
    } else if (kind === "about") {
      sheet.appendChild(el("h3", null, "关于本作"));
      sheet.appendChild(el("p", null, PACK.title + " · " + PACK.subtitle));
      sheet.appendChild(el("p", null, "一桩密室毒杀，牵出十二年前的旧案；三案十一幕，" +
        "卷宗靠你自己一份份调出来。"));
      var stat = el("table");
      [["档案", Object.keys(PACK.dossiers).length + " 份"],
       ["场景", Object.keys(PACK.scenes).length + " 个"],
       ["线索/物证", Object.keys(PACK.items).length + " 条（核心 " + PACK.core_total + "）"],
       ["结局", PACK.endings.length + " 种"],
       ["幕", PACK.act_numbers.length + " 幕"]].forEach(function (pair) {
        var tr = el("tr");
        tr.appendChild(el("td", "k", pair[0]));
        tr.appendChild(el("td", null, pair[1]));
        tableRow(stat, pair[0], pair[1]);
      });
      sheet.appendChild(stat);
      sheet.appendChild(el("p", "empty", "终端与网页共用同一套剧本、同一份存档形状；" +
        "两端行为由 tools/audit_web.py 逐步比对把关。"));
      sheet.appendChild(closeRow());
    } else if (kind === "restart") {
      sheet.appendChild(el("h3", null, "重开这一卷？"));
      sheet.appendChild(el("p", null, "手上的卷宗、记事簿与进度都会重来。想留着就先「存档」。"));
      var redo = el("button", "btn", "重来");
      redo.addEventListener("click", function () {
        game.newGame();
        ui.overlay = null;
        ui.read = "log";
        ui.dossier = "";
        ui.cursor = 0;
        ui.tab = "log";
        toast("//新案开卷//", "dossier");
        render();
      });
      sheet.appendChild(closeRow(redo));
    } else if (kind === "save") {
      sheet.appendChild(el("h3", null, "存档 · 搬档"));
      sheet.appendChild(el("p", null, "「存档」写在本机浏览器里；下面的 JSON 可以直接抄走，" +
        "贴到手机、平板或终端版（终端用 " + "%USERPROFILE%\\.gongwei\\save.json" + "）。"));
      var area = el("textarea");
      area.spellcheck = false;
      var current = readSave();
      area.value = current ? JSON.stringify(current) : "";
      area.placeholder = "把存档 JSON 贴到这里，再点「导入」";
      sheet.appendChild(area);
      var actions = el("div", "sheet-actions");
      var doExport = el("button", "btn small", "导出本机存档");
      doExport.addEventListener("click", function () {
        var payload = game.save();
        payload.stamp = nowStamp();
        area.value = JSON.stringify(payload);
        toast("已抄到上面的框里。");
      });
      var doImport = el("button", "btn small", "导入");
      doImport.addEventListener("click", function () {
        var text = area.value.trim();
        if (!text) { toast("框里还没有东西。", "error"); return; }
        var data;
        try { data = JSON.parse(text); }
        catch (e) { toast("这段不是合法存档：" + e.message, "error"); return; }
        try { game.fromSave(data); }
        catch (e2) { toast("这份存档读不了：" + e2.message, "error"); return; }
        if (game.atVerdict() && !game.state.ending) { game.finalize(); }
        ui.screen = "game";
        ui.overlay = null;
        ui.read = "log";
        ui.dossier = "";
        toast("导入完成。");
        render();
      });
      var doStore = el("button", "btn small", "存入本机");
      doStore.addEventListener("click", function () { doSave(); });
      var doLoadLocal = el("button", "btn small", "读本机存档");
      doLoadLocal.addEventListener("click", function () { ui.overlay = null; doLoad(); });
      actions.appendChild(doExport);
      actions.appendChild(doStore);
      actions.appendChild(doLoadLocal);
      actions.appendChild(doImport);
      var close = el("button", "btn", "合上");
      close.addEventListener("click", function () { ui.overlay = null; renderOverlay(); });
      actions.appendChild(close);
      sheet.appendChild(actions);
    }
    wrap.appendChild(sheet);
    wrap.addEventListener("click", function (ev) {
      if (ev.target === wrap) { ui.overlay = null; renderOverlay(); }
    });
    document.body.appendChild(wrap);
  }

  function tableRow(table, key, value) {
    var tr = el("tr");
    tr.appendChild(el("td", "k", key));
    tr.appendChild(el("td", null, value));
    table.appendChild(tr);
  }

  function renderToasts() {
    var box = document.getElementById("toasts");
    if (!box) {
      box = el("div", "toasts");
      box.id = "toasts";
      document.body.appendChild(box);
    }
    clear(box);
    ui.toasts.forEach(function (t) {
      box.appendChild(el("div", "toast " + t.kind, t.text));
    });
  }

  // ------------------------------------------------------------------
  // 键盘（不在输入框里时）
  // ------------------------------------------------------------------

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && ui.overlay) {
      ui.overlay = null;
      renderOverlay();
      return;
    }
    var target = ev.target;
    if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) { return; }
    if (ui.overlay) { return; }
    if (ui.screen === "title") {
      if (/^[1-9]$/.test(ev.key)) {
        var btns = root.querySelectorAll(".menu .opt");
        var idx = parseInt(ev.key, 10) - 1;
        if (btns[idx]) { btns[idx].click(); }
      }
      return;
    }
    if (ev.key === "ArrowUp") { ev.preventDefault(); moveCursor(-1); return; }
    if (ev.key === "ArrowDown") { ev.preventDefault(); moveCursor(1); return; }
    if (/^[1-9]$/.test(ev.key)) {
      var opts = game.options();
      var n = parseInt(ev.key, 10);
      if (opts[n - 1]) { runOption(opts[n - 1]); }
      return;
    }
    if (ev.key === "Enter") {
      var list = game.options();
      if (list[ui.cursor]) { runOption(list[ui.cursor]); }
      return;
    }
    if (ev.key.length === 1 && ev.key >= " ") {
      var input = document.getElementById("cmd");
      if (input) { input.focus(); }
    }
  });

  // 起手：先看标题屏
  render();
})();
