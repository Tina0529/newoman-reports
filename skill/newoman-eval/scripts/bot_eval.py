#!/usr/bin/env python3
"""
GBase Bot Answer Rate Evaluation Script
========================================
Sends questions from cases.yaml to a GBase bot via streaming API,
then evaluates whether each response is a real answer or "unanswered".

Unanswered criteria:
  1. Empty output / system error
  2. Only filler phrases (e.g. "お調べいたします")
  3. "見つかりませんでした" type responses

Everything else = answered (content accuracy doesn't matter).

Usage:
  python bot_eval.py --bot-id <UUID> [--token <TOKEN>] [--output results.json]
"""

import argparse
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import httpx
import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
API_BASE = "https://api.gbase.ai"
DEFAULT_TOKEN = os.environ.get(
    "GBASE_API_TOKEN",
    "ak-N2yrPLPGyUteUy1MqbtSeNN91Y9TfGn2qDRigPwgfWrnoRac",
)

# Filler phrases that do NOT constitute a real answer
FILLER_PATTERNS = [
    r"お調べいたします",
    r"お探しいたします",
    r"確認いたします",
    r"お待ちください",
    r"少々お待ち",
]

# "Not found" patterns → unanswered
NOT_FOUND_PATTERNS = [
    r"見つかりませんでした",
    r"見つけることができませんでした",
    r"該当する情報[がは].*(?:ありません|ございません)",
    r"一致する情報[がは].*(?:ありません|ございません)",
    r"お探しの情報[がは].*(?:ありません|ございません)",
    r"情報が見つかりません",
    r"回答できません",
    r"お答えすることが(?:できません|難しい)",
    r"対応しておりません",
]

# System error patterns → unanswered
ERROR_PATTERNS = [
    r"エラーが発生",
    r"システムエラー",
    r"internal\s*(?:server\s*)?error",
    r"something went wrong",
    r"an error occurred",
    r"申し訳ございません.{0,40}(?:エラー|障害|不具合)",
]


def is_unanswered(answer: str) -> tuple[bool, str]:
    """
    Determine if the bot's answer is 'unanswered'.

    Returns (is_unanswered: bool, reason: str).
    """
    if not answer or not answer.strip():
        return True, "empty"

    text = answer.strip()

    # --- Tier 1: system errors ---
    for pat in ERROR_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True, "error"

    # --- Tier 2: "not found" responses ---
    for pat in NOT_FOUND_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True, "not_found"

    # --- Tier 3: filler-only responses ---
    # Remove all known filler phrases, punctuation, whitespace, and
    # trailing control tokens like "nonclarificationtruetrue"
    cleaned = text
    # Remove trailing control tokens (GBase appends these)
    cleaned = re.sub(r"(?:nonclarification|true|false)+\s*$", "", cleaned)
    # Remove filler phrases
    for pat in FILLER_PATTERNS:
        cleaned = re.sub(pat, "", cleaned)
    # Remove store name references that are part of filler
    cleaned = re.sub(r"ニュウマン高輪[のに]?(?:情報|店舗)?[をのに]?", "", cleaned)
    # Remove punctuation and whitespace
    cleaned = re.sub(r"[\s。、！？!?\.\,\n\r…]+", "", cleaned)

    if len(cleaned) < 5:
        return True, "filler_only"

    return False, "answered"


def ask_question(
    client: httpx.Client,
    bot_id: str,
    token: str,
    question: str,
    timeout: float = 60.0,
) -> dict:
    """Send a question to the GBase bot and collect the streaming answer."""
    session_id = str(uuid.uuid4())
    url = f"{API_BASE}/questions/{bot_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "question": question,
        "session_id": session_id,
        "stream": True,
        "stream_obj": True,
        "is_test": True,
    }

    answer_parts = []
    text_parts = []  # For FAQ plain-text responses
    message_id = None
    error = None
    is_faq = False

    try:
        with client.stream(
            "POST", url, headers=headers, json=body, timeout=timeout
        ) as resp:
            if resp.status_code != 200:
                return {
                    "answer": "",
                    "message_id": None,
                    "error": f"HTTP {resp.status_code}",
                    "source": "error",
                }
            for line in resp.iter_lines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    content = obj.get("content", "")
                    if content:
                        if isinstance(content, list):
                            answer_parts.extend(str(c) for c in content)
                        elif isinstance(content, str):
                            answer_parts.append(content)
                        else:
                            answer_parts.append(str(content))
                    if not message_id:
                        message_id = obj.get("message_id")
                    if obj.get("use_faq"):
                        is_faq = True
                except json.JSONDecodeError:
                    # FAQ responses come as plain text (not JSON)
                    text_parts.append(line)
                    is_faq = True
    except httpx.TimeoutException:
        error = "timeout"
    except Exception as e:
        error = str(e)

    # Combine JSON answer and plain-text FAQ answer
    json_answer = "".join(answer_parts)
    text_answer = "\n".join(text_parts)
    final_answer = json_answer if json_answer else text_answer

    return {
        "answer": final_answer,
        "message_id": message_id,
        "error": error,
        "source": "faq" if is_faq else "rag",
    }


def load_questions(cases_path: str) -> list[dict]:
    """Load questions from cases.yaml."""
    with open(cases_path, "r", encoding="utf-8") as f:
        cases = yaml.safe_load(f)

    questions = []
    for i, case in enumerate(cases):
        q = case.get("vars", {}).get("user_input", "")
        desc = case.get("description", f"case-{i+1:03d}")
        cat = case.get("metadata", {}).get("category", "unknown")
        if q:
            questions.append({"index": i + 1, "description": desc, "question": q, "category": cat})
    return questions


def main():
    parser = argparse.ArgumentParser(description="GBase Bot Answer Rate Evaluation")
    parser.add_argument(
        "--bot-id",
        required=True,
        help="GBase bot (AI) ID (UUID)",
    )
    parser.add_argument(
        "--token",
        default=DEFAULT_TOKEN,
        help="GBase API token (default: env GBASE_API_TOKEN or built-in)",
    )
    parser.add_argument(
        "--cases",
        default=str(Path(__file__).parent / "cases.yaml"),
        help="Path to cases.yaml",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON path (default: results/eval-{bot_id_short}-{timestamp}.json)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of questions (0 = all)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between requests in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Per-question timeout in seconds (default: 60)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Number of concurrent requests (default: 1)",
    )
    args = parser.parse_args()

    # Load questions
    questions = load_questions(args.cases)
    if args.limit > 0:
        questions = questions[: args.limit]

    total = len(questions)
    print(f"Bot ID: {args.bot_id}")
    print(f"Questions: {total}")
    print(f"Delay: {args.delay}s | Timeout: {args.timeout}s")
    print("=" * 60)

    # Prepare output path
    if args.output:
        out_path = Path(args.output)
    else:
        results_dir = Path(__file__).parent / "results"
        results_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        short_id = args.bot_id[:8]
        out_path = results_dir / f"eval-{short_id}-{ts}.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Run evaluation
    results = []
    answered = 0
    unanswered = 0
    errors = 0
    reasons = {"empty": 0, "error": 0, "not_found": 0, "filler_only": 0, "answered": 0}
    source_stats = {"rag": 0, "faq": 0, "unknown": 0, "error": 0}
    category_stats = {}

    with httpx.Client(timeout=args.timeout) as client:
        for i, q in enumerate(questions):
            idx = q["index"]
            desc = q["description"]
            question = q["question"]
            cat = q["category"]

            # Progress
            pct = (i + 1) / total * 100
            sys.stdout.write(f"\r[{i+1}/{total}] ({pct:.0f}%) {desc}: {question[:30]}...")
            sys.stdout.flush()

            # Ask
            start_t = time.time()
            resp = ask_question(client, args.bot_id, args.token, question, args.timeout)
            elapsed = time.time() - start_t

            answer = resp["answer"]
            err = resp["error"]
            source = resp.get("source", "unknown")

            if err:
                is_unans = True
                reason = "error"
                errors += 1
            else:
                is_unans, reason = is_unanswered(answer)

            if is_unans:
                unanswered += 1
            else:
                answered += 1

            reasons[reason] = reasons.get(reason, 0) + 1
            source_stats[source] = source_stats.get(source, 0) + 1

            # Category stats
            if cat not in category_stats:
                category_stats[cat] = {"total": 0, "answered": 0, "unanswered": 0}
            category_stats[cat]["total"] += 1
            if is_unans:
                category_stats[cat]["unanswered"] += 1
            else:
                category_stats[cat]["answered"] += 1

            result = {
                "index": idx,
                "description": desc,
                "category": cat,
                "question": question,
                "answer": answer[:500],  # truncate for storage
                "answer_length": len(answer),
                "is_unanswered": is_unans,
                "reason": reason,
                "source": source,
                "message_id": resp["message_id"],
                "error": err,
                "elapsed_seconds": round(elapsed, 2),
            }
            results.append(result)

            # Status indicator
            mark = "X" if is_unans else "O"
            src_tag = f" [{source}]" if source != "rag" else ""
            sys.stdout.write(f" [{mark}] {reason}{src_tag} ({elapsed:.1f}s)\n")

            # Delay between requests
            if i < total - 1 and args.delay > 0:
                time.sleep(args.delay)

    # Summary
    answer_rate = answered / total * 100 if total > 0 else 0
    print("\n" + "=" * 60)
    print(f"RESULTS SUMMARY")
    print(f"=" * 60)
    print(f"Bot ID:       {args.bot_id}")
    print(f"Total:        {total}")
    print(f"Answered:     {answered} ({answer_rate:.1f}%)")
    print(f"Unanswered:   {unanswered} ({100-answer_rate:.1f}%)")
    print(f"  - empty:      {reasons.get('empty', 0)}")
    print(f"  - error:      {reasons.get('error', 0)}")
    print(f"  - not_found:  {reasons.get('not_found', 0)}")
    print(f"  - filler:     {reasons.get('filler_only', 0)}")
    print()
    print("Answer Source:")
    print(f"  RAG:  {source_stats.get('rag', 0)}")
    print(f"  FAQ:  {source_stats.get('faq', 0)}")
    print()
    print("Category Breakdown:")
    for cat, stats in sorted(category_stats.items()):
        cat_rate = stats["answered"] / stats["total"] * 100 if stats["total"] > 0 else 0
        print(f"  {cat:20s}: {stats['answered']}/{stats['total']} ({cat_rate:.1f}%)")

    # Save results
    output_data = {
        "meta": {
            "bot_id": args.bot_id,
            "timestamp": datetime.now().isoformat(),
            "total_questions": total,
            "cases_file": str(args.cases),
        },
        "summary": {
            "answered": answered,
            "unanswered": unanswered,
            "answer_rate": round(answer_rate, 2),
            "reasons": reasons,
            "source_stats": source_stats,
            "category_stats": category_stats,
        },
        "results": results,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"\nResults saved to: {out_path}")


if __name__ == "__main__":
    main()
