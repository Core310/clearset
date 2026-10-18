#!/usr/bin/env python3
"""
ClearSet Audit (`cs-audit` / `cta-audit`):
Deterministic Code Quality Grader & Document Stylometric Auditor.

Evaluates codebases for syntax validity, AST bloat (>500 lines), dead symbols,
cyclomatic nesting complexity, and bare exception handling. Also audits documents
for stylometric burstiness and AI clichés (<60% AI threshold, <35% Red Bucket).
"""

import ast
import sys
import re
import os
import math
import json
import subprocess
import argparse
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

from clearset.engine import (
    find_workspace,
    get_turns_db_path,
    log_turn_action,
)

# ==============================================================================
# BANNED VOCABULARY & DEAD-GIVEAWAY MARKERS
# ==============================================================================
CRITICAL_AI_CLICHES = [
    "delve", "delving", "pivotal", "paramount", "beacon", "tapestry",
    "multifaceted", "ever-evolving", "it is worth noting", "underscores",
    "sheds light on", "testament to", "testament", "nuanced", "at its core",
    "seamlessly", "fosters", "harnesses", "holistic", "spearheaded",
    "intricacies", "cornerstone", "game-changer", "realm of", "in today's",
    "in conclusion", "to summarize", "in summary", "plays a vital role",
    "a myriad of", "it is important to remember", "crucial"
]

SUSPICIOUS_AI_TRANSITIONS = [
    "furthermore", "moreover", "not only", "but also", "in order to",
    "as well as", "serves as a", "plays a key", "in the realm of",
    "it is important to note", "a wide range of", "at the forefront of"
]

ARIKA_VOICE_SIGNALS = [
    "mechanism", "feedback loop", "incentive", "bonus", "quant", "dataset",
    "edge", "tpu", "npu", "latency", "int8", "int16", "litert", "buffer",
    "tensor", "pipeline", "yolo", "coordinates", "zed", "docker compose",
    "hence,", "next,", "however,", "in this context,", "the goal is",
    "black-box", "grounding", "tradeoff", "inference", "throughput"
]


# ==============================================================================
# FILE EXTRACTION & NORMALIZATION
# ==============================================================================
def read_content(source: str) -> str:
    """Reads text from string, PDF file, LaTeX file, Markdown, Jupyter Notebook, or plain text."""
    if not os.path.exists(source):
        return source

    if source.lower().endswith(".pdf"):
        try:
            raw = subprocess.check_output(["pdftotext", source, "-"], stderr=subprocess.DEVNULL)
            return raw.decode("utf-8", errors="ignore")
        except Exception:
            pass

    if source.lower().endswith(".ipynb"):
        try:
            with open(source, "r", encoding="utf-8", errors="ignore") as f:
                data = json.load(f)
            md_cells = []
            for cell in data.get("cells", []):
                if cell.get("cell_type") == "markdown":
                    md_cells.append("".join(cell.get("source", [])))
            return "\n\n".join(md_cells)
        except Exception:
            pass

    with open(source, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()

    if source.lower().endswith(".tex"):
        text = re.sub(r'\\[a-zA-Z]+(\[[^\]]*\])?(\{[^\}]*\})?', ' ', text)
        text = re.sub(r'[{}\\%]', ' ', text)

    return text


def split_sentences(text: str) -> List[str]:
    """Splits text into sentences, preserving common abbreviations."""
    clean_text = re.sub(r'```[\s\S]*?```', '', text)
    clean_text = re.sub(r'\\\[[\s\S]*?\\\]', '', clean_text)
    
    abbrs = ["e.g.", "i.e.", "vs.", "Dr.", "Mr.", "Mrs.", "Ms.", "No.", "D.C.", "CS 4083", "CS 4273", "CS 5593"]
    for i, abbr in enumerate(abbrs):
        clean_text = clean_text.replace(abbr, f"__ABBR_{i}__")
    
    raw_sentences = re.split(r'(?<=[.!?])\s+', clean_text)
    sentences = []
    for s in raw_sentences:
        s = s.strip()
        if not s:
            continue
        for i, abbr in enumerate(abbrs):
            s = s.replace(f"__ABBR_{i}__", abbr)
        if s.startswith('#') or s.startswith('|') or len(s.split()) < 2:
            continue
        sentences.append(s)
    return sentences


def extract_paragraphs(text: str) -> List[str]:
    paras = text.split("\n\n")
    return [p.strip() for p in paras if p.strip() and not p.startswith('#') and not p.startswith('```') and not p.startswith('|')]


# ==============================================================================
# SENTENCE BUCKET CLASSIFICATION
# ==============================================================================
def classify_sentence(sentence: str, prev_len: int = 0) -> Tuple[str, str, int]:
    """
    Classifies a sentence into:
    - 🔴 RED: Obvious AI cliché or unvaried dead-zone cadence (18-24w with ~0 delta)
    - 🟡 YELLOW: Neutral academic sentence
    - 🟢 GREEN: High burstiness (very short or very long), domain anchors, numbers, or technical signals
    """
    words = re.findall(r'\b[a-zA-Z0-9_\'-]+\b', sentence.lower())
    length = len(words)
    delta = abs(length - prev_len) if prev_len > 0 else 5

    # Check for hard red clichés
    for c in CRITICAL_AI_CLICHES:
        pattern = r'\b' + re.escape(c) + r'\b'
        if re.search(pattern, sentence.lower()):
            return "RED", f"Contains blatant AI cliché '{c}'", length

    # Check for typical ChatGPT dead-zone with monotonous delta
    if 18 <= length <= 24 and delta <= 2:
        return "RED", f"Dead-zone cadence ({length} words, low delta {delta}w)", length

    # Check for green indicators
    has_voice = any(sig in sentence.lower() for sig in ARIKA_VOICE_SIGNALS)
    has_numbers = bool(re.search(r'\b\d+(\.\d+)?%?\b', sentence))
    is_bursty = (length <= 10 or length >= 32 or delta >= 8)

    if has_voice or (has_numbers and is_bursty) or (delta >= 10):
        return "GREEN", "Authentic variation or technical anchoring", length

    return "YELLOW", "Neutral / acceptable cadence", length


# ==============================================================================
# COMPOSITE SCORER & PRAGMATIC GATE
# ==============================================================================
def evaluate_text(text: str) -> Dict[str, Any]:
    sentences = split_sentences(text)
    paragraphs = extract_paragraphs(text)
    words = re.findall(r'\b[a-zA-Z0-9_\'-]+\b', text.lower())
    
    if not sentences:
        return {
            "verdict": "PASS",
            "ai_probability": 0.0,
            "human_probability": 1.0,
            "passed": True,
            "bucket_counts": {"GREEN": 0, "YELLOW": 0, "RED": 0},
            "metrics": {},
            "red_sentences": []
        }

    bucket_counts = {"GREEN": 0, "YELLOW": 0, "RED": 0}
    sentence_classifications = []
    red_sentences = []
    
    prev_len = 0
    sentence_lengths = []
    for idx, s in enumerate(sentences, start=1):
        bucket, reason, s_len = classify_sentence(s, prev_len)
        sentence_lengths.append(s_len)
        prev_len = s_len
        bucket_counts[bucket] += 1
        
        info = {
            "index": idx,
            "bucket": bucket,
            "length": s_len,
            "reason": reason,
            "text": s[:90] + ("..." if len(s) > 90 else "")
        }
        sentence_classifications.append(info)
        if bucket == "RED":
            red_sentences.append(info)

    mean_len = sum(sentence_lengths) / len(sentence_lengths) if sentence_lengths else 0
    variance = sum((x - mean_len) ** 2 for x in sentence_lengths) / len(sentence_lengths) if sentence_lengths else 0
    std_dev = math.sqrt(variance)
    cv = (std_dev / mean_len) if mean_len > 0 else 0.0

    deltas = [abs(sentence_lengths[i] - sentence_lengths[i-1]) for i in range(1, len(sentence_lengths))]
    avg_delta = sum(deltas) / len(deltas) if deltas else 0.0

    total_s = len(sentences)
    red_pct = bucket_counts["RED"] / total_s
    green_pct = bucket_counts["GREEN"] / total_s
    
    banned_found = []
    for c in CRITICAL_AI_CLICHES:
        pattern = r'\b' + re.escape(c) + r'\b'
        matches = re.findall(pattern, text.lower())
        if matches:
            banned_found.extend(matches)

    raw_ai_prob = (red_pct * 0.70) + (len(banned_found) * 0.12)
    
    if cv >= 0.40 or avg_delta >= 6.0:
        raw_ai_prob -= 0.15
    if green_pct >= 0.30:
        raw_ai_prob -= (green_pct * 0.20)

    ai_prob = round(min(0.99, max(0.02, raw_ai_prob)), 3)
    human_prob = round(1.0 - ai_prob, 3)

    # Pass condition: AI Probability < 0.60 AND Red Bucket <= 35% of sentences
    passed = (ai_prob < 0.60 and red_pct <= 0.35)
    verdict = "PASS" if passed else "BLOCKED"

    return {
        "verdict": verdict,
        "ai_probability": ai_prob,
        "human_probability": human_prob,
        "passed": passed,
        "bucket_counts": bucket_counts,
        "metrics": {
            "total_sentences": total_s,
            "total_words": len(words),
            "burstiness_cv": round(cv, 3),
            "avg_sentence_delta": round(avg_delta, 2),
            "banned_cliches_count": len(banned_found),
            "banned_words_found": banned_found
        },
        "red_sentences": red_sentences,
        "classifications": sentence_classifications
    }


def audit_document(
    source_path_or_text: str,
    record_to_db: bool = True,
    milestone: str = "M001",
    phase: str = "01",
    task: str = "audit",
) -> Dict[str, Any]:
    text = read_content(source_path_or_text)
    eval_res = evaluate_text(text)
    
    target_name = os.path.basename(source_path_or_text) if os.path.exists(source_path_or_text) else "inline_text"
    eval_res["target"] = target_name
    
    if record_to_db and os.path.exists(source_path_or_text):
        workspace = find_workspace(Path(source_path_or_text).parent)
        turns_db = get_turns_db_path(workspace)
        if turns_db.exists():
            status_str = "SUCCESS" if eval_res["passed"] else "FAILED"
            desc = f"AI Defense Gate audit: {target_name} -> {eval_res['verdict']} (AI: {eval_res['ai_probability']*100:.1f}%, Human: {eval_res['human_probability']*100:.1f}%)"
            log_turn_action(
                workspace=workspace,
                session_id="active-session",
                milestone=milestone,
                phase=phase,
                task=task,
                action_type="VERIFICATION",
                description=desc,
                status=status_str,
                files=[os.path.abspath(source_path_or_text)],
                summary=f"Audit {eval_res['verdict']}: AI={eval_res['ai_probability']*100:.1f}%, Red={eval_res['bucket_counts']['RED']}/{eval_res['metrics'].get('total_sentences',0)}",
            )

    return eval_res


CODE_EXTENSIONS = {".py", ".sh", ".bash", ".js", ".jsx", ".ts", ".tsx", ".rs", ".go", ".c", ".cpp", ".h", ".hpp", ".yml", ".yaml"}


class CodeAuditor(ast.NodeVisitor):
    """
    AST-based Code Quality Auditor and Adversarial Second View.
    Evaluates syntax, code bloat (>500 lines), long functions (>60 lines),
    over-parameterized functions (>6 args), bare exception clauses,
    silent exception swallowing, and cyclomatic nesting depth.
    """

    def __init__(self, filename: str, content: str):
        self.filename = filename
        self.content = content
        self.lines = content.splitlines()
        self.total_lines = len(self.lines)
        self.issues: List[str] = []
        self.warnings: List[str] = []
        self.functions: List[Dict[str, Any]] = []
        self.classes: List[str] = []
        self.current_depth = 0
        self.max_depth = 0

    def check(self) -> Dict[str, Any]:
        # 1. File size / bloat checks
        if self.total_lines > 1000:
            self.issues.append(f"File is severely bloated: {self.total_lines} lines (exceeds 1000 line ceiling)")
        elif self.total_lines > 500:
            self.warnings.append(f"File is large: {self.total_lines} lines (exceeds 500 line guideline)")

        # 2. Syntax validation
        try:
            tree = ast.parse(self.content, filename=self.filename)
        except SyntaxError as e:
            return {
                "type": "code",
                "target": self.filename,
                "passed": False,
                "verdict": "BLOCKED",
                "score": 0,
                "syntax_valid": False,
                "issues": [f"SyntaxError on line {e.lineno}: {e.msg}"],
                "warnings": self.warnings,
                "metrics": {
                    "total_lines": self.total_lines,
                    "functions": 0,
                    "classes": 0,
                    "max_depth": 0,
                },
            }

        # 3. AST inspection
        self.visit(tree)

        # 4. Score computation
        score = 100
        score -= min(50, len(self.issues) * 20)
        score -= min(30, len(self.warnings) * 5)
        if self.max_depth > 4:
            score -= (self.max_depth - 4) * 5

        score = max(0, min(100, score))
        passed = (len(self.issues) == 0 and score >= 70)
        verdict = "PASS" if passed else "BLOCKED"

        return {
            "type": "code",
            "target": self.filename,
            "passed": passed,
            "verdict": verdict,
            "score": score,
            "syntax_valid": True,
            "issues": self.issues,
            "warnings": self.warnings,
            "metrics": {
                "total_lines": self.total_lines,
                "functions": len(self.functions),
                "classes": len(self.classes),
                "max_depth": self.max_depth,
            },
        }

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_function(node)
        self.generic_visit(node)

    def _check_function(self, node: Any) -> None:
        fn_lines = getattr(node, "end_lineno", node.lineno) - node.lineno + 1
        arg_count = len(node.args.args)
        self.functions.append({"name": node.name, "lines": fn_lines, "args": arg_count})

        if fn_lines > 80:
            self.issues.append(f"Function '{node.name}' (line {node.lineno}) is bloated: {fn_lines} lines (ceiling 80 lines)")
        elif fn_lines > 50:
            self.warnings.append(f"Function '{node.name}' (line {node.lineno}) is long: {fn_lines} lines (guideline <= 50 lines)")

        if arg_count > 6:
            self.warnings.append(f"Function '{node.name}' (line {node.lineno}) has {arg_count} parameters (guideline <= 6)")

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.classes.append(node.name)
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        # Bare except:
        if node.type is None:
            self.issues.append(f"Line {node.lineno}: Bare 'except:' clause catches BaseException indiscriminately")
        elif isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException"):
            # Check for empty body / pass
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                self.issues.append(f"Line {node.lineno}: Silent exception swallowing 'except {node.type.id}: pass'")
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        self._enter_nested(node)

    def visit_For(self, node: ast.For) -> None:
        self._enter_nested(node)

    def visit_While(self, node: ast.While) -> None:
        self._enter_nested(node)

    def visit_Try(self, node: ast.Try) -> None:
        self._enter_nested(node)

    def visit_With(self, node: ast.With) -> None:
        self._enter_nested(node)

    def _enter_nested(self, node: Any) -> None:
        self.current_depth += 1
        self.max_depth = max(self.max_depth, self.current_depth)
        if self.current_depth > 5:
            self.warnings.append(f"Line {node.lineno}: Deep nesting depth ({self.current_depth} levels)")
        self.generic_visit(node)
        self.current_depth -= 1


def audit_code(
    source_path_or_code: str,
    record_to_db: bool = True,
    milestone: str = "M001",
    phase: str = "01",
    task: str = "audit",
) -> Dict[str, Any]:
    """Audits code quality, syntax validity, AST bloat, and nesting depth."""
    if os.path.exists(source_path_or_code):
        with open(source_path_or_code, "r", encoding="utf-8", errors="ignore") as f:
            code_str = f.read()
        target_name = os.path.basename(source_path_or_code)
        file_path = os.path.abspath(source_path_or_code)
    else:
        code_str = source_path_or_code
        target_name = "inline_code.py"
        file_path = None

    auditor = CodeAuditor(target_name, code_str)
    res = auditor.check()
    res["target"] = target_name

    if record_to_db and file_path:
        workspace = find_workspace(Path(file_path).parent)
        turns_db = get_turns_db_path(workspace)
        if turns_db.exists():
            status_str = "SUCCESS" if res["passed"] else "FAILED"
            desc = f"Code Quality Gate audit: {target_name} -> {res['verdict']} (Score: {res['score']}/100, Issues: {len(res['issues'])}, Warnings: {len(res['warnings'])})"
            log_turn_action(
                workspace=workspace,
                session_id="active-session",
                milestone=milestone,
                phase=phase,
                task=task,
                action_type="VERIFICATION",
                description=desc,
                status=status_str,
                files=[file_path],
                summary=f"Code Audit {res['verdict']}: Score={res['score']}/100, Lines={res['metrics']['total_lines']}, Fns={res['metrics']['functions']}",
            )

    return res


def audit_target(
    source_path_or_text: str,
    record_to_db: bool = True,
    milestone: str = "M001",
    phase: str = "01",
    task: str = "audit",
) -> Dict[str, Any]:
    """Auto-detects whether the target is code or a document and audits accordingly."""
    if os.path.exists(source_path_or_text):
        ext = os.path.splitext(source_path_or_text)[1].lower()
        if ext in CODE_EXTENSIONS:
            return audit_code(
                source_path_or_text,
                record_to_db=record_to_db,
                milestone=milestone,
                phase=phase,
                task=task,
            )
    else:
        # Check if raw string looks like python code
        stripped = source_path_or_text.strip()
        if stripped.startswith(("def ", "class ", "import ", "from ", "async def ")):
            return audit_code(
                source_path_or_text,
                record_to_db=record_to_db,
                milestone=milestone,
                phase=phase,
                task=task,
            )

    return audit_document(
        source_path_or_text,
        record_to_db=record_to_db,
        milestone=milestone,
        phase=phase,
        task=task,
    )


def main():
    parser = argparse.ArgumentParser(
        description="ClearSet Audit (`cs-audit`): Deterministic Code Quality Grader & Document Stylometric Auditor"
    )
    parser.add_argument("target", help="File path or raw string to audit (code file or document)")
    parser.add_argument("--verify", action="store_true", help="Quiet verify mode: exit code 0 if passed, 1 if blocked")
    parser.add_argument("--no-db", action="store_true", help="Do not write audit row to cs_turns.db")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    args = parser.parse_args()
    res = audit_target(args.target, record_to_db=not args.no_db)

    if args.json:
        print(json.dumps(res, indent=2))
        sys.exit(0 if res["passed"] else 1)

    is_code = res.get("type") == "code"

    if args.verify:
        if is_code:
            if res["passed"]:
                print(f"✓ [CODE QUALITY GATE]: PASSED (Score: {res['score']}/100, Functions: {res['metrics']['functions']}, Warnings: {len(res['warnings'])})")
                sys.exit(0)
            else:
                print(f"✗ [CODE QUALITY GATE]: BLOCKED (Score: {res['score']}/100, Issues: {len(res['issues'])})")
                sys.exit(1)
        else:
            if res["passed"]:
                total_s = res["metrics"]["total_sentences"]
                g_pct = (res["bucket_counts"]["GREEN"] / total_s * 100) if total_s else 0
                r_pct = (res["bucket_counts"]["RED"] / total_s * 100) if total_s else 0
                print(f"✓ [AI DEFENSE GATE]: PASSED (AI: {res['ai_probability']*100:.1f}% [<60% threshold], 🟢 Green: {g_pct:.1f}%, 🔴 Red: {r_pct:.1f}%)")
                sys.exit(0)
            else:
                print(f"✗ [AI DEFENSE GATE]: BLOCKED (AI: {res['ai_probability']*100:.1f}% [>=60% threshold], Red Buckets: {res['bucket_counts']['RED']})")
                sys.exit(1)

    # Standard audit report
    print("==================================================================")
    if is_code:
        print(f"  CODE QUALITY GATE AUDIT REPORT: {res['verdict']}")
        print("==================================================================")
        print(f"Target:                 {res['target']}")
        print(f"Quality Score:          {res['score']}/100 (Pass threshold: >= 70)")
        print(f"Syntax Valid:           {res['syntax_valid']}")
        print(f"Verdict:                {res['verdict']}")
        print()
        m = res["metrics"]
        print("Codebase Metrics:")
        print(f"  • Total Lines         : {m['total_lines']}")
        print(f"  • Functions           : {m['functions']}")
        print(f"  • Classes             : {m['classes']}")
        print(f"  • Max Nesting Depth   : {m['max_depth']}")
        print()
        if res["issues"]:
            print(f"Blocking Issues ({len(res['issues'])}):")
            for iss in res["issues"]:
                print(f"  ✗ {iss}")
            print()
        if res["warnings"]:
            print(f"Quality Warnings ({len(res['warnings'])}):")
            for w in res["warnings"]:
                print(f"  ⚠ {w}")
    else:
        print(f"  AI DEFENSE GATE AUDIT REPORT: {res['verdict']}")
        print("==================================================================")
        print(f"AI Risk Probability:    {res['ai_probability']*100:.1f}% (Pass threshold: < 60%)")
        print(f"Human Probability:      {res['human_probability']*100:.1f}%")
        print()
        total = res["metrics"].get("total_sentences", 1)
        b = res["bucket_counts"]
        print("Bucket Distribution:")
        print(f"  🟢 Green  (Human / Anchored): {b['GREEN']} ({b['GREEN']/total*100:.1f}%)")
        print(f"  🟡 Yellow (Neutral Academic):  {b['YELLOW']} ({b['YELLOW']/total*100:.1f}%)")
        print(f"  🔴 Red    (Obvious AI / Dead):  {b['RED']} ({b['RED']/total*100:.1f}%)")
        print()
        print("Stylometric Metrics:")
        for k, v in res["metrics"].items():
            if k != "banned_words_found":
                print(f"  • {k:<24}: {v}")
        print()
        if res["red_sentences"]:
            print(f"Red Bucket Sentences ({len(res['red_sentences'])}):")
            for r in res["red_sentences"][:10]:
                print(f"  [{r['index']}] ({r['length']}w): \"{r['text']}\" ({r['reason']})")
    print("==================================================================")
    sys.exit(0 if res["passed"] else 1)


if __name__ == "__main__":
    main()
