#!/usr/bin/env python3
"""
GBaseSupport Message Analyzer
チャットボットメッセージ履歴分析ツール

Usage (CSV mode):
    python3 analyze.py --csv <path> --client <name> --period <period> [--output <dir>]

Usage (API mode):
    python3 analyze.py --dataset-id <id> --token <token> --start-date 2025-12-01 --end-date 2025-12-31 \
        --client <name> --period <period> [--output <dir>]
"""

import pandas as pd
import json
import re
import argparse
import sys
import time
import shutil
from datetime import datetime
from collections import Counter
from pathlib import Path
import html as html_module

try:
    import requests
except ImportError:
    requests = None

# ========================================
# Skill root directory (for loading templates)
# ========================================

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = SKILL_DIR / "assets"

# ========================================
# 未回答判定用キーワード
# ========================================

UNANSWERED_KEYWORDS = [
    "見つかりませんでした",
    "情報が見つかりません",
    "お答えできません",
    "一致する情報は見つかりませんでした",
]

# 垫语（自動回答のプレフィックス）
FILLER_PHRASES = [
    "お調べいたします",
    "少々お待ちください",
    "確認いたします",
    "ニュウマン高輪の情報をお調べいたします",
]

# ========================================
# 質問分類キーワード（零售/商業施設）
# ========================================

CATEGORY_KEYWORDS = {
    "位置・ナビゲーション": [
        "どこ", "場所", "位置", "行き方", "アクセス", "何階", "フロア", "マップ", "案内",
        "LUFTBAUM", "ルフトバウム", "28F", "29F", "屋上", "南館", "北館", "South", "North",
        "エレベーター", "エスカレーター", "階段", "入口", "出口",
    ],
    "店舗・商品照会": [
        "店舗", "ショップ", "店", "ブランド", "カフェ", "レストラン", "食べ物", "飲み物",
        "服", "ファッション", "雑貨", "コスメ", "美容", "クリニック",
        "メニュー", "商品", "在庫", "価格", "料金",
        "わんこ", "犬", "ペット", "リード",
        "和菓子", "スイーツ", "パン", "本", "本屋",
    ],
    "施設・サービス": [
        "駐車場", "駐輪場", "ATM", "トイレ", "お手洗い", "化粧室", "授乳室", "ベビールーム",
        "コインロッカー", "荷物", "預かり", "Wi-Fi", "wifi", "充電", "コンセント",
        "ベビーカー", "車椅子", "レンタル", "貸出",
    ],
    "営業時間": [
        "営業時間", "何時から", "何時まで", "開店", "閉店", "休業日", "定休日",
        "年末年始", "祝日", "イベント",
    ],
    "イベント・キャンペーン": [
        "イベント", "キャンペーン", "セール", "割引", "ポイント", "会員", "特典",
        "展示会", "期間限定", "ポップアップ",
    ],
    "クレーム・フィードバック": [
        "最悪", "ひどい", "不満", "クレーム", "改善", "要望", "ありがとう", "お世話",
        "助かった", "便利", "嬉しい",
    ],
}


def detect_language(text):
    """テキストから言語を検出"""
    if not isinstance(text, str):
        return "その他"

    if re.search(r'[\uAC00-\uD7A3]', text):
        return "韓国語"
    if re.search(r'[\u3040-\u309F\u30A0-\u30FF]', text):
        return "日本語"
    if re.search(r'[\u4E00-\u9FFF]', text) and any(c in text for c in '的是在一不了有和个人我这上个为到'):
        return "中国語"
    if re.match(r'^[a-zA-Z\s\d\W]+$', text) and len(re.findall(r'[a-zA-Z]{2,}', text)) > 2:
        return "英語"

    return "その他"


def is_unanswered(answer):
    """未回答かどうかを判定"""
    if pd.isna(answer) or not isinstance(answer, str):
        return True, "情報なし"

    answer_stripped = answer.strip()
    if not answer_stripped:
        return True, "情報なし"

    for keyword in UNANSWERED_KEYWORDS:
        if keyword in answer:
            return True, "情報なし"

    cleaned = answer_stripped
    for filler in FILLER_PHRASES:
        cleaned = cleaned.replace(filler, "")
    cleaned = cleaned.strip()

    if len(cleaned) < 20:
        if "申し訳ございません" in answer or "確認できませんでした" in answer:
            return True, "情報なし"
        return True, "再確認"

    return False, None


def classify_question(question):
    """質問を分類"""
    if pd.isna(question) or not isinstance(question, str):
        return "雑談・その他"

    question_lower = question.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower() in question_lower:
                return category

    return "雑談・その他"


def categorize_unanswered(question, answer):
    """未回答のエラータイプを分類"""
    if pd.isna(answer) or not isinstance(answer, str):
        return "情報なし"

    for kw in UNANSWERED_KEYWORDS:
        if kw in answer:
            return "情報なし"

    if any(p in answer for p in ["該当する", "見つかりません", "一致しません"]):
        return "検索失敗"

    return "再確認"


def count_session_depth(df):
    """会話深度を集計"""
    session_counts = df.groupby('チャット ID').size()
    depth = {"1回": 0, "2回": 0, "3回": 0, "4回+": 0}
    for count in session_counts:
        if count == 1:
            depth["1回"] += 1
        elif count == 2:
            depth["2回"] += 1
        elif count == 3:
            depth["3回"] += 1
        else:
            depth["4回+"] += 1
    return depth


def detect_media_type(answer):
    """回答に含まれるメディアタイプを検出"""
    if pd.isna(answer) or not isinstance(answer, str):
        return "テキストのみ"

    has_link = bool(re.search(r'https?://', answer))
    has_image = bool(re.search(r'!\[.*?\]\(.*?\)|<img|src=', answer))
    has_table = bool(re.search(r'<table|---------|\|.*\|', answer))

    if has_image:
        return "画像含む"
    elif has_table:
        return "テーブル含む"
    elif has_link:
        return "リンク含む"
    else:
        return "テキストのみ"


def escape_html(text):
    """HTML特殊文字をエスケープ"""
    if pd.isna(text):
        return ""
    return html_module.escape(str(text))


# ========================================
# GBase API データ取得
# ========================================

def _api_headers(token):
    """API リクエスト用ヘッダーを生成"""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def resolve_ai_id(base_url, token, dataset_id):
    """dataset_id から ai_id を逆引きする

    方法1: GET /datasets/{dataset_id} → robots フィールドから直接取得（高速）
    方法2: GET /robots 一覧から dataset_id を探す（フォールバック）
    """
    if requests is None:
        print("❌ requests ライブラリが必要です: pip install requests")
        sys.exit(1)

    headers = _api_headers(token)

    # --- 方法1: GET /datasets/{dataset_id} から robots を直接取得 ---
    try:
        resp = requests.get(
            f"{base_url}/datasets/{dataset_id}",
            headers=headers,
            timeout=30,
        )
        if resp.status_code == 200:
            ds_data = resp.json()
            robots = ds_data.get("robots", [])
            if robots:
                robot = robots[0]
                robot_id = robot.get("id", "") if isinstance(robot, dict) else str(robot)
                robot_name = robot.get("name", "") if isinstance(robot, dict) else ""
                if robot_id:
                    print(f"✅ dataset_id → ai_id 解決: {robot_id} ({robot_name})")
                    return str(robot_id)
    except Exception:
        pass  # フォールバックへ

    # --- 方法2: GET /robots 一覧から探す ---
    page = 1
    size = 200

    while True:
        resp = requests.get(
            f"{base_url}/robots",
            headers=headers,
            params={"page": page, "size": size},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        items = data.get("items", [])
        if not items:
            break

        for robot in items:
            robot_id = robot.get("id")
            if not robot_id:
                continue

            datasets = robot.get("datasets", [])
            for ds in datasets:
                ds_id = ds.get("id", "") if isinstance(ds, dict) else str(ds)
                if str(ds_id) == str(dataset_id):
                    print(f"✅ dataset_id → ai_id 解決: {robot_id} ({robot.get('name', '')})")
                    return str(robot_id)

            if str(robot.get("default_dataset_id", "")) == str(dataset_id):
                print(f"✅ dataset_id → ai_id 解決: {robot_id} ({robot.get('name', '')})")
                return str(robot_id)

        total_pages = data.get("pages", 1)
        if page >= total_pages:
            break
        page += 1

    print(f"❌ dataset_id '{dataset_id}' に対応するAIが見つかりません")
    sys.exit(1)


def fetch_from_api(base_url, token, dataset_id, start_date, end_date, ai_id=None):
    """GBase API から消息履歴を取得し、CSV 互換の DataFrame を返す

    1. dataset_id → ai_id の解決（ai_id が直接指定されている場合はスキップ）
    2. /questions/{ai_id}/session.messages.history.list で全メッセージを分页取得
    3. API レスポンスを CSV フォーマットの DataFrame に変換
    """
    if requests is None:
        print("❌ requests ライブラリが必要です: pip install requests")
        sys.exit(1)

    # Step 1: ai_id を解決
    if ai_id:
        print(f"✅ ai_id 直接指定: {ai_id}")
    elif dataset_id:
        ai_id = resolve_ai_id(base_url, token, dataset_id)
    else:
        print("❌ --dataset-id または --ai-id が必要です")
        sys.exit(1)

    # Step 2: 時間範囲をISO 8601形式に変換
    start_time = f"{start_date}T00:00:00Z"
    end_time = f"{end_date}T23:59:59Z"

    headers = _api_headers(token)
    all_messages = []
    page = 1
    size = 1000  # API最大値

    print(f"📡 API からメッセージ履歴を取得中...")
    print(f"   AI ID: {ai_id}")
    print(f"   期間: {start_date} ~ {end_date}")

    while True:
        resp = requests.post(
            f"{base_url}/questions/{ai_id}/session.messages.history.list",
            headers=headers,
            params={
                "start_time": start_time,
                "end_time": end_time,
                "page": page,
                "size": size,
                "include_test": "false",
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        items = data.get("items", [])
        all_messages.extend(items)

        total = data.get("total", 0)
        total_pages = data.get("pages", 1)
        print(f"   ページ {page}/{total_pages} 取得完了（累計: {len(all_messages)}/{total}件）")

        if page >= total_pages:
            break
        page += 1
        time.sleep(0.3)  # レート制限対策

    if not all_messages:
        print("❌ 指定期間のメッセージが見つかりません")
        sys.exit(1)

    print(f"✅ 合計 {len(all_messages)} 件のメッセージを取得")

    # Step 3: API レスポンス → CSV互換 DataFrame に変換
    rows = []
    for msg in all_messages:
        # feedback_type/rating → ユーザーフィードバック
        feedback_type = msg.get("feedback_type")
        rating = msg.get("rating", 0)
        if feedback_type == "good" or (isinstance(rating, int) and rating > 0):
            feedback = "良い"
        elif feedback_type == "bad" or (isinstance(rating, int) and rating < 0):
            feedback = "悪い"
        else:
            feedback = "-"

        # transfer_to_human → 担当者に接続済み
        transfer = "はい" if msg.get("transfer_to_human") else "いいえ"

        rows.append({
            "質問時間": msg.get("created_at", ""),
            "質問": msg.get("question", ""),
            "回答": msg.get("answer", ""),
            "ユーザーフィードバック": feedback,
            "評価理由": msg.get("feedback_content", ""),
            "チャット ID": msg.get("session_id", ""),
            "ユーザー": msg.get("user_id", ""),
            "担当者に接続済み": transfer,
        })

    df = pd.DataFrame(rows)
    return df


def compute_kpi_for_dashboard(df, kpi, period, year_month, avg_daily, language_counts, feedback_rate):
    """Dashboard用のKPI統計を計算"""
    total = kpi["total_messages"]
    foreign_count = sum(int(language_counts.get(l, 0)) for l in ["英語", "中国語", "韓国語"])
    foreign_pct = foreign_count / total * 100 if total > 0 else 0

    # 有人対応率
    if '担当者に接続済み' in df.columns:
        human_count = len(df[df['担当者に接続済み'] == 'はい'])
        human_rate = human_count / total * 100 if total > 0 else 0
    else:
        human_rate = 0

    unique_users = df['ユーザー'].nunique() if 'ユーザー' in df.columns else 0

    # 曜日別分布 (月~日 = 0~6)
    weekday_counts = df['曜日'].value_counts().sort_index()
    weekday_data = [int(weekday_counts.get(i, 0)) for i in range(7)]

    return {
        "period": period,
        "year_month": year_month,
        "total_messages": total,
        "normal_answer_rate": round(kpi["normal_answer_rate"], 1),
        "unanswered_rate": round(kpi["unanswered_rate"], 1),
        "good_rating_rate": round(kpi["good_rate"], 1),
        "feedback_rate": round(feedback_rate, 1),
        "daily_average": round(avg_daily, 1),
        "unique_users": unique_users,
        "human_transfer_rate": round(human_rate, 1),
        "foreign_language_pct": round(foreign_pct, 1),
        "weekday_counts": weekday_data,
    }


def update_dashboard_json(site_dir, client_slug, client_name, month_stats,
                          report_filename, unanswered_filename=None):
    """Dashboard JSONを更新し、レポートHTMLをサイトディレクトリにコピー"""
    client_dir = Path(site_dir) / "clients" / client_slug
    reports_dir = client_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    json_path = client_dir / "dashboard-data.json"

    # 既存データを読み込み
    if json_path.exists():
        with open(json_path, "r", encoding="utf-8") as f:
            dashboard = json.load(f)
    else:
        dashboard = {
            "client": client_name,
            "client_slug": client_slug,
            "updated_at": "",
            "months": [],
        }

    # 同じ year_month のデータがあれば置換、なければ追加
    year_month = month_stats["year_month"]
    months = [m for m in dashboard["months"] if m["year_month"] != year_month]

    # report_file / unanswered_file パスを追加
    month_entry = dict(month_stats)
    month_entry["report_file"] = f"reports/{year_month}.html"
    if unanswered_filename:
        month_entry["unanswered_file"] = f"reports/{year_month}_unanswered.html"

    months.append(month_entry)
    months.sort(key=lambda m: m["year_month"])

    dashboard["months"] = months
    dashboard["updated_at"] = datetime.now().isoformat()
    dashboard["client"] = client_name
    dashboard["client_slug"] = client_slug

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, ensure_ascii=False, indent=2)

    print(f"✅ dashboard-data.json 更新: {json_path}")
    return json_path


def main():
    parser = argparse.ArgumentParser(
        description='GBaseSupport Message Analyzer',
        epilog='Either --csv (CSV mode) or --dataset-id + --token (API mode) is required.',
    )
    # Common arguments
    parser.add_argument('--client', required=True, help='Client name (e.g. NEWoMan高輪)')
    parser.add_argument('--period', required=True, help='Report period (e.g. 2025年12月)')
    parser.add_argument('--output', default=None, help='Output directory (default: same as CSV or current dir)')

    # CSV mode
    parser.add_argument('--csv', default=None, help='Path to chat history CSV file (CSV mode)')

    # API mode
    parser.add_argument('--dataset-id', default=None, help='GBase dataset ID (API mode)')
    parser.add_argument('--ai-id', default=None, help='GBase AI/robot ID - skip dataset_id lookup (API mode)')
    parser.add_argument('--token', default=None, help='GBase API bearer token (API mode)')
    parser.add_argument('--api-url', default='https://api.gbase.ai', help='GBase API base URL (default: https://api.gbase.ai)')
    parser.add_argument('--start-date', default=None, help='Start date YYYY-MM-DD (API mode)')
    parser.add_argument('--end-date', default=None, help='End date YYYY-MM-DD (API mode)')

    # Site integration mode
    parser.add_argument('--site-dir', default=None, help='Path to docs/ directory for dashboard site integration')
    parser.add_argument('--client-slug', default=None, help='URL-safe client identifier (e.g. newoman-takanawa)')

    args = parser.parse_args()

    client_name = args.client
    period = args.period

    # Determine data source mode
    if args.csv:
        # === CSV Mode ===
        csv_path = Path(args.csv).resolve()
        output_dir = Path(args.output).resolve() if args.output else csv_path.parent

        print(f"🔍 分析を開始します（CSVモード）: {csv_path}")

        for encoding in ['utf-8', 'utf-8-sig', 'shift-jis', 'cp932']:
            try:
                df = pd.read_csv(csv_path, encoding=encoding)
                print(f"✅ CSV読み込み成功（エンコーディング: {encoding}）")
                break
            except Exception:
                continue
        else:
            print("❌ CSV読み込みに失敗しました")
            sys.exit(1)

    elif (args.dataset_id or args.ai_id) and args.token:
        # === API Mode ===
        if not args.start_date or not args.end_date:
            parser.error('API mode requires --start-date and --end-date')

        output_dir = Path(args.output).resolve() if args.output else Path.cwd()

        print(f"🔍 分析を開始します（APIモード）")
        df = fetch_from_api(args.api_url, args.token, args.dataset_id, args.start_date, args.end_date, ai_id=args.ai_id)

    else:
        parser.error('Either --csv or (--dataset-id/--ai-id + --token + --start-date + --end-date) is required')

    print(f"📊 データ件数: {len(df)}件")

    # 前処理
    df['質問時間'] = pd.to_datetime(df['質問時間'], errors='coerce')
    df = df.dropna(subset=['質問時間'])

    # APIデータはUTC (+00:00) → JST (+09:00) に変換
    if df['質問時間'].dt.tz is not None:
        df['質問時間'] = df['質問時間'].dt.tz_convert('Asia/Tokyo').dt.tz_localize(None)
        print("🕐 タイムゾーン変換: UTC → JST (+9h)")

    df['日付'] = df['質問時間'].dt.date
    df['曜日'] = df['質問時間'].dt.dayofweek
    df['時間'] = df['質問時間'].dt.hour

    # KPI計算
    total_messages = len(df)

    unanswered_results = df['回答'].apply(is_unanswered)
    df['未回答フラグ'] = unanswered_results.apply(lambda x: x[0])
    df['未回答タイプ'] = unanswered_results.apply(lambda x: x[1] if x[0] else None)

    unanswered_count = df['未回答フラグ'].sum()
    answered_count = total_messages - unanswered_count

    feedback_df = df[df['ユーザーフィードバック'].notna() & (df['ユーザーフィードバック'] != '-')]
    good_feedback = len(feedback_df[feedback_df['ユーザーフィードバック'].isin(['良い', '良い評価'])])
    bad_feedback = len(feedback_df[feedback_df['ユーザーフィードバック'].isin(['悪い', '悪い評価'])])

    feedback_count = good_feedback + bad_feedback
    feedback_rate = feedback_count / total_messages * 100 if total_messages > 0 else 0
    good_rate = good_feedback / feedback_count * 100 if feedback_count > 0 else 0
    normal_answer_rate = answered_count / total_messages * 100 if total_messages > 0 else 0
    unanswered_rate = unanswered_count / total_messages * 100 if total_messages > 0 else 0

    kpi = {
        "total_messages": total_messages,
        "answered_count": answered_count,
        "unanswered_count": int(unanswered_count),
        "good_feedback": good_feedback,
        "bad_feedback": bad_feedback,
        "feedback_count": feedback_count,
        "normal_answer_rate": normal_answer_rate,
        "unanswered_rate": unanswered_rate,
        "good_rate": good_rate,
        "feedback_rate": feedback_rate,
    }

    print(f"\n📈 KPIサマリー:")
    print(f"  総メッセージ数: {kpi['total_messages']}")
    print(f"  正常回答率: {kpi['normal_answer_rate']:.1f}%")
    print(f"  未回答率: {kpi['unanswered_rate']:.1f}%")
    print(f"  好評価率: {kpi['good_rate']:.1f}%")

    # 時間分析
    daily_counts = df.groupby(df['質問時間'].dt.day).size()
    max_day_in_data = int(df['質問時間'].dt.day.max())
    min_day_in_data = int(df['質問時間'].dt.day.min())
    daily_data = [int(daily_counts.get(i, 0)) for i in range(min_day_in_data, max_day_in_data + 1)]

    year = int(df['質問時間'].dt.year.iloc[0])
    month = int(df['質問時間'].dt.month.iloc[0])
    month_str = str(month)
    weekday_names_ja = ['月', '火', '水', '木', '金', '土', '日']
    daily_labels = [f"{month_str}/{i}({weekday_names_ja[datetime(year, month, i).weekday()]})"
                    for i in range(min_day_in_data, max_day_in_data + 1)]

    weekday_counts = df['曜日'].value_counts().sort_index()
    weekday_data = [int(weekday_counts.get(i, 0)) for i in range(7)]

    hour_ranges = [(0, 6), (6, 9), (9, 12), (12, 15), (15, 18), (18, 21), (21, 24)]
    hour_data = [int(len(df[(df['時間'] >= s) & (df['時間'] < e)])) for s, e in hour_ranges]

    num_days = len(daily_counts)
    avg_daily = float(total_messages) / num_days if num_days > 0 else 0
    max_day = int(daily_counts.idxmax())
    max_count = int(daily_counts.max())
    min_day = int(daily_counts.idxmin())
    min_count = int(daily_counts.min())

    # 質問分類
    df['カテゴリ'] = df['質問'].apply(classify_question)
    category_counts = df['カテゴリ'].value_counts()

    # ユーザー行動
    session_depth = count_session_depth(df)
    df['言語'] = df['質問'].apply(detect_language)
    language_counts = df['言語'].value_counts()

    # メディア
    df['メディアタイプ'] = df['回答'].apply(detect_media_type)
    media_counts = df['メディアタイプ'].value_counts()

    # エラーパターン
    unanswered_df = df[df['未回答フラグ'] == True].copy()
    if len(unanswered_df) > 0:
        unanswered_df['エラータイプ'] = unanswered_df.apply(
            lambda row: categorize_unanswered(row['質問'], row['回答']), axis=1)
    else:
        unanswered_df['エラータイプ'] = []

    error_counts = unanswered_df['エラータイプ'].value_counts()
    error_stats = {
        "info_nashi": int(error_counts.get("情報なし", 0)),
        "search_fail": int(error_counts.get("検索失敗", 0)),
        "reconfirm": int(error_counts.get("再確認", 0)),
    }

    # 未回答一覧データ
    unanswered_list = []
    for idx, row in unanswered_df.iterrows():
        error_type = row.get('エラータイプ', '情報なし')
        badge_class = {'情報なし': 'badge-red', '検索失敗': 'badge-yellow', '再確認': 'badge-gray'}.get(error_type, 'badge-gray')
        unanswered_list.append({
            'timestamp': row['質問時間'].strftime('%Y-%m-%d %H:%M:%S'),
            'error_type': error_type,
            'badge_class': badge_class,
            'question': escape_html(str(row['質問'])[:100] + ('...' if len(str(row['質問'])) > 100 else '')),
            'answer': escape_html(str(row['回答'])[:150] + ('...' if len(str(row['回答'])) > 150 else '')),
        })

    # テンプレート読み込み
    with open(TEMPLATE_DIR / "report-template.html", "r", encoding="utf-8") as f:
        main_template = f.read()
    with open(TEMPLATE_DIR / "unanswered-template.html", "r", encoding="utf-8") as f:
        unanswered_template = f.read()

    # ========================================
    # メインレポート生成（テンプレート置換）
    # ========================================

    generated_date = datetime.now().strftime("%Y/%m/%d")

    category_order = ["位置・ナビゲーション", "雑談・その他", "店舗・商品照会", "施設・サービス", "営業時間"]
    badge_colors = {
        "位置・ナビゲーション": "badge-blue",
        "雑談・その他": "badge-gray",
        "店舗・商品照会": "badge-green",
        "施設・サービス": "badge-yellow",
        "営業時間": "badge-purple",
    }
    category_data = []
    for cat in category_order:
        count = int(category_counts.get(cat, 0))
        pct = count / total_messages * 100 if total_messages > 0 else 0
        category_data.append({"name": cat, "count": count, "percent": pct, "badge": badge_colors.get(cat, "badge-blue")})

    main_html = main_template
    main_html = main_html.replace("NEWoMan 高輪", client_name)
    main_html = main_html.replace("NEWoMan高輪 2025年12月", f"{client_name} {period}")
    main_html = main_html.replace("2025/01/14", generated_date)

    # 分析期間を動的に設定（データの実際の日付範囲）
    date_from = df['質問時間'].min().strftime('%Y/%m/%d')
    date_to = df['質問時間'].max().strftime('%Y/%m/%d')
    main_html = main_html.replace("2025/12/01 - 2025/12/31", f"{date_from} - {date_to}")

    unanswered_filename = f"{client_name}_{period}_未回答一覧.html"
    main_html = main_html.replace("__UNANSWERED_LINK__", unanswered_filename)

    # KPI replacements
    main_html = re.sub(r'<div class="kpi-value">909</div>', f'<div class="kpi-value">{kpi["total_messages"]}</div>', main_html)
    main_html = re.sub(r'<div class="kpi-value">89\.1%</div>', f'<div class="kpi-value">{kpi["normal_answer_rate"]:.1f}%</div>', main_html)
    main_html = re.sub(r'<div class="kpi-sublabel">810/909</div>', f'<div class="kpi-sublabel">{kpi["answered_count"]}/{kpi["total_messages"]}</div>', main_html)
    main_html = re.sub(r'<div class="kpi-value">10\.9%</div>', f'<div class="kpi-value">{kpi["unanswered_rate"]:.1f}%</div>', main_html)
    main_html = re.sub(r'<div class="kpi-sublabel">99/909</div>', f'<div class="kpi-sublabel">{kpi["unanswered_count"]}/{kpi["total_messages"]}</div>', main_html)
    main_html = re.sub(r'<div class="kpi-value">70\.0%</div>', f'<div class="kpi-value">{kpi["good_rate"]:.1f}%</div>', main_html)
    main_html = re.sub(r'<div class="kpi-value">2\.2%</div>', f'<div class="kpi-value">{kpi["feedback_rate"]:.1f}%</div>', main_html)
    main_html = re.sub(r'<div class="kpi-sublabel">20/909</div>', f'<div class="kpi-sublabel">評価あり {kpi["feedback_count"]}件中</div>', main_html)

    # Stats
    main_html = re.sub(r'<div class="stat-value">29\.3</div>', f'<div class="stat-value">{avg_daily:.1f}</div>', main_html)
    main_html = re.sub(r'<div class="stat-value">84</div>', f'<div class="stat-value">{max_count}</div>', main_html)
    main_html = re.sub(r'<div class="stat-value">6</div>', f'<div class="stat-value">{min_count}</div>', main_html)
    max_date_label = f"{month}/{max_day}"
    min_date_label = f"{month}/{min_day}"
    main_html = main_html.replace("__MAX_DATE__", max_date_label)
    main_html = main_html.replace("__MIN_DATE__", min_date_label)

    # Chart data
    main_html = re.sub(r"data: \[19,24,33,33,21,47,44,22,17,19,30,34,37,65,33,24,36,22,84,42,45,20,30,8,9,6,17,27,27,13,21\]", f"data: {daily_data}", main_html)
    main_html = re.sub(r"__DAILY_LABELS__", f"{daily_labels}", main_html)
    main_html = re.sub(r"data: \[121, 108, 117, 94, 145, 143, 181\]", f"data: {weekday_data}", main_html)
    main_html = re.sub(r"data: \[4, 4, 151, 344, 259, 129, 18\]", f"data: {hour_data}", main_html)

    # Category
    cat_values = [d["count"] for d in category_data]
    main_html = re.sub(r"data: \[302, 256, 233, 97, 11\]", f"data: {cat_values}", main_html)

    table_rows = ""
    for cat in category_data:
        table_rows += f'''
                            <tr>
                                <td><span class="badge {cat['badge']}">{cat['name']}</span></td>
                                <td class="number">{cat['count']}</td>
                                <td class="number">{cat['percent']:.1f}%</td>
                            </tr>'''
    main_html = re.sub(r'<tbody>.*?</tbody>', f'<tbody>{table_rows}</tbody>', main_html, flags=re.DOTALL)

    # Session depth
    depth_data = [int(session_depth[k]) for k in ["1回", "2回", "3回", "4回+"]]
    main_html = re.sub(r"data: \[376, 117, 35, 30\]", f"data: {depth_data}", main_html)

    # Language
    lang_values = [int(language_counts.get(l, 0)) for l in ["日本語", "英語", "中国語", "韓国語"]]
    main_html = re.sub(r"data: \[811, 55, 32, 11\]", f"data: {lang_values}", main_html)

    # Media
    media_values = [int(media_counts.get(m, 0)) for m in ["リンク含む", "画像含む", "テーブル含む", "テキストのみ"]]
    main_html = re.sub(r"data: \[269, 83, 179, 639\]", f"data: {media_values}", main_html)

    # Unanswered CTA
    main_html = re.sub(r'<div class="cta-value">104</div>', f'<div class="cta-value">{kpi["unanswered_count"]}</div>', main_html)
    main_html = re.sub(r'<span><span class="badge badge-red">情報なし</span> 83件</span>', f'<span><span class="badge badge-red">情報なし</span> {error_stats["info_nashi"]}件</span>', main_html)
    main_html = re.sub(r'<span><span class="badge badge-yellow">検索失敗</span> 20件</span>', f'<span><span class="badge badge-yellow">検索失敗</span> {error_stats["search_fail"]}件</span>', main_html)
    main_html = re.sub(r'<span><span class="badge badge-gray">再確認</span> 1件</span>', f'<span><span class="badge badge-gray">再確認</span> {error_stats["reconfirm"]}件</span>', main_html)

    # Error cards
    uc = kpi["unanswered_count"]
    main_html = re.sub(r'<div class="error-value">83</div>', f'<div class="error-value">{error_stats["info_nashi"]}</div>', main_html)
    main_html = re.sub(r'<div class="error-percent">80%</div>', f'<div class="error-percent">{error_stats["info_nashi"]/uc*100:.0f}%</div>' if uc > 0 else '<div class="error-percent">0%</div>', main_html)
    main_html = re.sub(r'<div class="error-value">20</div>', f'<div class="error-value">{error_stats["search_fail"]}</div>', main_html)
    main_html = re.sub(r'<div class="error-percent">19%</div>', f'<div class="error-percent">{error_stats["search_fail"]/uc*100:.0f}%</div>' if uc > 0 else '<div class="error-percent">0%</div>', main_html)
    main_html = re.sub(r'<div class="error-value">1</div>', f'<div class="error-value">{error_stats["reconfirm"]}</div>', main_html)
    main_html = re.sub(r'<div class="error-percent">1%</div>', f'<div class="error-percent">{error_stats["reconfirm"]/uc*100:.0f}%</div>' if uc > 0 else '<div class="error-percent">0%</div>', main_html)

    # ========================================
    # 分析サマリー（動的生成）
    # ========================================

    # 利用ピーク時間帯
    peak_hour_idx = hour_data.index(max(hour_data))
    hour_range_labels = ["0〜6時", "6〜9時", "9〜12時", "12〜15時", "15〜18時", "18〜21時", "21〜24時"]
    peak_hour_label = hour_range_labels[peak_hour_idx]
    peak_hour_pct = max(hour_data) / total_messages * 100 if total_messages > 0 else 0

    # 最多曜日
    weekday_names_full = ['月曜日', '火曜日', '水曜日', '木曜日', '金曜日', '土曜日', '日曜日']
    peak_weekday = weekday_names_full[weekday_data.index(max(weekday_data))]

    # 外国語比率
    foreign_count = sum(int(language_counts.get(l, 0)) for l in ["英語", "中国語", "韓国語"])
    foreign_pct = foreign_count / total_messages * 100 if total_messages > 0 else 0

    # 最多カテゴリ
    top_cat = category_data[0] if category_data else None
    top_cat_name = top_cat["name"] if top_cat else ""
    top_cat_pct = top_cat["percent"] if top_cat else 0
    sorted_cats = sorted(category_data, key=lambda x: x["count"], reverse=True)
    top_cat_name = sorted_cats[0]["name"] if sorted_cats else ""
    top_cat_pct = sorted_cats[0]["percent"] if sorted_cats else 0

    # 未回答の主要エラータイプ
    total_errors = error_stats["info_nashi"] + error_stats["search_fail"] + error_stats["reconfirm"]
    main_error_pct = error_stats["info_nashi"] / total_errors * 100 if total_errors > 0 else 0

    summary_items_ja = [
        f"<strong>利用状況</strong>：月間<span class='highlight-text'>{total_messages}件</span>のメッセージを処理し、正常回答率は{kpi['normal_answer_rate']:.1f}%",
        f"<strong>質問傾向</strong>：最多カテゴリは<span class='highlight-text'>「{top_cat_name}」（{top_cat_pct:.0f}%）</span>",
        f"<strong>利用ピーク</strong>：<span class='highlight-text'>{peak_hour_label}（{peak_hour_pct:.0f}%）</span>に集中、{peak_weekday}が最多",
        f"<strong>インバウンド</strong>：<span class='highlight-text'>約{foreign_pct:.0f}%が外国語</span>での問い合わせ",
        f"<strong>改善ポイント</strong>：未回答の<span class='highlight-text'>{main_error_pct:.0f}%は情報なしエラー</span>でFAQ拡充で改善可能",
    ]
    summary_items_zh = [
        f"<strong>使用情况</strong>：月度处理<span class='highlight-text'>{total_messages}条</span>消息，正常回答率{kpi['normal_answer_rate']:.1f}%",
        f"<strong>问题趋势</strong>：最多类别为<span class='highlight-text'>「{top_cat_name}」（{top_cat_pct:.0f}%）</span>",
        f"<strong>使用高峰</strong>：集中在<span class='highlight-text'>{peak_hour_label}（{peak_hour_pct:.0f}%）</span>，{peak_weekday}最多",
        f"<strong>入境游</strong>：<span class='highlight-text'>约{foreign_pct:.0f}%为外语</span>咨询",
        f"<strong>改善要点</strong>：<span class='highlight-text'>{main_error_pct:.0f}%为信息缺失错误</span>，可通过完善FAQ改善",
    ]

    summary_html = "\n".join(
        f'                        <li data-ja="{ja}" data-zh="{zh}">{ja}</li>'
        for ja, zh in zip(summary_items_ja, summary_items_zh)
    )
    # 分析サマリーのul内容を置換
    main_html = re.sub(
        r'(<div class="summary-content">\s*<ul>).*?(</ul>)',
        rf'\1\n{summary_html}\n                    \2',
        main_html,
        flags=re.DOTALL,
    )

    # ========================================
    # 改善提案（動的生成）
    # ========================================

    # 未回答質問のキーワード頻度分析で提案を生成
    suggestion_items = []

    # 提案1: 情報なしエラーが多い場合
    if error_stats["info_nashi"] > 0:
        # 未回答質問から頻出キーワードを抽出
        unanswered_questions = unanswered_df['質問'].tolist()
        all_words = []
        for q in unanswered_questions:
            q_str = str(q)
            # 簡易キーワード抽出（カタカナ語、漢字語）
            words = re.findall(r'[\u30A0-\u30FF]{2,}|[\u4E00-\u9FFF]{2,}', q_str)
            all_words.extend(words)
        word_freq = Counter(all_words).most_common(5)
        top_words = '」「'.join([w for w, c in word_freq[:3]]) if word_freq else '不明'

        suggestion_items.append({
            "priority": "high", "badge": "badge-red",
            "title_ja": "FAQ情報の拡充", "title_zh": "FAQ信息补充",
            "desc_ja": f"「{top_words}」など未回答となっている質問のFAQ追加を推奨します。（情報なし: {error_stats['info_nashi']}件）",
            "desc_zh": f"建议补充「{top_words}」等未回答问题的FAQ。（信息缺失: {error_stats['info_nashi']}件）",
        })

    # 提案2: 検索失敗が多い場合
    if error_stats["search_fail"] > 5:
        suggestion_items.append({
            "priority": "high", "badge": "badge-red",
            "title_ja": "ナレッジベースの検索精度向上", "title_zh": "知识库搜索精度提升",
            "desc_ja": f"検索失敗が{error_stats['search_fail']}件あり、ナレッジベースの構造や表記ゆれへの対応改善を推奨します。",
            "desc_zh": f"搜索失败{error_stats['search_fail']}件，建议改善知识库结构和同义词处理。",
        })

    # 提案3: フィードバック率が低い場合
    if kpi["feedback_rate"] < 5:
        suggestion_items.append({
            "priority": "medium", "badge": "badge-yellow",
            "title_ja": "ユーザーフィードバックの促進", "title_zh": "促进用户反馈",
            "desc_ja": f"フィードバック率が{kpi['feedback_rate']:.1f}%と低いため、評価ボタンの視認性向上を推奨します。",
            "desc_zh": f"反馈率仅{kpi['feedback_rate']:.1f}%，建议提高评价按钮的可见性。",
        })

    # 提案4: 外国語が多い場合
    if foreign_pct > 5:
        top_foreign = max(["英語", "中国語", "韓国語"], key=lambda l: int(language_counts.get(l, 0)))
        suggestion_items.append({
            "priority": "medium", "badge": "badge-yellow",
            "title_ja": f"多言語対応の強化（{top_foreign}）", "title_zh": f"加强多语言支持（{top_foreign}）",
            "desc_ja": f"外国語での問い合わせが約{foreign_pct:.0f}%あり、{top_foreign}のFAQ充実を推奨します。",
            "desc_zh": f"外语咨询约{foreign_pct:.0f}%，建议充实{top_foreign}FAQ。",
        })

    # 提案5: 好評率が低い場合
    if kpi["good_rate"] < 60:
        suggestion_items.append({
            "priority": "high", "badge": "badge-red",
            "title_ja": "回答品質の改善", "title_zh": "回答质量改善",
            "desc_ja": f"好評率が{kpi['good_rate']:.1f}%と低いため、回答の詳細度や正確性の見直しを推奨します。",
            "desc_zh": f"好评率{kpi['good_rate']:.1f}%偏低，建议改善回答的详细度和准确性。",
        })

    # フォールバック: 提案が少ない場合
    if len(suggestion_items) < 2:
        suggestion_items.append({
            "priority": "low", "badge": "badge-green",
            "title_ja": "定期的なFAQ見直し", "title_zh": "定期FAQ审查",
            "desc_ja": "月次でのFAQ見直しと更新を継続し、回答品質の維持向上を図りましょう。",
            "desc_zh": "建议每月审查并更新FAQ，持续提升回答质量。",
        })

    suggestion_html = ""
    for item in suggestion_items:
        priority_class = f"priority-{item['priority']}"
        suggestion_html += f'''
                <li class="suggestion-item {priority_class}">
                    <div class="suggestion-title">
                        <span class="badge {item['badge']}" data-ja="優先度：{item['priority'].replace('high','高').replace('medium','中').replace('low','低')}" data-zh="优先级：{item['priority'].replace('high','高').replace('medium','中').replace('low','低')}">優先度：{item['priority'].replace('high','高').replace('medium','中').replace('low','低')}</span>
                        <span data-ja="{item['title_ja']}" data-zh="{item['title_zh']}">{item['title_ja']}</span>
                    </div>
                    <div class="suggestion-desc" data-ja="{item['desc_ja']}" data-zh="{item['desc_zh']}">{item['desc_ja']}</div>
                </li>'''

    # 改善提案のul内容を置換
    main_html = re.sub(
        r'(<ul class="suggestion-list">).*?(</ul>)',
        rf'\1{suggestion_html}\n            \2',
        main_html,
        flags=re.DOTALL,
    )

    # ========================================
    # 未回答一覧ページ生成
    # ========================================

    total_unanswered = len(unanswered_list)
    info_nashi_pct = int(error_stats["info_nashi"] / total_unanswered * 100) if total_unanswered > 0 else 0
    search_fail_pct = int(error_stats["search_fail"] / total_unanswered * 100) if total_unanswered > 0 else 0
    reconfirm_pct = int(error_stats["reconfirm"] / total_unanswered * 100) if total_unanswered > 0 else 0

    unanswered_html = unanswered_template
    unanswered_html = unanswered_html.replace("{{CLIENT_NAME}}", client_name)
    unanswered_html = unanswered_html.replace("{{PERIOD}}", period)
    unanswered_html = unanswered_html.replace("{{MAIN_REPORT_FILENAME}}", f"{client_name}_{period}_分析レポート.html")
    unanswered_html = unanswered_html.replace("{{TOTAL_UNANSWERED}}", str(total_unanswered))
    unanswered_html = unanswered_html.replace("{{INFO_NASHI_COUNT}}", str(error_stats["info_nashi"]))
    unanswered_html = unanswered_html.replace("{{INFO_NASHI_PERCENT}}", str(info_nashi_pct))
    unanswered_html = unanswered_html.replace("{{SEARCH_FAIL_COUNT}}", str(error_stats["search_fail"]))
    unanswered_html = unanswered_html.replace("{{SEARCH_FAIL_PERCENT}}", str(search_fail_pct))
    unanswered_html = unanswered_html.replace("{{RECONFIRM_COUNT}}", str(error_stats["reconfirm"]))
    unanswered_html = unanswered_html.replace("{{RECONFIRM_PERCENT}}", str(reconfirm_pct))

    table_rows = ""
    for i, item in enumerate(unanswered_list, 1):
        table_rows += f'''
<tr>
    <td class="number">{i}</td>
    <td class="timestamp">{item['timestamp']}</td>
    <td><span class="badge {item['badge_class']}" data-ja="{item['error_type']}" data-zh="{item['error_type']}">{item['error_type']}</span></td>
    <td class="question-cell">{item['question']}</td>
    <td class="answer-cell">{item['answer']}</td>
</tr>'''
    unanswered_html = unanswered_html.replace("{{TABLE_ROWS}}", table_rows)

    # ========================================
    # ファイル出力
    # ========================================

    output_dir.mkdir(parents=True, exist_ok=True)

    main_filename = output_dir / f"{client_name}_{period}_分析レポート.html"
    with open(main_filename, "w", encoding="utf-8") as f:
        f.write(main_html)
    print(f"\n✅ メインレポート生成: {main_filename}")

    sub_filename = None
    if total_unanswered > 10:
        sub_filename = output_dir / f"{client_name}_{period}_未回答一覧.html"
        with open(sub_filename, "w", encoding="utf-8") as f:
            f.write(unanswered_html)
        print(f"✅ 未回答一覧生成: {sub_filename}")

    # ========================================
    # サイト統合（--site-dir 指定時）
    # ========================================

    if args.site_dir and args.client_slug:
        site_dir = Path(args.site_dir).resolve()

        # year_month を period から抽出（例: "2026年1月" → "2026-01"）
        ym_match = re.search(r'(\d{4})\D+(\d{1,2})', period)
        if ym_match:
            year_month = f"{ym_match.group(1)}-{int(ym_match.group(2)):02d}"
        else:
            year_month = df['質問時間'].iloc[0].strftime('%Y-%m')

        # KPI統計を計算
        month_stats = compute_kpi_for_dashboard(
            df, kpi, period, year_month, avg_daily, language_counts, feedback_rate
        )

        # dashboard-data.json を更新
        update_dashboard_json(
            site_dir, args.client_slug, client_name, month_stats,
            str(main_filename),
            str(sub_filename) if total_unanswered > 10 else None,
        )

        # レポートHTMLをサイトディレクトリにコピー
        reports_dir = site_dir / "clients" / args.client_slug / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        dest_main = reports_dir / f"{year_month}.html"
        shutil.copy2(main_filename, dest_main)
        # サイト用にリンクを修正（未回答一覧のファイル名を相対パスに）
        with open(dest_main, "r", encoding="utf-8") as f:
            html_content = f.read()
        html_content = html_content.replace(
            f'href="{client_name}_{period}_未回答一覧.html"',
            f'href="{year_month}_unanswered.html"'
        )
        with open(dest_main, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"✅ レポートコピー: {dest_main}")

        if total_unanswered > 10:
            dest_sub = reports_dir / f"{year_month}_unanswered.html"
            shutil.copy2(sub_filename, dest_sub)
            print(f"✅ 未回答一覧コピー: {dest_sub}")

    print("\n🎉 分析完了！")


if __name__ == "__main__":
    main()
