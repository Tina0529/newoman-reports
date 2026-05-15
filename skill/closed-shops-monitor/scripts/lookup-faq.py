#!/usr/bin/env python3
"""
店舗名 → 関連 FAQ 検索ツール(担当者向け)

LUMINE から「◯◯店が閉店予定」と事前通知された際に使用。
全 10 言語の関連 FAQ を一括検出し、Lark 通知 + 任意で CSV 出力。

使い方:
  python lookup-faq.py "ZENB STORE & SANDWICH"
  python lookup-faq.py "davines" --csv /tmp/davines.csv
  python lookup-faq.py "hueLe Museum" --no-lark   # ローカル確認のみ
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import requests
import yaml


JST = timezone(timedelta(hours=9))
GBASE_API_BASE = "https://api.gbase.ai"


# ─────────────────────────────────────────────────────────────────
# 言語判定
# ─────────────────────────────────────────────────────────────────
LANGUAGE_LABELS = {
    "ja": "日本語",
    "en": "English",
    "zh": "中文",
    "zh-CHS": "中文簡体",
    "zh-CHT": "中文繁體",
    "zh-Hans": "中文簡体",
    "zh-Hant": "中文繁體",
    "ko": "한국어",
    "vi": "Tiếng Việt",
    "es": "Español",
    "pt": "Português",
    "th": "ไทย",
    "id": "Bahasa Indonesia",
    "hi": "हिन्दी",
    "ne": "नेपाली",
    "fr": "Français",
    "de": "Deutsch",
    "it": "Italiano",
    "ru": "Русский",
    "ar": "العربية",
    "unknown": "不明",
}

_RE_HIRAGANA_KATAKANA = re.compile(r"[぀-ヿ]")
_RE_CJK = re.compile(r"[一-鿿]")
_RE_HANGUL = re.compile(r"[가-힣]")
_RE_THAI = re.compile(r"[฀-๿]")
_RE_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_RE_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_RE_ARABIC = re.compile(r"[؀-ۿ]")
_RE_VIETNAMESE_CHARS = re.compile(r"[ăâđêôơưĂÂĐÊÔƠƯạảấầẩẫậắằẳẵặẹẻẽếềểễệỉĩịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]")
_RE_SPANISH_CHARS = re.compile(r"[ñÑ¿¡áéíóúüÁÉÍÓÚÜ]")
_RE_PORTUGUESE_CHARS = re.compile(r"[ãõâêôáéíóúçÃÕÂÊÔÁÉÍÓÚÇ]")


def detect_language_from_text(text: str) -> str:
    """文字種から言語を推定(API に language フィールドが無い場合の fallback)。"""
    if not text:
        return "unknown"

    # 高優先度: スクリプト依存の文字
    if _RE_HIRAGANA_KATAKANA.search(text):
        return "ja"
    if _RE_HANGUL.search(text):
        return "ko"
    if _RE_THAI.search(text):
        return "th"
    if _RE_DEVANAGARI.search(text):
        # ヒンディーとネパール語の判別は語彙レベルで困難 → デフォルト hi
        return "hi"
    if _RE_CYRILLIC.search(text):
        return "ru"
    if _RE_ARABIC.search(text):
        return "ar"

    # 中文 vs その他: 漢字のみ含み、平仮名/片仮名なし
    if _RE_CJK.search(text):
        return "zh"

    # ベトナム語の特殊文字
    if _RE_VIETNAMESE_CHARS.search(text):
        return "vi"

    # スペイン/ポルトガル: 特殊文字で判別
    has_spanish = bool(_RE_SPANISH_CHARS.search(text))
    has_portuguese = bool(_RE_PORTUGUESE_CHARS.search(text))
    if has_portuguese and not has_spanish:
        return "pt"
    if has_spanish:
        return "es"

    # 残りは英語と仮定
    if re.search(r"[A-Za-z]", text):
        return "en"

    return "unknown"


def get_faq_language(faq: dict[str, Any]) -> str:
    """API レスポンスから言語コードを取得。フィールド名揺れに対応。"""
    for key in ("language", "lang", "language_code", "languageCode", "locale"):
        v = faq.get(key)
        if v:
            return str(v).strip()
    # API に無い場合 → 文字種推定(question を主に使う)
    q = str(faq.get("question") or faq.get("title") or "")
    a = str(faq.get("answer") or faq.get("content") or "")
    return detect_language_from_text(q or a)


def language_label(code: str) -> str:
    return LANGUAGE_LABELS.get(code, code)


# ─────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────
@dataclass
class FaqHit:
    faq_id: str
    language: str
    question: str
    answer: str
    matched_keyword: str


# ─────────────────────────────────────────────────────────────────
# Normalization & alias expansion (monitor.py と同じロジック)
# ─────────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────
# GBase FAQ fetcher (全言語取得)
# ─────────────────────────────────────────────────────────────────
def fetch_all_faqs(dataset_id: str, token: str, page_size: int = 200) -> list[dict[str, Any]]:
    """全言語の FAQ を取得。"""
    headers = {"Authorization": f"Bearer {token}"}
    all_faqs: list[dict[str, Any]] = []
    page = 1
    while True:
        url = f"{GBASE_API_BASE}/datasets/{dataset_id}/faqs"
        params: dict[str, Any] = {"page": page, "size": page_size, "exclude_tree_nodes": "true"}
        resp = requests.get(url, headers=headers, params=params, timeout=60)
        resp.raise_for_status()
        body = resp.json()
        items = _extract_items(body)
        if not items:
            break
        all_faqs.extend(items)
        total = body.get("total") or body.get("count")
        if total is not None and len(all_faqs) >= total:
            break
        if len(items) < page_size:
            break
        page += 1
        if page > 200:
            break
        time.sleep(0.2)
    return all_faqs


def _extract_items(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("items", "data", "results", "faqs"):
            if isinstance(body.get(key), list):
                return body[key]
    return []


def faq_qa_text(faq: dict[str, Any]) -> tuple[str, str]:
    q = faq.get("question") or faq.get("title") or ""
    a = faq.get("answer") or faq.get("content") or faq.get("response") or ""
    return str(q), str(a)


# ─────────────────────────────────────────────────────────────────
# 検索
# ─────────────────────────────────────────────────────────────────
def search_all_languages(
    shop_name: str,
    aliases_dict: dict[str, list[str]],
    all_faqs: list[dict[str, Any]],
) -> list[FaqHit]:
    keywords = build_search_keywords(shop_name, aliases_dict)
    hits: list[FaqHit] = []
    seen_ids: set[str] = set()

    for faq in all_faqs:
        faq_id = str(faq.get("id") or faq.get("faq_id") or "")
        if not faq_id or faq_id in seen_ids:
            continue
        q, a = faq_qa_text(faq)
        haystack = f"{q}\n{a}".lower()
        matched = next((kw for kw in keywords if kw.lower() in haystack), None)
        if matched:
            hits.append(FaqHit(
                faq_id=faq_id,
                language=get_faq_language(faq),
                question=q,
                answer=a,
                matched_keyword=matched,
            ))
            seen_ids.add(faq_id)
    return hits


def group_by_language(hits: list[FaqHit]) -> dict[str, list[FaqHit]]:
    """言語コード → ヒット一覧。日本語が先頭、その他は件数降順。"""
    grouped: dict[str, list[FaqHit]] = {}
    for h in hits:
        grouped.setdefault(h.language, []).append(h)

    # 並び順: ja を先頭、その他は件数降順
    def sort_key(item: tuple[str, list[FaqHit]]) -> tuple[int, int, str]:
        code = item[0]
        return (0 if code == "ja" else 1, -len(item[1]), code)

    return dict(sorted(grouped.items(), key=sort_key))


# ─────────────────────────────────────────────────────────────────
# Lark notification
# ─────────────────────────────────────────────────────────────────
def build_lark_card(
    shop_name: str,
    keywords: list[str],
    grouped: dict[str, list[FaqHit]],
    run_at: str,
) -> dict[str, Any]:
    total = sum(len(v) for v in grouped.values())
    ja_hits = grouped.get("ja", [])

    # ヘッダー
    if total == 0:
        title = f"⚠️ [ニュウマン高輪] FAQ 事前調査 - 該当なし: {shop_name}"
        color = "yellow"
    else:
        title = f"🔍 [ニュウマン高輪] FAQ 事前調査結果: {shop_name}"
        color = "blue"

    elements: list[dict[str, Any]] = []

    # セクション 1: 検索条件
    cond_lines = [
        f"📅 **調査日時**: {run_at}",
        f"📌 **検索対象店舗**: `{shop_name}`",
        f"🔤 **検索キーワード** ({len(keywords)} 件):",
        "  " + "  /  ".join(f"`{k}`" for k in sorted(keywords)),
    ]
    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": "\n".join(cond_lines)},
    })

    # セクション 2: 言語別件数概要
    if total == 0:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    "🚨 **該当 FAQ が 1 件も見つかりませんでした。**\n\n"
                    "考えられる原因:\n"
                    "1. 店舗名のカナ表記等、別名が `shop-aliases.yaml` に未登録\n"
                    "2. 既に削除済み(過去の閉店店舗対応で清掃済み)\n"
                    "3. そもそも FAQ に登録されていない店舗"
                ),
            },
        })
        return _wrap_card(title, color, elements)

    elements.append({"tag": "hr"})
    summary_lines = [f"📊 **ヒット概要** (合計: **{total} 件**)\n"]
    for code, hits in grouped.items():
        label = language_label(code)
        marker = " ⭐ 詳細下記" if code == "ja" else ""
        summary_lines.append(f"  • `{code:8}` {label:14}: **{len(hits):3d}** 件{marker}")
    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": "\n".join(summary_lines)},
    })

    # セクション 3: 日本語版 詳細
    elements.append({"tag": "hr"})
    if not ja_hits:
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    "📝 **【日本語版 FAQ】**: **0 件**\n\n"
                    "⚠️ 日本語の FAQ には該当なし。他言語のみヒットしています。\n"
                    "別名辞書 `shop-aliases.yaml` への日本語表記追加を検討ください。"
                ),
            },
        })
    else:
        ja_header = f"📝 **【日本語版 FAQ 詳細】** ({len(ja_hits)} 件)"
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": ja_header},
        })

        for i, h in enumerate(ja_hits, 1):
            q_text = h.question.strip().replace("\n", " ")
            a_text = h.answer.strip().replace("\n", " ")
            if len(a_text) > 200:
                a_text = a_text[:200] + "…"
            content = (
                f"**[{i}/{len(ja_hits)}]**\n"
                f"  **Q**: {q_text}\n"
                f"  **A**: {a_text}\n"
                f"  〔matched: `{h.matched_keyword}`〕"
            )
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": content},
            })

    # セクション 4: 次のアクション
    elements.append({"tag": "hr"})
    action_text = (
        "💡 **次のアクション**\n"
        "  1. LUMINE 担当者と内容を確認\n"
        "  2. 削除 / 修正方針を決定\n"
        "  3. GBase 管理画面で該当言語版 FAQ を順次処理\n"
        f"  4. 全文 CSV が必要な場合: コマンドラインに `--csv` オプション追加\n\n"
        f"🔗 GBase 管理画面: <https://gbase.ai/datasets>"
    )
    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": action_text},
    })

    return _wrap_card(title, color, elements)


def _wrap_card(title: str, color: str, elements: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": color,
                "title": {"tag": "plain_text", "content": title},
            },
            "elements": elements,
        },
    }


def post_to_lark(webhook: str, payload: dict[str, Any]) -> bool:
    if not webhook:
        sys.stderr.write("[WARN] LARK_WEBHOOK_URL not set\n")
        return False
    resp = requests.post(webhook, json=payload, timeout=15)
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    ok = resp.status_code == 200 and body.get("code") in (0, None)
    if not ok:
        sys.stderr.write(f"[Lark error] {resp.status_code} {resp.text[:300]}\n")
    return ok


# ─────────────────────────────────────────────────────────────────
# CSV エクスポート
# ─────────────────────────────────────────────────────────────────
def write_csv(path: Path, hits: list[FaqHit], shop_name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "shop_name", "language_code", "language_label",
            "faq_id", "question", "answer", "matched_keyword",
        ])
        for h in hits:
            writer.writerow([
                shop_name,
                h.language,
                language_label(h.language),
                h.faq_id,
                h.question,
                h.answer,
                h.matched_keyword,
            ])


# ─────────────────────────────────────────────────────────────────
# Console preview
# ─────────────────────────────────────────────────────────────────
def print_console_preview(
    shop_name: str,
    keywords: list[str],
    grouped: dict[str, list[FaqHit]],
) -> None:
    total = sum(len(v) for v in grouped.values())
    print(f"\n🔍 検索: {shop_name!r}")
    print(f"検索キーワード ({len(keywords)} 件):")
    for k in sorted(keywords):
        print(f"  - {k!r}")
    print(f"\n📊 ヒット概要 (合計: {total} 件)")
    print("─" * 50)
    for code, hits in grouped.items():
        marker = " ⭐ ja" if code == "ja" else ""
        print(f"  {code:8} {language_label(code):14}: {len(hits):3d} 件{marker}")

    ja = grouped.get("ja", [])
    if ja:
        print("\n" + "─" * 50)
        print(f"【日本語版 FAQ 詳細】({len(ja)} 件)")
        print("─" * 50)
        for i, h in enumerate(ja, 1):
            print(f"\n[{i}/{len(ja)}]")
            print(f"  Q: {h.question}")
            ans = h.answer if len(h.answer) <= 300 else h.answer[:300] + "…"
            print(f"  A: {ans}")
            print(f"  matched: {h.matched_keyword}")


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="店舗名から関連 FAQ を検索")
    parser.add_argument("shop_name", help="店舗名(LUMINE 通知の表記そのまま)")
    parser.add_argument("--dataset-id", default=os.getenv("GBASE_DATASET_ID"))
    parser.add_argument("--token", default=os.getenv("GBASE_API_TOKEN"))
    parser.add_argument("--lark-webhook", default=os.getenv("LARK_WEBHOOK_URL"))
    parser.add_argument("--aliases-file", default="skill/closed-shops-monitor/data/shop-aliases.yaml")
    parser.add_argument("--csv", help="CSV エクスポートパス(全文・全言語)")
    parser.add_argument("--no-lark", action="store_true", help="Lark に送信しない(ローカル確認のみ)")
    args = parser.parse_args()

    if not args.dataset_id or not args.token:
        print("ERROR: --dataset-id と --token (or env) が必要", file=sys.stderr)
        return 2

    aliases_path = Path(args.aliases_file)
    run_at = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")

    print(f"[1/4] Loading aliases ...", flush=True)
    aliases_dict = load_aliases(aliases_path)
    keywords = build_search_keywords(args.shop_name, aliases_dict)
    print(f"      → {len(keywords)} keywords expanded")

    print(f"[2/4] Fetching all FAQs (all languages) ...", flush=True)
    all_faqs = fetch_all_faqs(args.dataset_id, args.token)
    print(f"      → {len(all_faqs)} FAQs fetched")

    print(f"[3/4] Searching ...", flush=True)
    hits = search_all_languages(args.shop_name, aliases_dict, all_faqs)
    grouped = group_by_language(hits)
    print(f"      → {len(hits)} total hits across {len(grouped)} languages")

    # コンソールプレビュー
    print_console_preview(args.shop_name, keywords, grouped)

    # CSV
    if args.csv:
        csv_path = Path(args.csv)
        write_csv(csv_path, hits, args.shop_name)
        print(f"\n💾 CSV exported: {csv_path}")

    # Lark
    if args.no_lark:
        print("\n⏭ Lark notification skipped (--no-lark)")
    else:
        print(f"\n[4/4] Sending Lark notification ...", flush=True)
        payload = build_lark_card(args.shop_name, keywords, grouped, run_at)
        if post_to_lark(args.lark_webhook, payload):
            print("      → Lark sent ✅")
        else:
            print("      → Lark FAILED ❌", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
