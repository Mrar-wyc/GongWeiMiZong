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
    draft: "",
    logOpen: true,          // 「行动记录」摊开还是收起（折叠条上的 aria-expanded 跟着它）
    lastAct: null           // 上一次铺过卷首过场的幕号：换了幕才铺
  };

  // ------------------------------------------------------------------
  // 小工具
  // ------------------------------------------------------------------

  /** 可选的 attrs：第三参写成对象、或另给第四参，都按 setAttribute 落上去。 */
  function el(tag, cls, text, attrs) {
    var node = document.createElement(tag);
    if (cls) { node.className = cls; }
    if (text !== undefined && text !== null) {
      if (typeof text === "object") { attrs = attrs || text; }
      else { node.textContent = text; }
    }
    return applyAttrs(node, attrs);
  }

  function applyAttrs(node, attrs) {
    if (!attrs) { return node; }
    Object.keys(attrs).forEach(function (key) {
      if (attrs[key] === null || attrs[key] === undefined) { return; }
      node.setAttribute(key, String(attrs[key]));
    });
    return node;
  }

  /** 描金分隔线：画法在 style.css 的 .rule 里。 */
  function sep() { return el("div", "rule"); }

  /**
   * 一枚图标：把 shell.html 里那只模板 svg 复制一份，只把 use 的 href 指到 #i-名字。
   * 一律走 getElementById + cloneNode —— 不用 createElementNS、不写 innerHTML，
   * 产物里才不会出现外链前缀（tests/test_web.py 的离线扫描盯着这个）。
   * 假 DOM（tests/webui_harness.js）里没有那块模板，退成一只空 svg，不报错。
   */
  function iconNode(name, box) {
    var tpl = document.getElementById("icon-tpl");
    var svg = tpl && tpl.firstChild && typeof tpl.firstChild.cloneNode === "function"
      ? tpl.firstChild.cloneNode(true)
      : applyAttrs(el("svg", "icon"), { viewBox: box || "0 0 24 24" });
    if (box) { svg.setAttribute("viewBox", box); }
    var uses = svg.querySelectorAll ? svg.querySelectorAll("use") : [];
    if (uses.length) { uses[0].setAttribute("href", "#i-" + name); }
    return svg;
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
    }, 4000);
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

  // 与 gongwei/game/save.py 的 SAVE_VERSION 对齐：太新的档终端版会拒读，
  // 网页版也不能闷头读进来（同一份档两端给相反的答案最坑人）。
  var SAVE_VERSION = 1;

  function saveVersionError(data) {
    if (!data || typeof data !== "object" || data.v === undefined || data.v === null) {
      return "";
    }
    var n = parseInt(data.v, 10);
    if (isNaN(n)) { return "存档版本号不是数字：" + data.v; }
    if (n > SAVE_VERSION) { return "存档版本 " + n + " 太新，本版本读不了"; }
    return "";
  }

  function writeSave() {
    try {
      var payload = game.save();
      payload.stamp = nowStamp();
      window.localStorage.setItem(SAVE_KEY, JSON.stringify(payload));
      return true;
    } catch (e) {
      storageOk = false;   // 案外页会据此说一句：本机存不下
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
    var verr = saveVersionError(data);
    if (verr) { toast("读档失败：" + verr, "error"); return; }
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
    // 门禁没开的选择根本不在这张桌上（见 game.options() 与 game.hiddenOptions()），
    // 所以这里没有「点了也做不了」这一档。
    var upd = opt.choice
      ? game.choose(opt.choice, opt.topic_id)
      : { toasts: [], new_clues: [], new_items: [], new_dossiers: [] };
    if (game.atVerdict() && !game.state.ending) { game.finalize(); }
    ui.read = "log";
    ui.dossier = "";
    toastUpd(upd);
    cueFor(upd);
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
    // 图景与案外都长在 #app 之外：下面这记 clear() 清不到它们，所以先报状态、再重画
    if (ui.screen !== "title") { noteProgress(); }
    applyStage();
    clear(root);
    if (ui.screen === "title") { renderTitle(); }
    else { renderGame(); }
    renderOverlay();
    renderToasts();
    maybeSplash();
  }

  function renderTitle() {
    var box = el("div", "center-screen title-screen");

    // 落花：只铺片数，位置 / 延时 / 飘法全交给 CSS 的 nth-child（纯装饰，读屏不念）
    var petals = el("div", "petals", null, { "aria-hidden": "true" });
    for (var i = 0; i < 10; i += 1) { petals.appendChild(el("span", "petal")); }
    box.appendChild(petals);

    // 朱砂印章徽：四字与内描金环都画在 shell.html 的精灵里（#i-seal-badge）
    var badge = el("div", "seal-badge");
    badge.appendChild(iconNode("seal-badge", "0 0 80 80"));
    box.appendChild(badge);

    box.appendChild(el("h1", "brand", PACK.title));
    box.appendChild(el("div", "brand-sub", PACK.subtitle + " · 网页版"));
    box.appendChild(sep());
    var quote = el("div", "quote", PACK.prologue);
    box.appendChild(quote);

    var menu = el("div", "menu");
    var entries = [["新案", "seal-btn", function () {
      game.newGame();
      ui.screen = "game";
      ui.read = "log";
      ui.cursor = 0;
      toast("//新案开卷——" + PACK.title + "//", "dossier");
      render();
      scrollReading(0);
    }, "scroll"]];
    if (hasSave()) {
      entries.push(["续前案（读档）", "title-btn", doLoad, "load"]);
    }
    entries.push(["玩法说明", "title-btn", function () { ui.overlay = { kind: "help" }; renderOverlay(); }, "help"]);
    entries.push(["关于本作", "title-btn", function () { ui.overlay = { kind: "about" }; renderOverlay(); }, "info"]);

    entries.forEach(function (row, i) {
      var btn = el("button", "opt " + row[1]);
      btn.appendChild(el("span", "num", String(i + 1)));
      btn.appendChild(el("span", "label", row[0]));
      if (row[3]) { btn.appendChild(iconNode(row[3])); }
      btn.addEventListener("click", row[2]);
      menu.appendChild(btn);
    });
    box.appendChild(menu);
    box.appendChild(el("div", "credit", "古风宫廷推理 · 单文件离线 · 与终端版同一套剧本"));
    root.appendChild(box);
    renderFooter(root);
  }

  function renderGame() {
    var st = game.state;

    // -- 顶栏：印章小徽 + 标题 + 幕/案副行 + 芯片行 + 图标钮
    var top = el("div", "topbar glass-panel");
    var row = el("div", "topbar-row");
    row.appendChild(el("span", "seal-badge", st.ending ? "终" : "宫"));
    var brand = el("div", "brand-box");
    brand.appendChild(el("span", "brand", PACK.title));
    // 「幕」跟着**眼前这一屏**走：正在读某份档案时印那份档案的幕（读第二幕的账目
    // 时别让人以为还在第一幕），否则印当前进度。不能直接看 st.open_dossier ——
    // 那是引擎替存档记着的「上次读到哪儿」，读完退回卷宗、或读一份旧存档之后
    // 它仍然指着旧档，顶栏就会印错幕（案① 已结案、人站在第六幕，却写着第一幕）。
    var headAct = game.headAct(ui.read === "dossier" ? ui.dossier : "");
    brand.appendChild(el("div", "brand-sub",
      game.actTitleOf(headAct) + " · 第 " + st.case + " 案"));
    row.appendChild(brand);
    row.appendChild(el("span", "seal", st.ending ? "已结案" : "第 " + st.chapter + " 幕"));
    row.appendChild(topActions());
    top.appendChild(row);

    // 芯片行：前三项是「此刻在哪儿、什么时候」，窄屏留着；后四项是读数，窄屏交给 CSS 收
    var chips = el("div", "hud-chips");
    chips.appendChild(hudChip("door", "所在", st.place, ""));
    chips.appendChild(hudChip("clock", "时辰", st.time, ""));
    chips.appendChild(hudChip("star", "回合", String(st.turn), "meta-extra"));
    chips.appendChild(hudChip("star", "评分", String(st.score), "meta-extra"));
    chips.appendChild(hudChip("evidence", "行囊", String(st.items_owned.length), "meta-extra"));
    chips.appendChild(hudChip("clue", "线索",
      st.clues.length + "/" + PACK.core_total, "meta-extra"));
    if (st.hurt) { chips.appendChild(hudChip("person", "心绪", String(st.hurt), "")); }
    top.appendChild(chips);

    var tabs = el("div", "tabs");
    [["log", "卷宗", "scroll"], ["index", "档目", "book"], ["notes", "记事", "letter"],
     ["search", "检索", "magnify"], ["collection", "案外", "leaf"]].forEach(function (pair) {
      var b = el("button", "tab" + (ui.tab === pair[0] ? " on" : ""));
      b.appendChild(iconNode(pair[2]));
      b.appendChild(el("span", null, pair[1]));
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

    if (st.ending) { left.appendChild(endingSeal(st.ending)); }
    left.appendChild(renderReading());
    if (!game.state.ending) { left.appendChild(renderOptions()); }
    left.appendChild(renderCommand());

    // 右栏：先四张仪表卡，再是各页签的那一份（窄屏靠分页切，rail 由 CSS 折叠）
    right.appendChild(renderRail());
    right.appendChild(renderIndex());
    right.appendChild(renderNotes());
    right.appendChild(renderSearchHits());
    right.appendChild(renderCollection());
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
    var headIcons = { log: "scroll", dossier: "letter", index: "book", search: "magnify" };
    head.appendChild(iconNode(headIcons[ui.read] || "scroll"));
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
      // 「行动记录」是一条可折叠的栏：摊开时下面才是卷宗正文（默认摊开）
      body.appendChild(logBar());
      if (ui.logOpen) { body.appendChild(logList()); }
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
    // 逐行走名牌：档案里的「供词」才是全篇真正带人名的话（见 07-DL-TWO）
    saidLinesInto(body, game.dossierView(did, dossierColumns()).slice(2).join("\n"));
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
      var box = el("div", "log-entry log-" + kind + (saysIt(text) ? " dlg" : ""));
      if (kind === "scene") {
        var scene = PACK.scenes[game.state.scene];
        if (scene) { box.appendChild(el("span", "scene-title", scene.title + " · " + scene.place)); }
      }
      box.appendChild(saidParagraph(text));
      wrap.appendChild(box);
    });
    return wrap;
  }

  /** 「行动记录」那一条折叠栏：aria-expanded 跟着 ui.logOpen 走。 */
  function logBar() {
    var bar = el("div", "log-bar");
    var b = el("button", "btn small bare log-toggle");
    b.setAttribute("aria-expanded", ui.logOpen ? "true" : "false");
    b.appendChild(iconNode("scroll"));
    b.appendChild(el("span", null, "行动记录"));
    b.appendChild(el("span", "caret"));
    b.addEventListener("click", function () {
      ui.logOpen = !ui.logOpen;
      render();
      if (ui.logOpen) { scrollReading(1e9); }
    });
    bar.appendChild(b);
    bar.appendChild(el("span", "count", game.state.log.length + " 则"));
    return bar;
  }

  /** 这一则里有没有「名字：」的对话行 —— 有才给 .dlg 的边（一字不改，只换观感）。 */
  function saysIt(text) {
    return String(text).split("\n").some(function (line) {
      var rest = line.replace(/^\s+/, "");
      var cut = rest.indexOf("：");
      return cut > 0 && !!SPEAKERS[rest.slice(0, cut)];
    });
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
        b.appendChild(el("span", "did kv", did));
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
      b.appendChild(el("span", "did kv", hit[0] + " · " + hit[1]));
      b.appendChild(el("span", "snippet", hit[2]));
      b.addEventListener("click", function () { readDossier(hit[0]); });
      wrap.appendChild(b);
    });
    return wrap;
  }

  function renderOptions() {
    var panel = el("div", "panel options page page-log");
    var head = el("div", "panel-head");
    head.appendChild(iconNode("scroll"));
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
      body.appendChild(el("p", "empty", "此刻无事可做：翻翻档目，或问问在场的人。"));
      return;
    }
    opts.forEach(function (opt, i) {
      var b = el("button", "choice-card opt" + (i === ui.cursor ? " focus" : ""));
      b.appendChild(el("span", "choice-num num", String(opt.index)));
      var label = el("span", "choice-label label", opt.label);
      if (opt.detail) { label.appendChild(el("span", "detail", opt.detail)); }
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
    // 吸底那一条要挂在**面板**上：面板自己有 overflow:hidden，挂在内层就不吸了
    var panel = el("div", "panel page page-log command-bar");
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

  // ------------------------------------------------------------------
  // 右栏：四张仪表卡
  //
  // 全是真数据：进度读 game.state 与 PACK 的计数，人物心意读 state.trust，
  // 刻度用 PACK.characters[cid].confide_at（999 = 永不肯深谈，只显示数字）。
  // 窄屏怎么折叠是 CSS 的事 —— 这里一个宽度判断都不写。
  // ------------------------------------------------------------------

  /** 顶栏右侧的图标钮：只有图标没有字（按文案找按钮的脚本不会多认出一个「案外」）。 */
  function topActions() {
    var box = el("div", "top-actions");
    [["save", "存档", doSave],
     ["load", "读档 / 搬档", function () { ui.overlay = { kind: "save" }; renderOverlay(); }],
     ["leaf", "案外", function () { ui.tab = "collection"; render(); }],
     ["help", "帮助", function () { ui.overlay = { kind: "help" }; renderOverlay(); }],
     ["home", "回到标题", backToTitle]].forEach(function (spec) {
      var b = el("button", "btn small icon-btn", null,
        { title: spec[1], "aria-label": spec[1] });
      b.appendChild(iconNode(spec[0]));
      b.addEventListener("click", spec[2]);
      box.appendChild(b);
    });
    return box;
  }

  /** 顶栏的一枚芯片：图标 + 「词 + b(读数)」。文本与从前一字不差。 */
  function hudChip(icon, label, value, extra) {
    var chip = el("span", "hud-chip" + (extra ? " " + extra : ""));
    chip.appendChild(iconNode(icon));
    chip.appendChild(document.createTextNode(label + " "));
    chip.appendChild(el("b", null, esc(value)));
    return chip;
  }

  function railHead(card, icon, title, count) {
    var head = el("div", "panel-head");
    head.appendChild(iconNode(icon));
    head.appendChild(el("span", null, title));
    head.appendChild(el("span", "count", count || ""));
    card.appendChild(head);
    return head;
  }

  function railProgress() {
    var st = game.state;
    var card = el("div", "panel rail-card");
    railHead(card, "progress", "进度", game.actTitleOf(st.chapter));
    var body = el("div", "panel-body");
    [["线索", st.clues.length + "/" + PACK.core_total],
     ["档目", game.knownDossiers().length + "/" + Object.keys(PACK.dossiers).length],
     ["评分", String(st.score)]].forEach(function (pair) {
      var row = el("div", "rail-stat");
      row.appendChild(el("span", "rail-label", pair[0]));
      row.appendChild(el("span", "rail-num", pair[1]));
      body.appendChild(row);
    });
    card.appendChild(body);
    return card;
  }

  function railTrust() {
    var st = game.state;
    var chars = PACK.characters || {};
    var card = el("div", "panel rail-card");
    var body = el("div", "panel-body trust-list");
    var ready = 0;
    Object.keys(chars).forEach(function (cid) {
      var ch = chars[cid] || {};
      var now = Number(st.trust[cid]);
      if (!isFinite(now)) { now = 0; }
      var at = Number(ch.confide_at);
      if (!isFinite(at) || at <= 0) { at = 999; }
      var row = el("div", "trust-row");
      row.appendChild(el("span", "trust-name", ch.name || cid));
      if (at !== 999) {
        // 刻度就是「深谈那道线」：条填满，说明这个人可以深谈了
        var bar = el("div", "trust-bar");
        var fill = el("div", "trust-fill");
        fill.setAttribute("style",
          "width:" + Math.max(0, Math.min(100, Math.round(now / at * 100))) + "%");
        bar.appendChild(fill);
        row.appendChild(bar);
        if (now >= at) { row.appendChild(el("span", "trust-candie")); ready += 1; }
      }
      row.appendChild(el("span", "trust-num", String(now)));
      body.appendChild(row);
    });
    railHead(card, "person", "人物心意", ready ? ready + " 人可深谈" : "");
    card.appendChild(body);
    return card;
  }

  /** 一小撮芯片（线索囊 / 随身之物共用）：点一下就去检索这个词。 */
  function chipRow(ids, kind) {
    var wrap = el("div", "chip-row");
    ids.forEach(function (id) {
      var item = PACK.items[id] || {};
      var name = item.name || id;
      var b = el("button", "btn small bare " + kind, name);
      b.addEventListener("click", function () { doSearch(name); });
      wrap.appendChild(b);
    });
    return wrap;
  }

  function railClues() {
    var st = game.state;
    var card = el("div", "panel rail-card");
    railHead(card, "clue", "线索囊", st.clues.length + "/" + PACK.core_total);
    var body = el("div", "panel-body");
    var recent = st.clues.slice(-5).reverse();
    if (recent.length) { body.appendChild(chipRow(recent, "clue-chip")); }
    else { body.appendChild(el("p", "empty", "还没有线索。")); }
    card.appendChild(body);
    return card;
  }

  function railBag() {
    var owned = game.state.items_owned || [];
    var card = el("div", "panel rail-card");
    railHead(card, "evidence", "随身之物", String(owned.length));
    var body = el("div", "panel-body");
    if (owned.length) { body.appendChild(chipRow(owned, "item-chip")); }
    else { body.appendChild(el("p", "empty", "行囊还空着。")); }
    card.appendChild(body);
    return card;
  }

  function renderRail() {
    var wrap = el("div", "rail");
    wrap.appendChild(railProgress());
    wrap.appendChild(railTrust());
    wrap.appendChild(railClues());
    wrap.appendChild(railBag());
    return wrap;
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
    // page-log 也挂上：手机上翻到「卷宗」那一页时，存档 / 帮助也得够得着
    var panel = el("div", "panel page page-log page-index page-notes page-search page-collection");
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
    if (!ui.overlay) {
      // 关掉浮层时松开底下的页面滚动（假 DOM 没有 removeAttribute，只能写空值）
      document.body.setAttribute("data-overlay", "");
      return;
    }
    document.body.setAttribute("data-overlay", "1");
    var wrap = el("div", "overlay");
    wrap.id = "overlay";
    var sheet = el("div", "sheet glass-panel");
    var kind = ui.overlay.kind;

    function closeRow(extra) {
      var row = el("div", "sheet-actions");
      if (extra) { row.appendChild(extra); }
      var b = el("button", "btn", "合上");
      b.addEventListener("click", function () { ui.overlay = null; renderOverlay(); });
      row.appendChild(b);
      return row;
    }

    // 顶上常驻一行出口：帮助那张表很长，在手机上要滚到底才够得着「合上」
    // （按钮文案与底下那个「合上」不重名，免得按文案找按钮的脚本两头都命中）
    function sheetTop() {
      var bar = el("div", "sheet-top");
      bar.appendChild(el("span", null, "Esc 可合上"));
      var close = el("button", "btn small bare", "收起");
      close.addEventListener("click", function () { ui.overlay = null; renderOverlay(); });
      bar.appendChild(close);
      return bar;
    }
    sheet.appendChild(sheetTop());

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
       ["数字 1-9", "选第 N 项动作"],
       ["↑ ↓（行里有字时）", "翻敲过的指令"]].forEach(function (pair) {
        var tr = el("tr");
        tr.appendChild(el("td", "k", pair[0]));
        tr.appendChild(el("td", null, pair[1]));
        table.appendChild(tr);
      });
      sheet.appendChild(table);
      sheet.appendChild(el("div", "rule"));
      sheet.appendChild(el("h4", null, "终端版还多这些敲法"));
      sheet.appendChild(el("p", "empty", "下面这张表是终端版认的写法。" +
        "网页版没有「问 / 出示 / 前往 / 查证 / 复核 / 指认 / 目 / 幕」这些动词，" +
        "只认上面那张表，外加「把选项上的字敲出来」这一条。"));
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
        var verr = saveVersionError(data);
        if (verr) { toast("这份存档读不了：" + verr, "error"); return; }
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
      // 提示条是唯一的异步反馈：让读屏软件也念一遍（旧版只在屏幕上闪 4 秒）
      box.setAttribute("role", "status");
      box.setAttribute("aria-live", "polite");
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

  // ------------------------------------------------------------------
  // 图景
  //
  // #stage / #stage-card 是 shell.html 里 #app 的同级节点，这里只改它们身上的
  // data-* 属性。render() 每次 clear(root) 只清 #app，所以图景不会跟着一次次
  // 重画从头动起，阅读区的卷动位置也碰不到。
  //
  // 台账（色调 / 明暗 / 字形）由 gongwei/web/art.py 生成，一路带进 #art 块；
  // 读不到就退到 default_*，图景只是不换，游戏照玩。
  // ------------------------------------------------------------------

  var ART = window.__GONGWEI_ART__ || {};
  var SET_KEY = "gongwei_settings";
  var MARKS_KEY = "gongwei_marks";

  var PACE_MS = { quick: 1200, normal: 2200, slow: 3600 };
  var settings = { motion: "on", pace: "normal", sfx: "on", volume: 60 };
  var marks = { acts: [], endings: [] };
  var storageOk = true;

  var stage = document.getElementById("stage");
  var stageCard = document.getElementById("stage-card");
  // act 从 null 起手：标题屏要的就是第 0 幕，若与初值相同就一个属性都不写，
  // 页面就变成「属性全靠 shell.html 里那三个默认值」——两边一旦不同步没人看得出来。
  var shown = { tone: "", light: "", act: null, scene: "" };
  var cardTimer = null;

  function readStore(key) {
    try {
      var raw = window.localStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }

  function writeStore(key, value) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
      return true;
    } catch (e) {
      storageOk = false;
      return false;
    }
  }

  function loadSettings() {
    var saved = readStore(SET_KEY) || {};
    if (saved.motion === "on" || saved.motion === "off") { settings.motion = saved.motion; }
    if (PACE_MS[saved.pace]) { settings.pace = saved.pace; }
    if (saved.sfx === "on" || saved.sfx === "off") { settings.sfx = saved.sfx; }
    var vol = Number(saved.volume);
    if (isFinite(vol) && vol >= 0 && vol <= 100) { settings.volume = Math.round(vol); }
    document.body.setAttribute("data-motion", settings.motion);
  }

  function saveSettings() {
    if (!writeStore(SET_KEY, settings)) {
      toast("设定存不进本机：这一屏改了，下一屏会忘。", "error");
    }
    document.body.setAttribute("data-motion", settings.motion);
  }

  function loadMarks() {
    var saved = readStore(MARKS_KEY) || {};
    marks.acts = Array.isArray(saved.acts) ? saved.acts : [];
    marks.endings = Array.isArray(saved.endings) ? saved.endings : [];
  }

  // 案外只记「到过哪儿」，不记剧情：没到过的幕与结局一律只说「未至 / 未解」，
  // 不然收集册会先把后面的幕名和结局名漏给玩家。
  function noteProgress() {
    var st = game.state, changed = false;
    if (st.chapter && marks.acts.indexOf(st.chapter) < 0) { marks.acts.push(st.chapter); changed = true; }
    if (st.ending && marks.endings.indexOf(st.ending) < 0) { marks.endings.push(st.ending); changed = true; }
    if (changed) { writeStore(MARKS_KEY, marks); }
  }

  function isVerdictScene(id) { return (PACK.verdict_scenes || []).indexOf(id) >= 0; }

  // 引擎只认「现在这一支结局」（game.endingInfo），案外册要把 20 支全列出来，
  // 所以这里自己按 id 在 PACK.endings 里找一遍。
  function endingById(eid) {
    var list = PACK.endings || [];
    for (var i = 0; i < list.length; i += 1) {
      if (list[i].id === eid) { return list[i]; }
    }
    return null;
  }

  // 台账里那份 tones 就用在这么一道闸上：万一配色表被手改过、或只带来半份台账，
  // 宁可退回默认景，也不要让 #stage 顶着一个 CSS 根本画不出来的色调（那一屏会是白的）。
  function knownTone(tone) {
    var list = ART.tones || [];
    if (!list.length) { return tone || "hall"; }
    return list.indexOf(tone) >= 0 ? tone : (ART.default_tone || "hall");
  }

  // 色调优先级：结案 > 判决屏 > 当场有对谈的人 > 所在地。台账里没有的地点退到 default。
  function toneOf(scene, st) {
    var byPlace = ART.place_tone || {};
    var tone;
    if (st.ending || (scene && scene.kind === "ending")) { tone = ART.tone_ending || "ending"; }
    else if (isVerdictScene(st.scene)) { tone = ART.tone_verdict || "verdict"; }
    else if (scene && (scene.interlocutor || scene.hall)) { tone = ART.tone_encounter || "interrogation"; }
    else { tone = byPlace[scene ? scene.place : ""] || ART.default_tone || "hall"; }
    return knownTone(tone);
  }

  function lightOf(scene, st) {
    var byTime = ART.time_light || {};
    return byTime[st.time] || byTime[scene ? scene.time : ""] || ART.default_light || "day";
  }

  function paintStage(tone, light, act) {
    if (!stage) { return; }
    if (tone !== shown.tone) { stage.setAttribute("data-tone", tone); shown.tone = tone; }
    if (light !== shown.light) { stage.setAttribute("data-light", light); shown.light = light; }
    if (act !== shown.act) { stage.setAttribute("data-act", String(act)); shown.act = act; }
  }

  function showCard(title, sub) {
    if (!stageCard || !title) { return; }
    clear(stageCard);
    stageCard.appendChild(el("b", null, title));
    if (sub) { stageCard.appendChild(el("span", null, sub)); }
    stageCard.className = "stage-card on";
    if (cardTimer) { clearTimeout(cardTimer); }
    cardTimer = setTimeout(function () {
      cardTimer = null;
      if (stageCard) { stageCard.className = "stage-card"; }
    }, PACE_MS[settings.pace] || PACE_MS.normal);
  }

  // 每次重画都报一次：换幕说一句，换场换色调与明暗。标题屏一律报 hall/day。
  function applyStage() {
    if (ui.screen === "title") {
      paintStage(knownTone(ART.default_tone), ART.default_light || "day", 0);
      shown.scene = "";
      return;
    }
    var st = game.state;
    var scene = PACK.scenes[st.scene] || {};
    var act = st.chapter || 0;
    var actChanged = act !== shown.act;
    var sceneChanged = st.scene !== shown.scene;
    paintStage(toneOf(scene, st), lightOf(scene, st), act);
    shown.scene = st.scene;
    if (actChanged && act) {
      showCard(game.actTitleOf(act), (scene.place || "") + (st.time ? " · " + st.time : ""));
    } else if (sceneChanged && isVerdictScene(st.scene)) {
      showCard("判决 · " + (scene.title || ""), scene.place || "");
    } else if (sceneChanged && st.ending) {
      showCard("结案 · " + (scene.title || ""), scene.place || "");
    }
  }

  // ------------------------------------------------------------------
  // 音效：现吹，不放音频文件
  //
  // 一簇正弦/三角波，几十毫秒起音、一两秒衰减干净。浏览器不许没交互就出声，
  // 所以第一声一定落在点按之后；没有 WebAudio 的环境（老浏览器、测试沙箱）
  // 一律静默跳过，不报错。
  // ------------------------------------------------------------------

  var CUES = {
    scene: [[392, 0, 0.9, 0.10, "sine"], [523.25, 0.08, 1.1, 0.07, "sine"]],
    clue: [[659.25, 0, 0.35, 0.10, "triangle"], [987.77, 0.09, 0.5, 0.07, "triangle"]],
    dossier: [[220, 0, 0.5, 0.10, "sine"], [329.63, 0.06, 0.6, 0.07, "sine"]],
    verdict: [[146.83, 0, 1.6, 0.16, "sine"], [110, 0.06, 1.8, 0.12, "sine"]],
    ending: [[261.63, 0, 1.0, 0.10, "sine"], [329.63, 0.18, 1.1, 0.09, "sine"],
             [392, 0.36, 1.5, 0.08, "sine"]]
  };

  var audioCtx = null;

  function audioCue(name) {
    var notes = CUES[name];
    if (!notes || settings.sfx !== "on" || settings.volume <= 0) { return; }
    var Ctor = window.AudioContext || window.webkitAudioContext;
    if (!Ctor) { return; }
    if (!audioCtx) {
      try { audioCtx = new Ctor(); } catch (e) { audioCtx = null; return; }
    }
    var now = audioCtx.currentTime;
    notes.forEach(function (note) {
      var osc = audioCtx.createOscillator();
      var gain = audioCtx.createGain();
      osc.type = note[4] || "sine";
      osc.frequency.value = note[0];
      var peak = (settings.volume / 100) * note[3];
      gain.gain.setValueAtTime(0.0001, now + note[1]);
      gain.gain.exponentialRampToValueAtTime(peak, now + note[1] + 0.04);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + note[1] + note[2]);
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start(now + note[1]);
      osc.stop(now + note[1] + note[2] + 0.05);
    });
  }

  function cueFor(upd) {
    if (!upd) { return; }
    if (upd.ended) { audioCue("ending"); return; }
    if (upd.scene_changed) { audioCue("scene"); return; }
    if ((upd.new_dossiers || []).length) { audioCue("dossier"); return; }
    if ((upd.new_clues || []).length || (upd.new_items || []).length) { audioCue("clue"); }
  }

  // ------------------------------------------------------------------
  // 说话人名牌
  //
  // 卷宗里的正文是逐字跟着存档走的，所以只在「名字：」那一段外面套一个 span，
  // 其余一字不动：换行照旧补回去，textContent 与以前完全一样。
  // ------------------------------------------------------------------

  // 名字必须真的在人物表里。旁白里「结案文书上写的是：……」这类句子的第一处
  // 冒号也落在十二字内，只按冒号切会把它染成名牌——全篇有二十三处。
  var SPEAKERS = (function () {
    var map = {};
    var chars = PACK.characters || {};
    Object.keys(chars).forEach(function (cid) {
      var name = chars[cid] && chars[cid].name;
      if (name) { map[name] = cid; }
    });
    return map;
  })();

  function saidLine(line) {
    // 供词是缩进排的：07-DL-TWO 只有第一行顶格，后两行各带六个空格。
    var lead = /^\s*/.exec(line)[0];
    var rest = line.slice(lead.length);
    // 旁注行（正文以 // 开头，如「//份档号：…」「//另有一事记在尸格末尾」）：
    // 整行降一档，只把开头的 // 点金——正文一字不动，pane 文本仍然逐字相同
    if (rest.slice(0, 2) === "//") {
      var note = el("span", "note-line");
      if (lead) { note.appendChild(document.createTextNode(lead)); }
      note.appendChild(el("span", "note-mark", "//"));
      note.appendChild(document.createTextNode(rest.slice(2)));
      return note;
    }
    // 【线索】/【物证】那一小撮记号点个底色：只多套一层 span，正文一字不动
    var mark = /^【(?:线索|物证)】/.exec(rest);
    if (mark) {
      var tagged = el("span", "said-line kv-line");
      if (lead) { tagged.appendChild(document.createTextNode(lead)); }
      tagged.appendChild(el("span", "kv", mark[0]));
      tagged.appendChild(document.createTextNode(rest.slice(mark[0].length)));
      return tagged;
    }
    var cut = rest.indexOf("：");
    if (cut <= 0 || !SPEAKERS[rest.slice(0, cut)]) { return el("span", null, line); }
    var span = el("span", "said-line");
    if (lead) { span.appendChild(document.createTextNode(lead)); }
    span.appendChild(el("span", "said-name", rest.slice(0, cut + 1)));
    span.appendChild(document.createTextNode(rest.slice(cut + 1)));
    return span;
  }

  /** 逐行套名牌，并把换行原样补回去：整段文字与从前一字不差。 */
  function saidLinesInto(node, text) {
    String(text).split("\n").forEach(function (line, i) {
      if (i) { node.appendChild(document.createTextNode("\n")); }
      node.appendChild(saidLine(line));
    });
    return node;
  }

  function saidParagraph(text) {
    return saidLinesInto(el("p"), text);
  }

  // 结局印：rank 早就跟着内容包一路带到网页端了（gongwei/web/pack.py），
  // 只是从前没人用它。印的是「评等 + 结局名」，与顶栏那个「已结案」小印分开。
  function endingSeal(eid) {
    var e = endingById(eid);
    var box = el("div", "ending-seal");
    box.appendChild(el("div", "seal-stamp", e && e.rank ? e.rank : "卷终"));
    if (e) {
      box.appendChild(el("div", "seal-title", e.title));
      if (e.subtitle) { box.appendChild(el("div", "seal-sub", e.subtitle)); }
    }
    return box;
  }

  // ------------------------------------------------------------------
  // 卷首过场：换幕时铺一层
  //
  // 只在幕号真的变了的那一次 render() 之后铺（ui.lastAct 记着上次报过哪一幕）。
  // 点一下、或按 Esc 收起；动效开关交给 CSS（body[data-motion="off"] 把动画压平），
  // 这里只管把 .on 加上、收起时去掉。
  // ------------------------------------------------------------------

  var splashTimer = null;

  function closeSplash() {
    var node = document.getElementById("splash");
    if (!node) { return; }
    node.className = "splash";            // 去掉 on：CSS 在这一档收尾
    node.setAttribute("id", "");          // 腾出 id，下一幕的过场才认准自己那一个
    if (splashTimer) { clearTimeout(splashTimer); }
    splashTimer = setTimeout(function () {
      splashTimer = null;
      if (node.remove) { node.remove(); }
    }, 260);
  }

  /** 汉字的幕号（1 → 一，11 → 十一）。 */
  function hanNum(n) {
    var digits = "〇一二三四五六七八九";
    if (!n || n < 1) { return "〇"; }
    if (n < 10) { return digits.charAt(n); }
    if (n === 10) { return "十"; }
    if (n < 20) { return "十" + digits.charAt(n - 10); }
    return digits.charAt(Math.floor(n / 10)) + "十" + (n % 10 ? digits.charAt(n % 10) : "");
  }

  function showSplash(act) {
    closeSplash();
    var box = el("div", "splash on");
    box.id = "splash";
    box.appendChild(el("div", "splash-veil", null, { "aria-hidden": "true" }));
    var card = el("div", "splash-card");
    card.appendChild(el("div", "splash-art", null, { "aria-hidden": "true" }));
    card.appendChild(el("div", "splash-num", hanNum(act)));
    card.appendChild(el("div", "splash-title", game.actTitleOf(act)));
    card.appendChild(sep());
    card.appendChild(el("div", "splash-quote", PACK.prologue));
    var stamp = el("div", "seal-stamp");
    stamp.appendChild(iconNode("seal"));
    stamp.appendChild(el("span", null, hanNum(act) + "幕"));
    card.appendChild(stamp);
    card.appendChild(el("div", "splash-hint", "轻触任意处 · 入局"));
    box.appendChild(card);
    box.addEventListener("click", closeSplash);
    document.body.appendChild(box);
  }

  /** 每次 render() 收尾都过一下：幕号变了才铺过场，回标题屏就收起来。 */
  function maybeSplash() {
    var act = ui.screen === "game" ? (game.state.chapter || 0) : 0;
    if (act === ui.lastAct) { return; }
    ui.lastAct = act;
    if (!act || game.state.ending) { closeSplash(); return; }
    showSplash(act);
  }

  // ------------------------------------------------------------------
  // 案外：行囊 / 幕册 / 结局册 / 音画设定
  // ------------------------------------------------------------------

  function glyphSpan(tag) {
    var known = ART.glyphs || [];
    var span = el("span", "glyph");
    span.setAttribute("data-glyph", known.indexOf(tag) >= 0 ? tag : (ART.glyph_fallback || "mark"));
    return span;
  }

  function bagRows() {
    var st = game.state;
    var owned = [];
    (st.clues || []).forEach(function (id) { owned.push(id); });
    (st.items_owned || []).forEach(function (id) { if (owned.indexOf(id) < 0) { owned.push(id); } });
    owned.sort(function (a, b) {
      var ia = PACK.items[a] || {}, ib = PACK.items[b] || {};
      return (ib.core ? 1 : 0) - (ia.core ? 1 : 0);
    });
    var list = el("div", "bag");
    if (!owned.length) {
      list.appendChild(el("div", "empty", "行囊还空着。"));
      return list;
    }
    owned.forEach(function (id) {
      var item = PACK.items[id] || {};
      var row = el("div", "bag-row" + (item.core ? " core" : ""));
      row.appendChild(glyphSpan(item.tag || ""));
      row.appendChild(el("span", "bag-name", item.name || id));
      list.appendChild(row);
    });
    return list;
  }

  function settingsRow(label, choices, current, apply) {
    var row = el("div", "setting-row");
    row.appendChild(el("span", "setting-label", label));
    var group = el("span", "setting-choices");
    choices.forEach(function (pair) {
      var b = el("button", "btn small" + (pair[1] === current() ? " on" : ""), pair[0]);
      b.addEventListener("click", function () { apply(pair[1]); render(); });
      group.appendChild(b);
    });
    row.appendChild(group);
    return row;
  }

  function renderSettings() {
    var box = el("div", "settings");
    box.appendChild(settingsRow("动效", [["开", "on"], ["关", "off"]],
      function () { return settings.motion; },
      function (v) { settings.motion = v; saveSettings(); }));
    box.appendChild(settingsRow("过场停留", [["快", "quick"], ["中", "normal"], ["慢", "slow"]],
      function () { return settings.pace; },
      function (v) { settings.pace = v; saveSettings(); }));
    box.appendChild(settingsRow("音效", [["开", "on"], ["关", "off"]],
      function () { return settings.sfx; },
      function (v) { settings.sfx = v; saveSettings(); if (v === "on") { audioCue("dossier"); } }));
    box.appendChild(settingsRow("音量", [["静音", 0], ["25%", 25], ["50%", 50], ["75%", 75], ["100%", 100]],
      function () { return settings.volume; },
      function (v) { settings.volume = v; saveSettings(); audioCue("clue"); }));
    if (!storageOk) {
      box.appendChild(el("div", "empty",
        "本机存不下（隐私模式，或站点数据满了）：进度与设定都只留在这一屏。"));
    }
    return box;
  }

  function renderCollection() {
    var panel = el("div", "panel page page-collection");
    var acts = PACK.act_numbers || [];
    var endings = PACK.endings || [];

    var head = el("div", "panel-head");
    head.appendChild(el("span", null, "案外"));
    head.appendChild(el("span", "count", "幕 " + marks.acts.length + "/" + acts.length +
      " · 结局 " + marks.endings.length + "/" + endings.length));
    panel.appendChild(head);

    var body = el("div", "panel-body");

    body.appendChild(el("h4", null, "幕册"));
    var actList = el("div", "marks");
    acts.forEach(function (n) {
      var done = marks.acts.indexOf(n) >= 0;
      var row = el("div", "mark-row" + (done ? " on" : ""));
      row.appendChild(el("span", "mark-num", "第 " + n + " 幕"));
      row.appendChild(el("span", "mark-name", done ? game.actTitleOf(n) : "未至"));
      actList.appendChild(row);
    });
    body.appendChild(actList);

    body.appendChild(el("h4", null, "结局册"));
    var endList = el("div", "marks");
    endings.forEach(function (e) {
      var done = marks.endings.indexOf(e.id) >= 0;
      var row = el("div", "mark-row" + (done ? " on" : ""));
      row.appendChild(el("span", "mark-rank", done && e.rank ? e.rank : "·"));
      row.appendChild(el("span", "mark-name", done ? e.title : "未解"));
      if (done && e.subtitle) { row.appendChild(el("span", "mark-sub", e.subtitle)); }
      endList.appendChild(row);
    });
    body.appendChild(endList);

    body.appendChild(el("h4", null, "行囊"));
    body.appendChild(bagRows());

    body.appendChild(el("h4", null, "音画设定"));
    body.appendChild(renderSettings());

    panel.appendChild(body);
    return panel;
  }

  // 过场是铺在 #app 外面的一层：Esc 先合浮层（上面那条监听器），再退过场
  document.addEventListener("keydown", function (ev) {
    if (ev.key !== "Escape" || ui.overlay) { return; }
    closeSplash();
  });

  // 起手：先读设定与案外进度，再看标题屏
  loadSettings();
  loadMarks();
  render();
})();
