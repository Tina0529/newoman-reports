#!/usr/bin/env python3
"""
Generate a self-contained comparison HTML report from two eval JSON files.

Reads the template from templates/comparison.html, injects bot metadata and
JSON data inline so the output HTML requires no external data files.

Usage:
  python gen_report.py \
    --bot1-json eval-fa228b57-xxx.json \
    --bot2-json eval-b50d5b21-xxx.json \
    --output docs/bot-eval/index.html
"""

import argparse
import json
import re
import sys
from pathlib import Path


TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "comparison.html"


def main():
    p = argparse.ArgumentParser(description="Generate bot comparison HTML report")
    p.add_argument("--bot1-json", required=True, help="Path to Bot 1 eval JSON")
    p.add_argument("--bot2-json", required=True, help="Path to Bot 2 eval JSON")
    p.add_argument("--bot1-name", default="NEWoMan高輪 検証環境")
    p.add_argument("--bot1-model", default="Claude Sonnet 4.5")
    p.add_argument("--bot1-short", default="検証環境")
    p.add_argument("--bot2-name", default="NEWoMan高輪 正式環境")
    p.add_argument("--bot2-model", default="Gemini 2.5 Flash")
    p.add_argument("--bot2-short", default="正式環境")
    p.add_argument("--output", default=None, help="Output HTML path (default: stdout)")
    args = p.parse_args()

    # Load eval JSONs
    with open(args.bot1_json, "r", encoding="utf-8") as f:
        bot1_data = json.load(f)
    with open(args.bot2_json, "r", encoding="utf-8") as f:
        bot2_data = json.load(f)

    bot1_id = bot1_data["meta"]["bot_id"]
    bot2_id = bot2_data["meta"]["bot_id"]

    # Read template
    if not TEMPLATE_PATH.exists():
        print(f"ERROR: Template not found at {TEMPLATE_PATH}", file=sys.stderr)
        sys.exit(1)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    # === Inject bot metadata ===
    # Replace bot card contents
    template = template.replace(
        "NEWoMan高輪 検証環境</div>\n"
        '      <div class="bot-model">Model: Claude Sonnet 4.5</div>\n'
        f'      <div class="bot-id">ID: fa228b57-59e1-447b-87e2-02c494195961</div>',
        f"{args.bot1_name}</div>\n"
        f'      <div class="bot-model">Model: {args.bot1_model}</div>\n'
        f'      <div class="bot-id">ID: {bot1_id}</div>',
    )
    template = template.replace(
        "NEWoMan高輪 正式環境</div>\n"
        '      <div class="bot-model">Model: Gemini 2.5 Flash</div>\n'
        f'      <div class="bot-id">ID: b50d5b21-262a-4802-a8c4-512af224c72f</div>',
        f"{args.bot2_name}</div>\n"
        f'      <div class="bot-model">Model: {args.bot2_model}</div>\n'
        f'      <div class="bot-id">ID: {bot2_id}</div>',
    )

    # Replace short names in JS
    template = template.replace(
        "const BOT1_SHORT='検証環境',BOT2_SHORT='正式環境';",
        f"const BOT1_SHORT='{args.bot1_short}',BOT2_SHORT='{args.bot2_short}';",
    )

    # Replace table header short names
    template = template.replace(
        '<th>検証環境<br><span style="font-weight:400;opacity:.6">Sonnet4.5</span></th>',
        f'<th>{args.bot1_short}<br><span style="font-weight:400;opacity:.6">{args.bot1_model}</span></th>',
    )
    template = template.replace(
        '<th>正式環境<br><span style="font-weight:400;opacity:.6">Gemini2.5Flash</span></th>',
        f'<th>{args.bot2_short}<br><span style="font-weight:400;opacity:.6">{args.bot2_model}</span></th>',
    )

    # === Inject data inline ===
    # Replace the async fetch-based loadData with inline data
    bot1_json_str = json.dumps(bot1_data, ensure_ascii=False)
    bot2_json_str = json.dumps(bot2_data, ensure_ascii=False)

    # Find and replace the entire loadData function (multi-line, ends with lone "}")
    old_load = re.search(
        r"async function loadData\(\)\{.*?\n\}",
        template,
        re.DOTALL,
    )
    if old_load:
        template = template.replace(
            old_load.group(0),
            f"function loadData(){{BOT1={bot1_json_str};BOT2={bot2_json_str};return true}}",
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
        print(f"  Questions: {len(bot1_data['results'])}")
    else:
        sys.stdout.write(template)


if __name__ == "__main__":
    main()
