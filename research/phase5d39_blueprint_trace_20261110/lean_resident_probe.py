"""Measure trusted Lean inputs with the built-in resident LSP diagnostics barrier."""

import argparse
import hashlib
import json
import os
from pathlib import Path
from queue import Empty, Queue
import re
import subprocess
import tempfile
from threading import Thread
import time


FOUNDATIONAL_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def proof_scope(messages, targets):
    """An empty diagnostic list is not a completed proof certificate."""
    if any(item["severity"] == 1 for item in messages):
        return {"status": "REJECTED", "axioms": {}}
    axioms = {}
    for target in targets:
        reports = [item["message"] for item in messages if item["message"].startswith(f"'{target}' ")]
        if len(reports) != 1:
            return {"status": "MISSING_AXIOM_CLOSURE", "axioms": axioms}
        report, = reports
        if report == f"'{target}' does not depend on any axioms":
            axioms[target] = []
            continue
        found = re.fullmatch(rf"'{re.escape(target)}' depends on axioms:\s*\[([^]]*)\]", report)
        if not found:
            return {"status": "MALFORMED_AXIOM_CLOSURE", "axioms": axioms}
        axioms[target] = [name.strip() for name in found[1].split(",") if name.strip()]
        if not set(axioms[target]) <= FOUNDATIONAL_AXIOMS:
            return {"status": "UNAPPROVED_AXIOM_CLOSURE", "axioms": axioms}
    return {"status": "KERNEL_ACCEPTED", "axioms": axioms}


def cold_check(command, cwd, path, source, targets, *, timeout, env=None):
    started = time.perf_counter()
    path.write_text(source, encoding="utf-8", newline="\n")
    proc = subprocess.run([*command, "--json", str(path)], cwd=cwd, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=timeout, creationflags=FLAGS)
    messages = []
    for line in proc.stdout.splitlines():
        item = json.loads(line)
        messages.append({"severity": {"error": 1, "warning": 2, "information": 3}.get(item["severity"], 4),
                         "message": item["data"], "line": item.get("pos", {}).get("line")})
    scope = proof_scope(messages, targets)
    if proc.returncode and scope["status"] == "KERNEL_ACCEPTED":
        scope["status"] = "PROCESS_FAILED"
    return {**scope, "source_sha256": sha(source), "elapsed_seconds": time.perf_counter() - started,
            "exit_code": proc.returncode, "messages": messages,
            "stderr": proc.stderr.decode(errors="replace").replace(str(path.parent), "$D39_CASE_DIR")[-4000:]}


def batch_scoped_diagnostics(command, cwd, path, source, blocks, *, timeout):
    """Classify one batch of independent named blocks, including rejected controls."""
    raw = cold_check(command, cwd, path, source, [], timeout=timeout)
    covered = {n for first, last, _ in blocks for n in range(first, last + 1)}
    if any(item["severity"] == 1 and item["line"] not in covered for item in raw["messages"]):
        raise ValueError("Lean batch reported a failure outside its named source blocks")
    statuses = []
    for first, last, targets in blocks:
        messages = [item for item in raw["messages"] if item["line"] is not None and first <= item["line"] <= last]
        statuses.append(proof_scope(messages, targets))
    return {"source_sha256": raw["source_sha256"], "elapsed_seconds": raw["elapsed_seconds"],
            "exit_code": raw["exit_code"], "scopes": statuses, "messages": raw["messages"]}


class ResidentLean:
    def __init__(self, command, cwd, timeout, env=None):
        self.timeout = timeout
        self.messages = Queue()
        self.next_id = 0
        self.open_uri = None
        self.version = 0
        self.stderr_log = tempfile.TemporaryFile()
        start = time.perf_counter()
        self.process = subprocess.Popen([*command, "--server"], cwd=cwd, env=env, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=self.stderr_log, creationflags=FLAGS)
        self.reader = Thread(target=self.read_stdout, daemon=True)
        self.reader.start()
        try:
            workspace = {"uri": cwd.as_uri(), "name": "D39 verified Lean input"}
            self.request("initialize", {"processId": os.getpid(), "rootUri": cwd.as_uri(), "capabilities": {},
                                        "workspaceFolders": [workspace]})
            self.send({"method": "initialized", "params": {}})
            self.startup_seconds = time.perf_counter() - start
        except Exception:
            self.close()
            raise

    def read_stdout(self):
        pipe = self.process.stdout
        try:
            while True:
                headers = {}
                while True:
                    line = pipe.readline()
                    if not line:
                        raise EOFError("Lean server closed stdout")
                    if line in (b"\n", b"\r\n"):
                        break
                    name, value = line.decode("ascii").split(":", 1)
                    headers[name.lower()] = value.strip()
                size = int(headers["content-length"])
                if not 0 <= size <= MAX_RESPONSE_BYTES:
                    raise ValueError("Unexpected Lean LSP response size")
                raw = pipe.read(size)
                if len(raw) != size:
                    raise EOFError("Incomplete Lean LSP response")
                self.messages.put(json.loads(raw))
        except Exception as exc:
            self.messages.put(exc)

    def send(self, message):
        packet = json.dumps({"jsonrpc": "2.0", **message}, ensure_ascii=False).encode()
        self.process.stdin.write(f"Content-Length: {len(packet)}\r\n\r\n".encode() + packet)
        self.process.stdin.flush()

    def request(self, method, params):
        self.next_id += 1
        request_id = self.next_id
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        received = []
        while True:
            try:
                message = self.messages.get(timeout=max(0.0, deadline - time.monotonic()))
            except Empty as exc:
                raise TimeoutError(f"Lean LSP request did not complete: {method}") from exc
            if isinstance(message, Exception):
                raise message
            if "id" in message and "method" in message:
                self.send({"id": message["id"], "error": {"code": -32601, "message": "Unsupported client request"}})
            elif message.get("id") == request_id:
                if "error" in message:
                    raise ValueError(f"Lean LSP {method}: {message['error']}")
                return received
            else:
                received.append(message)

    def check(self, path, source, targets):
        start = time.perf_counter()
        uri = path.as_uri()
        self.version += 1
        if self.open_uri is None:
            path.write_text(source, encoding="utf-8", newline="\n")
            self.send({"method": "textDocument/didOpen", "params": {"textDocument": {
                "uri": uri, "languageId": "lean4", "version": self.version, "text": source},
                "dependencyBuildMode": "never"}})
            self.open_uri = uri
        elif self.open_uri == uri:
            self.send({"method": "textDocument/didChange", "params": {
                "textDocument": {"uri": uri, "version": self.version}, "contentChanges": [{"text": source}]}})
        else:
            raise ValueError("Use the same open Lean document for a resident sequence")
        replies = self.request("textDocument/waitForDiagnostics", {"uri": uri, "version": self.version})
        publications = [item["params"]["diagnostics"] for item in replies
                        if item.get("method") == "textDocument/publishDiagnostics"
                        and item["params"]["uri"] == uri and item["params"].get("version") == self.version]
        messages = [{"severity": item["severity"], "message": item["message"],
                     "line": item["range"]["start"]["line"] + 1} for item in publications[-1]] if publications else []
        return {**proof_scope(messages, targets), "source_sha256": sha(source), "document_version": self.version,
                "elapsed_seconds": time.perf_counter() - start, "matching_publications": len(publications), "messages": messages}

    def close(self):
        try:
            if self.process.poll() is None:
                if self.open_uri is not None:
                    self.send({"method": "textDocument/didClose", "params": {"textDocument": {"uri": self.open_uri}}})
                self.request("shutdown", None)
                self.send({"method": "exit"})
                self.process.wait(timeout=5)
        except (OSError, ValueError, TimeoutError, EOFError, subprocess.TimeoutExpired):
            self.process.terminate()
            self.process.wait(timeout=5)
        finally:
            self.stderr_log.seek(0)
            self.stderr_excerpt = self.stderr_log.read().decode(errors="replace")[-4000:]
            self.stderr_log.close()
            self.process.stdin.close()
            self.process.stdout.close()


def compare(command, cwd, inputs, *, timeout=120, env=None, scratch_parent=None):
    """Call only with reviewed sources. Changes replace one open document in order."""
    with tempfile.TemporaryDirectory(prefix="d39_resident_", dir=scratch_parent) as folder:
        temp = Path(folder)
        cold = [cold_check(command, cwd, temp / f"cold_{index}.lean", s, t, timeout=timeout, env=env)
                for index, (s, t) in enumerate(inputs)]
        resident = ResidentLean(command, cwd, timeout, env=env)
        try:
            warm = [resident.check(temp / "resident.lean", s, t) for s, t in inputs]
        finally:
            closing = time.perf_counter()
            resident.close()
            close_seconds = time.perf_counter() - closing
    return {"cold": cold, "resident": warm, "resident_startup_seconds": resident.startup_seconds,
            "resident_shutdown_seconds": close_seconds,
            "resident_stderr": resident.stderr_excerpt.replace(str(temp), "$D39_CASE_DIR").replace(str(cwd), "$D39_PROJECT"),
            "cold_total_seconds": sum(r["elapsed_seconds"] for r in cold),
            "resident_total_seconds": resident.startup_seconds + sum(r["elapsed_seconds"] for r in warm),
            "resident_total_including_shutdown_seconds": resident.startup_seconds + close_seconds + sum(r["elapsed_seconds"] for r in warm),
            "all_statuses_match": all(a["status"] == b["status"] and a["axioms"] == b["axioms"]
                                      for a, b in zip(cold, warm, strict=True))}


def smoke(exe, output):
    target = "d39_resident_target"
    prefix = f"import Lean\nset_option warningAsError true\ntheorem {target} (n : Nat) : n + 0 = n := by\n  "
    inputs = [(prefix + proof + f"\n#print axioms {target}\n", [target])
              for proof in ("exact Nat.add_zero n", "exact True.intro", "exact Nat.add_zero n", "sorry")]
    results = compare([str(exe)], exe.parent, inputs, timeout=40)
    expected = ["KERNEL_ACCEPTED", "REJECTED", "KERNEL_ACCEPTED", "REJECTED"]
    results["expected_statuses"] = expected
    results["scope"] = "Trusted Lean core protocol controls only. No BlueprintTrace module or author environment is used."
    results["status"] = "PASS" if results["all_statuses_match"] and [r["status"] for r in results["cold"]] == expected else "FAIL"
    with output.open("xb") as destination:
        destination.write((json.dumps(results, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps({k: results[k] for k in ("status", "cold_total_seconds", "resident_total_seconds")}))
    if results["status"] != "PASS":
        raise SystemExit(1)


def batch_smoke(exe, output):
    proofs = ("exact Nat.add_zero n", "exact True.intro", "exact Nat.add_zero n", "sorry")
    lines = ["import Lean", "set_option warningAsError true"]
    blocks = []
    for index, proof in enumerate(proofs, 1):
        target = f"d39_batch_{index}"
        first = len(lines) + 1
        lines.extend([f"theorem {target} (n : Nat) : n + 0 = n := by", "  " + proof, f"#print axioms {target}"])
        blocks.append((first, len(lines), [target]))
    with tempfile.TemporaryDirectory(prefix="d39_batch_") as folder:
        results = batch_scoped_diagnostics([str(exe)], exe.parent, Path(folder) / "batch.lean",
                                           "\n".join(lines) + "\n", blocks, timeout=40)
    expected = ["KERNEL_ACCEPTED", "REJECTED", "KERNEL_ACCEPTED", "REJECTED"]
    results["expected_statuses"] = expected
    results["scope"] = "Independent trusted core blocks. Batch exit is nonzero when a block rejects. Each result uses its own source and axiom closure. Not an author environment result."
    results["status"] = "PASS" if [r["status"] for r in results["scopes"]] == expected and results["exit_code"] != 0 else "FAIL"
    with output.open("xb") as destination:
        destination.write((json.dumps(results, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps({"status": results["status"], "elapsed_seconds": results["elapsed_seconds"]}))
    if results["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lean", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-smoke", action="store_true")
    args = parser.parse_args()
    action = batch_smoke if args.batch_smoke else smoke
    action(args.lean.resolve(), args.output)
