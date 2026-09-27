/* 网页端引擎的命令行驱动：把同一串动作喂给 JS 引擎，逐步打印存档。
 *
 * 这是 `tools/audit_web.py` 的另一半：那边用 `gongwei/autoplay.py` 走 Python
 * 引擎，这边走 JS 引擎，两边逐步比对**存档**。记号与 `gongwei/autoplay.py`
 * 的 `resolve()` 逐条对应（前缀 / @N / @Nf / !前缀 / #档号）。
 *
 * 用法: node web/src/driver.js <pack.json> <script.json>
 *   script.json 形如 {"steps": ["俯身验尸", "#01-FY-XFE", "移步侧殿"]}
 * 输出: 每步一行 `<序号>\t<存档 JSON>`；出错则打印 ERROR 并以 1 退出。
 */
"use strict";

var fs = require("fs");
var path = require("path");
var GongweiGame = require(path.join(__dirname, "game.js"));

function sortDeep(value) {
  if (Array.isArray(value)) { return value.map(sortDeep); }
  if (value && typeof value === "object") {
    var out = {};
    Object.keys(value).sort().forEach(function (k) { out[k] = sortDeep(value[k]); });
    return out;
  }
  return value;
}

function canonical(value) {
  return JSON.stringify(sortDeep(value));
}

function resolve(game, step) {
  var opts = game.options();
  if (step.indexOf("#") === 0) {
    var did = step.slice(1).trim();
    if (!game.dossierExists(did)) { throw new Error("剧本里没有档案 " + did); }
    if (!game.canReadDossier(did)) {
      var lockedCase = game.dossierCase(did);
      if (lockedCase > game.state.case) {
        throw new Error("档案 " + did + " 属于第 " + lockedCase + " 案，还没走到");
      }
      throw new Error("档案 " + did + " 此时还读不到（requires 未满足）");
    }
    return {
      label: "阅档 #" + did, enabled: true, hint: "",
      action: function () { return game.readDossier(did); }
    };
  }
  if (step.indexOf("@") === 0) {
    var raw = step.slice(1);
    var fresh = raw.slice(-1) === "f";
    var idx = parseInt(fresh ? raw.slice(0, -1) : raw, 10);
    var pool = opts.filter(function (o) {
      return o.enabled && (!fresh || !o.asked);
    });
    if (idx >= pool.length) {
      throw new Error(step + " 越界：当前只有 " + pool.length + " 个可用选项");
    }
    return pool[idx];
  }
  if (step.indexOf("!") === 0) {
    var hits = opts.filter(function (o) { return o.label.indexOf(step.slice(1)) === 0; });
    if (hits.length) { throw new Error("断言失败：" + step.slice(1) + " 本来不该出现"); }
    return null;
  }
  var matched = opts.filter(function (o) { return o.label.indexOf(step) === 0; });
  if (matched.length !== 1) {
    var names = opts.map(function (o) { return o.index + "." + o.label; }).join(" / ");
    throw new Error("「" + step + "」匹配到 " + matched.length + " 项（当前：" + names + "）");
  }
  var chosen = matched[0];
  if (!chosen.enabled) {
    throw new Error("「" + chosen.label + "」被锁住：" + chosen.hint);
  }
  return chosen;
}

function act(game, chosen) {
  if (chosen.choice) { return game.choose(chosen.choice, chosen.topic_id); }
  return chosen.action();
}

function main(argv) {
  var packPath = argv[2], scriptPath = argv[3];
  if (!packPath || !scriptPath) {
    console.error("用法: node web/src/driver.js <pack.json> <script.json>");
    return 2;
  }
  var pack = JSON.parse(fs.readFileSync(packPath, "utf8"));
  var script = JSON.parse(fs.readFileSync(scriptPath, "utf8"));
  var steps = Array.isArray(script) ? script : (script.steps || []);

  var game = new GongweiGame.Game(pack);
  var out = [];
  out.push("PACK\t" + pack.title + "\t" + steps.length);
  for (var i = 0; i < steps.length; i++) {
    var step = steps[i];
    var target;
    try {
      target = resolve(game, step);
    } catch (err) {
      console.log(out.join("\n"));
      console.error("ERROR " + (i + 1) + " " + err.message);
      return 1;
    }
    if (target !== null) {
      try {
        act(game, target);
      } catch (err2) {
        console.log(out.join("\n"));
        console.error("ERROR " + (i + 1) + " " + err2.message);
        return 1;
      }
      if (game.atVerdict() && !game.state.ending) { game.finalize(); }
    }
    var payload = game.save();
    var opts = game.options().map(function (o) {
      return [o.index, o.label, o.enabled, o.hint];
    });
    // 最后一行的 "hidden" 是被门禁挡住、玩家看不见的那批（与 Python 侧同形）：
    // 比对「桌上摆了什么」之外，也比对「桌上没什么」。
    opts.push(["hidden"].concat(game.hiddenOptions().map(function (o) {
      return o.label;
    })));
    out.push((i + 1) + "\t" + canonical({
      v: payload.v, state: payload.state
    }) + "\t" + canonical(opts));
  }
  out.push("DONE\t" + steps.length + "\t" + game.state.scene + "\t" + game.state.ending);
  console.log(out.join("\n"));
  return 0;
}

process.exitCode = main(process.argv);
