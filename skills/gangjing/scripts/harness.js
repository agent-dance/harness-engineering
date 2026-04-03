#!/usr/bin/env node
/**
 * Break My Code — JS Attack Harness (v2)
 *
 * Process-isolated execution: each attack runs in a child_process.fork()
 * with a per-attack timeout. If the child hangs or crashes, the parent
 * kills it and records the verdict.
 *
 * Usage:
 *   node harness.js attack_config.json [--timeout 5] [-o output.json]
 */
const { fork } = require("child_process");
const fs = require("fs");
const path = require("path");

const VERDICTS = { crashed: "\u{1F4A5}", wrong: "\u{1F3AF}", hung: "\u23F3", leaked: "\u{1F513}", survived: "\u{1F6E1}\uFE0F" };
const SEV_W = { CRITICAL: 20, HIGH: 10, MEDIUM: 5, LOW: 2 };

// ── Child worker mode ───────────────────────────────────────────────
// When invoked with --worker, this script runs a single attack in an
// isolated process and sends the result back via IPC.
if (process.argv.includes("--worker")) {
  const UNSET = Symbol("UNSET");
  const PROTO_KEYS = ["isAdmin", "role", "admin", "polluted", "__admin"];

  function cleanProto() {
    for (const k of PROTO_KEYS) {
      try { delete Object.prototype[k]; } catch (_) {}
    }
  }

  function vNoProto(_val) {
    const f = [];
    for (const k of PROTO_KEYS) {
      if (Object.prototype[k] !== undefined)
        f.push(`Object.prototype.${k} = ${JSON.stringify(Object.prototype[k])}`);
    }
    if (({}).isAdmin === true) f.push("({}).isAdmin === true");
    return f;
  }

  function vNoHtml(val) {
    const f = [], pat = /<\s*(script|img|svg|iframe|on\w+\s*=)/i;
    (function walk(v, p) {
      if (typeof v === "string" && pat.test(v)) f.push(`HTML at ${p}: ${v.slice(0, 80)}`);
      else if (v && typeof v === "object" && !Array.isArray(v))
        for (const [k, x] of Object.entries(v)) walk(x, `${p}.${k}`);
      else if (Array.isArray(v))
        v.forEach((x, i) => walk(x, `${p}[${i}]`));
    })(val, "root");
    return f;
  }

  function vNoNaN(val) {
    const f = [];
    (function walk(v, p) {
      if (typeof v === "number" && (Number.isNaN(v) || !Number.isFinite(v)))
        f.push(`NaN/Inf at ${p}: ${v}`);
      else if (v && typeof v === "object" && !Array.isArray(v))
        for (const [k, x] of Object.entries(v)) walk(x, `${p}.${k}`);
      else if (Array.isArray(v))
        v.forEach((x, i) => walk(x, `${p}[${i}]`));
    })(val, "root");
    return f;
  }

  const VALIDATORS = { no_proto_pollution: vNoProto, no_html: vNoHtml, no_nan: vNoNaN };

  function isThenable(v) { return v && typeof v === "object" && typeof v.then === "function"; }

  function judgeReturn(ret, result, expectException, expected, validators) {
    if (expectException) {
      result.verdict = "wrong";
      result.detail = `Expected throw but got: ${safeStr(ret)}`;
    } else if (expected !== UNSET) {
      if (!deepEqual(expected, ret)) {
        result.verdict = "wrong";
        result.detail = `Expected ${safeStr(expected).slice(0, 80)}, got ${safeStr(ret).slice(0, 120)}`;
      }
    }

    if (!result.verdict) {
      const findings = [];
      for (const vn of validators) {
        const vfn = VALIDATORS[vn];
        if (vfn) findings.push(...vfn(ret));
      }
      if (findings.length) {
        result.semantic_findings = findings;
        result.verdict = findings.some(f => /pollut|HTML/i.test(f)) ? "leaked" : "wrong";
        result.detail = `Semantic: ${findings.join("; ")}`;
      } else {
        result.verdict = "survived";
        result.detail = safeStr(ret).slice(0, 200);
      }
    }
  }

  function handleError(e, result, expectException) {
    if (expectException) {
      result.verdict = "survived";
      result.detail = `Threw ${e.constructor?.name || "Error"} (expected): ${e.message}`.slice(0, 200);
    } else {
      result.verdict = "crashed";
      result.detail = `${e.constructor?.name || "Error"}: ${e.message}`.slice(0, 200);
    }
  }

  process.on("message", (msg) => {
    const { targetPath, attack } = msg;
    const { name, category, severity = "MEDIUM", payload_description } = attack;
    const funcName = attack.function || attack.target_function;
    const args = attack.args || [];
    const expectException = attack.expect_exception || false;
    const expected = "expected" in attack ? attack.expected : UNSET;
    const validators = attack.validators || [];

    const result = {
      name, category, severity,
      payload: payload_description || JSON.stringify(args).slice(0, 200),
      verdict: null, detail: null, semantic_findings: [],
    };

    cleanProto();

    function finish() {
      cleanProto();
      process.send(result);
      process.exit(0);
    }

    try {
      const targetModule = require(targetPath);
      const fn = targetModule[funcName];
      if (typeof fn !== "function") {
        result.verdict = "crashed";
        result.detail = `Function '${funcName}' not found`;
        finish();
        return;
      }

      const ret = fn(...args);

      if (isThenable(ret)) {
        ret.then((resolved) => {
          judgeReturn(resolved, result, expectException, expected, validators);
          finish();
        }).catch((e) => {
          handleError(e, result, expectException);
          finish();
        });
      } else {
        judgeReturn(ret, result, expectException, expected, validators);
        finish();
      }
    } catch (e) {
      handleError(e, result, expectException);
      finish();
    }
  });

  function safeStr(v) {
    try { return JSON.stringify(v) || String(v); }
    catch (_) { return String(v); }
  }

  function deepEqual(a, b) {
    if (a === b) return true;
    if (a == null || b == null) return a === b;
    if (typeof a !== typeof b) return false;
    if (typeof a !== "object") return false;
    if (Array.isArray(a) !== Array.isArray(b)) return false;
    if (a instanceof Date && b instanceof Date) return a.getTime() === b.getTime();
    if (a instanceof RegExp && b instanceof RegExp) return a.toString() === b.toString();
    const ka = Object.keys(a), kb = Object.keys(b);
    if (ka.length !== kb.length) return false;
    return ka.every(k => deepEqual(a[k], b[k]));
  }

  return;
}

// ── Parent orchestrator ─────────────────────────────────────────────

function runAttackIsolated(targetPath, attack, timeoutSec) {
  return new Promise((resolve) => {
    const child = fork(__filename, ["--worker"], {
      stdio: ["pipe", "pipe", "pipe", "ipc"],
      timeout: (timeoutSec + 1) * 1000,
    });

    let settled = false;
    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        child.kill("SIGKILL");
        resolve({
          name: attack.name, category: attack.category,
          severity: attack.severity || "MEDIUM",
          payload: attack.payload_description || JSON.stringify(attack.args || []).slice(0, 200),
          verdict: "hung", detail: `Timed out (${timeoutSec}s)`,
          semantic_findings: [],
        });
      }
    }, timeoutSec * 1000);

    child.on("message", (result) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        resolve(result);
      }
    });

    child.on("exit", (code) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        resolve({
          name: attack.name, category: attack.category,
          severity: attack.severity || "MEDIUM",
          payload: attack.payload_description || JSON.stringify(attack.args || []).slice(0, 200),
          verdict: "crashed", detail: `Child exited with code ${code}`,
          semantic_findings: [],
        });
      }
    });

    child.on("error", (err) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        resolve({
          name: attack.name, category: attack.category,
          severity: attack.severity || "MEDIUM",
          payload: attack.payload_description || "",
          verdict: "crashed", detail: `Fork error: ${err.message}`,
          semantic_findings: [],
        });
      }
    });

    child.send({ targetPath, attack });
  });
}

async function main() {
  const args = process.argv.slice(2);
  let configPath = null, timeout = 5, outputPath = null;

  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--timeout" && args[i + 1]) { timeout = parseInt(args[++i], 10); }
    else if ((args[i] === "-o" || args[i] === "--output") && args[i + 1]) { outputPath = args[++i]; }
    else if (!configPath && args[i] !== "--worker") { configPath = args[i]; }
  }

  if (Number.isNaN(timeout) || timeout <= 0) {
    process.stderr.write(`Invalid timeout: ${timeout}, using default 5s\n`);
    timeout = 5;
  }

  if (!configPath) {
    process.stderr.write("Usage: node harness.js config.json [--timeout 5] [-o out.json]\n");
    process.exit(1);
  }

  const config = JSON.parse(fs.readFileSync(configPath, "utf8"));
  const targetPath = path.resolve(path.dirname(configPath), config.target_module);
  const attacks = config.attacks;
  const results = [];

  process.stderr.write(`${"=".repeat(60)}\n  \u{1F480} ${config.target_module}\n${"=".repeat(60)}\n`);

  for (let i = 0; i < attacks.length; i++) {
    const r = await runAttackIsolated(targetPath, attacks[i], timeout);
    const sym = VERDICTS[r.verdict] || "?";
    const sem = (r.semantic_findings || []).length ? " [sem]" : "";
    process.stderr.write(`  [${String(i + 1).padStart(2)}/${attacks.length}] ${sym} ${r.verdict.toUpperCase().padEnd(10)} [${(r.severity || "MEDIUM").padEnd(8)}] ${r.name}${sem}\n`);
    results.push(r);
  }

  let penalty = 0, maxP = 0;
  for (const r of results) {
    const w = SEV_W[r.severity] || 5;
    maxP += w;
    if (r.verdict !== "survived") penalty += w;
  }
  const score = maxP > 0 ? Math.max(0, Math.round(100 * (1 - penalty / maxP))) : 100;
  const grade = score >= 90 ? "A" : score >= 75 ? "B" : score >= 60 ? "C" : score >= 40 ? "D" : "F";
  const summary = {};
  for (const v of Object.keys(VERDICTS)) summary[v] = results.filter(r => r.verdict === v).length;

  const output = {
    target: config.target_module,
    total_attacks: results.length,
    summary, resilience_score: score, grade, results,
  };

  const jsonStr = JSON.stringify(output, null, 2);
  if (outputPath) {
    fs.writeFileSync(outputPath, jsonStr);
    process.stderr.write(`\nResults: ${outputPath}\n`);
  } else {
    process.stdout.write(jsonStr + "\n");
  }
  process.stderr.write(`\n  \u2192 Score: ${score}/100 (Grade: ${grade})\n`);
}

main().catch(e => { process.stderr.write(`Fatal: ${e.message}\n`); process.exit(1); });
