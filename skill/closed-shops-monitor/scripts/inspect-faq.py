#!/usr/bin/env python3
"""
FAQ 個別調査ツール - 検出漏れの原因分析

使い方:
  python inspect-faq.py <faq_id> [--shop-name "<期待した店舗名>"]

出力:
  1. FAQ の question / answer 全文
  2. language フィールド値
  3. 期待した店舗名のキーワードがマッチするか診断
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

import requests
import yaml


GBASE_API_BASE = "https://api.gbase.ai"


# lookup-faq.py からコピーした関連関数
def normalize_name(name: str) -> str:
    s = name.strip()
    s = s.translate(str.maketrans(
        "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz＆",
        "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz&",
    ))
    s = s.lower()
    s = re.sub(r"[\s　・·\-_/.\"'!&+:,()]", "", s)
    return s


def aliases_lookup(shop_name: str, aliases_dict: dict[str, list[str]]) -> list[str]:
    target = normalize_name(shop_name)
    for k, v in aliases_dict.items():
        if normalize_name(k) == target:
            return list(v)
    return []


def build_search_keywords(shop_name: str, aliases_dict: dict[str, list[str]]) -> list[str]:
    extras = aliases_lookup(shop_name, aliases_dict)
    auto: set[str] = set()
    for word in [shop_name, *extras]:
        if not word:
            continue
        auto.add(word)
        auto.add(word.lower())
        stripped = re.sub(r"^(the\s+|ザ[\s・]?)", "", word, flags=re.IGNORECASE)
        if stripped != word:
            auto.add(stripped)
            auto.add(stripped.lower())
    return [k for k in auto if len(k) >= 3]


def load_aliases(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {k: list(v or []) for k, v in data.items()}


_JP_CHAR_RE = re.compile(r"[぀-ヿ぀-ゟ゠-ヿ㐀-䶿一-鿿]")


def is_japanese_text(text: str, min_chars: int = 3) -> bool:
    if not text:
        return False
    return len(_JP_CHAR_RE.findall(text)) >= min_chars


# ─────────────────────────────────────────────────────────────────
# Inspect logic
# ─────────────────────────────────────────────────────────────────
def fetch_faq_detail(faq_id: str, token: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GBASE_API_BASE}/datasets/faqs/detailed/{faq_id}"
    resp = requests.get(url, headers=headers, timeout=30)
    print(f"[API] GET {url}")
    print(f"[API] status={resp.status_code}")
    if resp.status_code != 200:
        print(f"[API ERROR] body: {resp.text[:500]}")
        return {}
    return resp.json() or {}


def search_in_dataset(dataset_id: str, faq_id: str, token: str) -> dict[str, Any] | None:
    """search-list API で faq_id を逆引き(detailed が動かない場合の fallback)。"""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GBASE_API_BASE}/datasets/{dataset_id}/faqs/search-list"
    body = {"query": faq_id, "size": 5}
    resp = requests.post(url, headers=headers, json=body, timeout=30)
    if resp.status_code != 200:
        return None
    data = resp.json()
    items = data if isinstance(data, list) else data.get("items") or data.get("data") or []
    for it in items:
        if str(it.get("id") or it.get("faq_id")) == faq_id:
            return it
    return None


def fetch_via_list_pages(dataset_id: str, faq_id: str, token: str, language: str | None = None) -> dict[str, Any] | None:
    """list API を全ページ走査して faq_id を探す(最終手段)。"""
    headers = {"Authorization": f"Bearer {token}"}
    page = 1
    while page <= 200:
        url = f"{GBASE_API_BASE}/datasets/{dataset_id}/faqs"
        params: dict[str, Any] = {"page": page, "size": 200, "exclude_tree_nodes": "true"}
        if language:
            params["language"] = language
        resp = requests.get(url, headers=headers, params=params, timeout=60)
        if resp.status_code != 200:
            return None
        body = resp.json()
        items = body if isinstance(body, list) else body.get("items") or body.get("data") or []
        if not items:
            return None
        for it in items:
            if str(it.get("id") or it.get("faq_id")) == faq_id:
                print(f"[INFO] Found in list page={page} (language={language})")
                return it
        if len(items) < 200:
            return None
        page += 1
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("faq_id")
    parser.add_argument("--shop-name", default="\"+Base 0\"　Johnny Depp: A Bunch Of Stuff",
                        help="期待した店舗名(キーワード診断用)")
    parser.add_argument("--dataset-id", default=os.getenv("GBASE_DATASET_ID"))
    parser.add_argument("--token", default=os.getenv("GBASE_API_TOKEN"))
    parser.add_argument("--aliases-file", default="skill/closed-shops-monitor/data/shop-aliases.yaml")
    args = parser.parse_args()

    if not args.token or not args.dataset_id:
        print("ERROR: env GBASE_DATASET_ID and GBASE_API_TOKEN required", file=sys.stderr)
        return 2

    print("=" * 70)
    print(f"FAQ INSPECT: {args.faq_id}")
    print("=" * 70)

    # Step 1: detailed API
    print("\n[Step 1] fetch_faq_detail (GET /datasets/faqs/detailed/{id})")
    print("-" * 70)
    faq = fetch_faq_detail(args.faq_id, args.token)

    # Step 2: fallback - list scan with language=ja
    if not faq:
        print("\n[Step 2] Fallback: scan list pages (language=ja)")
        print("-" * 70)
        faq = fetch_via_list_pages(args.dataset_id, args.faq_id, args.token, language="ja")

    # Step 3: fallback - all languages
    if not faq:
        print("\n[Step 3] Fallback: scan list pages (no language filter)")
        print("-" * 70)
        faq = fetch_via_list_pages(args.dataset_id, args.faq_id, args.token)

    if not faq:
        print(f"\n❌ FAQ {args.faq_id} not found in any way. May be already deleted.")
        return 1

    # Display content
    print("\n" + "=" * 70)
    print("📋 FAQ CONTENT")
    print("=" * 70)
    print(f"\nAll fields:")
    for k, v in faq.items():
        if isinstance(v, str) and len(v) > 200:
            print(f"  {k}: {v[:200]}...(truncated, total {len(v)} chars)")
        else:
            print(f"  {k}: {v}")

    q = str(faq.get("question") or faq.get("title") or "")
    a = str(faq.get("answer") or faq.get("content") or faq.get("response") or "")
    lang = faq.get("language") or faq.get("lang") or faq.get("language_code") or "(not set)"

    print(f"\n📝 Question:\n  {q}")
    print(f"\n📝 Answer (full):\n  {a}")
    print(f"\n🌐 Language field: {lang}")
    print(f"🌐 is_japanese_text(Q): {is_japanese_text(q)}")
    print(f"🌐 is_japanese_text(A): {is_japanese_text(a)}")
    print(f"🌐 JP chars in Q: {len(_JP_CHAR_RE.findall(q))}")
    print(f"🌐 JP chars in A: {len(_JP_CHAR_RE.findall(a))}")

    # Keyword diagnosis
    print("\n" + "=" * 70)
    print("🔍 KEYWORD MATCH DIAGNOSIS")
    print("=" * 70)
    aliases = load_aliases(Path(args.aliases_file))
    keywords = build_search_keywords(args.shop_name, aliases)
    print(f"\nExpected shop name: {args.shop_name!r}")
    print(f"Expanded keywords ({len(keywords)} 件):")
    for k in sorted(keywords):
        print(f"  - {k!r}")

    haystack = f"{q}\n{a}".lower()
    print(f"\nMatch test (case-insensitive substring match):")
    any_match = False
    for kw in sorted(keywords):
        hit = kw.lower() in haystack
        marker = "✅" if hit else "❌"
        print(f"  {marker} {kw!r}")
        if hit:
            any_match = True

    print("\n" + "=" * 70)
    print("🩺 DIAGNOSIS RESULT")
    print("=" * 70)
    if any_match:
        if is_japanese_text(q) or is_japanese_text(a):
            print("✅ Should HAVE been detected. Possibly FAQ is in dataset but not in language=ja list.")
        else:
            print("⚠️  Keyword matches but FAQ has no Japanese text → filtered out by is_japanese_text().")
            print("    監視は日本語のみのため除外されました。")
    else:
        print("❌ No keyword matched. Reasons might be:")
        print("    1. FAQ uses a different name/spelling (need to add to shop-aliases.yaml)")
        print("    2. FAQ is too generic (e.g., '芸術展について' without naming the artist)")
        print(f"    Keywords tried: {sorted(keywords)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
