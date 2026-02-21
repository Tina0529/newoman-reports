#!/usr/bin/env python3
"""
Generate a self-contained comparison HTML report from eval JSON files.

Supports single-round (legacy) and multi-round modes.

Single-round (legacy):
  python gen_report.py \
    --bot1-json eval-fa228b57-xxx.json \
    --bot2-json eval-b50d5b21-xxx.json \
    --output docs/bot-eval/index.html

Multi-round:
  python gen_report.py \
    --round "第1回:2026-02-20:eval-fa228b57-R1.json:eval-b50d5b21-R1.json" \
    --round "第2回:2026-02-28:eval-fa228b57-R2.json:eval-b50d5b21-R2.json" \
    --output docs/bot-eval/index.html
"""

import argparse
import json
import re
import sys
from pathlib import Path


TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "comparison.html"


def parse_round_arg(s):
    """Parse a --round argument: 'label:date:bot1json:bot2json'"""
    parts = s.split(":")
    if len(parts) < 4:
        print(f"ERROR: --round format must be 'label:date:bot1json:bot2json', got: {s}", file=sys.stderr)
        sys.exit(1)
    # Rejoin in case path contains colons (unlikely but safe)
    label, date = parts[0], parts[1]
    # Find the split point - date is YYYY-MM-DD format, rest are file paths
    # Actually paths could have colons on Windows, but this is Mac/Linux
    bot1_path = parts[2]
    bot2_path = ":".join(parts[3:])
    return {"label": label, "date": date, "bot1_path": bot1_path, "bot2_path": bot2_path}


def main():
    p = argparse.ArgumentParser(description="Generate bot comparison HTML report")
    # Multi-round mode
    p.add_argument("--round", action="append", dest="rounds", default=[],
                   help="Round spec: 'label:date:bot1json:bot2json' (repeatable)")
    # Legacy single-round mode
    p.add_argument("--bot1-json", default=None, help="Path to Bot 1 eval JSON (legacy)")
    p.add_argument("--bot2-json", default=None, help="Path to Bot 2 eval JSON (legacy)")
    # Bot metadata (shared across all rounds)
    p.add_argument("--bot1-name", default="NEWoMan高輪 検証環境")
    p.add_argument("--bot1-model", default="Claude Sonnet 4.5")
    p.add_argument("--bot1-short", default="検証環境")
    p.add_argument("--bot2-name", default="NEWoMan高輪 本番環境")
    p.add_argument("--bot2-model", default="Gemini 2.5 Flash")
    p.add_argument("--bot2-short", default="本番環境")
    p.add_argument("--output", default=None, help="Output HTML path (default: stdout)")
    args = p.parse_args()

    # Build rounds list
    rounds = []
    if args.rounds:
        for r in args.rounds:
            spec = parse_round_arg(r)
            with open(spec["bot1_path"], "r", encoding="utf-8") as f:
                bot1_data = json.load(f)
            with open(spec["bot2_path"], "r", encoding="utf-8") as f:
                bot2_data = json.load(f)
            rounds.append({
                "label": spec["label"],
                "date": spec["date"],
                "bot1": bot1_data,
                "bot2": bot2_data,
            })
    elif args.bot1_json and args.bot2_json:
        # Legacy single-round mode
        with open(args.bot1_json, "r", encoding="utf-8") as f:
            bot1_data = json.load(f)
        with open(args.bot2_json, "r", encoding="utf-8") as f:
            bot2_data = json.load(f)
        date = bot1_data["meta"]["timestamp"][:10]
        rounds.append({
            "label": "第1回",
            "date": date,
            "bot1": bot1_data,
            "bot2": bot2_data,
        })
    else:
        print("ERROR: Provide either --round or --bot1-json/--bot2-json", file=sys.stderr)
        sys.exit(1)

    # Extract bot IDs from first round
    bot1_id = rounds[0]["bot1"]["meta"]["bot_id"]
    bot2_id = rounds[0]["bot2"]["meta"]["bot_id"]

    # Read template
    if not TEMPLATE_PATH.exists():
        print(f"ERROR: Template not found at {TEMPLATE_PATH}", file=sys.stderr)
        sys.exit(1)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    # === Inject bot metadata ===
    template = template.replace(
        "NEWoMan高輪 検証環境</div>\n"
        '      <div class="bot-model-tag">Claude Sonnet 4.5</div>\n'
        '      <div class="bot-id">ID: fa228b57-59e1-447b-87e2-02c494195961</div>',
        f"{args.bot1_name}</div>\n"
        f'      <div class="bot-model-tag">{args.bot1_model}</div>\n'
        f'      <div class="bot-id">ID: {bot1_id}</div>',
    )
    template = template.replace(
        "NEWoMan高輪 本番環境</div>\n"
        '      <div class="bot-model-tag">Gemini 2.5 Flash</div>\n'
        '      <div class="bot-id">ID: b50d5b21-262a-4802-a8c4-512af224c72f</div>',
        f"{args.bot2_name}</div>\n"
        f'      <div class="bot-model-tag">{args.bot2_model}</div>\n'
        f'      <div class="bot-id">ID: {bot2_id}</div>',
    )

    # Replace short names in JS
    template = template.replace(
        "const BOT1_SHORT='検証環境',BOT2_SHORT='本番環境';",
        f"const BOT1_SHORT='{args.bot1_short}',BOT2_SHORT='{args.bot2_short}';",
    )

    # Derive short model names for JS constants
    bot1_model_short = args.bot1_model.replace("Claude ", "")
    bot2_model_short = args.bot2_model
    template = template.replace(
        "const BOT1_MODEL='Sonnet 4.5',BOT2_MODEL='Gemini 2.5 Flash';",
        f"const BOT1_MODEL='{bot1_model_short}',BOT2_MODEL='{bot2_model_short}';",
    )

    # Replace table header short names
    template = template.replace(
        '<th>検証環境<br><span style="font-weight:400;opacity:.6">Sonnet 4.5</span></th>',
        f'<th>{args.bot1_short}<br><span style="font-weight:400;opacity:.6">{bot1_model_short}</span></th>',
    )
    template = template.replace(
        '<th>本番環境<br><span style="font-weight:400;opacity:.6">Gemini 2.5 Flash</span></th>',
        f'<th>{args.bot2_short}<br><span style="font-weight:400;opacity:.6">{bot2_model_short}</span></th>',
    )

    # === Inject data inline ===
    rounds_json = json.dumps(rounds, ensure_ascii=False)

    # Replace the loadData function
    old_load = re.search(
        r"async function loadData\(\)\{.*?\n\}",
        template,
        re.DOTALL,
    )
    if old_load:
        template = template.replace(
            old_load.group(0),
            f"function loadData(){{ROUNDS={rounds_json};return true}}",
        )

    # Replace async IIFE with sync call
    old_iife = re.search(
        r"\(async function\(\)\{.*?\}\)\(\);",
        template,
        re.DOTALL,
    )
    if old_iife:
        template = template.replace(
            old_iife.group(0),
            "(function(){var ok=loadData();if(!ok){document.querySelector('.container').innerHTML="
            "'<div style=\"text-align:center;padding:60px\"><h2>データ読み込みに失敗しました</h2></div>';"
            "return;}init()})();",
        )

    # Write output
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(template, encoding="utf-8")
        print(f"Report generated: {out_path}")
        print(f"  Bot 1: {args.bot1_name} ({args.bot1_model}) [{bot1_id}]")
        print(f"  Bot 2: {args.bot2_name} ({args.bot2_model}) [{bot2_id}]")
        print(f"  Rounds: {len(rounds)}")
        for i, r in enumerate(rounds):
            print(f"    {r['label']} ({r['date']}): {len(r['bot1']['results'])} questions")
    else:
        sys.stdout.write(template)


if __name__ == "__main__":
    main()
