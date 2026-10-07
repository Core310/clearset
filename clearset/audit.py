#!/usr/bin/env python3
"""
ClearSet Audit (`cs-audit` / `cta-audit`):
Deterministic Anti-AI Defense Gate & Human Writing Stylometric Auditor.

Enforces authentic human writing, spiky sentence-length burstiness, and blocks
blatant AI markers (<60% AI threshold, <35% Red Bucket concentration).
"""

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


def main():
    parser = argparse.ArgumentParser(
        description="ClearSet Audit (`cs-audit`): Deterministic Anti-AI Defense Gate & Stylometric Auditor"
    )
    parser.add_argument("target", help="File path or raw text string to audit (.ipynb, .pdf, .md, .tex, .txt)")
    parser.add_argument("--verify", action="store_true", help="Quiet verify mode: exit code 0 if passed, 1 if blocked")
    parser.add_argument("--no-db", action="store_true", help="Do not write audit row to cs_turns.db")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    args = parser.parse_args()
    res = audit_document(args.target, record_to_db=not args.no_db)

    if args.json:
        print(json.dumps(res, indent=2))
        sys.exit(0 if res["passed"] else 1)

    if args.verify:
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
