#!/usr/bin/env python3
"""
Break My Code — Attack Harness

Executes attack vectors against a target function and collects results.
The LLM generates attack_config.json, this script runs it and produces
structured output for the destruction report.

Usage:
    python harness.py attack_config.json [--timeout 5]

attack_config.json format:
{
  "target_module": "/path/to/target.py",
  "target_function": "function_name",
  "attacks": [
    {
      "name": "Attack name",
      "category": "Type Chaos",
      "severity": "HIGH",
      "payload_description": "human-readable description",
      "args": [arg1, arg2],
      "kwargs": {},
      "expected": "expected_value or null",
      "expect_exception": false,
      "validators": ["no_nan", "no_html", "no_invisible_unicode"]
    }
  ]
}
"""

import argparse
import importlib.util
import json
import math
import multiprocessing
import os
import re
import sys
import time
import unicodedata
from pathlib import Path


VERDICTS = {
    "crashed": "💥",
    "wrong": "🎯",
    "hung": "⏳",
    "leaked": "🔓",
    "survived": "🛡️",
}

SEVERITY_WEIGHTS = {"CRITICAL": 20, "HIGH": 10, "MEDIUM": 5, "LOW": 2}


# ---------------------------------------------------------------------------
# Semantic validators — catch silent failures that execution alone misses
# ---------------------------------------------------------------------------

def _deep_check(obj, predicate, path="root", _seen=None, _depth=0, _max_depth=50):
    """Walk a nested structure (dict/list) and apply predicate to all leaf values.
    Guards against circular references and excessive nesting."""
    if _depth > _max_depth:
        return [f"Max depth ({_max_depth}) exceeded at {path}"]
    if _seen is None:
        _seen = set()
    obj_id = id(obj)
    if isinstance(obj, (dict, list, tuple)):
        if obj_id in _seen:
            return [f"Circular reference detected at {path}"]
        _seen.add(obj_id)
    findings = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            findings.extend(_deep_check(v, predicate, f"{path}.{k}", _seen, _depth+1, _max_depth))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            findings.extend(_deep_check(v, predicate, f"{path}[{i}]", _seen, _depth+1, _max_depth))
    else:
        hit = predicate(obj, path)
        if hit:
            findings.append(hit)
    return findings


def validate_no_nan(value):
    """Flag NaN or Infinity in return values — classic validation bypass."""
    import decimal
    def check(v, path):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return f"NaN/Inf found at {path}: {v!r}"
        if isinstance(v, decimal.Decimal) and (v.is_nan() or v.is_infinite()):
            return f"NaN/Inf found at {path}: {v!r}"
    return _deep_check(value, check)


def validate_no_html(value):
    """Flag stored HTML/script tags — potential XSS persistence."""
    pattern = re.compile(r"<\s*(script|img|svg|iframe|on\w+\s*=)", re.IGNORECASE)
    def check(v, path):
        if isinstance(v, str) and pattern.search(v):
            return f"Unsanitized HTML at {path}: {v[:80]!r}"
    return _deep_check(value, check)


def validate_no_invisible_unicode(value):
    """Flag zero-width chars, RTL overrides, and other invisible characters."""
    invisible_cats = {"Cf", "Mn", "Cc"}
    invisible_codepoints = {
        0x200B, 0x200C, 0x200D, 0xFEFF,  # zero-width
        0x202A, 0x202B, 0x202C, 0x202D, 0x202E,  # bidi
        0x2066, 0x2067, 0x2068, 0x2069,  # bidi isolate
    }
    def check(v, path):
        if isinstance(v, str):
            for ch in v:
                cp = ord(ch)
                if cp in invisible_codepoints or (unicodedata.category(ch) in invisible_cats and cp > 127):
                    return f"Invisible Unicode U+{cp:04X} ({unicodedata.name(ch, '?')}) at {path}"
    return _deep_check(value, check)


def validate_no_path_escape(value):
    """Flag path traversal sequences (../) in return values.
    Simple absolute paths are NOT flagged — only traversal patterns."""
    def check(v, path):
        if isinstance(v, str) and ".." in v and ("../" in v or "..\\" in v or v == ".."):
            return f"Path traversal at {path}: {v[:80]!r}"
    return _deep_check(value, check)


def validate_no_bool_as_int(value):
    """Flag booleans smuggled through as integers."""
    def check(v, path):
        if isinstance(v, bool):
            return f"Boolean value at {path}: {v!r} (may have been smuggled as int)"
    return _deep_check(value, check)


def validate_dict_field(value, field=None, expected=None, op="eq"):
    """Validate a specific field in a dict return value.
    Supports ops: eq, ne, lt, gt, le, ge."""
    if not isinstance(value, dict) or field is None:
        return []
    actual = value.get(field)
    ops = {"eq": lambda a,b: a==b, "ne": lambda a,b: a!=b,
           "lt": lambda a,b: a<b, "gt": lambda a,b: a>b,
           "le": lambda a,b: a<=b, "ge": lambda a,b: a>=b}
    check = ops.get(op, ops["eq"])
    if not check(actual, expected):
        return [f"Field '{field}': expected {op} {expected!r}, got {actual!r}"]
    return []


VALIDATORS = {
    "no_nan": validate_no_nan,
    "no_html": validate_no_html,
    "no_invisible_unicode": validate_no_invisible_unicode,
    "no_path_escape": validate_no_path_escape,
    "no_bool_as_int": validate_no_bool_as_int,
}


# ---------------------------------------------------------------------------
# Core execution engine
# ---------------------------------------------------------------------------

def load_target(module_path: str, function_name: str):
    """Dynamically load a function from a file path."""
    path = Path(module_path).resolve()
    spec = importlib.util.spec_from_file_location("target_module", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, function_name)


def run_single_attack(target_func, attack, timeout):
    """Run one attack vector with timeout + semantic validation."""
    args = attack.get("args", [])
    kwargs = attack.get("kwargs", {})
    _UNSET = object()
    expected = attack.get("expected", _UNSET)
    expect_exception = attack.get("expect_exception", False)
    validator_names = attack.get("validators", [])

    result = {
        "name": attack["name"],
        "category": attack["category"],
        "severity": attack.get("severity", "MEDIUM"),
        "payload": attack.get("payload_description", str(args)),
        "verdict": None,
        "detail": None,
        "semantic_findings": [],
        "elapsed_ms": None,
    }

    def _execute(conn):
        try:
            start = time.monotonic()
            ret = target_func(*args, **kwargs)
            elapsed = (time.monotonic() - start) * 1000
            conn.send(("ok", ret, elapsed))
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            conn.send(("exception", f"{type(e).__name__}: {e}", elapsed))

    parent_conn, child_conn = multiprocessing.Pipe()
    proc = multiprocessing.Process(target=_execute, args=(child_conn,))
    proc.start()
    proc.join(timeout=timeout)

    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=2)
        if proc.is_alive():
            proc.kill()
        result["verdict"] = "hung"
        result["detail"] = f"Did not complete within {timeout}s"
        return result

    if not parent_conn.poll():
        result["verdict"] = "crashed"
        result["detail"] = "Process died without sending result"
        return result

    status, value, elapsed = parent_conn.recv()
    result["elapsed_ms"] = round(elapsed, 2)

    if status == "exception":
        if expect_exception:
            result["verdict"] = "survived"
            result["detail"] = f"Raised expected exception: {value}"
        else:
            result["verdict"] = "crashed"
            result["detail"] = value
        return result

    # status == "ok"
    if expect_exception:
        result["verdict"] = "wrong"
        result["detail"] = f"Expected exception but got: {repr(value)}"
        return result

    if expected is not _UNSET and value != expected:
        result["verdict"] = "wrong"
        result["detail"] = f"Expected {repr(expected)}, got {repr(value)}"
        return result

    # Execution succeeded — now run semantic validators on the return value
    all_findings = []
    for vname in validator_names:
        validator_fn = VALIDATORS.get(vname)
        if validator_fn:
            findings = validator_fn(value)
            all_findings.extend(findings)

    if all_findings:
        result["semantic_findings"] = all_findings
        if any("HTML" in f or "Invisible" in f or "Path escape" in f for f in all_findings):
            result["verdict"] = "leaked"
        else:
            result["verdict"] = "wrong"
        result["detail"] = f"Execution OK, but semantic check failed: {'; '.join(all_findings)}"
    else:
        result["verdict"] = "survived"
        detail_val = repr(value)
        if len(detail_val) > 200:
            detail_val = detail_val[:200] + "..."
        result["detail"] = f"Returned {detail_val}" + (" (correct)" if expected is not None else "")

    return result


def calculate_score(results):
    """Calculate resilience score from attack results."""
    total = len(results)
    if total == 0:
        return 100

    penalty = 0
    max_penalty = 0
    for r in results:
        w = SEVERITY_WEIGHTS.get(r["severity"], 5)
        max_penalty += w
        if r["verdict"] != "survived":
            penalty += w

    if max_penalty == 0:
        return 100
    return max(0, round(100 * (1 - penalty / max_penalty)))


def grade(score):
    if score >= 90:
        return "A"
    elif score >= 75:
        return "B"
    elif score >= 60:
        return "C"
    elif score >= 40:
        return "D"
    return "F"


def main():
    parser = argparse.ArgumentParser(description="Break My Code attack harness")
    parser.add_argument("config", help="Path to attack_config.json")
    parser.add_argument("--timeout", type=int, default=5,
                        help="Per-attack timeout in seconds")
    parser.add_argument("--output", "-o",
                        help="Output JSON file (default: stdout)")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    target_func = load_target(config["target_module"], config["target_function"])
    attacks = config["attacks"]
    results = []

    for i, attack in enumerate(attacks):
        sys.stderr.write(f"[{i+1}/{len(attacks)}] {attack['name']}...")
        result = run_single_attack(target_func, attack, args.timeout)
        symbol = VERDICTS.get(result["verdict"], "?")
        sys.stderr.write(f" {symbol} {result['verdict'].upper()}")
        if result["semantic_findings"]:
            sys.stderr.write(f" (semantic: {len(result['semantic_findings'])} finding(s))")
        sys.stderr.write("\n")
        results.append(result)

    score = calculate_score(results)
    output = {
        "target": f"{config['target_module']}::{config['target_function']}",
        "total_attacks": len(results),
        "summary": {
            v: sum(1 for r in results if r["verdict"] == v)
            for v in VERDICTS
        },
        "resilience_score": score,
        "grade": grade(score),
        "results": results,
    }

    json_output = json.dumps(output, indent=2, ensure_ascii=False, default=str)

    if args.output:
        with open(args.output, "w") as f:
            f.write(json_output)
        sys.stderr.write(f"\nResults written to {args.output}\n")
    else:
        print(json_output)

    sys.stderr.write(f"\n{'='*50}\n")
    sys.stderr.write(f"RESILIENCE SCORE: {score}/100 (Grade: {grade(score)})\n")
    survived = output["summary"]["survived"]
    sys.stderr.write(f"Survived: {survived}/{len(results)}")
    semantic_total = sum(len(r["semantic_findings"]) for r in results)
    if semantic_total:
        sys.stderr.write(f" | Semantic findings: {semantic_total}")
    sys.stderr.write(f"\n{'='*50}\n")


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn", force=True)
    main()
