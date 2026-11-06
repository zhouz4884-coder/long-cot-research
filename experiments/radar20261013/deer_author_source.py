"""Execute functions from the immutable author file, never a STOP proxy.

CPU controls provide their backend explicitly; production imports the complete
author module with its real libraries. The dataset adapter withholds all Gold.
This module by itself is not a GPU runner or a same-protocol performance result.
"""
import ast
import hashlib
import importlib.util
from pathlib import Path
import types

EXPECTED_QWEN_SHA256='96460df9d532e02ca82535f6b5a6757cffff40bcbb233a4d6a1bd074684cc095'
ROOT=Path(__file__).resolve().parent


def pinned_path():
    path=ROOT/'vendor/DEER/vllm-deer-qwen3.py'
    assert hashlib.sha256(path.read_bytes()).hexdigest()==EXPECTED_QWEN_SHA256, 'Pinned author source changed'
    return path


def load_author_module():
    path=pinned_path()
    spec=importlib.util.spec_from_file_location('pinned_deer_qwen_author',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_original_functions_for_cpu_controls(namespace):
    path=pinned_path()
    tree=ast.parse(path.read_text(encoding='utf-8'))
    functions=[node for node in tree.body if isinstance(node,ast.FunctionDef)]
    module=types.ModuleType('pinned_deer_qwen_cpu_controls')
    module.__dict__.update(namespace)
    exec(compile(ast.Module(body=functions,type_ignores=[]),str(path),'exec'),module.__dict__)
    return module


def invoke_author_batch(author, questions, arguments):
    """Run author's full main(), adapting input schema and output capture only.

Question list is restricted to problem_id/question fields before entering the
author state machine. The author requires answer for output_dict, so use a
sentinel; the real Gold is never supplied to it. Source final generation and
errors are retained, including final regeneration after a high-confidence trial.
"""
    ids=[q['problem_id'] for q in questions]
    texts=[q['question'] for q in questions]
    assert len(ids)==len(set(ids))
    assert questions and all(set(q)=={'problem_id','question'} for q in questions), 'Supply no labels to generation'
    markers={pid:'<withheld-id:'+hashlib.sha256(pid.encode('utf-8')).hexdigest()+'>' for pid in ids}
    assert len(set(markers.values()))==len(ids)
    captured=[]
    originals={name:getattr(author,name) for name in ['parse_args','read_jsonl','write_jsonl']}
    author.parse_args=lambda:arguments
    # The source only copies answer into output_dict; it never puts it in a model
    # prompt or a decision. A unique non-Gold marker avoids its duplicate-text
    # sorting ambiguity without changing any question or dropping frozen IDs.
    author.read_jsonl=lambda path:[{'problem':q['question'],'answer':markers[q['problem_id']]} for q in questions]
    def capture(rows,path):
        assert not captured, 'Multiple final writes are not a complete single author run'
        captured.extend(rows)
    author.write_jsonl=capture
    try:
        author.main()
    finally:
        for name,value in originals.items():setattr(author,name,value)
    assert len(captured)==len(questions), 'Missing author outputs, do not treat run as complete'
    by_marker={row['gold_answer']:row for row in captured}
    assert len(by_marker)==len(ids) and set(by_marker)==set(markers.values()),'Missing/duplicated source ID marker'
    ordered=[]
    for pid,text in zip(ids,texts):
        marker=markers[pid];row=by_marker[marker]
        assert row['question']==text,'Source question/ID differs'
        ordered.append(dict(row,problem_id=pid,source_id_marker=marker,gold_answer='<withheld>'))
    return ordered
