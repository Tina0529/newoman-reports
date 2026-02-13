#!/usr/bin/env python3
"""
GBaseSupport Message Analyzer
チャットボットメッセージ履歴分析ツール

Usage:
    python3 analyze.py --csv <path> --client <name> --period <period> [--output <dir>]
"""

import pandas as pd
import json
import re
import argparse
import sys
from datetime import datetime
from collections import Counter
from pathlib import Path
import html as html_module

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


def main():
    parser = argparse.ArgumentParser(description='GBaseSupport Message Analyzer')
    parser.add_argument('--csv', required=True, help='Path to chat history CSV file')
    parser.add_argument('--client', required=True, help='Client name (e.g. NEWoMan高輪)')
    parser.add_argument('--period', required=True, help='Report period (e.g. 2025年12月)')
    parser.add_argument('--output', default=None, help='Output directory (default: same as CSV)')
    args = parser.parse_args()

    csv_path = Path(args.csv).resolve()
    client_name = args.client
    period = args.period
    output_dir = Path(args.output).resolve() if args.output else csv_path.parent

    print(f"🔍 分析を開始します: {csv_path}")

    # CSV読み込み
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

    print(f"📊 データ件数: {len(df)}件")

    # 前処理
    df['質問時間'] = pd.to_datetime(df['質問時間'], errors='coerce')
    df = df.dropna(subset=['質問時間'])

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
    main_html = main_html.replace("2025/01/14", generated_date)

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

    if total_unanswered > 10:
        sub_filename = output_dir / f"{client_name}_{period}_未回答一覧.html"
        with open(sub_filename, "w", encoding="utf-8") as f:
            f.write(unanswered_html)
        print(f"✅ 未回答一覧生成: {sub_filename}")

    print("\n🎉 分析完了！")


if __name__ == "__main__":
    main()
