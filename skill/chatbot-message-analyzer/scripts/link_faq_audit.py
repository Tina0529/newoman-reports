#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
link_faq_audit.py — 月次レポート用の2モジュール

1) リンク監査  : bot 回答内の店舗リンク(?scd=)を最新「全ショップ情報一覧」と照合し、
                 scd 不一致 / 存在しない scd / 外部ドメイン幻覚候補を検出。
2) FAQ 期限監視: この dataset(=この bot) の全 FAQ を /datasets/{dataset_id}/faqs で取得し、
                 翌月までに期限切れになる会期・日付つき FAQ を抽出して一覧化。

いずれも GBase API モード(token + dataset_id) でのみ動作。CSV モードでは呼ばれない。
標準ライブラリのみ（urllib）。analyze.py から import して使う。

検証状況: 2026-06 に実データで検証済み。リンク監査=誤リンク率2.71%(709回答/823リンク)。
FAQ 期限監視=全FAQ 10750件(bot↔dataは1:1で他 bot 混入なし)を走査し過時イベント4件抽出。
"""
import json
import re
import time
import unicodedata
import urllib.request
import urllib.parse
import datetime


def _norm_name(s):
    """店名を正規化（全半角/大小文字/引用符/読みカッコ/記号差を吸収）。
    誤リンク判定の偽陽性（表記ゆれ）を防ぐ。"""
    s = unicodedata.normalize("NFKC", s or "")     # 全角→半角, ＝→=, 半角カナ→全角 等
    s = re.sub(r"[（(].*?[)）]", "", s)             # 読みガナ等のカッコを除去
    s = re.sub(r"[\"'`’“”、・,\s\-ー=&＋+|/]", "", s)  # 引用符/空白/区切り記号を除去
    return s.lower()

# ───────────────────────── 共通 HTTP ─────────────────────────

def _get(base_url, path, token, params=None, timeout=60):
    url = base_url.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _post(base_url, path, token, params=None, body=None, timeout=90):
    url = base_url.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body if body is not None else {}).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# ───────────────────── 1. リンク監査 ─────────────────────

# 外部ドメイン ホワイトリスト（幻覚ではなく正規リンク。誤検知を防ぐ）
LINK_DOMAIN_WHITELIST = {
    "www.newoman.jp", "newoman.jp",                      # 施設公式（floorguide 等）
    "prd-mygpt.s3.ap-northeast-1.amazonaws.com",          # FAQ 画像（立面図/地図）
    "platinumaps.jp",                                     # デジタルフロアガイド
    "www.lumine.ne.jp", "lumine.ne.jp",                  # LUMINE 公式
    "montakanawa.jp", "www.montakanawa.jp",              # TAKANAWA GATEWAY CITY 公式
}

_SCD_RE = re.compile(r"floorguide/detail/\?scd=(\d+)", re.I)
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
_BARE_URL_RE = re.compile(r"(?<!\()(https?://[^\s)\]\"']+)")

# 店名ではない汎用アンカー（これらは誤リンク判定の対象外）
_GENERIC_ANCHORS = {
    "", "こちら", "こちらから", "詳細", "詳細はこちら", "リンク", "リンクはこちら",
    "公式サイト", "公式ページ", "店舗情報", "店舗ページ", "フロアガイド",
    "デジタルフロアガイド", "地図", "マップ", "map", "here", "click here",
    "ウェブサイト", "サイト", "ホームページ", "詳しくはこちら", "店舗一覧",
}


def _host(u):
    try:
        return urllib.parse.urlparse(u).netloc.lower()
    except Exception:
        return "?"


def fetch_shop_ground_truth(base_url, token, dataset_id):
    """最新の「全ショップ情報一覧」ドキュメントを取得し、店名↔scd マップを返す。

    Returns dict: {filename, exported, shop_count, name2scd, scd2name, valid_scds}
    取得失敗時は None。
    """
    try:
        files = _get(base_url, f"/datasets/{dataset_id}/files", token,
                     {"size": 50, "file_type": "document", "order_by": "updated_at"}).get("items", [])
    except Exception as e:
        print(f"⚠️  ショップ一覧の取得に失敗: {e}")
        return None
    cand = [f for f in files if "全ショップ情報一覧" in (f.get("filename") or "")]
    if not cand:
        print("⚠️  「全ショップ情報一覧」ドキュメントが見つかりません")
        return None
    cand.sort(key=lambda f: f.get("updated_at", ""), reverse=True)
    gt = cand[0]

    # 全 chunk を取得して本文を復元
    texts, page = [], 1
    while True:
        try:
            r = _get(base_url, f"/datasets/{dataset_id}/files/{gt['id']}/chunks", token,
                     {"page": page, "size": 100})
        except Exception as e:
            print(f"⚠️  ショップ一覧 chunk 取得失敗: {e}")
            break
        texts += [c.get("text", "") for c in r.get("items", [])]
        if page >= r.get("pages", 1) or not r.get("items"):
            break
        page += 1
    text = "\n".join(texts)

    name2scd, scd2name = {}, {}
    for block in re.split(r"\n##\s+", text):
        mname = re.match(r"([^\n（(]+)", block.strip())
        mscd = re.search(r"SCDコード:\s*(\d{3,})", block)
        if mname and mscd:
            nm = mname.group(1).strip()
            scd = mscd.group(1)
            name2scd[nm] = scd
            scd2name[scd] = nm
    mcount = re.search(r"ショップ数:\s*(\d+)", text)
    mexport = re.search(r"導出時間:\s*([\d\-: ]+)", text)
    return {
        "filename": gt.get("filename"),
        "exported": (mexport.group(1).strip() if mexport else gt.get("updated_at", "")[:10]),
        "shop_count": int(mcount.group(1)) if mcount else len(scd2name),
        "name2scd": name2scd,
        "scd2name": scd2name,
        "valid_scds": set(scd2name.keys()),
    }


def audit_answer_links(records, gt):
    """回答リスト × ground truth でリンク監査。

    records: list of dict {date, question, answer}
    gt: fetch_shop_ground_truth() の戻り値
    Returns: 統計 dict（テンプレ注入用）
    """
    scd2name = gt["scd2name"]
    name2scd = gt["name2scd"]
    valid = gt["valid_scds"]
    # 正規化した店名→scd（確証できる誤リンクのみ検出するため）
    norm_name2scd = {}
    for _n, _s in name2scd.items():
        norm_name2scd[_norm_name(_n)] = _s

    total_floor = 0
    floor_ok = 0
    scd_invalid = []    # (店名, scd, date) — 存在しない scd
    scd_mismatch = []   # (店名, scd, 実際の店名, date) — 別店に誤リンク
    ext_domains = {}    # host -> count（ホワイトリスト除外後）
    ext_samples = []    # (anchor, url, date)
    ans_with_link = 0

    for rec in records:
        ans = rec.get("answer") or ""
        if not ans:
            continue
        pairs = list(_MD_LINK_RE.findall(ans))  # [(anchor,url)]
        md_urls = {u for _, u in pairs}
        for u in _BARE_URL_RE.findall(ans):
            if u not in md_urls:
                pairs.append(("", u))
        if pairs:
            ans_with_link += 1
        for anchor, url in pairs:
            h = _host(url)
            ms = _SCD_RE.search(url)
            if "newoman.jp" in h and ms:
                total_floor += 1
                scd = ms.group(1)
                if scd not in valid:
                    scd_invalid.append((anchor.strip(), scd, rec.get("date", "")))
                else:
                    gtname = scd2name[scd]
                    a = anchor.strip()
                    an = _norm_name(a)
                    gn = _norm_name(gtname)
                    # 汎用アンカー(こちら等) or 空 → 照合対象外
                    if a.lower() in _GENERIC_ANCHORS or not an:
                        floor_ok += 1
                    # 正規化して同一・包含 → 同店の表記ゆれ → OK
                    elif an == gn or an in gn or gn in an:
                        floor_ok += 1
                    # アンカーが一覧に実在する別店で、その正しい scd ≠ リンクの scd → 確証された誤リンク
                    elif an in norm_name2scd and norm_name2scd[an] != scd:
                        scd_mismatch.append((a, scd, gtname, rec.get("date", "")))
                    else:
                        # アンカー店名が一覧に無い（撤退/別名/英日対照など）→ 確証不可、誤検知回避のため OK 扱い
                        floor_ok += 1
            elif h in LINK_DOMAIN_WHITELIST:
                continue  # 正規リンク
            elif h and h != "?":
                ext_domains[h] = ext_domains.get(h, 0) + 1
                if len(ext_samples) < 30:
                    ext_samples.append((anchor.strip(), url, rec.get("date", "")))

    floor_err = len(scd_invalid) + len(scd_mismatch)
    return {
        "gt_filename": gt["filename"],
        "gt_exported": gt["exported"],
        "shop_count": gt["shop_count"],
        "answers_with_link": ans_with_link,
        "floor_total": total_floor,
        "floor_ok": floor_ok,
        "scd_invalid": scd_invalid,
        "scd_mismatch": scd_mismatch,
        "floor_error_count": floor_err,
        "floor_error_rate": (100.0 * floor_err / total_floor) if total_floor else 0.0,
        "ext_domain_count": sum(ext_domains.values()),
        "ext_domains": sorted(ext_domains.items(), key=lambda x: -x[1]),
        "ext_samples": ext_samples,
    }


# ───────────────────── 2. FAQ 期限監視 ─────────────────────

_JP_DATE_PATTERNS = [
    # (regex, parser) — マッチ → (year, month, day) を返す。年が無いものは year=None
    (re.compile(r"(20\d{2})[年/\-\.](\d{1,2})[月/\-\.](\d{1,2})日?"),
     lambda m: (int(m.group(1)), int(m.group(2)), int(m.group(3)))),
    (re.compile(r"(?<!\d)(\d{1,2})[月/](\d{1,2})日?"),
     lambda m: (None, int(m.group(1)), int(m.group(2)))),
]
# 会期・イベントを示唆するキーワード（営業時間や常設店の誤検知を避けるため活動系に限定）
_EXPIRY_HINT = re.compile(
    r"開催|会期|期間限定|フェア|POP[\s\-]?UP|ポップアップ|催事|開幕|イベント|"
    r"期間中|まで開催|まで開|までの期間|までの開催|フェスティバル|フェスタ|マルシェ")


def _extract_dates(text, ref_date):
    """text 中の日付を (year,month,day) で抽出。年が無い場合は ref_date 近傍で補完。"""
    found = []
    for rx, fn in _JP_DATE_PATTERNS:
        for m in rx.finditer(text):
            try:
                y, mo, d = fn(m)
            except Exception:
                continue
            if not (1 <= mo <= 12 and 1 <= d <= 31):
                continue
            if y is None:
                # 年補完: ref 年で作り、過去すぎるなら翌年
                y = ref_date.year
                try:
                    cand = datetime.date(y, mo, d)
                except ValueError:
                    continue
                if (ref_date - cand).days > 180:
                    y += 1
            try:
                found.append(datetime.date(y, mo, d))
            except ValueError:
                continue
    return found


def fetch_expiring_faqs(base_url, token, dataset_id, report_period_end, language="ja"):
    """翌月末までに期限切れになる会期・日付つき FAQ を抽出。

    dataset_id: 該当 bot の dataset（bot↔dataset は 1:1 なので、この dataset の FAQ
                がそのままこの bot の全 FAQ。他 bot の混入は無い）。
    report_period_end: datetime.date — レポート対象月の末日（例: 5月レポート→2026-05-31）
    判定窓: [今日, 翌月末]。窓内に切れる日付を含む & 会期ヒント語あり → 候補。
            既に過去日だが「開催予定」等が残っている FAQ も「過時残存」として別枠。
    Returns: dict {checked, next_month_label, expiring:[...], stale:[...]} / 取得失敗時 None
    """
    # 翌月末を計算
    y, m = report_period_end.year, report_period_end.month
    if m == 12:
        ny, nm = y + 1, 1
    else:
        ny, nm = y, m + 1
    # 翌月末日
    if nm == 12:
        nm_end = datetime.date(ny, 12, 31)
    else:
        nm_end = datetime.date(ny, nm + 1, 1) - datetime.timedelta(days=1)
    today = report_period_end  # レポート実行時点 ≒ 月末

    # この dataset(=この bot) の全 FAQ を取得（会期イベントは user_input=対話学習側にも入るため全件対象）
    faqs = _load_all_faqs(base_url, token, dataset_id, language)
    if faqs is None:
        return None

    expiring, stale = [], []
    for fq in faqs:
        q = (fq.get("question") or "").strip()
        a = (fq.get("answer") or "")
        # 回答本文(bot生成)のみを走査。質問文はユーザー原文の日付ノイズ源のため除外
        if not _EXPIRY_HINT.search(a):
            continue
        dates = _extract_dates(a, today)
        if not dates:
            continue
        future = [d for d in dates if d >= today]
        past = [d for d in dates if d < today]
        # 翌月末までに切れる未来日
        soon = [d for d in future if d <= nm_end]
        if soon:
            expiring.append({
                "faq_id": fq.get("id") or fq.get("faq_id") or "",
                "question": q,
                "expire_date": min(soon).isoformat(),
                "snippet": _snip(a),
            })
        elif past and not future:
            # 全日付が過去 → 既に終了したイベントが残存
            stale.append({
                "faq_id": fq.get("id") or fq.get("faq_id") or "",
                "question": q,
                "expire_date": max(past).isoformat(),
                "snippet": _snip(a),
            })
    expiring.sort(key=lambda x: x["expire_date"])
    stale.sort(key=lambda x: x["expire_date"], reverse=True)
    return {
        "checked": len(faqs),
        "next_month_label": f"{ny}年{nm}月",
        "expiring": expiring,
        "stale": stale,
    }


def _snip(text, n=80):
    t = re.sub(r"\s+", " ", text or "").strip()
    return t[:n] + ("…" if len(t) > n else "")


def _faq_items(resp):
    """様々な返却形（list直 / {items} / {data} / {faqs} / {data:{items}}）から FAQ 配列を取り出す。"""
    if isinstance(resp, list):
        return resp, None, None
    if isinstance(resp, dict):
        for k in ("items", "data", "faqs", "list", "results"):
            v = resp.get(k)
            if isinstance(v, list):
                return v, resp.get("total"), resp.get("pages")
            if isinstance(v, dict) and isinstance(v.get("items"), list):
                return v["items"], v.get("total", resp.get("total")), v.get("pages", resp.get("pages"))
    return [], None, None


def _load_all_faqs(base_url, token, dataset_id, language):
    """この dataset の全 FAQ を /datasets/{dataset_id}/faqs ページングで取得。
    （bot↔dataset は 1:1 のため、これがそのまま該当 bot の全 FAQ。
      ai_id 系の /faqs/list は ID 指定・search は検索用で「全件列挙」に不適。）
    返り値: list[dict(question, answer, id)] / None
    """
    out, page, total = [], 1, None
    while True:
        params = {"page": page, "size": 100, "exclude_tree_nodes": "true"}
        if language:
            params["language"] = language  # 多言語(1問答=10言語)のうち指定言語版のみ取得
        try:
            r = _get(base_url, f"/datasets/{dataset_id}/faqs", token, params, timeout=90)
        except Exception as e:
            print(f"⚠️  faqs 取得失敗(page {page}): {e}")
            return out or None
        items, total, pages = _faq_items(r)
        for it in items:
            if not isinstance(it, dict):
                continue
            out.append({"id": it.get("id") or it.get("faq_id"),
                        "question": it.get("question"),
                        "answer": it.get("answer")})
        if not items or not pages or page >= pages:
            break
        page += 1
        time.sleep(0.1)
    print(f"   FAQ 取得: {len(out)}" + (f"/{total} 件" if total else " 件"))
    return out or None


# ───────────────────── 3. テンプレ注入用 HTML ─────────────────────

def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def render_link_placeholders(audit):
    """リンク監査 → {{LINK_*}} プレースホルダ dict。audit=None なら非表示。"""
    if not audit:
        return {
            "LINK_SECTION_DISPLAY": "display:none",
            "LINK_FLOOR_TOTAL": "0", "LINK_ERROR_COUNT": "0", "LINK_ERROR_RATE": "0.00",
            "LINK_EXT_COUNT": "0", "LINK_GT_FILE": "-", "LINK_GT_EXPORTED": "-",
            "LINK_ERROR_ROWS": "", "LINK_EXT_ROWS": "", "LINK_EXT_DISPLAY": "display:none",
        }
    rows = []
    for nm, scd, gtname, date in audit["scd_mismatch"]:
        rows.append(
            f'<tr><td>{_esc(date)}</td><td><span style="color:var(--danger,#dc2626);font-weight:600;">誤リンク</span></td>'
            f'<td>{_esc(nm)}</td><td>scd={_esc(scd)}</td>'
            f'<td>実際は「{_esc(gtname)}」を指す</td></tr>')
    for nm, scd, date in audit["scd_invalid"]:
        rows.append(
            f'<tr><td>{_esc(date)}</td><td><span style="color:var(--warning,#d97706);font-weight:600;">不明scd</span></td>'
            f'<td>{_esc(nm)}</td><td>scd={_esc(scd)}</td>'
            f'<td>最新一覧に存在しない scd（誤記 or 撤退店）</td></tr>')
    ext_rows = []
    for h, c in audit["ext_domains"][:20]:
        ext_rows.append(f'<tr><td>{_esc(h)}</td><td>{c}</td></tr>')
    return {
        "LINK_SECTION_DISPLAY": "",
        "LINK_FLOOR_TOTAL": str(audit["floor_total"]),
        "LINK_ERROR_COUNT": str(audit["floor_error_count"]),
        "LINK_ERROR_RATE": f'{audit["floor_error_rate"]:.2f}',
        "LINK_EXT_COUNT": str(audit["ext_domain_count"]),
        "LINK_GT_FILE": _esc(audit["gt_filename"] or "-"),
        "LINK_GT_EXPORTED": _esc(audit["gt_exported"] or "-"),
        "LINK_ERROR_ROWS": "\n".join(rows) or '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);">該当なし（リンク誤りは検出されませんでした）</td></tr>',
        "LINK_EXT_ROWS": "\n".join(ext_rows),
        "LINK_EXT_DISPLAY": "" if ext_rows else "display:none",
    }


def render_faq_placeholders(faq):
    """FAQ 期限監視 → {{FAQEXP_*}} プレースホルダ dict。faq=None なら非表示。"""
    if not faq:
        return {
            "FAQEXP_SECTION_DISPLAY": "display:none",
            "FAQEXP_NEXT_MONTH": "-", "FAQEXP_CHECKED": "0",
            "FAQEXP_EXPIRING_COUNT": "0", "FAQEXP_STALE_COUNT": "0",
            "FAQEXP_ROWS": "", "FAQEXP_STALE_ROWS": "", "FAQEXP_STALE_DISPLAY": "display:none",
        }
    rows = []
    for f in faq["expiring"]:
        rows.append(
            f'<tr><td>{_esc(f["expire_date"])}</td><td>{_esc(f["question"])}</td>'
            f'<td>{_esc(f["snippet"])}</td></tr>')
    stale_rows = []
    for f in faq["stale"]:
        stale_rows.append(
            f'<tr><td>{_esc(f["expire_date"])}</td><td>{_esc(f["question"])}</td>'
            f'<td>{_esc(f["snippet"])}</td></tr>')
    return {
        "FAQEXP_SECTION_DISPLAY": "",
        "FAQEXP_NEXT_MONTH": _esc(faq["next_month_label"]),
        "FAQEXP_CHECKED": str(faq["checked"]),
        "FAQEXP_EXPIRING_COUNT": str(len(faq["expiring"])),
        "FAQEXP_STALE_COUNT": str(len(faq["stale"])),
        "FAQEXP_ROWS": "\n".join(rows) or '<tr><td colspan="3" style="text-align:center;color:var(--text-muted);">翌月に期限切れになる FAQ はありません</td></tr>',
        "FAQEXP_STALE_ROWS": "\n".join(stale_rows),
        "FAQEXP_STALE_DISPLAY": "" if stale_rows else "display:none",
    }
