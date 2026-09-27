/* 宫闱迷踪 · 网页端引擎
 *
 * 这是 `gongwei/game/engine.py` 的 JS 对等实现：同一份剧本、同一套判定、
 * 同一份存档形状（`{v, state:{...}}`，与 `gongwei/game/save.py` 逐字对齐）。
 *
 * **为什么可以有两份实现而不算重复劳动**：剧本、条件、结局规则都是
 * `tools/build_web.py` 从 Python 侧生成过来的数据（条件以 AST 形式带上），
 * 这里只有「怎么算」——选项怎么筛、效果怎么落、档案怎么收、结局怎么裁。
 * `tools/audit_web.py` 会拿同一串动作分别喂给两边，逐字比对**每一步的存档**；
 * 一旦哪天引擎改了一边忘了另一边，那道门禁就会红。
 */
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) {
    module.exports = factory();
  } else {
    root.GongweiGame = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // ------------------------------------------------------------------
  // 比较与条件求值
  // ------------------------------------------------------------------

  function cmp(value, op, num) {
    switch (op) {
      case ">=": return value >= num;
      case "<=": return value <= num;
      case "==": return value === num;
      case "!=": return value !== num;
      case ">": return value > num;
      case "<": return value < num;
    }
    throw new Error("未知比较运算符: " + op);
  }

  function trustOf(st, cid) {
    var v = st.trust[cid];
    return v === undefined ? 0 : v;
  }

  function dossierRead(st, did) {
    var pair = st.dossiers[did];
    return !!pair && !!pair[0];
  }

  function dossierKnown(st, did) {
    var pair = st.dossiers[did];
    return !!pair && !pair[1];
  }

  function dossiersReadCount(st) {
    var n = 0;
    for (var did in st.dossiers) {
      if (st.dossiers[did][0]) { n += 1; }
    }
    return n;
  }

  var ENGINE = null;   // 当前引擎（求值条件时要用它数核心证据）

  function coreCount(st) {
    var content = ENGINE.content;
    var held = st.clues.concat(st.items_owned);
    var seen = {}, n = 0;
    for (var i = 0; i < held.length; i++) {
      var id = held[i];
      if (seen[id]) { continue; }
      seen[id] = true;
      var item = content.items[id];
      if (item && item.core) { n += 1; }
    }
    return n;
  }

  /** 解释一条条件 AST（Python 侧 `gongwei/game/conditions.py` 生成的）。 */
  function evalAst(node, st) {
    if (node === null || node === undefined) { return true; }
    var op = node[0];
    switch (op) {
      case "always": return true;
      case "never": return false;
      case "clue":
        return st.clues.indexOf(node[1]) >= 0 || st.items_owned.indexOf(node[1]) >= 0;
      case "flag": return st.flags.indexOf(node[1]) >= 0;
      case "dossier": return dossierRead(st, node[1]);
      case "missing_dossier": return !dossierRead(st, node[1]);
      case "dossiers_count": return cmp(dossiersReadCount(st), node[1], node[2]);
      case "trust": return cmp(trustOf(st, node[1]), node[2], node[3]);
      case "clues_count": return cmp(st.clues.length, node[1], node[2]);
      case "items_count": return cmp(st.items_owned.length, node[1], node[2]);
      case "core_count": return cmp(coreCount(st), node[1], node[2]);
      case "clues_count_in": {
        var ids = node[1], hit = 0;
        for (var i = 0; i < ids.length; i++) {
          if (st.clues.indexOf(ids[i]) >= 0) { hit += 1; }
        }
        return cmp(hit, node[2], node[3]);
      }
      case "clues_at_least": {
        var list = node[1], got = 0;
        for (var j = 0; j < list.length; j++) {
          if (st.clues.indexOf(list[j]) >= 0 || st.items_owned.indexOf(list[j]) >= 0) {
            got += 1;
          }
        }
        return got >= node[2];
      }
      case "suspect": return st.accused === node[1];
      case "suspect_in": return node[1].indexOf(st.accused) >= 0;
      case "visited": return st.visited.indexOf(node[1]) >= 0;
      case "time_at":
        return ENGINE.timeIndex(st.time) >= ENGINE.timeIndex(node[1]);
      case "all":
        return node[1].every(function (n) { return evalAst(n, st); });
      case "any":
        return node[1].some(function (n) { return evalAst(n, st); });
      case "not": return !evalAst(node[1], st);
    }
    throw new Error("未知条件节点: " + JSON.stringify(node));
  }

  // ------------------------------------------------------------------
  // 排版（与 gongwei/game/engine.py 的 char_width / _wrap_cjk 对齐）
  // ------------------------------------------------------------------

  function charWidth(ch) {
    var cp = ch.codePointAt(0);
    if (cp >= 0x1f300 && cp <= 0x1faff) { return 2; }
    if (cp >= 0x1100 && (
      cp <= 0x115f || cp === 0x2329 || cp === 0x232a ||
      (cp >= 0x2e80 && cp <= 0xa4cf && cp !== 0x303f) ||
      (cp >= 0xac00 && cp <= 0xd7a3) ||
      (cp >= 0xf900 && cp <= 0xfaff) ||
      (cp >= 0xfe30 && cp <= 0xfe6f) ||
      (cp >= 0xff00 && cp <= 0xff60) ||
      (cp >= 0xffe0 && cp <= 0xffe6) ||
      (cp >= 0x20000 && cp <= 0x3fffd))) {
      return 2;
    }
    return 1;
  }

  function displayWidth(text) {
    var w = 0;
    for (var ch of text) { w += charWidth(ch); }
    return w;
  }

  function wrapCjk(text, width) {
    if (width <= 0) { return [text]; }
    var out = [], cur = "", used = 0;
    for (var ch of text) {
      var w = charWidth(ch);
      if (used + w > width && cur) { out.push(cur); cur = ""; used = 0; }
      cur += ch; used += w;
    }
    if (cur) { out.push(cur); }
    return out;
  }

  function nowStamp() {
    var d = new Date();
    function p(n) { return (n < 10 ? "0" : "") + n; }
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) +
      " " + p(d.getHours()) + ":" + p(d.getMinutes());
  }

  // ------------------------------------------------------------------
  // 引擎
  // ------------------------------------------------------------------

  function Game(pack) {
    this.content = pack;
    this.time_order = pack.time_order || ["子时三刻"];
    this.topics_by_char = {};
    for (var i = 0; i < pack.topics.length; i++) {
      var t = pack.topics[i];
      (this.topics_by_char[t.owner] = this.topics_by_char[t.owner] || []).push(t);
    }
    ENGINE = this;
    this.state = this.newGame();
  }

  Game.prototype.timeIndex = function (t) {
    var i = this.time_order.indexOf(t);
    return i < 0 ? 0 : i;
  };

  // -- 新局 -----------------------------------------------------------
  Game.prototype.newGame = function () {
    var c = this.content;
    var st = {
      scene: c.start_scene, chapter: 1, case: 1, time: "", place: "",
      clues: [], items_owned: [], trust: {}, flags: [], visited: [],
      seen_choices: [], topics_asked: [], log: [], accused: "",
      score: 0, hurt: 0, ending: "", turn: 0, interrogating: "",
      dossiers: {}, notes: [], dossier_titles: {}, act_titles: {},
      open_dossier: ""
    };
    for (var cid in c.characters) { st.trust[cid] = c.characters[cid].trust; }
    for (var k = 0; k < (c.starter_dossiers || []).length; k++) {
      var did = c.starter_dossiers[k];
      if (c.dossiers[did]) { st.dossiers[did] = [false, false]; }
    }
    this.state = st;
    this.goTo(c.start_scene, null);
    return st;
  };

  // -- 存档（与 GameState.to_save 逐字对齐） ---------------------------
  Game.prototype.toSave = function () {
    var st = this.state;
    var dossiers = {}, did;
    var keys = Object.keys(st.dossiers).sort();
    for (var i = 0; i < keys.length; i++) {
      did = keys[i];
      dossiers[did] = [!!st.dossiers[did][0], !!st.dossiers[did][1]];
    }
    var titles = {}, tkeys = Object.keys(st.dossier_titles).sort();
    for (var j = 0; j < tkeys.length; j++) { titles[tkeys[j]] = st.dossier_titles[tkeys[j]]; }
    var acts = {}, akeys = Object.keys(st.act_titles).sort();
    for (var k = 0; k < akeys.length; k++) { acts[akeys[k]] = st.act_titles[akeys[k]]; }
    return {
      scene: st.scene, chapter: st.chapter, case: st.case, time: st.time, place: st.place,
      clues: st.clues.slice(), items_owned: st.items_owned.slice(),
      trust: Object.assign({}, st.trust),
      flags: st.flags.slice().sort(),
      visited: st.visited.slice().sort(),
      seen_choices: st.seen_choices.slice().sort(),
      topics_asked: st.topics_asked.slice(),
      log: st.log.slice(-160).map(function (e) { return [e[0], e[1]]; }),
      accused: st.accused, score: st.score, hurt: st.hurt,
      ending: st.ending, turn: st.turn, interrogating: st.interrogating,
      dossiers: dossiers, notes: st.notes.slice(),
      dossier_titles: titles, act_titles: acts,
      open_dossier: st.open_dossier
    };
  };

  Game.prototype.save = function () {
    return { v: 1, state: this.toSave(), title: this.content.title, stamp: nowStamp() };
  };

  Game.prototype.fromSave = function (payload) {
    var data = (payload && payload.state) ? payload.state : payload;
    var c = this.content;
    var st = this.newGame();
    st.scene = data.scene || c.start_scene;
    st.chapter = parseInt(data.chapter || 1, 10);
    st.case = parseInt(data.case || 1, 10);
    st.time = data.time === undefined ? st.time : data.time;
    st.place = data.place === undefined ? st.place : data.place;
    st.clues = (data.clues || []).slice();
    st.items_owned = (data.items_owned || []).slice();
    st.trust = {};
    var t = data.trust || {};
    for (var cid in t) { st.trust[cid] = parseInt(t[cid], 10); }
    st.flags = (data.flags || []).slice();
    st.visited = (data.visited || []).slice();
    st.seen_choices = (data.seen_choices || []).slice();
    st.topics_asked = (data.topics_asked || []).slice();
    st.log = (data.log || []).map(function (e) { return [e[0], e[1]]; });
    st.accused = data.accused || "";
    st.score = parseInt(data.score || 0, 10);
    st.hurt = parseInt(data.hurt || 0, 10);
    st.ending = data.ending || "";
    st.turn = parseInt(data.turn || 0, 10);
    st.interrogating = data.interrogating || "";
    st.dossiers = {};
    var ds = data.dossiers || {};
    for (var did in ds) {
      var pair = ds[did] || [false, false];
      st.dossiers[did] = [!!pair[0], !!pair[1]];
    }
    st.notes = (data.notes || []).slice();
    st.dossier_titles = Object.assign({}, data.dossier_titles || {});
    st.act_titles = Object.assign({}, data.act_titles || {});
    st.open_dossier = data.open_dossier || "";
    this.state = st;
    return st;
  };

  // -- 场景 -----------------------------------------------------------
  Game.prototype.scene = function (id) {
    return this.content.scenes[id || this.state.scene];
  };

  // -- 档案 -----------------------------------------------------------
  Game.prototype.dossierExists = function (did) {
    return !!this.content.dossiers[did];
  };

  // 这份档案属于第几案（按它的幕号查内容包里的 act_case 表）。
  Game.prototype.dossierCase = function (did) {
    var d = this.content.dossiers[did];
    if (!d) { return 0; }
    var m = this.content.act_case || {};
    return m[String(d.act)] || 1;
  };

  Game.prototype.canReadDossier = function (did) {
    var d = this.content.dossiers[did];
    if (!d) { return false; }
    if (dossierKnown(this.state, did)) { return true; }
    var open = (d.requires === null || d.requires === undefined)
      || !!evalAst(d.requires, this.state);
    if (open) { return true; }
    // 剧情锁：还没走到的案子，档号拼对了也调不到。
    if (this.dossierCase(did) > this.state.case) { return false; }
    return d.requires === null || d.requires === undefined;
  };

  Game.prototype.collectDossier = function (did, upd, guessed) {
    var c = this.content;
    if (!c.dossiers[did]) { return false; }
    if (!(did in this.state.dossiers)) {
      this.state.dossiers[did] = [false, !!guessed];
      if (upd && !guessed) { upd.new_dossiers.push(did); }
      return true;
    }
    return false;
  };

  Game.prototype.readDossier = function (did) {
    var upd = newUpdate();
    var d = this.content.dossiers[did];
    if (!d) { throw new Error("剧本缺少档案: " + did); }
    if (!this.canReadDossier(did)) { throw new Error("这份档案还不能调阅: " + did); }
    var first = !dossierRead(this.state, did);
    var guessed = false;
    if (!(did in this.state.dossiers)) {
      guessed = true;
      this.collectDossier(did, upd, true);
    }
    var st = this.state.dossiers[did];
    st[0] = true;
    this.state.open_dossier = did;
    this.state.turn += 1;
    if (first) {
      upd.new_dossiers.push(did);
      upd.toasts.push(d.found_msg || "//得到新档案——收录至档目//");
      var body = d.body;
      if (guessed) {
        body = body + "\n\n——这份档案不在册上。是你自己把档号拼出来的。";
      }
      this.state.log.push(["dossier", body]);
      upd.narration.push(body);
      // 与 Python 引擎同构：效果只在第一次打开时结算。
      this.applyEffect(d.effect, upd);
    } else {
      this.state.log.push(["system", "重阅 " + did + " · " + this.titleOfDossier(did)]);
    }
    for (var i = 0; i < (d.links || []).length; i++) {
      this.collectDossier(d.links[i], upd, false);
    }
    return upd;
  };

  Game.prototype.closeDossier = function () {
    this.state.open_dossier = "";
  };

  Game.prototype.dossierHints = function (did) {
    var d = this.content.dossiers[did];
    if (!d) { return 0; }
    var missing = 0;
    for (var i = 0; i < (d.links || []).length; i++) {
      var link = d.links[i];
      if (!this.content.dossiers[link]) { continue; }
      if (!dossierKnown(this.state, link)) { missing += 1; }
    }
    return missing;
  };

  Game.prototype.knownDossiers = function () {
    var out = [];
    for (var did in this.state.dossiers) {
      if (!this.state.dossiers[did][1]) { out.push(did); }
    }
    return out.sort();
  };

  Game.prototype.titleOfDossier = function (did) {
    var custom = this.state.dossier_titles[did];
    if (custom) { return custom; }
    var d = this.content.dossiers[did];
    return d ? d.title : did;
  };

  Game.prototype.actTitleOf = function (act) {
    var custom = this.state.act_titles[String(act)];
    if (custom) { return custom; }
    return this.content.act_titles[String(act)] || String(act);
  };

  /**
   * 顶栏那个「幕」该印第几幕：手上正读着档案，就印那份档案的幕（读第二幕的账目
   * 时别让人以为还停在第一幕）；没在读档案，就印当前的进度。
   *
   * 传的是**界面此刻正在显示的那一份**，不要改成直接看 `state.open_dossier`：
   * 那是引擎替存档记着的「上次读到哪儿」，读完退回卷宗、或读一份旧存档之后
   * 它仍然指着旧档，顶栏就会印错幕 —— 案① 已经结案、人站在第六幕的药库前，
   * 顶栏却写着「第一幕 · 贤妃薨（勘验）」。
   */
  Game.prototype.headAct = function (readingDossierId) {
    var d = readingDossierId ? this.content.dossiers[readingDossierId] : null;
    if (d && d.act) { return d.act; }
    return this.state.chapter;
  };

  Game.prototype.dossierIndex = function () {
    var out = [];
    var acts = this.content.act_numbers || [];
    var known = this.knownDossiers();
    for (var i = 0; i < acts.length; i++) {
      var act = acts[i], rows = [];
      for (var j = 0; j < known.length; j++) {
        var did = known[j], d = this.content.dossiers[did];
        if (!d || d.act !== act) { continue; }
        rows.push([did, this.titleOfDossier(did), this.dossierHints(did),
                   dossierRead(this.state, did)]);
      }
      if (rows.length) { out.push([act, rows]); }
    }
    return out;
  };

  Game.prototype.searchDossiers = function (term, limit) {
    limit = limit || 40;
    var t = (term || "").trim();
    if (!t) { return []; }
    var out = [];
    var keys = Object.keys(this.state.dossiers).sort();
    for (var i = 0; i < keys.length; i++) {
      var did = keys[i];
      if (!dossierRead(this.state, did)) { continue; }
      var d = this.content.dossiers[did];
      if (!d) { continue; }
      var hay = d.title + "\n" + d.body;
      var idx = hay.indexOf(t);
      if (idx < 0) { continue; }
      var lo = Math.max(0, idx - 18);
      var hi = Math.min(hay.length, idx + t.length + 22);
      var snippet = hay.slice(lo, hi).split("\n").join(" ");
      if (lo > 0) { snippet = "…" + snippet; }
      if (hi < hay.length) { snippet = snippet + "…"; }
      out.push([did, this.titleOfDossier(did), snippet]);
      if (out.length >= limit) { break; }
    }
    return out;
  };

  Game.prototype.dossierMeta = function (d) {
    var bits = [];
    if (d.time_code) { bits.push(d.time_code); }
    if (d.place_code) { bits.push(d.place_code); }
    if (d.people && d.people.length) {
      var names = [];
      for (var i = 0; i < d.people.length; i++) {
        var ch = this.content.characters[d.people[i]];
        names.push(ch ? ch.name : d.people[i]);
      }
      bits.push(names.join("、"));
    }
    return bits.join(" · ");
  };

  Game.prototype.dossierView = function (did, width) {
    width = width || 74;
    var d = this.content.dossiers[did];
    if (!d) { return ["找不到档案：" + did]; }
    var lines = [did + " · " + this.titleOfDossier(did)];
    var meta = this.dossierMeta(d);
    if (meta) { lines.push(meta); }
    lines.push("");
    var paras = (d.body || "").split("\n");
    for (var i = 0; i < paras.length; i++) {
      if (!paras[i].trim()) { lines.push(""); continue; }
      lines = lines.concat(wrapCjk(paras[i], width));
    }
    var hints = this.dossierHints(did);
    if (hints) {
      lines.push("");
      lines.push("——这份档案还牵着 " + hints + " 份未收集的档。");
    }
    return lines;
  };

  // -- 选项 -----------------------------------------------------------
  Game.prototype.options = function () {
    var scene = this.scene(), st = this.state;
    if (scene.kind === "ending") { return []; }
    var raw = scene.choices.map(function (ch) { return [ch, null]; });
    if (scene.interlocutor) {
      raw = raw.concat(this.interrogationChoices(scene.interlocutor));
    }
    var options = [];
    for (var i = 0; i < raw.length; i++) {
      var choice = raw[i][0], topicId = raw[i][1];
      var vis = choice.visible_if, lock = choice.locked_if || choice.locked_by;
      if (vis && !evalAst(vis, st)) { continue; }
      if (!choice.repeatable && st.seen_choices.indexOf(choice.key) >= 0) { continue; }
      var enabled = true, hint = "";
      if (lock && evalAst(lock, st)) {
        enabled = false;
        hint = choice.locked_hint || "条件不足";
      }
      options.push({
        index: 0, label: choice.label, detail: choice.detail || "",
        enabled: enabled, hint: hint, wants: choice.wants || "",
        tag: choice.tag || "", gated: !!(vis || lock),
        asked: st.seen_choices.indexOf(choice.key) >= 0,
        choice: choice, topic_id: topicId, engine: this
      });
    }
    for (var k = 0; k < options.length; k++) { options[k].index = k + 1; }
    return options;
  };

  Game.prototype.topicsFor = function (cid) {
    return this.topics_by_char[cid] || [];
  };

  Game.prototype.interrogationChoices = function (cid) {
    var out = [], st = this.state;
    var topics = this.topicsFor(cid);
    for (var i = 0; i < topics.length; i++) {
      var topic = topics[i];
      var enabled = true, hint = "";
      if (topic.gate && !evalAst(topic.gate, st)) {
        enabled = false;
        hint = topic.gate_hint || "尚不可问";
      }
      var asked = st.seen_choices.indexOf("topic::" + topic.id) >= 0;
      if (asked && enabled) { continue; }
      out.push([{
        // 与 Python 侧一致：问题选项自带 key = `"{to}::{label}"`，而这里的 to 是空串，
        // 所以 key 就是 `"::" + label`；`topic::<id>` 是另外记的一条（见 choose）。
        key: "::" + topic.label, label: topic.label,
        detail: topic.present ? "出示证物" : "", to: "",
        effect: topic.effect,
        locked_if: enabled ? null : ["always"], locked_hint: hint,
        wants: cid, tag: "interrogate", repeatable: false
      }, topic.id]);
    }
    var ch = this.content.characters[cid];
    // 与 Python 侧一致：问询场景可以自带退场去处（案② 回自己的前厅）
    var hall = this.scene().hall || this.content.interrogate_hall;
    out.push([{
      key: hall + "::" + "作揖告退 · 结束对「" +
        (ch ? ch.name : cid) + "」的问询",
      label: "作揖告退 · 结束对「" + (ch ? ch.name : cid) + "」的问询",
      detail: "", to: hall, effect: emptyEffect(),
      wants: cid, tag: "interrogate", repeatable: true
    }, null]);
    return out;
  };

  // -- 选择与效果 -----------------------------------------------------
  Game.prototype.choose = function (choice, topicId) {
    var upd = newUpdate();
    var st = this.state;
    if (st.seen_choices.indexOf(choice.key) < 0) { st.seen_choices.push(choice.key); }
    if (choice.suspect) {
      st.accused = choice.suspect;
      if (st.flags.indexOf("accused") < 0) { st.flags.push("accused"); }
    }
    if (topicId) {
      var tkey = "topic::" + topicId;
      if (st.seen_choices.indexOf(tkey) < 0) { st.seen_choices.push(tkey); }
      if (st.topics_asked.indexOf(topicId) < 0) { st.topics_asked.push(topicId); }
      var topic = this.topicById(topicId);
      var said = topic ? topic.response : "";
      if (said) {
        st.log.push(["narration", said]);
        upd.narration.push(said);
      }
    }
    this.applyEffect(choice.effect, upd);
    st.turn += 1;
    var target = (choice.effect && choice.effect.scene) || choice.to;
    if (target) {
      this.goTo(target, upd);
    } else if (!topicId) {
      st.log.push(["choice", choice.label]);
    }
    return upd;
  };

  Game.prototype.topicById = function (tid) {
    for (var i = 0; i < this.content.topics.length; i++) {
      if (this.content.topics[i].id === tid) { return this.content.topics[i]; }
    }
    return null;
  };

  Game.prototype.applyEffect = function (eff, upd) {
    upd = upd || newUpdate();
    if (!eff) { return upd; }
    var st = this.state, c = this.content, i;
    for (i = 0; i < (eff.add_clues || []).length; i++) {
      var cid = eff.add_clues[i];
      if (st.clues.indexOf(cid) >= 0 || st.items_owned.indexOf(cid) >= 0) { continue; }
      st.clues.push(cid);
      var item = c.items[cid];
      var name = item ? item.name : cid;
      upd.new_clues.push(name);
      upd.toasts.push("得到线索 · " + name);
      st.log.push(["clue", "【线索】" + name + " —— " + (item ? item.desc : "")]);
    }
    for (i = 0; i < (eff.add_items || []).length; i++) {
      var iid = eff.add_items[i];
      if (st.items_owned.indexOf(iid) >= 0 || st.clues.indexOf(iid) >= 0) { continue; }
      st.items_owned.push(iid);
      var it = c.items[iid];
      var iname = it ? it.name : iid;
      upd.new_items.push(iname);
      upd.toasts.push("收入行囊 · " + iname);
      st.log.push(["clue", "【物证】" + iname + " —— " + (it ? it.desc : "")]);
    }
    for (i = 0; i < (eff.trust || []).length; i++) {
      var pair = eff.trust[i], who = pair[0], delta = pair[1];
      if (!c.characters[who]) { continue; }
      var before = trustOf(st, who);
      var after = Math.max(0, Math.min(100, before + delta));
      st.trust[who] = after;
      if (after !== before) { upd.trust_changes.push([who, after - before]); }
    }
    for (i = 0; i < (eff.flags || []).length; i++) {
      if (st.flags.indexOf(eff.flags[i]) < 0) { st.flags.push(eff.flags[i]); }
    }
    for (i = 0; i < (eff.add_dossiers || []).length; i++) {
      this.collectDossier(eff.add_dossiers[i], upd, false);
    }
    if (eff.time && this.timeIndex(eff.time) >= this.timeIndex(st.time)) {
      st.time = eff.time;
    }
    st.score += eff.score || 0;
    st.hurt += eff.hurt || 0;
    if (eff.text) {
      st.log.push(["narration", eff.text]);
      upd.narration.push(eff.text);
    }
    return upd;
  };

  // -- 场景切换 -------------------------------------------------------
  Game.prototype.goTo = function (sceneId, upd) {
    upd = upd || newUpdate();
    var scene = this.content.scenes[sceneId];
    if (!scene) { throw new Error("剧本缺少场景: " + sceneId); }
    var st = this.state;
    st.scene = sceneId;
    var firstVisit = st.visited.indexOf(sceneId) < 0;
    if (firstVisit) { st.visited.push(sceneId); }
    if (scene.time && this.timeIndex(scene.time) >= this.timeIndex(st.time)) {
      st.time = scene.time;
    }
    if (scene.place) { st.place = scene.place; }
    if (scene.act) { st.chapter = scene.act; }
    if (scene.case) { st.case = scene.case; }
    st.interrogating = scene.interlocutor || "";
    upd.scene_changed = true;
    if (scene.body && firstVisit) { st.log.push(["scene", scene.body]); }
    if (scene.on_enter) { this.applyEffect(scene.on_enter, upd); }
    if (scene.kind === "ending") {
      st.ending = sceneId;
      upd.ended = true;
    }
    return upd;
  };

  // -- 结案 -----------------------------------------------------------
  Game.prototype.atVerdict = function () {
    return (this.content.verdict_scenes || []).indexOf(this.state.scene) >= 0;
  };

  Game.prototype.accuse = function (suspectId) {
    var upd = newUpdate();
    this.state.accused = suspectId;
    if (this.state.flags.indexOf("accused") < 0) { this.state.flags.push("accused"); }
    var row = this.content.verdicts[suspectId];
    if (row && row[0]) { this.goTo(row[0], upd); }
    return upd;
  };

  Game.prototype.pickEnding = function () {
    var all = this.content.endings, fallback = "ending_bystander";
    var list = [], i;
    for (i = 0; i < all.length; i++) {
      if ((all[i].case || 1) === this.state.case) { list.push(all[i]); }
    }
    if (!list.length) { list = all.slice(); }
    var preferred = fallback, found = false;
    for (i = 0; i < list.length; i++) {
      if (list[i].id === fallback) { found = true; }
    }
    if (!found) { preferred = list[list.length - 1].id; }
    for (var j = 0; j < list.length; j++) {
      var rule = list[j].rule;
      if (!rule || evalAst(rule, this.state)) { return list[j].id; }
    }
    return preferred;
  };

  Game.prototype.finalize = function () {
    var eid = this.pickEnding();
    this.goTo(eid, null);
    this.state.ending = eid;
    return eid;
  };

  Game.prototype.endingInfo = function () {
    var eid = this.state.ending, list = this.content.endings;
    for (var i = 0; i < list.length; i++) {
      if (list[i].id === eid) { return list[i]; }
    }
    return null;
  };

  // -- 查询 -----------------------------------------------------------
  Game.prototype.clueName = function (cid) {
    var item = this.content.items[cid];
    return item ? item.name : cid;
  };

  Game.prototype.coreTotal = function () {
    var n = 0;
    for (var id in this.content.items) {
      if (this.content.items[id].core) { n += 1; }
    }
    return n;
  };

  function newUpdate() {
    return {
      toasts: [], new_clues: [], new_items: [], new_dossiers: [],
      trust_changes: [], narration: [], scene_changed: false, ended: false
    };
  }

  function emptyEffect() {
    return {
      text: null, add_clues: [], add_items: [], add_dossiers: [],
      trust: [], flags: [], time: null, scene: null, unlock: null,
      score: 0, hurt: 0
    };
  }

  return {
    Game: Game,
    evalAst: evalAst,
    cmp: cmp,
    charWidth: charWidth,
    displayWidth: displayWidth,
    wrapCjk: wrapCjk,
    newUpdate: newUpdate
  };
});
