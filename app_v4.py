import streamlit as st
import pandas as pd
import re
import hashlib
import io
import json
from zoneinfo import ZoneInfo
from pathlib import Path
from datetime import datetime, date

st.set_page_config(
    page_title="全店舗口コミ管理ツール",
    layout="wide"
)

BASE = Path(__file__).parent
MASTER = BASE / "store_master_v3.csv"
REVIEWS = BASE / "reviews_v3.csv"
PROGRESS = BASE / "progress_v3.csv"
OLD_LOG = BASE / "review_log.csv"

def save_csv(df, path):
    st.session_state[path.name] = df.copy()

def classify(body):
    rules = {
        "設備・故障": [
            "券売機", "エアコン", "空調",
            "故障", "壊れ", "水漏れ",
            "冷房", "暖房", "トイレ",
            "照明", "換気"
        ],
        "衛生・清掃": [
            "汚い", "不衛生", "清潔",
            "清掃", "髪の毛", "異物",
            "臭い", "汚れ"
        ],
        "害虫・害獣": [
            "ゴキブリ", "ネズミ",
            "害虫", "ハエ", "虫"
        ],
        "接客": [
            "接客", "店員", "スタッフ",
            "態度", "対応", "店長"
        ],
        "料理・品質": [
            "味", "美味", "うまい",
            "まずい", "スープ", "麺",
            "餃子", "料理"
        ],
        "価格・会計": [
            "高い", "価格", "料金",
            "会計", "手数料", "カード",
            "決済"
        ],
        "店舗情報": [
            "閉店", "閉め", "営業時間",
            "休業", "移転"
        ]
    }

    result = [
        category
        for category, words in rules.items()
        if any(word in body for word in words)
    ]

    return "・".join(result) or "その他"

def judge(body):
    words = [
        "まずい", "汚い", "不衛生",
        "故障", "壊れ", "最悪",
        "高い", "残念", "悪い",
        "ゴキブリ", "ネズミ",
        "手数料", "規約違反",
        "閉店", "閉め", "水漏れ",
        "異物", "不満"
    ]

    if any(word in body for word in words):
        return "要確認"

    return "未確認"

def parse_reviews(raw, number, name):
    raw = raw.replace("\r", "")
    lines = [
        line.strip()
        for line in raw.split("\n")
        if line.strip()
    ]

    pattern = re.compile(
        r"^(?:\d+\s*(?:分|時間|日|週間|"
        r"か月|ヶ月|カ月|年)前|昨日|今日)"
        r"(?:に編集)?$"
    )

    positions = [
        i for i, line in enumerate(lines)
        if pattern.match(line)
    ]

    results = []

    for n, pos in enumerate(positions):
        author = ""

        for j in range(pos - 1, -1, -1):
            line = lines[j]

            if (
                "ローカルガイド" in line
                or re.match(
                    r"^\d+\s*件のクチコミ",
                    line
                )
            ):
                if j > 0:
                    author = lines[j - 1]
                break

            if pos - j > 15:
                break

        end = (
            positions[n + 1]
            if n + 1 < len(positions)
            else len(lines)
        )

        body_lines = []
        truncated = False

        for line in lines[pos + 1:end]:
            if line == "新規":
                continue

            if (
                line in ["高評価", "共有"]
                or re.match(
                    r"^[\ue000-\uf8ff]+$",
                    line
                )
            ):
                break

            if "もっと見る" in line:
                truncated = True
                line = line.replace(
                    "もっと見る", ""
                ).strip()

                if line:
                    body_lines.append(line)
                break

            if line.startswith((
                "食事の種類",
                "食事:",
                "1 人あたりの料金",
                "サービス:",
                "雰囲気:"
            )):
                break

            body_lines.append(line)

        body = "\n".join(body_lines).strip()

        if not body and not author:
            continue

        key = (
            number + "|" + author + "|" + body
        )

        review_id = hashlib.sha256(
            key.encode("utf-8")
        ).hexdigest()[:24]

        results.append({
            "ID": review_id,
            "取得日時": datetime.now(ZoneInfo("Asia/Tokyo")).strftime(
                "%Y-%m-%d %H:%M"
            ),
            "店舗番号": number,
            "店舗名": name,
            "投稿者": author,
            "投稿日表示": lines[pos],
            "評価": "",
            "口コミ本文": body,
            "分類": classify(body),
            "対応状況": judge(body),
            "省略あり": "あり" if truncated else "",
            "対応メモ": ""
        })

    return pd.DataFrame(results)

with st.sidebar:
    master_upload = st.file_uploader("店舗マスターCSV（store_master_v3.csv）", type=["csv"], key="master_upload")
if master_upload is None:
    st.info("左側から店舗マスターCSVを読み込んでください。")
    st.stop()
try:
    stores = pd.read_csv(master_upload, dtype=str).fillna("")
    if not {"店舗番号", "短縮名称", "口コミ収集対象", "Googleマップ検索URL"}.issubset(stores.columns):
        raise ValueError("店舗マスターの必要な列が不足しています")
except Exception as e:
    st.error(str(e))
    st.stop()

active = stores[
    stores["口コミ収集対象"] == "対象候補"
].reset_index(drop=True)

review_columns = [
    "ID", "取得日時", "店舗番号",
    "店舗名", "投稿者", "投稿日表示",
    "評価", "口コミ本文", "分類",
    "対応状況", "省略あり", "対応メモ"
]

progress_columns = ["店舗番号", "確認日"]
for path, columns in [(REVIEWS, review_columns), (PROGRESS, progress_columns)]:
    if path.name not in st.session_state:
        st.session_state[path.name] = pd.DataFrame(columns=columns)

def validated(df, columns):
    if not set(columns).issubset(df.columns):
        raise ValueError("必要な列が不足しています")
    return df[columns].fillna("").astype(str)

with st.sidebar:
    st.header("作業データの保存・再開")
    st.warning("作業データはブラウザの接続終了等で失われます。作業後は必ず保存してください。外部サーバーで処理されるため、社内機密や個人情報は入力しないでください。")
    upload = st.file_uploader("前回の作業ファイル", type=["json"])
    with st.expander("Ver.3のCSVから移行"):
        old_reviews = st.file_uploader("reviews_v3.csv", type=["csv"], key="old_reviews")
        old_progress = st.file_uploader("progress_v3.csv", type=["csv"], key="old_progress")
    if st.button("読み込んで現在の作業を置き換える"):
        try:
            if upload is not None:
                data = json.load(upload)
                if data.get("version") != 4:
                    raise ValueError("対応していないファイルです")
                r = validated(pd.DataFrame(data["reviews"], columns=review_columns), review_columns)
                p = validated(pd.DataFrame(data["progress"], columns=progress_columns), progress_columns)
            elif old_reviews is not None and old_progress is not None:
                r = validated(pd.read_csv(old_reviews, dtype=str), review_columns)
                p = validated(pd.read_csv(old_progress, dtype=str), progress_columns)
            else:
                raise ValueError("作業ファイル、またはCSV2点を選択してください")
            if r["ID"].eq("").any() or r["ID"].duplicated().any():
                raise ValueError("口コミIDが空欄または重複しています")
            save_csv(r, REVIEWS)
            save_csv(p.drop_duplicates(), PROGRESS)
            st.session_state.pop("store_index", None)
            st.session_state["paste_version"] = st.session_state.get("paste_version", 0) + 1
            st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1
            st.success("読み込み完了")
        except Exception as e:
            st.error(str(e))
    reviews = st.session_state[REVIEWS.name]
    progress = st.session_state[PROGRESS.name]
    st.download_button("作業データを一括保存", json.dumps({"version":4,"reviews":reviews.to_dict("records"),"progress":progress.to_dict("records")}, ensure_ascii=False).encode("utf-8"), file_name="口コミ作業データ.json", mime="application/json")

today = datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()

checked = set(
    progress.loc[
        progress["確認日"] == today,
        "店舗番号"
    ]
)

master_signature = hashlib.sha256(master_upload.getvalue()).hexdigest()
if st.session_state.get("master_signature") != master_signature:
    st.session_state["master_signature"] = master_signature
    st.session_state.pop("store_index", None)
    st.session_state["paste_version"] = st.session_state.get("paste_version", 0) + 1
if "store_index" not in st.session_state:
    st.session_state.store_index = next((i for i, n in enumerate(active["店舗番号"]) if n not in checked), 0)

if "paste_version" not in st.session_state:
    st.session_state.paste_version = 0

st.title("全店舗口コミ管理ツール Ver.4")

a, b, c, d = st.columns(4)

a.metric("登録店舗", len(stores))
b.metric("収集対象", len(active))
c.metric("本日確認済み", len(checked))
d.metric(
    "要確認",
    len(reviews[
        reviews["対応状況"] == "要確認"
    ])
)

st.progress(
    min(len(checked) / max(len(active), 1), 1.0)
)

tab1, tab2, tab3, tab4 = st.tabs([
    "口コミ収集",
    "全店舗口コミ一覧",
    "集計・分析",
    "店舗マスター"
])

with tab1:
    if active.empty:
        st.warning("対象店舗がありません")
        st.stop()

    labels = [
        f'{row["店舗番号"]} {row["短縮名称"]}'
        for _, row in active.iterrows()
    ]

    idx = st.selectbox(
        "確認する店舗",
        range(len(active)),
        index=st.session_state.store_index,
        format_func=lambda x: labels[x],
        key=f'store_{st.session_state.paste_version}'
    )

    row = active.iloc[idx]
    number = row["店舗番号"]
    name = row["短縮名称"]

    st.subheader(
        f"{idx + 1} / {len(active)}　{name}"
    )

    if number in checked:
        st.success("本日確認済み")

    url = row["Googleマップ検索URL"]

    if url.startswith("https://"):
        st.link_button(
            "Googleマップを開く", url
        )

    st.caption(
        "口コミを新しい順に並べ替え、"
        "Ctrl+A、Ctrl+Cでコピーしてください。"
    )

    raw = st.text_area(
        "コピーした口コミを貼り付け",
        height=250,
        key=f'paste_{st.session_state.paste_version}'
    )

    parsed = parse_reviews(raw, number, name)

    if raw and parsed.empty:
        st.warning(
            "口コミを認識できませんでした。"
            "コピー内容を確認してください。"
        )

    if not parsed.empty:
        st.success(
            f"{len(parsed)}件の口コミを認識しました"
        )

        st.dataframe(
            parsed[[
                "投稿日表示", "口コミ本文",
                "分類", "対応状況"
            ]],
            hide_index=True
        )

    def advance():
        global progress

        progress = pd.concat([
            progress,
            pd.DataFrame([{
                "店舗番号": number,
                "確認日": today
            }])
        ], ignore_index=True)

        progress = progress.drop_duplicates()
        save_csv(progress, PROGRESS)

        st.session_state.store_index = min(
            idx + 1, len(active) - 1
        )

        st.session_state.paste_version += 1
        st.rerun()

    x, y = st.columns(2)

    if x.button(
        "保存して次の店舗へ",
        disabled=parsed.empty,
        type="primary"
    ):
        combined = pd.concat(
            [reviews, parsed],
            ignore_index=True
        )

        combined = combined.drop_duplicates(
            subset=["ID"], keep="first"
        )

        save_csv(combined, REVIEWS)
        advance()

    if y.button("新着なし・次の店舗へ"):
        advance()

with tab2:
    st.subheader("全店舗の口コミ")

    keyword = st.text_input("キーワード検索")

    selected = st.selectbox(
        "対応状況",
        ["すべて", "要確認", "未確認", "対応済み"]
    )

    view = reviews.copy()

    if keyword:
        mask = view[
            ["店舗名", "口コミ本文", "分類"]
        ].apply(
            lambda col: col.str.contains(
                keyword, regex=False, na=False
            )
        ).any(axis=1)

        view = view[mask]

    if selected != "すべて":
        view = view[
            view["対応状況"] == selected
        ]

    st.write(f"表示件数：{len(view)}件")

    edited = st.data_editor(
        view,
        hide_index=True,
        column_config={
            "ID": None,
            "対応状況": st.column_config.SelectboxColumn(
                options=[
                    "未確認", "要確認", "対応済み"
                ],
                required=True
            )
        },
        disabled=[
            col for col in review_columns
            if col not in [
                "対応状況", "対応メモ", "分類"
            ]
        ],
        key=f'review_editor_{st.session_state.get("editor_version", 0)}_{keyword}_{selected}'
    )

    if st.button("対応状況・メモを保存"):
        updated = reviews.set_index("ID")

        updated.update(
            edited.set_index("ID")[[
                "対応状況", "対応メモ", "分類"
            ]]
        )

        save_csv(
            updated.reset_index(), REVIEWS
        )
        st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1
        st.rerun()

    st.download_button(
        "全口コミCSVダウンロード",
        reviews.to_csv(
            index=False
        ).encode("utf-8-sig"),
        file_name="全店舗口コミ一覧.csv",
        mime="text/csv"
    )

with tab3:
    st.subheader("分類別の口コミ件数")

    if reviews.empty:
        st.info("口コミを保存すると集計されます")
    else:
        counts = (
            reviews["分類"]
            .str.split("・")
            .explode()
        )

        # 複合名称を分割しないよう
        # 元の分類文字列で集計
        st.bar_chart(
            reviews["分類"].value_counts()
        )

        st.subheader("店舗別口コミ件数")

        st.bar_chart(
            reviews["店舗名"].value_counts()
        )

        st.subheader("対応状況別件数")

        st.bar_chart(
            reviews["対応状況"].value_counts()
        )

with tab4:
    show_all = st.checkbox(
        "対象外店舗も表示する"
    )

    st.dataframe(
        (stores if show_all else active)[["店舗番号", "短縮名称", "口コミ収集対象", "Googleマップ検索URL"]],
        hide_index=True,
        column_config={
            "Googleマップ検索URL":
                st.column_config.LinkColumn(
                    "Googleマップ",
                    display_text="店舗を開く"
                )
        }
    )