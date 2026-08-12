# ======================================================================
# Magic Park Navi / 学習・編集用 コメント付き版
# ======================================================================
# 元コードの動作は変えず、「どこで何をしているか」を追いやすいように
# 説明コメントを追加した版です。
#
# 【全体の地図 / この番号をそのまま本文で追ってください】
# 1. ライブラリ読み込み
# 2. Streamlitページ設定・見た目
# 3. 基本設定・固定データ
# 4. CSV・お気に入り関係
# 5. API取得・公式情報の照合
# 6. 計算・表示情報の加工
# 7. 徒歩ルート関係
# 8. 地図を作る関数
# 9. ここから実際の画面処理（アプリ本体）
# 10. API / CSVから元データを集める
# 11. attraction_df + poi_df → all_df（全施設）
# 12. all_df → display_df（今、画面に出す施設）
# 13. display_dfを並べ替える
# 14. 現在の状態（GPS / 今いる施設 / 次の目的地）
# 15. 選択中の徒歩ルート
# 16. 一覧地図（折りたたみ）
# 17. 施設カード表示
# 18. 選択カテゴリに応じてカード / お気に入り / 地図を実際に表示
# 19. 画面最下部の案内・データ出典
#
# ※ 本文では、各章の最初と最後に同じ番号・同じ名前を書いています。
#    例：# 5. API取得... から # ここまで 5. API取得... までが1セットです。
#
# 【DataFrameの役割】
# attraction_df : アトラクションだけの表
#                 ThemeParks.wiki + CSV補助情報 + 待ち時間 + 休止情報
# poi_df        : OpenStreetMapから取得したレストラン / ショップの表
# all_df        : attraction_df と poi_df を合体した「全施設」の表
# display_df    : all_dfを現在の検索・カテゴリ・エリア条件で絞った表示用の表
# favorite_df   : お気に入り施設だけの表
#
# 【session_stateで覚えているもの】
# current_spot  : 「📍 今ここ」で指定した現在いる施設
# route_target  : 「🚶 行く」で指定した次の目的地
# scroll_target : st.rerun()後に画面のどこへ戻るか
#
# 【自分で直したい場所の早見表】
# 見た目               → style.css / 冒頭CSS / show_facility_cards()
# パーク基本情報       → PARKS
# アトラクションエリア → ATTRACTION_AREAS
# レストラン等エリア   → FACILITY_AREAS
# レストラン座席数     → RESTAURANT_SEATS
# 待ち時間/API         → get_attractions() / get_live_data()
# レストラン/ショップ  → get_osm_pois()
# 検索・絞り込み       → display_dfを作る部分
# 並べ替え             → sort_mode / balanced_score()
# 地図ピン             → add_facility_marker()
# 徒歩ルート           → get_walking_route() / make_route_map()
# 施設カード           → show_facility_cards()
# お気に入り           → load_favorites() / save_favorites() / toggle_favorite()
# ======================================================================

# ======================================================================
# 1. ライブラリ読み込み
# ======================================================================
# 標準ライブラリ：JSON、計算、URL、正規表現、文字正規化、日付、並列処理など
import json
import math
import urllib.parse
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# 外部ライブラリ：地図、表データ、HTTP通信、Streamlit画面など
import folium
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup
from streamlit_folium import folium_static
from streamlit_gps_location import gps_location_button

# ======================================================================
# ここまで 1. ライブラリ読み込み
# ======================================================================

# ======================================================================
# 2. Streamlitページ設定・見た目
# ======================================================================
# ブラウザのタブ名・アイコン・ページ幅を設定します。
st.set_page_config(
    page_title="Magic Park Navi",
    page_icon="🏰",
    layout="centered",
)

# BASE_DIR = このapp.py自身が置いてあるフォルダ。
# CSVやstyle.cssを「app.pyと同じ場所」から探すための基準です。
BASE_DIR = Path(__file__).resolve().parent


# ------------------------------------------------------------------
# 関数：load_css()
# 役割：style.cssを読み込んで画面へ適用する
# 入力：入力なし
# 出力：戻り値なし
# どこで使う：アプリ起動直後
# 自分で触るなら：CSSファイル名や読み込み方法を変える時
# ------------------------------------------------------------------
def load_css():
    css_path = BASE_DIR / "style.css"
    if css_path.exists():
        st.markdown(
            f"<style>{css_path.read_text(encoding='utf-8')}</style>",
            unsafe_allow_html=True,
        )


load_css()

# ここからのst.markdown(<style>...)は、このファイル内だけの追加CSSです。
# カード内の補足情報が青い背景に埋もれないよう、文字と案内枠を高コントラスト化
st.markdown(
    """
    <style>
    /* 待機列・絶叫度・涼しい候補など、カード本文の文字 */
    div[data-testid="stVerticalBlockBorderWrapper"]
    div[data-testid="stMarkdownContainer"] p {
        color: #ffffff !important;
        font-weight: 700 !important;
        text-shadow: 0 1px 2px rgba(0, 0, 0, 0.45);
    }

    /* 無料パス・有料パスなどの情報ボックス */
    div[data-testid="stAlert"] {
        background: rgba(255, 255, 255, 0.94) !important;
        border: 2px solid rgba(255, 255, 255, 0.95) !important;
        border-radius: 14px !important;
    }

    div[data-testid="stAlert"] p,
    div[data-testid="stAlert"] div {
        color: #12304f !important;
        font-weight: 800 !important;
        text-shadow: none !important;
    }

    /* カード内のキャプションも読みやすくする */
    div[data-testid="stVerticalBlockBorderWrapper"]
    [data-testid="stCaptionContainer"] {
        color: #ffffff !important;
        font-weight: 700 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# 画面最上部の「Magic Park Navi」タイトル部分（hero）を表示します。
st.markdown(
    """
    <section class="hero">
      <div class="hero-kicker">PARK ADVENTURE</div>
      <h1>🏰 Magic Park Navi</h1>
      <p>今いる場所から、次のワクワクまで迷わずナビ</p>
    </section>
    """,
    unsafe_allow_html=True,
)

# ======================================================================
# ここまで 2. Streamlitページ設定・見た目
# ======================================================================

# ======================================================================
# 3. 基本設定・固定データ
# ======================================================================
# ここは主に「値を登録しておく場所」。まだAPI取得などの重い処理はしません。
# ------------------------------------------------------------------
# 基本設定
# ------------------------------------------------------------------

# PARKS = パークごとの設定をまとめた辞書。
# id=ThemeParks.wiki用ID / center=パーク中心 / bbox=OSM検索範囲 / official=公式URL
PARKS = {
    "東京ディズニーランド": {
        "id": "3cc919f1-d16d-43e0-8c3f-1dd269bd1a42",
        "center": [35.632416, 139.880666],
        "bbox": (35.6265, 139.8735, 35.6390, 139.8885),
        "official": {
            "アトラクション":
                "https://www.tokyodisneyresort.jp/tdl/attraction.html",
            "レストラン":
                "https://www.tokyodisneyresort.jp/tdl/restaurant/list.html",
            "ショップ":
                "https://www.tokyodisneyresort.jp/tdl/shop/list.html",
            "ランドマーク":
                "https://www.tokyodisneyresort.jp/tdl/",
            "休止情報":
                "https://www.tokyodisneyresort.jp/tdl/monthly/stop.html",
        },
    },
    "東京ディズニーシー": {
        "id": "67b290d5-3478-4f23-b601-2f8fb71ba803",
        "center": [35.626015, 139.885409],
        "bbox": (35.6185, 139.8765, 35.6330, 139.8970),
        "official": {
            "アトラクション":
                "https://www.tokyodisneyresort.jp/tds/attraction.html",
            "レストラン":
                "https://www.tokyodisneyresort.jp/tds/restaurant/list.html",
            "ショップ":
                "https://www.tokyodisneyresort.jp/tds/shop/list.html",
            "ランドマーク":
                "https://www.tokyodisneyresort.jp/tds/",
            "休止情報":
                "https://www.tokyodisneyresort.jp/tds/monthly/stop.html",
        },
    },
}

# 外部サービスの接続先。APIを変更する時はこの3つを確認します。
THEMEPARKS_API = "https://api.themeparks.wiki/v1/entity"
OVERPASS_API = "https://overpass-api.de/api/interpreter"
VALHALLA_API = "https://valhalla1.openstreetmap.de/route"

# アプリが読むCSVファイル。すべてapp.pyと同じフォルダを基準にしています。
NAME_FILE = BASE_DIR / "attraction_names.csv"
FAVORITES_FILE = BASE_DIR / "favorites.csv"
ICON_FILE = BASE_DIR / "icon_catalog.csv"
OFFICIAL_LINKS_FILE = BASE_DIR / "official_links.csv"

# 施設種別ごとの基本アイコン。お気に入り未設定時の地図やカードで使用。
TYPE_ICONS = {
    "アトラクション": "🎡",
    "レストラン": "🍽️",
    "ショップ": "🛍️",
    "ランドマーク": "📍",
}

# 絶叫度を数値順に扱いたい時の対応表。
THRILL_ORDER = {
    "穏やか": 0,
    "軽いスリル": 1,
    "絶叫強め": 2,
}

# APIの英語ステータス → 画面に出す日本語の対応表。
STATUS_JA = {
    "OPERATING": "営業中",
    "DOWN": "一時休止",
    "CLOSED": "受付終了",
    "REFURBISHMENT": "休止中",
    "UNKNOWN": "情報なし",
}

# ThemeParks.wikiの東京ディズニー情報では、各アトラクションの
# 所属エリアが安定して返らないため、公式パーク区分に合わせて保持する。
# 【固定データ】アトラクション名 → エリア名の対応表。
# これは処理ではなく「名簿」。エリアを直す時はここを編集します。
ATTRACTION_AREAS = {
    "東京ディズニーランド": {
        "ワールドバザール": {
            "オムニバス",
            "ペニーアーケード",
        },
        "アドベンチャーランド": {
            "カリブの海賊",
            "ジャングルクルーズ：ワイルドライフ・エクスペディション",
            "スイスファミリー・ツリーハウス",
            "魅惑のチキルーム：スティッチ・プレゼンツ“アロハ・エ・コモ・マイ！”",
        },
        "ウエスタンランド": {
            "ウエスタンランド・シューティングギャラリー",
            "ウエスタンランド・シューティングギャラリー",
            "ウエスタンリバー鉄道",
            "カントリーベア・シアター",
            "蒸気船マークトウェイン号",
            "トムソーヤ島いかだ",
            "ビッグサンダー・マウンテン",
        },
        "クリッターカントリー": {
            "スプラッシュ・マウンテン",
            "ビーバーブラザーズのカヌー探険",
        },
        "ファンタジーランド": {
            "アリスのティーパーティー",
            "イッツ・ア・スモールワールド",
            "キャッスルカルーセル",
            "シンデレラのフェアリーテイル・ホール",
            "白雪姫と七人のこびと",
            "空飛ぶダンボ",
            "ピノキオの冒険旅行",
            "ピーターパン空の旅",
            "プーさんのハニーハント",
            "ホーンテッドマンション",
            "ミッキーのフィルハーマジック",
            "美女と野獣“魔法のものがたり”",
        },
        "トゥーンタウン": {
            "ガジェットのゴーコースター",
            "グーフィーのペイント＆プレイハウス",
            "チップとデールのツリーハウス",
            "トゥーンパーク",
            "ドナルドのボート",
            "ミニーの家",
            "ロジャーラビットのカートゥーンスピン",
        },
        "トゥモローランド": {
            "スター・ツアーズ：ザ・アドベンチャーズ・コンティニュー",
            "スティッチ・エンカウンター",
            "ベイマックスのハッピーライド",
            "モンスターズ・インク“ライド＆ゴーシーク！”",
        },
    },
    "東京ディズニーシー": {
        "メディテレーニアンハーバー": {
            "ソアリン：ファンタスティック・フライト",
            "ヴェネツィアン・ゴンドラ",
            "フォートレス・エクスプロレーション",
            "フォートレス・エクスプロレーション“ザ・レオナルドチャレンジ”",
            "ディズニーシー・トランジットスチーマーライン（メディテレーニアンハーバー）",
        },
        "アメリカンウォーターフロント": {
            "タワー・オブ・テラー",
            "タートル・トーク",
            "トイ・ストーリー・マニア！",
            "ビッグシティ・ヴィークル",
            "ディズニーシー・エレクトリックレールウェイ（アメリカンウォーターフロント）",
            "ディズニーシー・トランジットスチーマーライン（アメリカンウォーターフロント）",
        },
        "ポートディスカバリー": {
            "アクアトピア",
            "ニモ＆フレンズ・シーライダー",
            "ディズニーシー・エレクトリックレールウェイ（ポートディスカバリー）",
        },
        "ロストリバーデルタ": {
            "インディ・ジョーンズ・アドベンチャー：クリスタルスカルの魔宮",
            "レイジングスピリッツ",
            "ディズニーシー・トランジットスチーマーライン（ロストリバーデルタ）",
        },
        "アラビアンコースト": {
            "キャラバンカルーセル",
            "シンドバッド・ストーリーブック・ヴォヤッジ",
            "ジャスミンのフライングカーペット",
            "マジックランプシアター",
        },
        "マーメイドラグーン": {
            "アリエルのプレイグラウンド",
            "ジャンピン・ジェリーフィッシュ",
            "スカットルのスクーター",
            "フランダーのフライングフィッシュコースター",
            "ブローフィッシュ・バルーンレース",
            "マーメイドラグーンシアター",
            "ワールプール",
        },
        "ミステリアスアイランド": {
            "センター・オブ・ジ・アース",
            "海底2万マイル",
        },
        "ファンタジースプリングス": {
            "アナとエルサのフローズンジャーニー",
            "ピーターパンのネバーランドアドベンチャー",
            "フェアリー・ティンカーベルのビジーバギー",
            "ラプンツェルのランタンフェスティバル",
        },
    },
}


# ------------------------------------------------------------------
# 関数：attraction_area()
# 役割：アトラクション名から所属エリアを探す
# 入力：park_name / attraction_name
# 出力：エリア名
# どこで使う：attraction_dfのarea列作成
# 自分で触るなら：アトラクションのエリア判定を変える時
# ------------------------------------------------------------------
def attraction_area(park_name, attraction_name):
    """アトラクション名から所属エリアを返す。"""
    target = normalize_name(attraction_name)

    for area_name, names in ATTRACTION_AREAS.get(
            park_name,
            {},
    ).items():
        for name in names:
            if normalize_name(name) == target:
                return area_name

    return "エリア未設定"


# ======================================================================
# ここまで 3. 基本設定・固定データ
# ======================================================================

# ======================================================================
# 4. CSV・お気に入り関係
# ======================================================================
# ここからしばらくは「関数の定義」。後半で呼ばれるまで中身は動きません。
# ------------------------------------------------------------------
# CSV・お気に入り
# attraction_names.csv / favorites.csv / icon_catalog.csv を扱う
# ------------------------------------------------------------------

@st.cache_data
# ------------------------------------------------------------------
# 関数：load_attraction_master()
# 役割：attraction_names.csvを読む
# 入力：入力なし
# 出力：DataFrame
# どこで使う：アトラクションへCSV情報を結合する前
# 自分で触るなら：CSV列を変える時
# ------------------------------------------------------------------
def load_attraction_master():
    """日本語名・待機環境・絶叫度などの補助情報を読む。"""
    if not NAME_FILE.exists():
        return pd.DataFrame()

    return pd.read_csv(
        NAME_FILE,
        dtype={"entity_id": "string"},
    )


@st.cache_data
# ------------------------------------------------------------------
# 関数：load_icon_catalog()
# 役割：お気に入り用アイコン一覧を読む
# 入力：入力なし
# 出力：DataFrame
# どこで使う：カードのアイコン変更UI
# 自分で触るなら：アイコンCSVを変える時
# ------------------------------------------------------------------
def load_icon_catalog():
    """お気に入りアイコン一覧を読む。"""
    if not ICON_FILE.exists():
        return pd.DataFrame(
            [
                {"category": "基本", "icon": "⭐", "name": "星"},
                {"category": "基本", "icon": "❤️", "name": "ハート"},
                {"category": "場所", "icon": "📍", "name": "場所"},
            ]
        )

    return (
        pd.read_csv(ICON_FILE, dtype=str)
        .dropna(subset=["icon"])
        .drop_duplicates("icon")
    )


# ------------------------------------------------------------------
# 関数：load_favorites()
# 役割：favorites.csvを読む
# 入力：入力なし
# 出力：{施設ID: アイコン}
# どこで使う：地図・カード表示前
# 自分で触るなら：お気に入り保存形式を変える時
# ------------------------------------------------------------------
def load_favorites():
    """
    お気に入りを読む。
    戻り値は {施設ID: アイコン}。
    """
    if not FAVORITES_FILE.exists():
        return {}

    try:
        favorite_df = pd.read_csv(
            FAVORITES_FILE,
            dtype={"entity_id": "string", "icon": "string"},
        )
    except (OSError, pd.errors.EmptyDataError):
        return {}

    if "entity_id" not in favorite_df.columns:
        return {}

    if "icon" not in favorite_df.columns:
        favorite_df["icon"] = "⭐"

    return {
        str(row["entity_id"]): (
            str(row["icon"])
            if pd.notna(row["icon"])
            else "⭐"
        )
        for _, row in favorite_df.iterrows()
        if pd.notna(row["entity_id"])
    }


# ------------------------------------------------------------------
# 関数：save_favorites()
# 役割：お気に入りをCSVへ保存
# 入力：favorites辞書
# 出力：戻り値なし
# どこで使う：追加/解除/アイコン変更時
# 自分で触るなら：保存列を変える時
# ------------------------------------------------------------------
def save_favorites(favorites):
    """お気に入りをCSVへ保存する。"""
    rows = [
        {"entity_id": entity_id, "icon": icon}
        for entity_id, icon in sorted(favorites.items())
    ]

    pd.DataFrame(
        rows,
        columns=["entity_id", "icon"],
    ).to_csv(
        FAVORITES_FILE,
        index=False,
        encoding="utf-8-sig",
    )


# ------------------------------------------------------------------
# 関数：toggle_favorite()
# 役割：お気に入りを追加または解除
# 入力：entity_id / default_icon
# 出力：戻り値なし・最後にrerun
# どこで使う：カードの☆/★ボタン
# 自分で触るなら：お気に入り動作を変える時
# ------------------------------------------------------------------
def toggle_favorite(entity_id, default_icon):
    """お気に入りを追加・解除する。"""
    favorites = load_favorites()
    entity_id = str(entity_id)

    if entity_id in favorites:
        del favorites[entity_id]
    else:
        favorites[entity_id] = default_icon

    save_favorites(favorites)
    st.rerun()


# ------------------------------------------------------------------
# 関数：change_favorite_icon()
# 役割：お気に入りアイコンを変更
# 入力：entity_id / icon
# 出力：戻り値なし・最後にrerun
# どこで使う：アイコン変更ボタン
# 自分で触るなら：変更ルールを変える時
# ------------------------------------------------------------------
def change_favorite_icon(entity_id, icon):
    """お気に入りアイコンを変更する。"""
    favorites = load_favorites()
    entity_id = str(entity_id)

    if entity_id not in favorites:
        return

    favorites[entity_id] = icon
    save_favorites(favorites)
    st.rerun()


# ======================================================================
# ここまで 4. CSV・お気に入り関係
# ======================================================================

# ======================================================================
# 5. API取得・公式情報の照合
# ======================================================================
# ThemeParks.wiki / 公式サイト / OpenStreetMap から情報を集める関数群です。
# ------------------------------------------------------------------
# API取得
# ThemeParks.wiki / 東京ディズニー公式 / OpenStreetMap を扱う
# ------------------------------------------------------------------


# ------------------------------------------------------------------
# 関数：parse_official_date()
# 役割：公式の日付文字列をdate型へ変換
# 入力：value
# 出力：dateまたはNone
# どこで使う：休止期間比較
# 自分で触るなら：公式日付書式が変わった時
# ------------------------------------------------------------------
def parse_official_date(value):
    """公式サイトの日付文字列をdateへ変換する。"""
    value = str(value or "").strip()

    if not value or value == "未定":
        return None

    try:
        return datetime.strptime(
            value,
            "%Y/%m/%d",
        ).date()
    except ValueError:
        return None


@st.cache_data(ttl=3600)
# ------------------------------------------------------------------
# 関数：get_attractions()
# 役割：ThemeParks.wikiからアトラクション基本情報と座標を取得
# 入力：park_id
# 出力：list[dict]
# どこで使う：画面のデータ取得ブロック
# 自分で触るなら：API形式が変わった時
# ------------------------------------------------------------------
def get_attractions(park_id):
    """ThemeParks.wikiからアトラクションと座標を取る。"""
    response = requests.get(
        f"{THEMEPARKS_API}/{park_id}/children",
        timeout=20,
    )
    response.raise_for_status()

    rows = []

    for item in response.json().get("children", []):
        if str(item.get("entityType", "")).upper() != "ATTRACTION":
            continue

        location = item.get("location") or {}
        lat = location.get("latitude")
        lon = location.get("longitude")

        if lat is None or lon is None:
            continue

        rows.append(
            {
                "entity_id": str(
                    item.get("id") or item.get("entityId")
                ),
                "name_en": item.get("name", "名称不明"),
                "lat": float(lat),
                "lon": float(lon),
                "type": "アトラクション",
                "osm_tags": {},
            }
        )

    return rows


@st.cache_data(ttl=300)
# ------------------------------------------------------------------
# 関数：get_live_data()
# 役割：営業状況・待ち時間・パス情報を取得
# 入力：park_id
# 出力：list[dict]
# どこで使う：attraction_dfへmerge
# 自分で触るなら：待ち時間項目を変える時
# ------------------------------------------------------------------
def get_live_data(park_id):
    """ThemeParks.wikiから営業状況・待ち時間・パス情報を取る。"""
    response = requests.get(
        f"{THEMEPARKS_API}/{park_id}/live",
        timeout=20,
    )
    response.raise_for_status()

    rows = []

    for item in response.json().get("liveData", []):
        queue = item.get("queue") or {}

        standby = (
                queue.get("STANDBY")
                or queue.get("standby")
                or {}
        )
        free_pass = (
                queue.get("RETURN_TIME")
                or queue.get("returnTime")
                or {}
        )
        paid_pass = (
                queue.get("PAID_RETURN_TIME")
                or queue.get("paidReturnTime")
                or {}
        )

        rows.append(
            {
                "entity_id": str(
                    item.get("id") or item.get("entityId")
                ),
                "status": item.get("status", "UNKNOWN"),
                "wait_time": standby.get("waitTime"),
                "free_pass_available": bool(free_pass),
                "free_pass_state": (
                        free_pass.get("state")
                        or free_pass.get("status")
                        or ""
                ),
                "free_pass_start": (
                        free_pass.get("returnStart")
                        or free_pass.get("startTime")
                        or ""
                ),
                "free_pass_end": (
                        free_pass.get("returnEnd")
                        or free_pass.get("endTime")
                        or ""
                ),
                "paid_pass_available": bool(paid_pass),
                "paid_pass_state": (
                        paid_pass.get("state")
                        or paid_pass.get("status")
                        or ""
                ),
                "paid_pass_start": (
                        paid_pass.get("returnStart")
                        or paid_pass.get("startTime")
                        or ""
                ),
                "paid_pass_end": (
                        paid_pass.get("returnEnd")
                        or paid_pass.get("endTime")
                        or ""
                ),
            }
        )

    return rows


@st.cache_data(ttl=3600)
# ------------------------------------------------------------------
# 関数：get_official_suspensions()
# 役割：公式休止ページから施設名と期間を取得
# 入力：park_name
# 出力：list[dict]
# どこで使う：休止情報付与
# 自分で触るなら：公式ページ構造が変わった時
# ------------------------------------------------------------------
def get_official_suspensions(park_name):
    """
    東京ディズニーリゾート公式の休止情報ページから、
    アトラクション名と休止期間を取得する。
    """
    url = PARKS[park_name]["official"]["休止情報"]

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 Version/17.0 "
            "Mobile/15E148 Safari/604.1"
        ),
        "Accept-Language": "ja-JP,ja;q=0.9",
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException:
        return []

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    page_text = soup.get_text(
        "\n",
        strip=True,
    )

    # 例：
    # ウエスタンリバー鉄道
    # 2026/8/4 - 2026/8/24
    pattern = re.compile(
        r"([^\n]{2,80})\s*\n+"
        r"(\d{4}/\d{1,2}/\d{1,2}|未定)"
        r"\s*-\s*"
        r"(\d{4}/\d{1,2}/\d{1,2}|未定)"
    )

    records = []

    for match in pattern.finditer(page_text):
        name = match.group(1).strip()
        start_text = match.group(2).strip()
        end_text = match.group(3).strip()

        # 説明文などを誤って施設名にしない
        if len(name) > 60:
            continue

        start_date = parse_official_date(start_text)
        end_date = parse_official_date(end_text)

        records.append(
            {
                "name": name,
                "normalized": normalize_name(name),
                "start_date": start_date,
                "end_date": end_date,
                "start_text": start_text,
                "end_text": end_text,
            }
        )

    return records


@st.cache_data
# ------------------------------------------------------------------
# 関数：get_official_restaurant_info()
# 役割：official_links.csvから公式レストラン情報を読む
# 入力：park_name
# 出力：list[dict]
# どこで使う：レストラン照合
# 自分で触るなら：CSV必須列を変える時
# ------------------------------------------------------------------
def get_official_restaurant_info(park_name):
    """
    official_links.csvの既存列だけから、
    レストラン名と公式URLを読み込む。
    外部ページ巡回や未存在のCSV列には依存しない。
    """
    if not OFFICIAL_LINKS_FILE.exists():
        return []

    df = pd.read_csv(
        OFFICIAL_LINKS_FILE,
        dtype=str,
    ).fillna("")

    required = {
        "park",
        "type",
        "name_ja",
        "official_url",
    }
    if not required.issubset(df.columns):
        return []

    df = df[
        (df["park"].str.strip() == park_name)
        & (df["type"].str.strip() == "レストラン")
        ].copy()

    records = []

    for _, row in df.iterrows():
        name = row["name_ja"].strip()
        url = row["official_url"].strip()

        if not name:
            continue

        records.append(
            {
                "name": name,
                "normalized": normalize_name(name),
                "official_url": url,
            }
        )

    return records


# ============================================================
# レストラン / ショップのエリア情報
# ============================================================
#
# 【重要】
# 以前は起動時に東京ディズニーリゾート公式一覧ページへアクセスし、
# HTMLからエリアを読み取っていました。
#
# ただしStreamlit Cloudでは公式ページのHTML構造や取得内容の違いにより、
# エリアを取得できず「エリア未設定」になることがありました。
#
# そのため現在は、レストラン / ショップのエリアを
# app.py内に固定データとして持たせています。
#
# メリット:
#   ・エリア未設定になりにくい
#   ・ページ表示が速い
#   ・公式サイトへの追加通信が不要
#   ・Streamlit Cloudでも挙動が安定する
#
# CSVは今までどおり official_links.csv を使います。
# エリア情報だけはこの FACILITY_AREAS から取得します。
# ============================================================

# この巨大な辞書も「固定データ」。レストラン / ショップ名から所属エリアを引く表です。
FACILITY_AREAS = {'東京ディズニーランド': {'レストラン': {'れすとらん北齋': 'ワールドバザール',
                                                          'アイスクリームコーン': 'ワールドバザール',
                                                          'イーストサイド・カフェ': 'ワールドバザール',
                                                          'グレートアメリカン・ワッフルカンパニー': 'ワールドバザール',
                                                          'スウィートハート・カフェ': 'ワールドバザール',
                                                          'センターストリート・コーヒーハウス': 'ワールドバザール',
                                                          'リフレッシュメントコーナー': 'ワールドバザール',
                                                          'カフェ・オーリンズ': 'アドベンチャーランド',
                                                          'クリスタルパレス・レストラン': 'アドベンチャーランド',
                                                          'ザ・ガゼーボ': 'アドベンチャーランド',
                                                          'スキッパーズ・ギャレー': 'アドベンチャーランド',
                                                          'スクウィーザーズ・トロピカル・ジュースバー': 'アドベンチャーランド',
                                                          'チャイナボイジャー': 'アドベンチャーランド',
                                                          'パークサイドワゴン': 'アドベンチャーランド',
                                                          'フレッシュフルーツオアシス': 'アドベンチャーランド',
                                                          'ブルーバイユー・レストラン': 'アドベンチャーランド',
                                                          'ボイラールーム・バイツ': 'アドベンチャーランド',
                                                          'ポリネシアンテラス・レストラン': 'アドベンチャーランド',
                                                          'ロイヤルストリート・ベランダ': 'アドベンチャーランド',
                                                          'カウボーイ・クックハウス': 'ウエスタンランド',
                                                          'キャンプ・ウッドチャック・キッチン': 'ウエスタンランド',
                                                          'ザ・ダイヤモンドホースシュー': 'ウエスタンランド',
                                                          'ハングリー ベア レストラン': 'ウエスタンランド',
                                                          'ハングリーベア・レストラン': 'ウエスタンランド',
                                                          'ペコスビル・カフェ': 'ウエスタンランド',
                                                          'プラザパビリオン・レストラン': 'ウエスタンランド',
                                                          'グランマ・サラのキッチン': 'クリッターカントリー',
                                                          'ラケッティのラクーンサルーン': 'クリッターカントリー',
                                                          'ラケッティのラグーンサルーン': 'クリッターカントリー',
                                                          'キャプテンフックス・ギャレー': 'ファンタジーランド',
                                                          'クイーン・オブ・ハートのバンケットホール': 'ファンタジーランド',
                                                          'トルバドールタバン': 'ファンタジーランド',
                                                          'ラ・タベルヌ・ド・ガストン': 'ファンタジーランド',
                                                          'ル・フウズ': 'ファンタジーランド',
                                                          'ル・プティポッパー': 'ファンタジーランド',
                                                          'トゥーントーン・トリート': 'トゥーンタウン',
                                                          'ヒューイ・デューイ・ルーイのグッドタイム・カフェ': 'トゥーンタウン',
                                                          'トゥモローランド・テラス': 'トゥモローランド',
                                                          'パン・ギャラクティック・ピザ・ポート': 'トゥモローランド',
                                                          'ビッグポップ': 'トゥモローランド',
                                                          'フードブース（トゥモローランド側）': 'トゥモローランド',
                                                          'プラズマ・レイズ・ダイナー': 'トゥモローランド',
                                                          'ポッピングポッド': 'トゥモローランド'},
                                           'ショップ': {'カメラセンター': 'ワールドバザール',
                                                        'グランドエンポーリアム': 'ワールドバザール',
                                                        'シルエットスタジオ': 'ワールドバザール',
                                                        'タウンセンターファッション': 'ワールドバザール',
                                                        'ディズニー＆カンパニー': 'ワールドバザール',
                                                        'トイ・ステーション': 'ワールドバザール',
                                                        'ハウス・オブ・グリーティング': 'ワールドバザール',
                                                        'ハリントンズ・ジュエリー＆ウォッチ': 'ワールドバザール',
                                                        'ビビディ・バビディ・ブティック': 'ワールドバザール',
                                                        'ペイストリーパレス': 'ワールドバザール',
                                                        'ホームストア': 'ワールドバザール',
                                                        'マジックショップ': 'ワールドバザール',
                                                        'ワールドバザール・コンフェクショナリー': 'ワールドバザール',
                                                        'アドベンチャーランド・バザール': 'アドベンチャーランド',
                                                        'アドベンチャーランド・バザール（カプセルトイ）': 'アドベンチャーランド',
                                                        'クリスタルアーツ': 'アドベンチャーランド',
                                                        'クリスタルアーツ（制作物）※ガラス製品': 'アドベンチャーランド',
                                                        'ゴールデンガリオン': 'アドベンチャーランド',
                                                        'ジャングルカーニバル（丸太投げ）': 'アドベンチャーランド',
                                                        'ジャングルカーニバル（ボール転がし）': 'アドベンチャーランド',
                                                        'パイレーツ・トレジャー': 'アドベンチャーランド',
                                                        'パーティグラ・ギフト': 'アドベンチャーランド',
                                                        'ラ・プティート・パフュームリー': 'アドベンチャーランド',
                                                        'ル・マルシェ・ブルー': 'アドベンチャーランド',
                                                        'ウエスタンウエア': 'ウエスタンランド',
                                                        'ウエスタンランド写真館': 'ウエスタンランド',
                                                        'カントリーベア・バンドワゴン': 'ウエスタンランド',
                                                        'ゼネラルストア': 'ウエスタンランド',
                                                        'トレーディングポスト': 'ウエスタンランド',
                                                        'ハッピーキャンパーサプライ': 'ウエスタンランド',
                                                        'フロンティア・ウッドクラフト': 'ウエスタンランド',
                                                        'スプラッシュダウン・フォト': 'クリッターカントリー',
                                                        'ガラスの靴': 'ファンタジーランド',
                                                        'ガラスの靴（制作物）※ガラス製品': 'ファンタジーランド',
                                                        'キングダム・トレジャー': 'ファンタジーランド',
                                                        'ストロンボリズ・ワゴン': 'ファンタジーランド',
                                                        'ストロンボリーズ・ワゴン': 'ファンタジーランド',
                                                        'ハーモニーフェア': 'ファンタジーランド',
                                                        'ビレッジショップス': 'ファンタジーランド',
                                                        'プーさんコーナー': 'ファンタジーランド',
                                                        'ブレイブリトルテイラー・ショップ': 'ファンタジーランド',
                                                        'プレジャーアイランド・キャンディーズ': 'ファンタジーランド',
                                                        'ギャグファクトリー／ファイブ・アンド・ダイム': 'トゥーンタウン',
                                                        'ギャグファクトリー/ファイブ・アンド・ダイム（カプセルトイ）': 'トゥーンタウン',
                                                        'トゥーンタウン・デリバリー・カンパニー': 'トゥーンタウン',
                                                        'コズミック・エンカウンター': 'トゥモローランド',
                                                        'スターゲイザーサプライ': 'トゥモローランド',
                                                        'トレジャーコメット': 'トゥモローランド',
                                                        'トレジャーコメット（カプセルトイ）': 'トゥモローランド',
                                                        'モンスターズ・インク・カンパニーストア': 'トゥモローランド'}},
                  '東京ディズニーシー': {'レストラン': {'カフェ・ポルトフィーノ': 'メディテレーニアンハーバー',
                                                        'ザンビーニブラザーズリストランテ': 'メディテレーニアンハーバー',
                                                        'ザンビーニ・ブラザーズ・リストランテ': 'メディテレーニアンハーバー',
                                                        'マゼランズ': 'メディテレーニアンハーバー',
                                                        'マンマ・ビスコッティーズ・ベーカリー': 'メディテレーニアンハーバー',
                                                        'リストランテ・ディ・カナレット': 'メディテレーニアンハーバー',
                                                        'リフレスコス': 'メディテレーニアンハーバー',
                                                        'S.S.コロンビア・ダイニングルーム': 'アメリカンウォーターフロント',
                                                        'ケープコッド・クックオフ': 'アメリカンウォーターフロント',
                                                        'テディ・ルーズヴェルト・ラウンジ': 'アメリカンウォーターフロント',
                                                        'ドックサイドダイナー': 'アメリカンウォーターフロント',
                                                        'ニューヨーク・デリ': 'アメリカンウォーターフロント',
                                                        'ハドソンリバー・ハーベスト': 'アメリカンウォーターフロント',
                                                        'レストラン櫻': 'アメリカンウォーターフロント',
                                                        'ベイサイド・テイクアウト': 'ポートディスカバリー',
                                                        'ホライズンベイ・レストラン': 'ポートディスカバリー',
                                                        'エクスペディション・イート': 'ロストリバーデルタ',
                                                        'トロピック・アルズ': 'ロストリバーデルタ',
                                                        'ミゲルズ・エルドラド・キャンティーナ': 'ロストリバーデルタ',
                                                        'ユカタン・ベースキャンプ・グリル': 'ロストリバーデルタ',
                                                        'ユカタン・ベースキャンプ・グリル（テイクアウトカウンター）': 'ロストリバーデルタ',
                                                        'ロストリバークックハウス': 'ロストリバーデルタ',
                                                        'オープンセサミ': 'アラビアンコースト',
                                                        'カスバ・フードコート': 'アラビアンコースト',
                                                        'セバスチャンのカリプソキッチン': 'マーメイドラグーン',
                                                        'ノーチラスギャレー': 'ミステリアスアイランド',
                                                        'リフレッシュメント・ステーション': 'ミステリアスアイランド',
                                                        'ヴォルケイニア・レストラン': 'ミステリアスアイランド',
                                                        'アレンデール・ロイヤルバンケット': 'ファンタジースプリングス',
                                                        'オーケンのオーケーフード': 'ファンタジースプリングス',
                                                        'スナグリーダックリング': 'ファンタジースプリングス',
                                                        'ルックアウト・クックアウト': 'ファンタジースプリングス'},
                                         'ショップ': {
                                             'イル・ポスティーノ・ステーショナリー': 'メディテレーニアンハーバー',
                                             'ヴァレンティーナズ・スウィート': 'メディテレーニアンハーバー',
                                             'ヴィラ・ドナルド・ホームショップ': 'メディテレーニアンハーバー',
                                             'ヴェネツィアン・カーニバル・マーケット': 'メディテレーニアンハーバー',
                                             'エンポーリオ': 'メディテレーニアンハーバー',
                                             'ガッレリーア・ディズニー': 'メディテレーニアンハーバー',
                                             'スプレンディード': 'メディテレーニアンハーバー',
                                             'ピッコロメルカート': 'メディテレーニアンハーバー',
                                             'フィガロズ・クロージアー': 'メディテレーニアンハーバー',
                                             'フォトグラフィカ': 'メディテレーニアンハーバー',
                                             'ベッラ・ミンニ・コレクション': 'メディテレーニアンハーバー',
                                             'マーチャント・オブ・ヴェニス・コンフェクション': 'メディテレーニアンハーバー',
                                             'ミラマーレ': 'メディテレーニアンハーバー',
                                             'リメンブランツェ': 'メディテレーニアンハーバー',
                                             'アーント・ペグズ・ヴィレッジストア': 'アメリカンウォーターフロント',
                                             'スチームボート・ミッキーズ': 'アメリカンウォーターフロント',
                                             'スリンキー・ドッグのギフトトロリー': 'アメリカンウォーターフロント',
                                             'タワー・オブ・テラー・メモラビリア': 'アメリカンウォーターフロント',
                                             'タワー・オブ・テラー・メモラビリア（カプセルトイ）': 'アメリカンウォーターフロント',
                                             'ニュージーズ・ノヴェルティ': 'アメリカンウォーターフロント',
                                             'マクダックス・デパートメントストア': 'アメリカンウォーターフロント',
                                             'スカイウォッチャー・スーヴェニア': 'ポートディスカバリー',
                                             'ディスカバリーギフト': 'ポートディスカバリー',
                                             'エクスペディション・フォトアーカイヴ': 'ロストリバーデルタ',
                                             'ペドラーズ・アウトポスト': 'ロストリバーデルタ',
                                             'ルックアウト・トレーダー': 'ロストリバーデルタ',
                                             'ロストリバーアウトフィッター': 'ロストリバーデルタ',
                                             'スプリングス・トレジャー': 'ファンタジースプリングス',
                                             'ファンタジースプリングス・ギフト': 'ファンタジースプリングス',
                                             'アグラバーマーケットプレイス': 'アラビアンコースト',
                                             'アグラバーマーケットプレイス（制作物）※ガラス製品': 'アラビアンコースト',
                                             'アブーズ・バザール': 'アラビアンコースト',
                                             'ヴィレッジ・ショップス': 'アラビアンコースト',
                                             'キス・デ・ガール・ファッション': 'マーメイドラグーン',
                                             'コーヴ・オブ・ワンダー': 'マーメイドラグーン',
                                             'スリーピーホエール・ショップ': 'マーメイドラグーン',
                                             'スリーピーホエール・ショップ（制作物）※切り絵': 'マーメイドラグーン',
                                             'スリーピーホエール・ショップ（制作物）※似顔絵': 'マーメイドラグーン',
                                             'マーメイドトレジャー': 'マーメイドラグーン',
                                             'マーメイドトレジャー（カプセルトイ）': 'マーメイドラグーン',
                                             'ノーチラスギフト': 'ミステリアスアイランド',
                                             'ストロンボリーズ・ワゴン': 'メディテレーニアンハーバー'}}}

# ============================================================
# レストラン座席数
# ============================================================
#
# 東京ディズニーリゾート公式の各レストラン詳細ページにある
# 「座席数」を固定データとして持たせる。
#
# 公式に座席数の記載がある店舗だけ表示する。
# ワゴンなど、公式ページに座席数の記載がない施設は
# 無理に0席や不明と表示せず、座席バッジ自体を出さない。
#
# 表示例:
#   🪑 約690席
#
# ※ 座席数は将来変更される可能性があるため、
#    更新する場合はこの辞書だけ直せばよい。
# ============================================================

# この辞書はレストラン名 → 座席数の固定データ。
# 座席数を直す時はカード表示処理ではなく、まずここを直します。
RESTAURANT_SEATS = {'東京ディズニーシー': {'S.S.コロンビア・ダイニングルーム': 180,
                                           'アレンデール・ロイヤルバンケット': 570,
                                           'カフェ・ポルトフィーノ': 540,
                                           'ケープコッド・クックオフ': 420,
                                           'ザンビーニブラザーズリストランテ': 860,
                                           'スナグリーダックリング': 620,
                                           'セバスチャンのカリプソキッチン': 580,
                                           'テディ・ルーズヴェルト・ラウンジ': 120,
                                           'トロピック・アルズ': 40,
                                           'ニューヨーク・デリ': 480,
                                           'ノーチラスギャレー': 40,
                                           'ハドソンリバー・ハーベスト': 40,
                                           'ベイサイド・テイクアウト': 80,
                                           'ホライズンベイ・レストラン': 500,
                                           'マゼランズ': 170,
                                           'マンマ・ビスコッティーズ・ベーカリー': 150,
                                           'ミゲルズ・エルドラド・キャンティーナ': 580,
                                           'ユカタン・ベースキャンプ・グリル': 680,
                                           'リストランテ・ディ・カナレット': 180,
                                           'リフレスコス': 80,
                                           'リフレッシュメント・ステーション': 30,
                                           'ルックアウト・クックアウト': 200,
                                           'レストラン櫻': 250,
                                           'ロストリバークックハウス': 30,
                                           'ヴォルケイニア・レストラン': 590},
                    '東京ディズニーランド': {'れすとらん北齋': 260,
                                             'アイスクリームコーン': 170,
                                             'イーストサイド・カフェ': 240,
                                             'キャプテンフックス・ギャレー': 230,
                                             'キャンプ・ウッドチャック・キッチン': 400,
                                             'クイーン・オブ・ハートのバンケットホール': 500,
                                             'クリスタルパレス・レストラン': 310,
                                             'グランマ・サラのキッチン': 480,
                                             'グレートアメリカン・ワッフルカンパニー': 140,
                                             'ザ・ガゼーボ': 90,
                                             'ザ・ダイヤモンドホースシュー': 190,
                                             'スウィートハート・カフェ': 90,
                                             'センターストリート・コーヒーハウス': 160,
                                             'チャイナボイジャー': 230,
                                             'トゥモローランド・テラス': 1360,
                                             'ハングリー ベア レストラン': 690,
                                             'ハングリーベア・レストラン': 690,
                                             'パン・ギャラクティック・ピザ・ポート': 630,
                                             'ヒューイ・デューイ・ルーイのグッドタイム・カフェ': 420,
                                             'ブルーバイユー・レストラン': 140,
                                             'プラザパビリオン・レストラン': 380,
                                             'プラズマ・レイズ・ダイナー': 860,
                                             'ペコスビル・カフェ': 50,
                                             'ボイラールーム・バイツ': 150,
                                             'ポリネシアンテラス・レストラン': 210,
                                             'ラ・タベルヌ・ド・ガストン': 130,
                                             'リフレッシュメントコーナー': 150,
                                             'ロイヤルストリート・ベランダ': 20}}


# ------------------------------------------------------------------
# 関数：get_restaurant_seat_count()
# 役割：固定表から座席数を探す
# 入力：park_name / restaurant_name
# 出力：座席数またはNone
# どこで使う：レストランカード
# 自分で触るなら：座席検索を変える時
# ------------------------------------------------------------------
def get_restaurant_seat_count(park_name, restaurant_name):
    """
    レストラン名から座席数を取得する。

    normalize_name()で比較するため、
    「・」「空白」などの表記揺れがあっても一致しやすい。
    """
    target_name = normalize_name(
        restaurant_name
    )

    park_restaurants = RESTAURANT_SEATS.get(
        park_name,
        {},
    )

    for name, seat_count in park_restaurants.items():
        if normalize_name(name) == target_name:
            return seat_count

    return None


# ------------------------------------------------------------------
# 関数：resolve_facility_area()
# 役割：施設1件の表示用エリアを決める
# 入力：row / park_name
# 出力：エリア名
# どこで使う：all_dfのarea列
# 自分で触るなら：エリア判定を変える時
# ------------------------------------------------------------------
def resolve_facility_area(row, park_name):
    """
    施設1件の所属エリアを返す。

    アトラクション:
        既存のATTRACTION_AREASから作成済みのarea列をそのまま使う。

    レストラン / ショップ:
        FACILITY_AREASに登録した施設名からエリアを取得する。

    施設名の「・」「/」「空白」などの表記揺れは
    normalize_name()で吸収して比較する。
    """
    facility_type = str(
        row.get("type") or ""
    )

    # アトラクションは既存のエリア判定をそのまま使用
    if facility_type == "アトラクション":
        return str(
            row.get("area")
            or "エリア未設定"
        )

    # レストラン / ショップ以外はエリア不要
    if facility_type not in {
        "レストラン",
        "ショップ",
    }:
        return ""

    facility_map = (
        FACILITY_AREAS
        .get(park_name, {})
        .get(facility_type, {})
    )

    target_name = normalize_name(
        row.get("name_ja")
    )

    # 固定表の施設名と正規化して完全一致させる
    for facility_name, area_name in facility_map.items():
        if normalize_name(facility_name) == target_name:
            return area_name

    # 万一、新店舗などがCSVへ追加されたのに
    # FACILITY_AREASへの追加を忘れた場合だけここへ来る。
    return "エリア未設定"


# ------------------------------------------------------------------
# 関数：match_restaurant_info()
# 役割：アプリ店舗名と公式店舗名を類似度で照合
# 入力：restaurant_name / records
# 出力：recordまたはNone
# どこで使う：restaurant_info列
# 自分で触るなら：照合しきい値を変える時
# ------------------------------------------------------------------
def match_restaurant_info(
        restaurant_name,
        restaurant_records,
):
    """アプリ内の店舗名と公式店舗情報を照合する。"""
    target = normalize_name(restaurant_name)

    if not target:
        return None

    best = None
    best_score = 0.0

    for record in restaurant_records:
        candidate = record["normalized"]

        if not candidate:
            continue

        if target == candidate:
            score = 1.0

        elif (
                target in candidate
                or candidate in target
        ):
            score = 0.95

        else:
            score = SequenceMatcher(
                None,
                target,
                candidate,
            ).ratio()

        if score > best_score:
            best_score = score
            best = record

    if best_score < 0.82:
        return None

    return best


# ------------------------------------------------------------------
# 関数：overpass_query()
# 役割：OSMへ送る検索文を作る
# 入力：bbox
# 出力：Overpass QL文字列
# どこで使う：get_osm_pois内
# 自分で触るなら：取得施設種別を変える時
# ------------------------------------------------------------------
def overpass_query(bbox):
    """レストラン・ショップ・ランドマーク用のOverpassクエリ。"""
    south, west, north, east = bbox

    return f"""
    [out:json][timeout:25];
    (
      nwr["amenity"~"restaurant|cafe|fast_food|food_court"]
          ({south},{west},{north},{east});
      nwr["shop"]
          ({south},{west},{north},{east});
    );
    out center tags;
    """


@st.cache_data(ttl=21600)
# ------------------------------------------------------------------
# 関数：get_osm_pois()
# 役割：OSMからレストラン/ショップを取得
# 入力：park_name
# 出力：list[dict]
# どこで使う：poi_df作成
# 自分で触るなら：OSM取得項目を変える時
# ------------------------------------------------------------------
def get_osm_pois(park_name):
    """
    OpenStreetMapから飲食・買物・ランドマークを取る。
    OSM側に登録がない項目は取得できない。
    """
    response = requests.post(
        OVERPASS_API,
        data={"data": overpass_query(PARKS[park_name]["bbox"])},
        headers={"User-Agent": "DisneyParkNavigatorPrototype/1.0"},
        timeout=35,
    )
    response.raise_for_status()

    rows = []

    for element in response.json().get("elements", []):
        tags = element.get("tags") or {}
        name = (
                tags.get("name:ja")
                or tags.get("name")
                or tags.get("name:en")
        )

        if not name:
            continue

        lat = element.get("lat")
        lon = element.get("lon")

        if lat is None or lon is None:
            center = element.get("center") or {}
            lat = center.get("lat")
            lon = center.get("lon")

        if lat is None or lon is None:
            continue

        amenity = tags.get("amenity", "")
        shop = tags.get("shop", "")

        if amenity in {
            "restaurant",
            "cafe",
            "fast_food",
            "food_court",
        }:
            poi_type = "レストラン"
        elif shop:
            poi_type = "ショップ"
        else:
            continue

        osm_id = f"osm:{element.get('type')}:{element.get('id')}"

        rows.append(
            {
                "entity_id": osm_id,
                "name_en": name,
                "name_ja": name,
                "lat": float(lat),
                "lon": float(lon),
                "type": poi_type,
                "status": "UNKNOWN",
                "wait_time": pd.NA,
                "osm_tags": tags,
            }
        )

    return rows


# ------------------------------------------------------------------
# 関数：contains_japanese()
# 役割：日本語文字を含むか判定
# 入力：value
# 出力：True/False
# どこで使う：日本語名フィルタ
# 自分で触るなら：判定範囲を変える時
# ------------------------------------------------------------------
def contains_japanese(value):
    """ひらがな・カタカナ・漢字が含まれるか。"""
    return bool(
        re.search(
            r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]",
            str(value or ""),
        )
    )


# ------------------------------------------------------------------
# 関数：deduplicate_facilities()
# 役割：同名施設の重複を1件へ整理
# 入力：frame
# 出力：DataFrame
# どこで使う：all_df/favorite_df整理
# 自分で触るなら：重複基準を変える時
# ------------------------------------------------------------------
def deduplicate_facilities(frame):
    """
    施設名を正規化して重複を1件にまとめる。
    ThemeParks.wiki由来のアトラクションをOSM由来より優先する。
    """
    if frame.empty:
        return frame

    result = frame.copy()
    result["_normalized_name"] = result["name_ja"].map(normalize_name)
    result["_source_priority"] = result["entity_id"].astype(str).map(
        lambda value: 1 if value.startswith("osm:") else 0
    )

    result = result.sort_values(
        ["_source_priority", "distance_m"],
        ascending=[True, True],
    )

    result = result.drop_duplicates(
        subset=["type", "_normalized_name"],
        keep="first",
    )

    return result.drop(
        columns=["_normalized_name", "_source_priority"],
        errors="ignore",
    )


# ※ OFFICIAL_LINKS_FILEは上の基本設定でも同じ値を定義済みです。
# 今のままでも動きますが、整理するなら1か所へまとめられます。
OFFICIAL_LINKS_FILE = BASE_DIR / "official_links.csv"


# ------------------------------------------------------------------
# 東京ディズニー公式の個別詳細ページ
# ------------------------------------------------------------------


# ------------------------------------------------------------------
# 関数：normalize_name()
# 役割：施設名の記号・空白差を消して比較しやすくする
# 入力：value
# 出力：正規化文字列
# どこで使う：名称照合全般
# 自分で触るなら：表記揺れルールを変える時
# ------------------------------------------------------------------
def normalize_name(value):
    """施設名の記号差を吸収して照合する。"""
    value = unicodedata.normalize(
        "NFKC",
        str(value or ""),
    ).lower()

    value = value.replace("ヴ", "ブ")
    value = value.replace("･", "・")
    value = value.replace("/", "・")

    value = re.sub(
        r"[\s　・･'\"“”‘’()（）\[\]【】"
        r"\-‐-–—~〜!！?？:：,，.。]",
        "",
        value,
    )

    return value


@st.cache_data
# ------------------------------------------------------------------
# 関数：load_official_links()
# 役割：official_links.csvを辞書へ変換
# 入力：入力なし
# 出力：公式情報辞書
# どこで使う：lookup_officialで使用
# 自分で触るなら：CSV列を変える時
# ------------------------------------------------------------------
def load_official_links():
    """公式リンクと、CSVに保存した公式サービス情報を読む。"""
    if not OFFICIAL_LINKS_FILE.exists():
        return {}

    df = pd.read_csv(
        OFFICIAL_LINKS_FILE,
        dtype=str,
    ).fillna("")

    required = {
        "park",
        "type",
        "name_ja",
        "official_url",
    }
    if not required.issubset(df.columns):
        return {}

    # ------------------------------------------------------------------
    # 関数：as_bool()
    # 役割：CSVの文字をTrue/Falseへ変換する内部関数
    # 入力：value
    # 出力：True/False
    # どこで使う：load_official_links内
    # 自分で触るなら：真偽値表記を増やす時
    # ------------------------------------------------------------------
    def as_bool(value):
        return str(value).strip().lower() in {
            "1", "true", "yes", "対象", "あり"
        }

    links = {}

    for _, row in df.iterrows():
        park = row["park"].strip()
        facility_type = row["type"].strip()
        name = row["name_ja"].strip()
        url = row["official_url"].strip()

        if not park or not facility_type or not name or not url:
            continue

        key = (
            park,
            facility_type,
            normalize_name(name),
        )

        links[key] = {
            "name": name,
            "normalized": normalize_name(name),
            "url": url,
            "mobile_order": as_bool(row.get("mobile_order", "")),
            "priority_seating": as_bool(row.get("priority_seating", "")),
        }

    return links


# ------------------------------------------------------------------
# 関数：detail_pattern()
# 役割：公式詳細URLのパターンを作る
# 入力：park_name / facility_type
# 出力：regexまたはNone
# どこで使う：get_official_facilities内
# 自分で触るなら：URL構造が変わった時
# ------------------------------------------------------------------
def detail_pattern(park_name, facility_type):
    park_code = "tdl" if park_name == "東京ディズニーランド" else "tds"
    section = {
        "アトラクション": "attraction",
        "レストラン": "restaurant",
        "ショップ": "shop",
    }.get(facility_type)

    if not section:
        return None

    return re.compile(
        rf"/{park_code}/{section}/detail/\d+/?$"
    )


@st.cache_data(ttl=21600)
# ------------------------------------------------------------------
# 関数：get_official_facilities()
# 役割：公式一覧から個別詳細URLと正式名を取得
# 入力：park_name / facility_type
# 出力：list[dict]
# どこで使う：match_official_facilityから使用
# 自分で触るなら：公式HTMLが変わった時
# ------------------------------------------------------------------
def get_official_facilities(park_name, facility_type):
    """
    公式一覧から detail/数字/ のURLを抽出し、
    各個別ページを開いて正式な施設名を取得する。
    """
    list_url = PARKS[park_name]["official"].get(facility_type)
    pattern = detail_pattern(park_name, facility_type)

    if not list_url or not pattern:
        return []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        "Accept-Language": "ja-JP,ja;q=0.9",
    }

    try:
        response = requests.get(
            list_url,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    base_host = urllib.parse.urlparse(list_url).netloc
    detail_urls = set()

    for anchor in soup.find_all("a", href=True):
        absolute_url = urllib.parse.urljoin(
            list_url,
            anchor.get("href", "").strip(),
        )
        parsed = urllib.parse.urlparse(absolute_url)

        if (
                parsed.netloc == base_host
                and pattern.search(parsed.path)
        ):
            detail_urls.add(absolute_url)

    # ------------------------------------------------------------------
    # 関数：fetch_detail()
    # 役割：公式詳細ページ1件から施設名を抜く内部関数
    # 入力：detail_url
    # 出力：dictまたはNone
    # どこで使う：get_official_facilities内
    # 自分で触るなら：名前抽出方法を変える時
    # ------------------------------------------------------------------
    def fetch_detail(detail_url):
        try:
            detail_response = requests.get(
                detail_url,
                headers=headers,
                timeout=20,
            )
            detail_response.raise_for_status()
        except requests.RequestException:
            return None

        detail_soup = BeautifulSoup(
            detail_response.text,
            "html.parser",
        )

        candidates = []

        for selector in [
            "h1",
            "main h2",
            'meta[property="og:title"]',
            'meta[name="twitter:title"]',
            "title",
        ]:
            for node in detail_soup.select(selector):
                if node.name == "meta":
                    text = node.get("content", "")
                else:
                    text = node.get_text(" ", strip=True)

                text = re.sub(
                    r"^【公式】|[｜|]\s*東京ディズニー.*$",
                    "",
                    str(text),
                ).strip()

                if 2 <= len(text) <= 100:
                    candidates.append(text)

        if not candidates:
            return None

        # h1があれば先頭になるので、最初の日本語候補を優先
        name = next(
            (
                item
                for item in candidates
                if contains_japanese(item)
            ),
            candidates[0],
        )

        return {
            "name": name,
            "normalized": normalize_name(name),
            "url": detail_url,
        }

    records = []

    # 詳細ページを並列取得して待ち時間を抑える
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(fetch_detail, url): url
            for url in detail_urls
        }

        for future in as_completed(futures):
            record = future.result()
            if (
                    record
                    and record["normalized"]
            ):
                records.append(record)

    return records


# ------------------------------------------------------------------
# 関数：official_match_score()
# 役割：施設名の一致度を0〜1で採点
# 入力：target / candidate
# 出力：float
# どこで使う：公式照合
# 自分で触るなら：一致判定を変える時
# ------------------------------------------------------------------
def official_match_score(target, candidate):
    """完全一致・包含・類似度を組み合わせて採点する。"""
    if not target or not candidate:
        return 0.0
    if target == candidate:
        return 1.0
    if target in candidate or candidate in target:
        shorter = min(len(target), len(candidate))
        longer = max(len(target), len(candidate))
        return 0.88 + 0.1 * (shorter / longer)
    return SequenceMatcher(None, target, candidate).ratio()


# ------------------------------------------------------------------
# 関数：match_official_facility()
# 役割：高確度で一致する公式個別ページを返す
# 入力：park_name / type / name
# 出力：dictまたはNone
# どこで使う：公式詳細候補取得
# 自分で触るなら：誤リンクしきい値を変える時
# ------------------------------------------------------------------
def match_official_facility(park_name, facility_type, facility_name):
    """
    個別詳細ページが高い確度で一致した場合だけURLを返す。
    一覧ページへのフォールバックはしない。
    """
    entries = get_official_facilities(park_name, facility_type)
    target = normalize_name(facility_name)

    if not target or not entries:
        return None

    scored = [
        (
            official_match_score(target, entry["normalized"]),
            entry,
        )
        for entry in entries
    ]
    score, best = max(scored, key=lambda item: item[0])

    # 誤リンク防止。個別ページを特定できないときはボタンを出さない。
    if score < 0.80:
        return None

    return {
        **best,
        "score": score,
    }


# ------------------------------------------------------------------
# 関数：get_suspension_info()
# 役割：施設名に合う公式休止recordを探す
# 入力：facility_name / records
# 出力：recordまたはNone
# どこで使う：休止情報列作成
# 自分で触るなら：休止名照合を変える時
# ------------------------------------------------------------------
def get_suspension_info(
        facility_name,
        suspension_records,
):
    """施設名に一致する公式休止情報を返す。"""
    target = normalize_name(facility_name)

    best = None
    best_score = 0.0

    for record in suspension_records:
        candidate = record["normalized"]

        if not target or not candidate:
            continue

        if target == candidate:
            score = 1.0
        elif target in candidate or candidate in target:
            score = 0.95
        else:
            score = SequenceMatcher(
                None,
                target,
                candidate,
            ).ratio()

        if score > best_score:
            best_score = score
            best = record

    if best_score < 0.86:
        return None

    return best


# ------------------------------------------------------------------
# 関数：suspension_status()
# 役割：今日の日付から休止中/休止予定を判定
# 入力：record
# 出力：状態dict
# どこで使う：公式休止表示
# 自分で触るなら：期間判定を変える時
# ------------------------------------------------------------------
def suspension_status(record):
    """
    公式休止期間から、
    現在休止中・今後休止予定を判定する。
    """
    if not record:
        return {
            "is_suspended": False,
            "is_upcoming": False,
            "text": "",
        }

    today = date.today()
    start_date = record["start_date"]
    end_date = record["end_date"]

    period_text = (
        f"{record['start_text']}〜"
        f"{record['end_text']}"
    )

    if start_date and today < start_date:
        return {
            "is_suspended": False,
            "is_upcoming": True,
            "text": f"休止予定：{period_text}",
        }

    if start_date and today >= start_date:
        if end_date is None or today <= end_date:
            return {
                "is_suspended": True,
                "is_upcoming": False,
                "text": f"公式休止中：{period_text}",
            }

    return {
        "is_suspended": False,
        "is_upcoming": False,
        "text": "",
    }


# ======================================================================
# ここまで 5. API取得・公式情報の照合
# ======================================================================

# ======================================================================
# 6. 計算・表示情報の加工
# ======================================================================
# GPSの値を整える、距離を計算する、表示用情報を作る補助処理です。
# ------------------------------------------------------------------
# 計算・表示情報
# GPS・距離・表示用情報の加工
# ------------------------------------------------------------------


# ------------------------------------------------------------------
# 関数：scroll_to_anchor()
# 役割：JSで指定位置へスクロール
# 入力：anchor_id
# 出力：戻り値なし
# どこで使う：rerun後の画面移動
# 自分で触るなら：スクロール方法を変える時
# ------------------------------------------------------------------
def scroll_to_anchor(anchor_id):
    """再実行後に指定した画面位置へ移動する。"""
    components.html(
        f"""
        <script>
        const target = window.parent.document.getElementById(
            {anchor_id!r}
        );
        if (target) {{
            setTimeout(() => {{
                target.scrollIntoView({{
                    behavior: "smooth",
                    block: "start"
                }});
            }}, 250);
        }}
        </script>
        """,
        height=0,
        width=0,
    )


# ------------------------------------------------------------------
# 関数：consume_scroll_target()
# 役割：スクロール予約を1回実行して消す
# 入力：anchor_id
# 出力：戻り値なし
# どこで使う：status/route表示前
# 自分で触るなら：画面移動管理を変える時
# ------------------------------------------------------------------
def consume_scroll_target(anchor_id):
    """このアンカーへの移動予約があれば一度だけ実行する。"""
    if st.session_state.get("scroll_target") != anchor_id:
        return

    scroll_to_anchor(anchor_id)
    st.session_state.pop("scroll_target", None)


# ------------------------------------------------------------------
# 関数：normalize_location()
# 役割：GPS返却値から緯度経度を取り出す
# 入力：value
# 出力：位置dictまたはNone
# どこで使う：GPS取得直後
# 自分で触るなら：GPSライブラリ形式が変わった時
# ------------------------------------------------------------------
def normalize_location(value):
    """GPS部品の返却形式から緯度・経度を取り出す。"""
    if not isinstance(value, dict):
        return None

    for candidate in (
            value,
            value.get("coords"),
            value.get("location"),
    ):
        if not isinstance(candidate, dict):
            continue

        if (
                candidate.get("latitude") is not None
                and candidate.get("longitude") is not None
        ):
            return {
                "latitude": float(candidate["latitude"]),
                "longitude": float(candidate["longitude"]),
            }

    return None


# ------------------------------------------------------------------
# 関数：distance_m()
# 役割：2地点の直線距離mを計算
# 入力：lat1/lon1/lat2/lon2
# 出力：float(m)
# どこで使う：全施設距離計算
# 自分で触るなら：距離計算を変える時
# ------------------------------------------------------------------
def distance_m(lat1, lon1, lat2, lon2):
    """2地点の直線距離。"""
    radius = 6_371_000

    lat1, lon1, lat2, lon2 = map(
        math.radians,
        [lat1, lon1, lat2, lon2],
    )

    d_lat = lat2 - lat1
    d_lon = lon2 - lon1

    value = (
            math.sin(d_lat / 2) ** 2
            + math.cos(lat1)
            * math.cos(lat2)
            * math.sin(d_lon / 2) ** 2
    )

    return radius * 2 * math.atan2(
        math.sqrt(value),
        math.sqrt(1 - value),
    )


# ------------------------------------------------------------------
# 関数：poi_details()
# 役割：OSMタグを料理/形式/価格等へ整理
# 入力：row
# 出力：表示用dict
# どこで使う：検索・施設詳細
# 自分で触るなら：表示項目を増やす時
# ------------------------------------------------------------------
def poi_details(row):
    """OSMタグから施設説明を組み立てる。"""
    tags = row.get("osm_tags") or {}

    cuisine_raw = tags.get("cuisine", "")
    cuisine = (
        cuisine_raw.replace(";", "・")
        if cuisine_raw
        else "情報なし"
    )

    amenity_labels = {
        "restaurant": "テーブルサービス系",
        "cafe": "カフェ系",
        "fast_food": "カウンターサービス系",
        "food_court": "フードコート系",
    }

    style = amenity_labels.get(
        tags.get("amenity", ""),
        "情報なし",
    )

    price = (
            tags.get("price")
            or tags.get("charge")
            or tags.get("fee")
            or "API情報なし"
    )

    opening_hours = tags.get("opening_hours") or "情報なし"

    return {
        "cuisine": cuisine,
        "style": style,
        "price": price,
        "opening_hours": opening_hours,
    }


# ------------------------------------------------------------------
# 関数：is_cool_spot()
# 役割：涼しい候補か判定
# 入力：row
# 出力：True/False
# どこで使う：cool_spot列
# 自分で触るなら：涼しい条件を変える時
# ------------------------------------------------------------------
def is_cool_spot(row):
    """
    涼しい場所の候補判定。
    アトラクションはCSVの待機列情報、
    その他施設はOSMタグと施設種別から判定する。
    """
    if row["type"] == "アトラクション":
        return row.get("queue_type") in {"屋内", "屋根あり"}

    tags = row.get("osm_tags") or {}

    if (
            tags.get("indoor") == "yes"
            or tags.get("covered") == "yes"
            or tags.get("building")
    ):
        return True

    # レストラン・ショップは屋内店舗が多いため候補扱い。
    # 確定情報ではないので表示上も「候補」とする。
    return row["type"] in {"レストラン", "ショップ"}


# ------------------------------------------------------------------
# 関数：official_url()
# 役割：施設種別の公式一覧URLを返す
# 入力：park_name / type
# 出力：URL
# どこで使う：official_url列
# 自分で触るなら：URL扱いを変える時
# ------------------------------------------------------------------
def official_url(park_name, facility_type):
    """施設種別に対応する東京ディズニー公式ページ。"""
    return PARKS[park_name]["official"].get(
        facility_type,
        PARKS[park_name]["official"]["ランドマーク"],
    )


# ------------------------------------------------------------------
# 関数：balanced_score()
# 役割：距離と待ち時間を半々で点数化
# 入力：frame
# 出力：DataFrame
# どこで使う：バランス順
# 自分で触るなら：重みを変える時
# ------------------------------------------------------------------
def balanced_score(frame):
    """
    距離と待ち時間を0～1へ正規化し、同じ重みで合算する。
    待ち時間がない施設は距離を中心に評価する。
    """
    result = frame.copy()

    max_distance = max(float(result["distance_m"].max()), 1.0)
    result["_distance_score"] = result["distance_m"] / max_distance

    attraction_mask = result["type"] == "アトラクション"
    waits = pd.to_numeric(
        result.loc[attraction_mask, "wait_time"],
        errors="coerce",
    )

    max_wait = max(float(waits.max()) if waits.notna().any() else 1.0, 1.0)

    result["_wait_score"] = 0.0
    result.loc[attraction_mask, "_wait_score"] = (
            pd.to_numeric(
                result.loc[attraction_mask, "wait_time"],
                errors="coerce",
            )
            .fillna(max_wait)
            / max_wait
    )

    result["_balance_score"] = (
            result["_distance_score"] * 0.5
            + result["_wait_score"] * 0.5
    )

    return result


# ======================================================================
# ここまで 6. 計算・表示情報の加工
# ======================================================================

# ======================================================================
# 7. 徒歩ルート関係
# ======================================================================
# ------------------------------------------------------------------
# 徒歩ルート
# Valhalla APIを使ったパーク内徒歩ルート
# ------------------------------------------------------------------


# ------------------------------------------------------------------
# 関数：decode_polyline6()
# 役割：Valhallaの圧縮ルートを座標列へ戻す
# 入力：encoded
# 出力：座標list
# どこで使う：get_walking_route内
# 自分で触るなら：通常は触らなくてよい
# ------------------------------------------------------------------
def decode_polyline6(encoded):
    """Valhallaのencoded polyline（精度6）を緯度経度へ戻す。"""
    coordinates = []
    index = 0
    lat = 0
    lon = 0
    factor = 1_000_000

    while index < len(encoded):
        values = []

        for _ in range(2):
            result = 0
            shift = 0

            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5

                if byte < 0x20:
                    break

            delta = ~(result >> 1) if result & 1 else result >> 1
            values.append(delta)

        lat += values[0]
        lon += values[1]
        coordinates.append([lat / factor, lon / factor])

    return coordinates


@st.cache_data(ttl=300)
# ------------------------------------------------------------------
# 関数：get_walking_route()
# 役割：Valhallaで徒歩ルートを取得
# 入力：出発/目的地の緯度経度
# 出力：route dict
# どこで使う：route_target表示時
# 自分で触るなら：ルートAPIを変える時
# ------------------------------------------------------------------
def get_walking_route(start_lat, start_lon, end_lat, end_lon):
    """
    Valhallaの歩行者ルートを取得する。
    OSM上の通路データを使うため、当日の通行規制までは反映しない。
    """
    request_data = {
        "locations": [
            {"lat": start_lat, "lon": start_lon},
            {"lat": end_lat, "lon": end_lon},
        ],
        "costing": "pedestrian",
        "units": "kilometers",
        "language": "ja-JP",
        "directions_options": {
            "units": "kilometers",
        },
    }

    response = requests.get(
        VALHALLA_API,
        params={
            "json": json.dumps(
                request_data,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        },
        timeout=30,
    )
    response.raise_for_status()

    trip = response.json().get("trip") or {}
    legs = trip.get("legs") or []

    if not legs:
        raise ValueError("徒歩ルートが返されませんでした。")

    summary = trip.get("summary") or {}
    shape = legs[0].get("shape")

    if not shape:
        raise ValueError("ルート形状が返されませんでした。")

    return {
        "points": decode_polyline6(shape),
        "distance_km": summary.get("length"),
        "time_seconds": summary.get("time"),
    }


# ======================================================================
# ここまで 7. 徒歩ルート関係
# ======================================================================

# ======================================================================
# 8. 地図を作る関数
# ======================================================================
# ここでは地図を「作る」。実際に画面へ出すのは後半のfolium_static()です。
# ------------------------------------------------------------------
# 地図
# Foliumで現在地・施設・ルートを描画
# ------------------------------------------------------------------


# ------------------------------------------------------------------
# 関数：add_facility_marker()
# 役割：地図へ施設マーカー1件を追加
# 入力：map / row / favorites
# 出力：戻り値なし
# どこで使う：make_overview_map内
# 自分で触るなら：ピン/色/吹き出しを変える時
# ------------------------------------------------------------------
def add_facility_marker(disney_map, row, favorites):
    """施設マーカーを追加する。"""
    entity_id = str(row["entity_id"])
    is_favorite = entity_id in favorites
    type_icon = TYPE_ICONS.get(row["type"], "📍")
    marker_text = favorites.get(entity_id, type_icon)

    wait_value = row.get("wait_time")
    status_text = str(
        row.get("状況", "情報なし")
    )

    if status_text == "休止中":
        wait_text = "休止中"

    elif status_text == "一時休止":
        wait_text = "一時休止"

    elif status_text == "受付終了":
        wait_text = "受付終了"

    elif pd.notna(wait_value):
        wait_text = f"{int(wait_value)}分"

    else:
        wait_text = "待ち時間情報なし"

    display_name = row["name_ja"]

    popup = f"""
    <b>{marker_text} {display_name}</b><br>
    種類：{row["type"]}<br>
    直線距離：{int(row["distance_m"])}m<br>
    待ち時間：{wait_text}<br>
    """

    if is_favorite:
        marker_icon = folium.DivIcon(
            html=f"""
            <div style="
                width:34px;
                height:34px;
                border-radius:50%;
                background:white;
                border:3px solid #f5b301;
                box-shadow:0 2px 5px rgba(0,0,0,.35);
                font-size:20px;
                line-height:28px;
                text-align:center;
            ">{marker_text}</div>
            """,
            icon_size=(34, 34),
            icon_anchor=(17, 17),
        )
    else:
        color = {
            "アトラクション": "red",
            "レストラン": "green",
            "ショップ": "purple",
            "ランドマーク": "cadetblue",
        }.get(row["type"], "gray")

        marker_icon = folium.Icon(
            color=color,
            icon="info-sign",
        )

    folium.Marker(
        [row["lat"], row["lon"]],
        tooltip=f"{marker_text} {display_name}",
        popup=folium.Popup(popup, max_width=300),
        icon=marker_icon,
    ).add_to(disney_map)


# ------------------------------------------------------------------
# 関数：make_overview_map()
# 役割：一覧用地図を作る
# 入力：frame / location / favorites
# 出力：folium.Map
# どこで使う：一覧地図/マップタブ
# 自分で触るなら：地図全体を変える時
# ------------------------------------------------------------------
def make_overview_map(frame, location, favorites, favorite_frame=None):
    """一覧確認用の小さい地図。"""

    # ----------------------------------------------------------
    # まず現在地を地図の中心として入れておく
    # ----------------------------------------------------------
    # これを最初に入れておけば、
    # 下の条件に入らなかった場合でも
    # map_lat / map_lon が必ず存在する。
    map_lat = location["latitude"]
    map_lon = location["longitude"]


    # ----------------------------------------------------------
    # 表示する施設がある場合
    # ----------------------------------------------------------
    # frameには現在画面に表示する施設が入っている。
    #
    # 例：
    # ワールドバザールを選択
    # ↓
    # frameにはワールドバザールの施設だけが入る
    #
    # その施設の緯度・経度の平均を
    # 地図の中心にする。

    if not frame.empty:
        # 施設の緯度の平均
        map_lat = frame["lat"].mean()
        # 施設の軽度の平均
        map_lon = frame["lon"].mean()
    else:
        #施設が一件もない場合は
        #現在地を地図の中心にする
        map_lat = location["latitude"],
        map_lon = location["longitude"],

 # ----------------------------------------------------------
 # 地図を作る
 # ----------------------------------------------------------
    disney_map = folium.Map(location=[map_lat, map_lon,],
        zoom_start=16,
        control_scale=True,
        dragging=True,
        touch_zoom=True,
        double_click_zoom=True,
        box_zoom=True,
        keyboard=True,
        scroll_wheel_zoom=False,
    )
    # ----------------------------------------------------------
    # GPS現在地
    # ----------------------------------------------------------
    folium.Marker(
        [
            location["latitude"],
            location["longitude"],
        ],
        tooltip="現在地",
        icon=folium.Icon(
            color="blue",
            icon="user",
        ),
    ).add_to(disney_map)
    # ----------------------------------------------------------
    # 今選択しているエリアの施設
    # ----------------------------------------------------------
    for _, row in frame.head(60).iterrows():
        add_facility_marker(
            disney_map,
            row,
            favorites,
        )

        # ----------------------------------------------------------
        # パーク内のお気に入りを追加
        # ----------------------------------------------------------
        # favorite_frameには、
        # 今選択しているランドまたはシーのお気に入り全部を入れる。
    if favorite_frame is not None and not favorite_frame.empty:

            # すでにエリア施設として地図へ追加した施設ID
            # 同じ施設を2重に出さないために使う。
            displayed_ids = set(
                frame["entity_id"]
                .astype(str)
                .tolist()
            )

            # パーク内のお気に入りを1件ずつ確認
            for _, favorite_row in favorite_frame.iterrows():

                entity_id = str(
                    favorite_row["entity_id"]
                )

                # エリア側ですでに表示済みなら追加しない
                if entity_id in displayed_ids:
                    continue

                # お気に入り施設を地図へ追加
                add_facility_marker(
                    disney_map,
                    favorite_row,
                    favorites,
                )

    return disney_map


# ------------------------------------------------------------------
# 関数：make_route_map()
# 役割：徒歩ルート地図を作る
# 入力：route / target / location
# 出力：folium.Map
# どこで使う：ルート表示
# 自分で触るなら：線/ピンを変える時
# ------------------------------------------------------------------
def make_route_map(route, target, location):
    """選択施設までの徒歩ルート専用地図。"""
    disney_map = folium.Map(
        location=[
            location["latitude"],
            location["longitude"],
        ],
        zoom_start=17,
        control_scale=True,
        scroll_wheel_zoom=False,
    )

    folium.PolyLine(
        route["points"],
        color="#2563eb",
        weight=7,
        opacity=0.85,
        tooltip="徒歩ルート",
    ).add_to(disney_map)

    folium.Marker(
        [
            location["latitude"],
            location["longitude"],
        ],
        tooltip="現在地",
        icon=folium.Icon(
            color="blue",
            icon="user",
        ),
    ).add_to(disney_map)

    folium.Marker(
        [target["lat"], target["lon"]],
        tooltip=target["name_ja"],
        icon=folium.Icon(
            color="red",
            icon="flag",
        ),
    ).add_to(disney_map)

    disney_map.fit_bounds(
        route["points"],
        padding=(20, 20),
    )

    return disney_map


# ======================================================================
# ここまで 8. 地図を作る関数
# ======================================================================

# ======================================================================
# 9. ここから実際の画面処理（アプリ本体）
# ======================================================================
# ここより上は主に「設定」と「関数定義」。
# ここから下はStreamlitが上から順番に実行し、データ取得・加工・表示まで行います。
# ------------------------------------------------------------------
# 画面
# ここからStreamlitのUIを組み立てる
# ------------------------------------------------------------------

st.markdown(
    '<div class="park-switch-label">PARK</div>',
    unsafe_allow_html=True,
)

# 9-1. パーク切り替え。選択結果はpark_nameへ入ります。
park_name = st.radio(
    "パーク",
    list(PARKS),
    horizontal=True,
    label_visibility="collapsed",
    format_func=lambda value: (
        "TDL"
        if value == "東京ディズニーランド"
        else "TDS"
    ),
    key="park_switch",
)

# 9-2. メインカテゴリ切り替え。現在のタブ名がcategory_pageへ入ります。
category_page = st.radio(
    "カテゴリ",
    [
        "🎢 アトラクション",
        "🍽 レストラン",
        "🛍 ショップ",
        "⭐ 行きたい",
        "🗺 マップ",
    ],
    horizontal=True,
    label_visibility="collapsed",
    key="main_category_page",
)

# 画面のカテゴリ名 → 内部データのtype名へ変換する対応表。
category_to_types = {
    "🎢 アトラクション": ["アトラクション"],
    "🍽 レストラン": ["レストラン"],
    "🛍 ショップ": ["ショップ"],
    "⭐ 行きたい": [
        "アトラクション",
        "レストラン",
        "ショップ",
    ],
    "🗺 マップ": [
        "アトラクション",
        "レストラン",
        "ショップ",
    ],
}

facility_types = category_to_types[category_page]

# 9-3. フィルタ条件の初期値。下のUI操作で必要なものだけ値が変わります。
category_search = ""
selected_area = "すべて"
cool_only = False
avoid_thrill = False
japanese_only = True
official_only = False

# 9-4. 通常3カテゴリだけ検索欄とエリア選択を表示します。
if category_page in {
    "🎢 アトラクション",
    "🍽 レストラン",
    "🛍 ショップ",
}:
    placeholders = {
        "🎢 アトラクション": "アトラクション名を検索",
        "🍽 レストラン": "レストラン名・料理を検索",
        "🛍 ショップ": "ショップ名を検索",
    }

    category_search = st.text_input(
        "施設検索",
        placeholder=placeholders[category_page],
        label_visibility="collapsed",
        key=f"category_search_{park_name}_{category_page}",
    )

    # パークごとの公式エリア一覧。
    # アトラクション・レストラン・ショップで共通利用する。
    area_options = [
        "すべて",
        *ATTRACTION_AREAS.get(park_name, {}).keys(),
    ]

    selected_area = st.selectbox(
        "エリア",
        area_options,
        key=f"facility_area_{park_name}_{category_page}",
    )

# 9-5. アトラクションタブだけ「屋内」「絶叫除外」フィルタを表示。
if category_page == "🎢 アトラクション":
    filter_col1, filter_col2 = st.columns(2)

    with filter_col1:
        cool_only = st.checkbox(
            "🧊 屋内・屋根あり",
            value=False,
            key=f"cool_{park_name}",
        )

    with filter_col2:
        avoid_thrill = st.checkbox(
            "😱 絶叫強めを除外",
            value=False,
            key=f"thrill_{park_name}",
        )

# 9-6. 並べ替え方法を選ぶUI。
sort_mode = st.selectbox(
    "並べ替え",
    [
        "距離が近い順",
        "待ち時間が短い順",
        "距離＋待ち時間のバランス順",
    ],
)

search_word = ""

# 9-7. GPS現在地取得。location_rawはGPSライブラリの生データです。
location_raw = gps_location_button(
    buttonText="現在地を取得"
)

# normalize_location()でGPS生データを{latitude, longitude}へ整えます。
location = normalize_location(location_raw)

if location is None:
    st.info(
        "「現在地を取得」を押して、"
        "ブラウザの位置情報を許可してください。"
    )
    st.stop()

# ======================================================================
# ここまで 9. ここから実際の画面処理（アプリ本体）
# ======================================================================

# ======================================================================
# 10. API / CSVから元データを集める
# ======================================================================
# ここで初めて、上で定義したget_attractions()などが実際に呼ばれます。
# データ取得
try:
    with st.spinner("施設情報を取得しています…"):
        attraction_rows = get_attractions(
            PARKS[park_name]["id"]
        )
        live_rows = get_live_data(
            PARKS[park_name]["id"]
        )
        official_suspensions = get_official_suspensions(
            park_name
        )
        restaurant_records = get_official_restaurant_info(
            park_name
        )

        try:
            poi_rows = get_osm_pois(park_name)
            osm_error = None
        except requests.RequestException as error:
            poi_rows = []
            osm_error = error

except requests.RequestException as error:
    st.error(f"アトラクションAPI接続エラー：{error}")
    st.stop()

# APIから返ったlistをpandasの表(DataFrame)へ変換します。
attraction_df = pd.DataFrame(attraction_rows)
live_df = pd.DataFrame(live_rows)
master_df = load_attraction_master()

if attraction_df.empty:
    st.error("アトラクションを取得できませんでした。")
    st.stop()

# 10-1. attraction_dfへCSVの日本語名・絶叫度・待機列情報などを追加。
# アトラクションへ日本語名などを追加
if not master_df.empty:
    useful_columns = [
        column
        for column in [
            "entity_id",
            "name_ja",
            "icon",
            "queue_type",
            "queue_icon",
            "weather_note",
            "thrill_level",
            "thrill_icon",
            "thrill_note",
        ]
        if column in master_df.columns
    ]

    attraction_df = attraction_df.merge(
        master_df[useful_columns],
        on="entity_id",
        how="left",
    )

attraction_df["name_ja"] = (
    attraction_df.get("name_ja")
    .fillna(attraction_df["name_en"])
)

attraction_df["area"] = attraction_df["name_ja"].map(
    lambda name: attraction_area(
        park_name,
        name,
    )
)

# 10-2. entity_idを共通キーに、待ち時間・営業状況をattraction_dfへ合体。
if not live_df.empty:
    attraction_df = attraction_df.merge(
        live_df,
        on="entity_id",
        how="left",
    )
else:
    attraction_df["status"] = "UNKNOWN"
    attraction_df["wait_time"] = pd.NA
    attraction_df["free_pass_available"] = False
    attraction_df["free_pass_state"] = ""
    attraction_df["free_pass_start"] = ""
    attraction_df["free_pass_end"] = ""
    attraction_df["paid_pass_available"] = False
    attraction_df["paid_pass_state"] = ""
    attraction_df["paid_pass_start"] = ""
    attraction_df["paid_pass_end"] = ""

attraction_df["status"] = (
    attraction_df["status"]
    .fillna("UNKNOWN")
)
# APIの英語statusを画面用の日本語「状況」列へ変換。
attraction_df["状況"] = attraction_df["status"].map(
    lambda value: STATUS_JA.get(
        str(value).upper(),
        str(value),
    )
)

# 10-3. 各アトラクション名を公式休止情報と照合。
attraction_df["suspension_info"] = (
    attraction_df["name_ja"].map(
        lambda name: get_suspension_info(
            name,
            official_suspensions,
        )
    )
)

attraction_df["suspension_status"] = (
    attraction_df["suspension_info"].map(
        suspension_status
    )
)

attraction_df["official_stop_text"] = (
    attraction_df["suspension_status"].map(
        lambda value: value.get("text", "")
    )
)

attraction_df["official_suspended"] = (
    attraction_df["suspension_status"].map(
        lambda value: bool(
            value.get("is_suspended")
        )
    )
)

attraction_df["official_upcoming_stop"] = (
    attraction_df["suspension_status"].map(
        lambda value: bool(
            value.get("is_upcoming")
        )
    )
)

# 現在が公式休止期間内なら、
# ThemeParks.wikiより公式情報を優先する
attraction_df.loc[
    attraction_df["official_suspended"],
    "status",
] = "REFURBISHMENT"

attraction_df.loc[
    attraction_df["official_suspended"],
    "状況",
] = "休止中"

# 10-4. OSM由来のレストラン / ショップをpoi_dfへまとめます。
# OSM施設と結合
poi_df = pd.DataFrame(poi_rows)

if not poi_df.empty:
    poi_df["状況"] = "情報なし"
    poi_df["queue_type"] = pd.NA
    poi_df["thrill_level"] = "穏やか"
    poi_df["icon"] = poi_df["type"].map(TYPE_ICONS)
    poi_df["area"] = ""

    # 同じ名前のアトラクションがOSMにもある場合は重複を避ける
    attraction_names = set(
        attraction_df["name_ja"]
        .astype(str)
        .str.lower()
    )

    poi_df = poi_df[
        ~poi_df["name_ja"]
        .astype(str)
        .str.lower()
        .isin(attraction_names)
    ]

# ======================================================================
# ここまで 10. API / CSVから元データを集める
# ======================================================================

# ======================================================================
# 11. attraction_df + poi_df → all_df（全施設）
# ======================================================================
# ここから全カテゴリ共通の距離・エリア・公式リンクなどを追加します。
all_df = pd.concat(
    [attraction_df, poi_df],
    ignore_index=True,
    sort=False,
)

# 全施設についてGPS現在地からの直線距離を計算しdistance_m列へ追加。
all_df["distance_m"] = all_df.apply(
    lambda row: round(
        distance_m(
            location["latitude"],
            location["longitude"],
            row["lat"],
            row["lon"],
        )
    ),
    axis=1,
)

all_df["wait_time"] = pd.to_numeric(
    all_df["wait_time"],
    errors="coerce",
).astype("Int64")

all_df["cool_spot"] = all_df.apply(
    is_cool_spot,
    axis=1,
)

all_df["official_url"] = all_df["type"].map(
    lambda facility_type:
    official_url(park_name, facility_type)
)

all_df["has_japanese_name"] = all_df["name_ja"].map(
    contains_japanese
)

# パーク外として除外したい施設名のキーワード。増やすならここへ追加。
EXCLUDED_NAME_WORDS = [
    "秋山写真館",
    "Lounge O",
    "ホテル",
    "駐車場",
    "コンビニ",
    "駅",
]

all_df["is_excluded_external"] = all_df["name_ja"].astype(str).map(
    lambda value: any(
        word.lower() in value.lower()
        for word in EXCLUDED_NAME_WORDS
    )
)
all_df = all_df[
    ~all_df["is_excluded_external"]
].copy()

# 同じ施設が複数ソースにある場合、deduplicate_facilities()で1件へ整理。
# 同名の施設や、ThemeParks.wikiとOSMの重複を整理
all_df = deduplicate_facilities(all_df)

# 公式個別ページの有無を一度だけ計算してカードでも再利用
# 11-1. official_links.csvを読み、各施設の公式個別ページを照合する準備。
# official_lookupは現在ほぼ使わず、manual_linksが実際の照合元です。
official_lookup = {}
manual_links = load_official_links()


# ------------------------------------------------------------------
# 関数：lookup_official()
# 役割：施設1件に合う公式情報をCSVから探す
# 入力：row
# 出力：dictまたはNone
# どこで使う：official_info列
# 自分で触るなら：照合精度を変える時
# ------------------------------------------------------------------
def lookup_official(row):
    """同じパーク・種別内で公式リンクを照合する。"""
    facility_type = row["type"]
    target = normalize_name(row["name_ja"])

    if facility_type not in {
        "アトラクション",
        "レストラン",
        "ショップ",
    }:
        return None

    exact = manual_links.get(
        (park_name, facility_type, target)
    )
    if exact:
        return exact

    candidates = [
        data
        for (csv_park, csv_type, _), data
        in manual_links.items()
        if csv_park == park_name and csv_type == facility_type
    ]

    best = None
    best_score = 0.0

    for candidate in candidates:
        candidate_name = candidate["normalized"]
        if not candidate_name:
            continue

        if target == candidate_name:
            score = 1.0
        elif target in candidate_name or candidate_name in target:
            shorter = min(len(target), len(candidate_name))
            longer = max(len(target), len(candidate_name))
            score = 0.90 + 0.09 * (shorter / longer)
        else:
            score = SequenceMatcher(
                None,
                target,
                candidate_name,
            ).ratio()

        if score > best_score:
            best_score = score
            best = candidate

    threshold = 0.80 if facility_type == "レストラン" else 0.86
    return best if best_score >= threshold else None


all_df["official_info"] = all_df.apply(
    lookup_official,
    axis=1,
)

# 11-2. 全施設の表示用エリアを最終決定します。
# ------------------------------------------------------------
# 全施設に表示用のエリアを設定
# ------------------------------------------------------------
# アトラクション:
#   既存のATTRACTION_AREASを利用。
#
# レストラン / ショップ:
#   app.py内のFACILITY_AREASを利用。
#
# ここでは外部サイトへ通信しない。
all_df["area"] = all_df.apply(
    lambda row: resolve_facility_area(
        row,
        park_name,
    ),
    axis=1,
)


# ------------------------------------------------------------------
# 関数：lookup_restaurant_data()
# 役割：レストランだけ公式recordと照合
# 入力：row
# 出力：recordまたはNone
# どこで使う：restaurant_info列
# 自分で触るなら：照合処理を変える時
# ------------------------------------------------------------------
def lookup_restaurant_data(row):
    if row["type"] != "レストラン":
        return None

    return match_restaurant_info(
        row["name_ja"],
        restaurant_records,
    )


# レストランだけ公式レストラン情報との照合結果をrestaurant_info列へ追加。
all_df["restaurant_info"] = all_df.apply(
    lookup_restaurant_data,
    axis=1,
)

all_df["has_official_detail"] = all_df[
    "official_info"
].map(bool)

# 公式詳細と照合できないショップを落とし、OSM由来のパーク外店舗などを除外。
# ショップは東京ディズニーリゾート公式の個別ページと
# 照合できたパーク内店舗だけ残す。
# OSM由来のコンビニ、美容院、マッサージ店などは表示しない。
shop_mask = all_df["type"] == "ショップ"
all_df = all_df[
    (~shop_mask)
    | all_df["has_official_detail"]
    ].copy()

all_df["mobile_order"] = all_df["official_info"].map(
    lambda value: bool(value and value.get("mobile_order"))
)

all_df["priority_seating"] = all_df["official_info"].map(
    lambda value: bool(value and value.get("priority_seating"))
)

# ======================================================================
# ここまで 11. attraction_df + poi_df → all_df（全施設）
# ======================================================================

# ======================================================================
# 12. all_df → display_df（今、画面に出す施設）
# ======================================================================
# all_dfは全施設のまま残し、copy()したdisplay_dfだけを条件で絞ります。
# 絞り込み
display_df = all_df[
    all_df["type"].isin(facility_types)
].copy()

# 12-1. 検索欄に文字がある時だけ、施設名・料理・エリア等を検索。
if category_page in {
    "🎢 アトラクション",
    "🍽 レストラン",
    "🛍 ショップ",
} and category_search.strip():
    query = category_search.strip()


    # ------------------------------------------------------------------
    # 関数：category_search_text()
    # 役割：検索対象の項目を1本の文字列にまとめる
    # 入力：row
    # 出力：str
    # どこで使う：カテゴリ検索
    # 自分で触るなら：検索対象項目を増やす時
    # ------------------------------------------------------------------
    def category_search_text(row):
        details = poi_details(row)
        tags = row.get("osm_tags") or {}

        return " ".join(
            str(value)
            for value in [
                row.get("name_ja", ""),
                row.get("name_en", ""),
                row.get("type", ""),
                row.get("area", ""),
                details.get("cuisine", ""),
                details.get("style", ""),
                tags.get("shop", ""),
            ]
        )


    display_df["_category_search"] = display_df.apply(
        category_search_text,
        axis=1,
    )
    display_df = display_df[
        display_df["_category_search"].str.contains(
            query,
            case=False,
            na=False,
        )
    ]

# 12-2. selected_areaが「すべて」以外の時だけエリア絞り込み。
# ------------------------------------------------------------
# エリア絞り込み
# ------------------------------------------------------------
# 「すべて」以外を選んだときだけ、そのエリアの施設へ絞る。
# アトラクション / レストラン / ショップすべて共通。
if (
        category_page in {
    "🎢 アトラクション",
    "🍽 レストラン",
    "🛍 ショップ",
}
        and selected_area != "すべて"
):
    display_df = display_df[
        display_df["area"]
        == selected_area
        ]

# 12-3. その他のフィルタ（涼しい/絶叫除外/日本語/公式）を順番に適用。
if cool_only:
    display_df = display_df[
        display_df["cool_spot"]
    ]

if avoid_thrill:
    display_df = display_df[
        display_df.get(
            "thrill_level",
            pd.Series(
                "穏やか",
                index=display_df.index,
            ),
        ) != "絶叫強め"
        ]

if japanese_only:
    display_df = display_df[
        display_df["has_japanese_name"]
    ]

if official_only:
    display_df = display_df[
        display_df["has_official_detail"]
    ]

# ======================================================================
# ここまで 12. all_df → display_df（今、画面に出す施設）
# ======================================================================

# ======================================================================
# 13. display_dfを並べ替える
# ======================================================================
# 並べ替え
if sort_mode == "距離が近い順":
    display_df = display_df.sort_values(
        ["distance_m", "wait_time"],
        na_position="last",
    )

elif sort_mode == "待ち時間が短い順":
    display_df = display_df.sort_values(
        ["wait_time", "distance_m"],
        na_position="last",
    )

else:
    display_df = balanced_score(
        display_df
    ).sort_values(
        ["_balance_score", "distance_m"],
        na_position="last",
    )

display_df = display_df.reset_index(drop=True)

# カードと地図で使うお気に入り・アイコン一覧を読み込み。
favorites = load_favorites()
icon_catalog = load_icon_catalog()

if osm_error:
    st.warning(
        "レストラン・ショップ・ランドマークの"
        "OSM取得に失敗しました。"
        "今回はアトラクションだけ表示します。"
    )

category_titles = {
    "🎢 アトラクション": "🎢 アトラクション",
    "🍽 レストラン": "🍽 レストラン",
    "🛍 ショップ": "🛍 ショップ",
    "⭐ 行きたい": "⭐ 行きたい",
    "🗺 マップ": "🗺 パークマップ",
}

st.markdown(
    f'<div class="section-title">{category_titles[category_page]}</div>',
    unsafe_allow_html=True,
)

st.markdown(
    f"""
    <div class="category-summary">
      {park_name} ｜ 表示 {len(display_df)}件 ｜ 取得 {len(all_df)}件
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    '<div id="page_status"></div>',
    unsafe_allow_html=True,
)
consume_scroll_target("page_status")

# ======================================================================
# ここまで 13. display_dfを並べ替える
# ======================================================================

# ======================================================================
# 14. 現在の状態（GPS / 今いる施設 / 次の目的地）
# ======================================================================
# session_stateに保存した値はst.rerun()しても残ります。
current_spot = st.session_state.get("current_spot")
route_target = st.session_state.get("route_target")

current_name = current_spot["name_ja"] if current_spot else "未設定"
target_name = route_target["name_ja"] if route_target else "未設定"

st.markdown(
    f"""
    <div class="status-grid">
      <div class="status-card">
        <div class="status-label">📡 GPS現在地</div>
        <div class="status-value">取得済み</div>
      </div>
      <div class="status-card">
        <div class="status-label">📍 今いる施設</div>
        <div class="status-value">{current_name}</div>
      </div>
      <div class="status-card">
        <div class="status-label">✨ 次の目的地</div>
        <div class="status-value">{target_name}</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ======================================================================
# ここまで 14. 現在の状態（GPS / 今いる施設 / 次の目的地）
# ======================================================================

# ======================================================================
# 15. 選択中の徒歩ルート
# ======================================================================
# 「🚶 行く」を押すとroute_targetが入り、if route_target:の中が表示されます。
# 選択中ルート
st.markdown(
    '<div id="route_section"></div>',
    unsafe_allow_html=True,
)
consume_scroll_target("route_section")

if route_target:
    st.subheader(f"🚶 {route_target['name_ja']}へ行く")

    # 「今ここ」があればその施設を出発点。なければGPS現在地を出発点にします。
    if current_spot:
        route_origin = {
            "latitude": current_spot["lat"],
            "longitude": current_spot["lon"],
        }
        origin_name = current_spot["name_ja"]
    else:
        route_origin = location
        origin_name = "GPS現在地"

    st.markdown(
        f"""
        <div class="route-box">
          <strong>{origin_name}</strong><br>
          ↓ 徒歩ルート<br>
          <strong>{route_target["name_ja"]}</strong>
        </div>
        """,
        unsafe_allow_html=True,
    )

    park_center = PARKS[park_name]["center"]
    distance_from_park = distance_m(
        route_origin["latitude"],
        route_origin["longitude"],
        park_center[0],
        park_center[1],
    )

    # パーク中心から10km以上離れている時は、パーク内ルート計算を止めます。
    if distance_from_park > 10_000:
        st.warning(
            f"出発地点がパークから約{distance_from_park / 1000:.0f}km離れています。"
            "パーク内ではGPSを使うか、カードの「今ここ」を押してください。"
        )
    else:
        try:
            with st.spinner("徒歩ルートを計算しています…"):
                route = get_walking_route(
                    route_origin["latitude"],
                    route_origin["longitude"],
                    route_target["lat"],
                    route_target["lon"],
                )

            route_distance = route.get("distance_km")
            route_seconds = route.get("time_seconds")

            metric_col1, metric_col2 = st.columns(2)

            with metric_col1:
                st.metric(
                    "徒歩ルート距離",
                    (
                        f"{route_distance:.2f}km"
                        if route_distance is not None
                        else "情報なし"
                    ),
                )

            with metric_col2:
                st.metric(
                    "徒歩目安",
                    (
                        f"{math.ceil(route_seconds / 60)}分"
                        if route_seconds is not None
                        else "情報なし"
                    ),
                )

            folium_static(
                make_route_map(
                    route,
                    route_target,
                    route_origin,
                ),
                width=700,
                height=280,
            )

            st.caption(
                "OpenStreetMap上の歩行可能な通路から計算した目安です。"
                "当日の規制・一方通行・入場制限は公式案内を優先してください。"
            )

        except (requests.RequestException, ValueError) as error:
            st.error(f"徒歩ルートを取得できませんでした：{error}")

    arrival_col, close_col = st.columns(2)

    # 「到着した」→ 目的地をcurrent_spotへ移し、route_targetを消します。
    with arrival_col:
        if st.button(
                "✅ 到着した",
                type="primary",
                use_container_width=True,
        ):
            arrived_spot = {
                "entity_id": str(route_target["entity_id"]),
                "name_ja": str(route_target["name_ja"]),
                "lat": float(route_target["lat"]),
                "lon": float(route_target["lon"]),
            }
            st.session_state["current_spot"] = arrived_spot
            st.session_state.pop("route_target", None)
            st.session_state["scroll_target"] = "page_status"
            st.rerun()

    # 「ルートを閉じる」→ route_targetだけ消します。
    with close_col:
        if st.button(
                "ルートを閉じる",
                use_container_width=True,
        ):
            st.session_state.pop("route_target", None)
            st.session_state["scroll_target"] = "page_status"
            st.rerun()

# ======================================================================
# ここまで 15. 選択中の徒歩ルート
# ======================================================================

# ======================================================================
# 16. 一覧地図（折りたたみ）
# ======================================================================
# display_dfには、
# すでに検索・エリア選択などで絞り込まれた施設だけが入っている。

# ----------------------------------------------------------
# エリアが選ばれている場合
# ----------------------------------------------------------
# 「すべて」ではなく、
# 例えば「ファンタジーランド」を選択した場合は、
# 折りたたまずに地図をそのまま表示する。
if (
        category_page in {
            "🎢 アトラクション",
            "🍽 レストラン",
            "🛍 ショップ",
        }
        and selected_area != "すべて"
):
    # 今選択しているエリア名を地図の上に表示
    st.markdown(f"### 🗺️ {selected_area}の地図")
    st.caption(
        "このエリアにある施設を地図に表示しています。"
    )
    # ----------------------------------------------------------
    # 現在選択中のパークのお気に入り全部
    # ----------------------------------------------------------
    # all_dfには現在選択中の
    # ランドまたはシーの施設だけが入っている。
    #
    # favorites.keys()に入っている施設IDと一致するものだけ抜き出す。
    park_favorite_df = all_df[
        all_df["entity_id"]
        .astype(str)
        .isin(
            [str(favorite_id) for favorite_id in favorites.keys()]
        )
    ].copy()

    # ----------------------------------------------------------
    # 確認用
    # お気に入りとして何が取れているか一時表示
    # ----------------------------------------------------------

    st.write(
        "お気に入り地図用",
        park_favorite_df[
            ["name_ja", "type", "area", "entity_id"]
        ]
    )

    # ----------------------------------------------------------
    # 地図を表示
    # ----------------------------------------------------------
    folium_static(
        make_overview_map(
            display_df,
            location,
            favorites,
            park_favorite_df,
        ),
        width=700,
        height=230,
    )
# ----------------------------------------------------------
# エリアが「すべて」の場合
# ----------------------------------------------------------
else:
    # 全施設の場合は地図が大きくなるので、
    # 今まで通り折りたたみ式にする。
    with st.expander("🗺️ 施設の地図を見る", expanded=False, ):
        folium_static(make_overview_map(display_df, location, favorites, ),
                      width=700, height=230, )


# ======================================================================
# ここまで 16. 一覧地図（折りたたみ）
# ======================================================================

# ======================================================================
# 17. 施設カード表示
# ======================================================================
# この関数は長いですが「for 1周 = 施設1件」。同じカード処理を件数分繰り返します。
# タブ

# ------------------------------------------------------------------
# 関数：show_facility_cards()
# 役割：施設一覧を1件ずつカード表示
# 入力：frame / key_prefix
# 出力：戻り値なし
# どこで使う：通常一覧・お気に入り一覧
# 自分で触るなら：カードUIを変える時
# ------------------------------------------------------------------
def show_facility_cards(frame, key_prefix):
    """施設カードを表示する。"""
    # frameの各行を1施設ずつrowへ取り出してカード化します。
    for index, row in frame.iterrows():
        entity_id = str(row["entity_id"])
        favorite = entity_id in favorites
        favorite_icon = favorites.get(
            entity_id,
            row.get("icon") or TYPE_ICONS.get(row["type"], "📍"),
        )

        type_icon = TYPE_ICONS.get(row["type"], "📍")
        official_info = row.get("official_info")
        if isinstance(official_info, float) and pd.isna(official_info):
            official_info = None

        # ここから「施設1件分」のカード本体。
        with st.container(border=True):
            title_col, star_col = st.columns(
                [5, 1],
                vertical_alignment="center",
            )

            with title_col:
                title_icon = (
                    favorite_icon
                    if favorite
                    else type_icon
                )

                st.markdown(
                    f"""
                    <h3 class="facility-title">
                      {title_icon} {row['name_ja']}
                    </h3>
                    """,
                    unsafe_allow_html=True,
                )

                info_parts = [
                    row["type"],
                    f"{int(row['distance_m'])}m",
                ]

                if row["type"] == "アトラクション":
                    status_text = str(
                        row.get("状況", "情報なし")
                    )

                    if status_text == "休止中":
                        wait_text = "休止中"

                    elif status_text == "一時休止":
                        wait_text = "一時休止"

                    elif status_text == "受付終了":
                        wait_text = "受付終了"

                    elif pd.notna(row["wait_time"]):
                        wait_text = f"{int(row['wait_time'])}分待ち"

                    else:
                        wait_text = "待ち時間情報なし"

                    info_parts.append(wait_text)
                    info_parts.append(status_text)

                wait_badge = ""
                area_badge = ""
                seat_badge = ""

                # ------------------------------------------------
                # レストラン座席数
                # ------------------------------------------------
                # 公式ページに座席数が掲載されている店舗だけ
                # 「🪑 約○○席」をカードへ表示する。
                if row["type"] == "レストラン":
                    seat_count = get_restaurant_seat_count(
                        park_name,
                        row["name_ja"],
                    )

                    if seat_count is not None:
                        seat_badge = (
                            f'<span class="badge">'
                            f'🪑 約{seat_count}席'
                            f'</span>'
                        )

                if row["type"] == "アトラクション":
                    wait_badge = (
                        f'<span class="badge badge-wait">{wait_text}</span>'
                    )

                # 3カテゴリすべてでエリア名をカードに表示する。
                if row["type"] in {
                    "アトラクション",
                    "レストラン",
                    "ショップ",
                }:
                    area_name = str(
                        row.get("area")
                        or "エリア未設定"
                    )

                    area_badge = (
                        f'<span class="badge">'
                        f'🗺 {area_name}'
                        f'</span>'
                    )

                st.markdown(
                    f"""
                    {wait_badge}
                    <span class="badge">{row["type"]}</span>
                    {area_badge}{seat_badge}
                    <span class="badge">📍 {int(row["distance_m"])}m</span>
                    """,
                    unsafe_allow_html=True,
                )

            with star_col:
                if st.button(
                        "★" if favorite else "☆",
                        key=f"{key_prefix}_star_{entity_id}_{index}",
                        help=(
                                "お気に入りから外す"
                                if favorite
                                else "お気に入りに追加"
                        ),
                        use_container_width=True,
                ):
                    toggle_favorite(
                        entity_id,
                        row.get("icon")
                        or TYPE_ICONS.get(row["type"], "⭐"),
                    )

            # アトラクションとレストラン/ショップで表示する詳細を分岐します。
            # 施設固有情報
            if row["type"] == "アトラクション":
                detail_parts = []

                if pd.notna(row.get("queue_type")):
                    detail_parts.append(
                        f"{row.get('queue_icon', '☂️')} "
                        f"待機列：{row['queue_type']}"
                    )

                if pd.notna(row.get("thrill_level")):
                    detail_parts.append(
                        f"{row.get('thrill_icon', '🙂')} "
                        f"{row['thrill_level']}"
                    )

                if row.get("cool_spot"):
                    detail_parts.append("🧊 涼しい候補")

                if detail_parts:
                    st.write("　".join(detail_parts))

                pass_parts = []

                if bool(row.get("free_pass_available")):
                    pass_parts.append(
                        "🆓 無料パス情報あり"
                    )

                if bool(row.get("paid_pass_available")):
                    pass_parts.append(
                        "💳 有料パス情報あり"
                    )

                if pass_parts:
                    st.info("　".join(pass_parts))

                official_stop_text = str(
                    row.get("official_stop_text") or ""
                ).strip()

                if official_stop_text:
                    if bool(row.get("official_suspended")):
                        st.error(
                            f"🚧 {official_stop_text}"
                        )
                    elif bool(row.get("official_upcoming_stop")):
                        st.warning(
                            f"📅 {official_stop_text}"
                        )

            else:
                details = poi_details(row)

                if row["type"] == "レストラン":
                    st.write(
                        f"🍴 形式：{details['style']}　"
                        f"料理：{details['cuisine']}"
                    )

                    service_parts = []

                    if bool(row.get("mobile_order")):
                        service_parts.append(
                            "📱 モバイルオーダー対象"
                        )

                    if bool(row.get("priority_seating")):
                        service_parts.append(
                            "🪑 プライオリティ・シーティング対応"
                        )

                    if service_parts:
                        st.success("　".join(service_parts))
                elif row["type"] == "ショップ":
                    shop_kind = (
                            (row.get("osm_tags") or {}).get("shop")
                            or "情報なし"
                    )

                    st.write(
                        f"🛍️ ショップ種別：{shop_kind}"
                    )

                if row.get("cool_spot"):
                    st.write(
                        "🧊 涼しいスポット候補"
                    )

            # 「今ここ」「行く」で共通利用する施設ID・名前・座標をまとめます。
            spot_payload = {
                "entity_id": entity_id,
                "name_ja": row["name_ja"],
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
            }

            action1, action2, action3 = st.columns(3)

            with action1:
                if st.button(
                        "📍 今ここ",
                        key=f"{key_prefix}_here_{entity_id}_{index}",
                        use_container_width=True,
                ):
                    st.session_state["current_spot"] = {
                        "entity_id": str(spot_payload["entity_id"]),
                        "name_ja": str(spot_payload["name_ja"]),
                        "lat": float(spot_payload["lat"]),
                        "lon": float(spot_payload["lon"]),
                    }
                    st.session_state["scroll_target"] = "page_status"
                    st.rerun()

            with action2:
                if st.button(
                        "🚶 行く",
                        key=f"{key_prefix}_route_{entity_id}_{index}",
                        type="primary",
                        use_container_width=True,
                ):
                    st.session_state["route_target"] = {
                        "entity_id": str(spot_payload["entity_id"]),
                        "name_ja": str(spot_payload["name_ja"]),
                        "lat": float(spot_payload["lat"]),
                        "lon": float(spot_payload["lon"]),
                    }
                    st.session_state["scroll_target"] = "route_section"
                    st.rerun()

            with action3:
                if official_info:
                    st.link_button(
                        "公式詳細",
                        official_info["url"],
                        use_container_width=True,
                    )
                else:
                    st.button(
                        "公式未確認",
                        key=f"{key_prefix}_official_none_{entity_id}_{index}",
                        disabled=True,
                        use_container_width=True,
                    )

            # お気に入り登録済み施設だけアイコン変更UIを表示します。
            # お気に入りだけアイコン変更
            if favorite and not icon_catalog.empty:
                with st.popover(
                        f"{favorite_icon} アイコン変更",
                        use_container_width=True,
                ):
                    categories = (
                        icon_catalog["category"]
                        .drop_duplicates()
                        .tolist()
                    )

                    current_category = (
                        icon_catalog.loc[
                            icon_catalog["icon"] == favorite_icon,
                            "category",
                        ].iloc[0]
                        if favorite_icon in set(icon_catalog["icon"])
                        else categories[0]
                    )

                    category = st.selectbox(
                        "カテゴリ",
                        categories,
                        index=categories.index(current_category),
                        key=f"{key_prefix}_category_{entity_id}_{index}",
                    )

                    category_df = icon_catalog[
                        icon_catalog["category"] == category
                        ]

                    icons = category_df["icon"].tolist()
                    icon_names = dict(
                        zip(
                            category_df["icon"],
                            category_df["name"],
                        )
                    )

                    selected_icon = st.selectbox(
                        "アイコン",
                        icons,
                        format_func=lambda icon:
                        f"{icon} {icon_names.get(icon, '')}",
                        key=f"{key_prefix}_icon_{entity_id}_{index}",
                    )

                    if st.button(
                            "このアイコンにする",
                            key=f"{key_prefix}_save_icon_{entity_id}_{index}",
                            use_container_width=True,
                    ):
                        change_favorite_icon(
                            entity_id,
                            selected_icon,
                        )


# ======================================================================
# ここまで 17. 施設カード表示
# ======================================================================

# ======================================================================
# 18. 選択カテゴリに応じてカード / お気に入り / 地図を実際に表示
# ======================================================================
if category_page in {
    "🎢 アトラクション",
    "🍽 レストラン",
    "🛍 ショップ",
}:
    if display_df.empty:
        st.info("条件に合う施設がありません。")
    else:
        show_facility_cards(
            display_df,
            key_prefix="all",
        )

# 「⭐ 行きたい」はall_dfからお気に入りIDの施設だけ抜き出します。
if category_page == "⭐ 行きたい":
    favorite_df = all_df[
        all_df["entity_id"]
        .astype(str)
        .isin(favorites.keys())
    ].copy()

    favorite_search = st.text_input(
        "行きたい場所を検索",
        placeholder="お気に入りの施設名を検索",
        label_visibility="collapsed",
        key=f"favorite_search_{park_name}",
    )

    if favorite_search.strip():
        favorite_df = favorite_df[
            favorite_df["name_ja"]
            .astype(str)
            .str.contains(
                favorite_search.strip(),
                case=False,
                na=False,
            )
        ]

    if favorite_df.empty:
        st.info(
            "このパークには、まだ行きたい場所がありません。"
        )
    else:
        favorite_df = deduplicate_facilities(
            favorite_df
        ).sort_values(
            ["distance_m", "wait_time"],
            na_position="last",
        ).reset_index(drop=True)

        show_facility_cards(
            favorite_df,
            key_prefix="favorite",
        )

# 「🗺 マップ」はカードではなくdisplay_dfを大きめ地図へ渡します。
if category_page == "🗺 マップ":
    st.markdown("### 🗺 施設マップ")
    st.caption(
        "マーカーを押すと施設名を確認できます。"
        "地図は指で移動・拡大できます。"
    )

    folium_static(
        make_overview_map(
            display_df,
            location,
            favorites,
        ),
        width=700,
        height=430,
    )

    route_map_target = st.session_state.get("route_target")
    if route_map_target:
        st.info(
            f"次の目的地：{route_map_target['name_ja']}"
        )

# ======================================================================
# ここまで 18. 選択カテゴリに応じてカード / お気に入り / 地図を実際に表示
# ======================================================================

# ======================================================================
# 19. 画面最下部の案内・データ出典
# ======================================================================
st.markdown(
    '<div class="bottom-nav-note">下のカテゴリを切り替えて施設を探せます</div>',
    unsafe_allow_html=True,
)

st.divider()
st.caption(
    "待ち時間：ThemeParks.wiki／"
    "施設・地図・ルート：OpenStreetMap関連サービス。"
    "東京ディズニーリゾート公式アプリではありません。"
)

# ======================================================================
# ここまで 19. 画面最下部の案内・データ出典
# ======================================================================
