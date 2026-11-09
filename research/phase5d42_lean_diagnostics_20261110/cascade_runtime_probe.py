"""Full-range Lean diagnostics for fixed trusted source, with cold/resident receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from time import perf_counter


ROOT = Path(__file__).resolve().parent
D40 = ROOT.parent / "phase5d40_proof_authoring_20261110"
D41 = ROOT.parent / "phase5d41_lean_scope_20261110"
sys.path.insert(0, str(D40))
from baseline_runtime_probe import CACHE, LEAN_ROOT, PREFIX, PROJECT, clean_env, verified_environment
from lean_resident_probe import FLAGS, ResidentLean, proof_scope


TIMEOUT = 120
TARGET = "d42_cascade"
VARIANTS = ("broken", "unrelated_edit", "root_edit", "standard_tactic")
PLAN = ROOT / "cascade_runtime_freeze.json"


def digest(text):
    return hashlib.sha256(text.encode("utf-8") if isinstance(text, str) else text).hexdigest()


def fixture_sources():
    inputs = json.loads((D41 / "D41_SCOPE_INPUT_FREEZE.json").read_bytes())
    imports = inputs["prior_scope_negatives"]["p14"]["original_imports"]
    prelude = "".join(f"import {module}\n" for module in imports) + "\nset_option warningAsError true\n\n"
    header = f"theorem {TARGET} : True := by\n"
    suffix = f"\n#print axioms {TARGET}\n"
    body = "  let _padding : Nat := 123\n  have hβ : Nat := /- 🧪 -/ True.intro\n  exact hβ\n"
    base = prelude + header + body + suffix
    sources = {"broken": base,
               "unrelated_edit": base.replace("_padding : Nat := 123", "_padding : Nat := 124", 1),
               "root_edit": base.replace("have hβ : Nat :=", "have hβ : True :=", 1),
               "standard_tactic": prelude + header + "  trivial\n" + suffix}
    return imports, prelude, sources


def edit_span(original, edited):
    left, right = original.encode(), edited.encode()
    start = 0
    while start < min(len(left), len(right)) and left[start] == right[start]:
        start += 1
    keep_tail = 0
    while keep_tail < min(len(left), len(right)) - start and left[-1 - keep_tail] == right[-1 - keep_tail]:
        keep_tail += 1
    l_end, r_end = len(left) - keep_tail, len(right) - keep_tail
    old, new = left[start:l_end].decode(), right[start:r_end].decode()
    return {"old_byte_span": [start, l_end], "replacement_byte_span": [start, r_end], "old": old, "new": new,
            "reconstructed_exact": left[:start] + new.encode() + left[l_end:] == right}


class SourceAnchors:
    def __init__(self, source):
        if "\r" in source:
            raise ValueError("Approved source must use exact LF line endings")
        self.lines = source.split("\n")
        self.bytes = source.encode()
        self.starts = [0]
        for line in self.lines[:-1]:
            self.starts.append(self.starts[-1] + len(line.encode()) + 1)

    def point(self, position, protocol):
        if not isinstance(position, dict):
            return None
        if protocol == "cli_scalar":
            line_index, offset = position["line"] - 1, position["column"]
        else:
            line_index, offset = position["line"], position["character"]
        if not 0 <= line_index < len(self.lines) or offset < 0:
            return None
        line = self.lines[line_index]
        if protocol == "cli_scalar":
            if offset > len(line):
                return None
            scalar = offset
        else:
            units = scalar = 0
            while scalar < len(line) and units < offset:
                units += len(line[scalar].encode("utf-16-le")) // 2
                scalar += 1
            if units != offset:
                return None
        return {"line_1_based": line_index + 1, "scalar_column_0_based": scalar,
                "utf8_byte_offset": self.starts[line_index] + len(line[:scalar].encode()),
                "line_sha256_without_newline": digest(line)}

    def anchor(self, start, end, protocol):
        lo, hi = self.point(start, protocol), self.point(end, protocol)
        span = None
        if lo and hi and lo["utf8_byte_offset"] <= hi["utf8_byte_offset"]:
            span = self.bytes[lo["utf8_byte_offset"]:hi["utf8_byte_offset"]].decode()
        return {"protocol_coordinates": protocol, "raw_start": start, "raw_end": end,
                "start": lo, "end": hi, "anchored_source": span}


def category(message):
    body = message.casefold()
    if "application type mismatch" in body:
        return "APPLICATION_TYPE_MISMATCH"
    if "type mismatch" in body:
        return "TYPE_MISMATCH"
    if "unknown identifier" in body or "unknown constant" in body:
        return "UNKNOWN_NAME"
    if "unsolved goals" in body or "missing cases" in body:
        return "GOALS_OR_CASES"
    if "maximum recursion depth" in body or "heartbeat" in body:
        return "RESOURCE_LIMIT"
    return "OTHER"


def frame(source, diagnostics, targets):
    checks = proof_scope(diagnostics, targets)
    errors = [m for m in diagnostics if m["severity"] == 1]
    source_order = sorted(errors, key=lambda m: (m["anchor"]["start"] is None,
                                                (m["anchor"]["start"] or {}).get("utf8_byte_offset", 0),
                                                m["reported_index"]))
    return {**checks, "source_sha256": digest(source), "source_bytes": len(source.encode()),
            "diagnostics_in_reporting_order": diagnostics, "error_count": len(errors),
            "error_report_indices": [m["reported_index"] for m in errors],
            "error_indices_sorted_by_source": [m["reported_index"] for m in source_order],
            "all_error_starts_bound": all(m["anchor"]["start"] is not None for m in errors)}


def cold_frame(command, path, source, targets, env, *, cwd=PROJECT, timeout=TIMEOUT):
    started = perf_counter()
    path.write_bytes(source.encode())
    proc = subprocess.run([*command, "--json", str(path)], cwd=cwd, env=env, capture_output=True,
                          timeout=timeout, creationflags=FLAGS)
    anchors = SourceAnchors(source)
    diagnostics = []
    for index, line in enumerate(proc.stdout.splitlines(), 1):
        item = json.loads(line)
        start, end = item.get("pos"), item.get("endPos")
        severity = {"error": 1, "warning": 2, "information": 3}.get(item["severity"], 4)
        diagnostics.append({"reported_index": index, "severity": severity, "message": item["data"],
                            "kind": item.get("kind"), "category": category(item["data"]) if severity == 1 else None,
                            "anchor": anchors.anchor(start, end, "cli_scalar")})
    result = frame(source, diagnostics, targets)
    if proc.returncode != 0 and result["status"] == "KERNEL_ACCEPTED":
        result["status"] = "PROCESS_FAILED"
    return {**result, "exit_code": proc.returncode, "elapsed_seconds": perf_counter() - started,
            "stderr": proc.stderr.decode(errors="replace").replace(str(path.parent), "<fixture_dir>")[-4000:]}


def resident_frame(server, path, source, targets):
    started = perf_counter()
    uri = path.as_uri()
    server.version += 1
    if server.open_uri is None:
        path.write_bytes(source.encode())
        server.send({"method": "textDocument/didOpen", "params": {"textDocument": {
            "uri": uri, "languageId": "lean4", "version": server.version, "text": source},
            "dependencyBuildMode": "never"}})
        server.open_uri = uri
    elif server.open_uri == uri:
        server.send({"method": "textDocument/didChange", "params": {
            "textDocument": {"uri": uri, "version": server.version}, "contentChanges": [{"text": source}]}})
    else:
        raise ValueError("Do not reuse a resident frame across document URIs")
    messages = server.request("textDocument/waitForDiagnostics", {"uri": uri, "version": server.version})
    publications = [m["params"] for m in messages if m.get("method") == "textDocument/publishDiagnostics"
                    and m["params"]["uri"] == uri and m["params"].get("version") == server.version]
    if not publications:
        raise ValueError("No completed diagnostic publication for this exact document version")
    anchors = SourceAnchors(source)
    diagnostics = []
    for index, item in enumerate(publications[-1]["diagnostics"], 1):
        full_range = item.get("fullRange", item["range"])
        severity = item.get("severity", 4)
        diagnostics.append({"reported_index": index, "severity": severity, "message": item["message"],
                            "kind": item.get("code"), "category": category(item["message"]) if severity == 1 else None,
                            "anchor": anchors.anchor(full_range["start"], full_range["end"], "lsp_utf16"),
                            "reported_lsp_range": item["range"]})
    return {**frame(source, diagnostics, targets), "document_version": server.version,
            "matching_publications": len(publications), "elapsed_seconds": perf_counter() - started}


def errors_key(result):
    return [(r["category"], r["message"], r["anchor"]["start"]) for r in result["diagnostics_in_reporting_order"]
            if r["severity"] == 1]


def run():
    started = perf_counter()
    environment = verified_environment()
    preparation = perf_counter() - started
    imports, prelude, sources = fixture_sources()
    frozen = json.loads(PLAN.read_bytes())
    if {name: digest(src) for name, src in sources.items()} != frozen["source_hashes"] or imports != frozen["imports"]:
        raise ValueError("Trusted synthetic source differs from the freeze")
    bindir = LEAN_ROOT / PREFIX / "bin"
    command = [str(bindir / "lake.exe"), "env", str(bindir / "lean.exe")]
    env = clean_env(CACHE)
    env["PATH"] = str(bindir) + os.pathsep + env["PATH"]
    with tempfile.TemporaryDirectory(prefix="d42-trusted-cascade-", dir=CACHE) as temp:
        folder = Path(temp)
        resident = ResidentLean(command, PROJECT, TIMEOUT, env=env)
        try:
            path = folder / "TrustedCascadeResident.lean"
            warmup = resident_frame(resident, path, prelude + "#check @True.intro\n", [])
            warm = {name: resident_frame(resident, path, sources[name], [TARGET]) for name in VARIANTS}
            stale_check = resident_frame(resident, path, sources["broken"], [TARGET])
        finally:
            close = perf_counter()
            resident.close()
            close_wall = perf_counter() - close
        print(json.dumps({"checkpoint": "resident_controls_closed", "errors": {n: v["error_count"] for n, v in warm.items()}}), flush=True)
        cold = {name: cold_frame(command, folder / f"Cold_{name}.lean", sources[name], [TARGET], env)
                for name in VARIANTS}
    checks = {
        "both_real_errors_in_each_original": all(group["broken"]["error_count"] == 2 for group in (warm, cold)),
        "unrelated_edit_preserves_both_reported_errors_and_start_anchors": all(errors_key(group["broken"]) ==
                                                                               errors_key(group["unrelated_edit"]) for group in (warm, cold)),
        "one_type_edit_removes_both_errors_and_closes_original_target": all(group["root_edit"]["status"] == "KERNEL_ACCEPTED"
                                                                           and group["root_edit"]["error_count"] == 0 for group in (warm, cold)),
        "ordinary_direct_tactic_closes_original_target": all(group["standard_tactic"]["status"] == "KERNEL_ACCEPTED" for group in (warm, cold)),
        "utf8_starts_agree_across_both_transports": all(errors_key(cold[name]) == errors_key(warm[name]) for name in VARIANTS),
        "all_error_starts_exactly_bound": all(result["all_error_starts_bound"] for group in (warm, cold) for result in group.values()),
        "returning_to_broken_version_recovers_both_errors": errors_key(stale_check) == errors_key(warm["broken"]),
    }
    return {"status": "PASS_TRUSTED_CASCADE" if all(checks.values()) else "FAIL_TRUSTED_CASCADE", "checks": checks,
            "scope": "Trusted artificial dependency cascade and negative edit control. No archive code, model or GPU.",
            "environment": environment, "preparation_seconds": preparation, "imports": imports,
            "freeze_sha256": digest(PLAN.read_bytes()), "sources": sources,
            "edits": {name: edit_span(sources["broken"], sources[name]) for name in VARIANTS[1:]},
            "resident_startup_seconds": resident.startup_seconds, "resident_warmup": warmup,
            "resident_shutdown_seconds": close_wall, "resident": warm, "resident_return_to_broken": stale_check,
            "cold": cold}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run()
    with args.output.open("xb") as handle:
        handle.write((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps({k: report[k] for k in ("status", "checks")}))
    raise SystemExit(0 if report["status"].startswith("PASS") else 1)
