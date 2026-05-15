#!/usr/bin/env python3
"""
NEWoMan高輪 閉店店舗監視 + FAQ 残存検出
- newoman.jp/takanawa/newshop/ から「クローズショップ」を取得
- 前回検出済みリストとの差分を計算(初登場のみ通知)
- GBase API で FAQ 全件取得 → ローカル文字列マッチで残存 FAQ を抽出
- Lark Webhook で通知

使い方:
  python monitor.py \
      --dataset-id <UUID> \
      --token <GBASE_API_TOKEN> \
      --lark-webhook <URL> \
      --aliases-file data/shop-aliases.yaml \
      --state-file data/notified-shops.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
import yaml
from bs4 import BeautifulSoup


JST = timezone(timedelta(hours=9))
NEWOMAN_URL = "https://www.newoman.jp/takanawa/newshop/"
GBASE_API_BASE = "https://api.gbase.ai"


# ─────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────
@dataclass
class ClosedShop:
    name: str
    closed_date: str
    floor: str
    name_normalized: str = ""

    def __post_init__(self) -> None:
        if not self.name_normalized:
            self.name_normalized = normalize_name(self.name)


@dataclass
class FaqHit:
    faq_id: str
    question: str
    answer_excerpt: str
    matched_alias: str


@dataclass
class ShopReport:
    shop: ClosedShop
    hits: list[FaqHit] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# Normalization & alias expansion
# ─────────────────────────────────────────────────────────────────
def normalize_name(name: str) -> str:
    """全角→半角、大小文字、スペース・記号統一"""
    s = name.strip()
    # 全角英数 + 全角記号 → 半角
    s = s.translate(str.maketrans(
        "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz＆",
        "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz&",
    ))
    s = s.lower()
    # スペース・中点・ハイフン・記号除去
    s = re.sub(r"[\s　・·\-_/.\"'!&+:,()]", "", s)
    return s


def aliases_lookup(shop_name: str, aliases_dict: dict[str, list[str]]) -> list[str]:
    """正規化キーで alias 辞書を検索(全角半角・記号差を吸収)。"""
    target = normalize_name(shop_name)
    for k, v in aliases_dict.items():
        if normalize_name(k) == target:
            return list(v)
    return []


def load_aliases(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {k: list(v or []) for k, v in data.items()}


def build_search_keywords(shop_name: str, aliases_dict: dict[str, list[str]]) -> list[str]:
    """Return list of keyword variants to search for."""
    extras = aliases_lookup(shop_name, aliases_dict)
    auto: set[str] = set()
    for word in [shop_name, *extras]:
        if not word:
            continue
        auto.add(word)
        auto.add(word.lower())
        # remove leading "THE " / "ザ "
        stripped = re.sub(r"^(the\s+|ザ[\s・]?)", "", word, flags=re.IGNORECASE)
        if stripped != word:
            auto.add(stripped)
            auto.add(stripped.lower())
    return [k for k in auto if len(k) >= 3]  # 3 文字未満の誤マッチ除外


# ─────────────────────────────────────────────────────────────────
# Scraper
# ─────────────────────────────────────────────────────────────────
def fetch_closed_shops(url: str = NEWOMAN_URL) -> list[ClosedShop]:
    resp = requests.get(url, timeout=30, headers={
        "User-Agent": "Mozilla/5.0 (closed-shops-monitor; +github.com/Tina0529/newoman-reports)"
    })
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # NEWoMan のクローズセクション: <div class="newshop-block" id="close">
    container = soup.find("div", id="close")
    if container is None:
        return _fallback_extract(soup)

    shops: list[ClosedShop] = []
    for row in container.find_all("div", class_="newshop-tbl__tr"):
        day_div = row.find("div", class_="newshop-tbl__day")
        floor_div = row.find("div", class_="newshop-tbl__floor")
        shop_div = row.find("div", class_="newshop-tbl__shop")
        if not (day_div and floor_div and shop_div):
            continue

        date_raw = day_div.get_text(" ", strip=True)
        # "2026.05.06 CLOSE" → "2026.05.06"
        date_match = re.search(r"(20\d{2}[./\-]\d{1,2}[./\-]\d{1,2})", date_raw)
        if not date_match:
            continue

        floor = floor_div.get_text(" ", strip=True)
        name_div = shop_div.find("div", class_="txt01")
        if name_div is None:
            continue
        name = name_div.get_text(" ", strip=True)
        if not name:
            continue

        shops.append(ClosedShop(
            name=name,
            closed_date=_normalize_date(date_match.group(1)),
            floor=floor,
        ))

    return shops


def _fallback_extract(soup: BeautifulSoup) -> list[ClosedShop]:
    """Simpler regex-based extraction as a safety net."""
    text = soup.get_text("\n")
    pattern = re.compile(
        r"(20\d{2}[./\-]\d{1,2}[./\-]\d{1,2})\s+"
        r"((?:South|North|サウス|ノース)[\s・·]?\d+F?)\s+"
        r"([A-Za-z0-9 \-+&'!.,]+|[぀-ヿ一-鿿][^\n]+)",
        re.MULTILINE,
    )
    shops: list[ClosedShop] = []
    for m in pattern.finditer(text):
        shops.append(ClosedShop(
            name=m.group(3).strip(),
            closed_date=_normalize_date(m.group(1)),
            floor=m.group(2).strip(),
        ))
    return shops


def _normalize_date(s: str) -> str:
    s = s.replace(".", "-").replace("/", "-").strip()
    parts = s.split("-")
    if len(parts) == 3:
        y, m, d = parts
        return f"{y}-{int(m):02d}-{int(d):02d}"
    return s


# ─────────────────────────────────────────────────────────────────
# State management (notified-shops.json)
# ─────────────────────────────────────────────────────────────────
def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"last_updated": None, "notified_shops": []}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def filter_new_shops(current: list[ClosedShop], state: dict[str, Any]) -> list[ClosedShop]:
    notified_keys = {s["name_normalized"] for s in state.get("notified_shops", [])}
    return [s for s in current if s.name_normalized not in notified_keys]


# ─────────────────────────────────────────────────────────────────
# GBase FAQ fetcher
# ─────────────────────────────────────────────────────────────────
def fetch_all_faqs(
    dataset_id: str,
    token: str,
    page_size: int = 200,
    language: str | None = None,
) -> list[dict[str, Any]]:
    """Page through all FAQs in dataset.

    language: 'ja' などを指定すると GBase API の language フィルタを通す。
    """
    headers = {"Authorization": f"Bearer {token}"}
    all_faqs: list[dict[str, Any]] = []
    page = 1
    while True:
        url = f"{GBASE_API_BASE}/datasets/{dataset_id}/faqs"
        params: dict[str, Any] = {"page": page, "size": page_size, "exclude_tree_nodes": "true"}
        if language:
            params["language"] = language
        resp = requests.get(url, headers=headers, params=params, timeout=60)
        if resp.status_code != 200:
            sys.stderr.write(f"[FAQ fetch error page {page}] {resp.status_code} {resp.text[:200]}\n")
            resp.raise_for_status()
        body = resp.json()
        items = _extract_items(body)
        if not items:
            break
        all_faqs.extend(items)
        # pagination guard
        total = body.get("total") or body.get("count")
        if total is not None and len(all_faqs) >= total:
            break
        if len(items) < page_size:
            break
        page += 1
        if page > 200:  # 40,000 件で打ち切り
            sys.stderr.write("[WARN] FAQ pagination cap reached at page 200\n")
            break
        time.sleep(0.2)  # rate-limit safe
    return all_faqs


def _extract_items(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("items", "data", "results", "faqs"):
            if isinstance(body.get(key), list):
                return body[key]
    return []


def fetch_faq_detail(faq_id: str, token: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GBASE_API_BASE}/datasets/faqs/detailed/{faq_id}"
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code != 200:
        return {}
    return resp.json() or {}


def faq_qa_text(faq: dict[str, Any], token: str | None = None) -> tuple[str, str]:
    """Return (question, answer) strings, fetching detail if needed."""
    q = faq.get("question") or faq.get("title") or ""
    a = faq.get("answer") or faq.get("content") or faq.get("response") or ""
    if (not q or not a) and token and faq.get("id"):
        detail = fetch_faq_detail(faq["id"], token)
        q = q or detail.get("question") or detail.get("title") or ""
        a = a or detail.get("answer") or detail.get("content") or ""
    return str(q), str(a)


# ─────────────────────────────────────────────────────────────────
# Local matching
# ─────────────────────────────────────────────────────────────────
def search_faq_hits(
    shop: ClosedShop,
    aliases_dict: dict[str, list[str]],
    all_faqs: list[dict[str, Any]],
    token: str | None,
    japanese_only: bool = True,
) -> list[FaqHit]:
    keywords = build_search_keywords(shop.name, aliases_dict)
    hits: list[FaqHit] = []
    seen_ids: set[str] = set()

    for faq in all_faqs:
        faq_id = str(faq.get("id") or faq.get("faq_id") or "")
        if not faq_id or faq_id in seen_ids:
            continue
        q, a = faq_qa_text(faq, token=token)

        # 日本語のみ対象 - 方案 B:
        # API に language タグがあれば 100% 信頼(中身が英語でも ja タグなら通す)
        # language タグが無い場合のみ文字種で兜底判定
        if japanese_only:
            api_lang = faq_language_tag(faq)
            if api_lang is not None:
                if not api_lang.startswith("ja"):
                    continue
            else:
                if not (is_japanese_text(q) or is_japanese_text(a)):
                    continue

        haystack = f"{q}\n{a}".lower()
        matched = next((kw for kw in keywords if kw.lower() in haystack), None)
        if matched:
            hits.append(FaqHit(
                faq_id=faq_id,
                question=q[:120],
                answer_excerpt=_excerpt_around(a, matched, span=80),
                matched_alias=matched,
            ))
            seen_ids.add(faq_id)
    return hits


_JP_CHAR_RE = re.compile(r"[぀-ヿ぀-ゟ゠-ヿ㐀-䶿一-鿿]")
_LANG_FIELD_KEYS = ("language", "lang", "language_code", "languageCode", "locale")


def is_japanese_text(text: str, min_chars: int = 3) -> bool:
    """日本語(ひらがな・カタカナ・漢字)を min_chars 以上含む場合 True。"""
    if not text:
        return False
    return len(_JP_CHAR_RE.findall(text)) >= min_chars


def faq_language_tag(faq: dict[str, Any]) -> str | None:
    """API レスポンスの language タグを返す(無ければ None)。"""
    for key in _LANG_FIELD_KEYS:
        v = faq.get(key)
        if v:
            return str(v).strip().lower()
    return None


def _excerpt_around(text: str, keyword: str, span: int = 80) -> str:
    if not text:
        return ""
    idx = text.lower().find(keyword.lower())
    if idx < 0:
        return text[: span * 2]
    start = max(0, idx - span)
    end = min(len(text), idx + len(keyword) + span)
    snippet = text[start:end].replace("\n", " ")
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{snippet}{suffix}"


# ─────────────────────────────────────────────────────────────────
# Lark notification
# ─────────────────────────────────────────────────────────────────
def notify_lark(webhook: str, payload: dict[str, Any]) -> bool:
    if not webhook:
        sys.stderr.write("[WARN] LARK_WEBHOOK_URL not set, skipping notification\n")
        return False
    resp = requests.post(webhook, json=payload, timeout=15)
    ok = resp.status_code == 200 and resp.json().get("code") in (0, None)
    if not ok:
        sys.stderr.write(f"[Lark error] {resp.status_code} {resp.text[:300]}\n")
    return ok


def card_no_change(total_closed: int, run_at: str) -> dict[str, Any]:
    return _lark_card(
        header_title="✅ [ニュウマン高輪] 閉店店舗監視 - 異常なし",
        header_color="green",
        body=(
            f"📅 実行日時: **{run_at}**\n"
            f"🏪 公式サイトの閉店リスト総数: **{total_closed} 件**\n"
            f"🆕 新規追加: **0 件**\n\n"
            "🔄 監視は正常稼働中です"
        ),
    )


def card_detection(reports: list[ShopReport], run_at: str, dataset_id: str) -> dict[str, Any]:
    n_total = len(reports)
    n_with_hits = sum(1 for r in reports if r.hits)
    n_zero = n_total - n_with_hits

    lines = [
        f"📅 検出日時: **{run_at}**",
        f"🏪 新規閉店店舗: **{n_total} 件** (FAQ ヒットあり {n_with_hits} / 0 件 {n_zero})",
        "",
    ]
    for i, rep in enumerate(reports, 1):
        s = rep.shop
        lines.append(f"**{i}. {s.name}**  (閉店日: {s.closed_date}、{s.floor})")
        if not rep.hits:
            lines.append("   └ FAQ ヒット: **0 件** ✅ 削除作業不要")
            lines.append("   └ ⚠️ 別名・カナ表記漏れがないか念のためご確認ください")
        else:
            lines.append(f"   └ FAQ ヒット: **{len(rep.hits)} 件**")
            for h in rep.hits[:5]:
                lines.append(f"      • Q: {h.question}  〔matched: {h.matched_alias}〕")
            if len(rep.hits) > 5:
                lines.append(f"      …他 {len(rep.hits) - 5} 件")
        lines.append("")

    lines.append("---")
    lines.append("👉 確認後、対応をお願いします:")
    lines.append(f"   • GBase 管理画面: <https://gbase.ai/datasets/{dataset_id}/faqs>")
    lines.append("   • 閉店店舗一覧: <https://www.newoman.jp/takanawa/newshop/#close>")

    color = "red" if n_with_hits else "yellow"
    title = (
        "🚨 [ニュウマン高輪] 新規閉店店舗の FAQ ヒット通知"
        if n_with_hits
        else "ℹ️ [ニュウマン高輪] 新規閉店店舗あり(FAQ ヒットなし)"
    )
    return _lark_card(header_title=title, header_color=color, body="\n".join(lines))


def card_error(error: str, run_at: str) -> dict[str, Any]:
    return _lark_card(
        header_title="❌ [ニュウマン高輪] 閉店店舗監視 - エラー",
        header_color="red",
        body=f"📅 {run_at}\n\n```\n{error[:1500]}\n```",
    )


def _lark_card(header_title: str, header_color: str, body: str) -> dict[str, Any]:
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": header_color,
                "title": {"tag": "plain_text", "content": header_title},
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": body}},
            ],
        },
    }


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-id", default=os.getenv("GBASE_DATASET_ID"))
    parser.add_argument("--token", default=os.getenv("GBASE_API_TOKEN"))
    parser.add_argument("--lark-webhook", default=os.getenv("LARK_WEBHOOK_URL"))
    parser.add_argument("--aliases-file", default="skill/closed-shops-monitor/data/shop-aliases.yaml")
    parser.add_argument("--state-file", default="skill/closed-shops-monitor/data/notified-shops.json")
    parser.add_argument("--dry-run", action="store_true", help="Skip Lark notify and state save")
    parser.add_argument("--force-notify-all", action="store_true",
                        help="Notify all currently closed shops (ignore state)")
    parser.add_argument("--language", default="ja",
                        help="FAQ 言語フィルタ(default: ja)。'all' で多言語対象")
    args = parser.parse_args()

    if not args.dataset_id or not args.token:
        print("ERROR: --dataset-id and --token (or env GBASE_DATASET_ID/GBASE_API_TOKEN) required",
              file=sys.stderr)
        return 2

    aliases_path = Path(args.aliases_file)
    state_path = Path(args.state_file)
    run_at = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")

    try:
        print(f"[1/5] Scraping {NEWOMAN_URL} ...", flush=True)
        current_shops = fetch_closed_shops()
        print(f"      → {len(current_shops)} closed shops found")

        print("[2/5] Loading state ...", flush=True)
        state = load_state(state_path)
        new_shops = current_shops if args.force_notify_all else filter_new_shops(current_shops, state)
        print(f"      → {len(new_shops)} NEW shops to process")

        if not new_shops:
            print("[3/5] No new shops, sending heartbeat ...", flush=True)
            payload = card_no_change(len(current_shops), run_at)
            if not args.dry_run:
                notify_lark(args.lark_webhook, payload)
            else:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

        print(f"[3/5] Loading aliases & fetching FAQs (language={args.language}) ...", flush=True)
        aliases_dict = load_aliases(aliases_path)
        api_lang = None if args.language == "all" else args.language
        all_faqs = fetch_all_faqs(args.dataset_id, args.token, language=api_lang)
        print(f"      → {len(all_faqs)} FAQs fetched, {len(aliases_dict)} alias entries loaded")

        print("[4/5] Matching FAQs locally ...", flush=True)
        japanese_only = args.language == "ja"
        reports: list[ShopReport] = []
        for shop in new_shops:
            hits = search_faq_hits(shop, aliases_dict, all_faqs,
                                   token=args.token, japanese_only=japanese_only)
            reports.append(ShopReport(shop=shop, hits=hits))
            print(f"      • {shop.name}: {len(hits)} hit(s)")

        print("[5/5] Sending Lark notification ...", flush=True)
        payload = card_detection(reports, run_at, args.dataset_id)
        if args.dry_run:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            notify_lark(args.lark_webhook, payload)

            # Update state
            state["last_updated"] = datetime.now(JST).isoformat()
            for rep in reports:
                state.setdefault("notified_shops", []).append({
                    "name": rep.shop.name,
                    "name_normalized": rep.shop.name_normalized,
                    "closed_date": rep.shop.closed_date,
                    "floor": rep.shop.floor,
                    "first_notified_at": state["last_updated"],
                    "faq_hit_count": len(rep.hits),
                    "faq_ids_at_detection": [h.faq_id for h in rep.hits],
                    "status": "pending_confirmation" if rep.hits else "no_action_needed",
                })
            save_state(state_path, state)
            print(f"      → state saved to {state_path}")

        return 0

    except Exception as e:  # pragma: no cover
        import traceback
        err = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"
        sys.stderr.write(err + "\n")
        if not args.dry_run:
            notify_lark(args.lark_webhook, card_error(err, run_at))
        return 1


if __name__ == "__main__":
    sys.exit(main())
