import json
import math
import urllib.parse
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import folium
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup
from streamlit_folium import folium_static
from streamlit_gps_location import gps_location_button



st.set_page_config(
    page_title="Magic Park Navi",
    page_icon="🏰",
    layout="centered",
)


BASE_DIR = Path(__file__).resolve().parent

def load_css():
    css_path = BASE_DIR / "style.css"
    if css_path.exists():
        st.markdown(
            f"<style>{css_path.read_text(encoding='utf-8')}</style>",
            unsafe_allow_html=True,
        )

load_css()

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

# ------------------------------------------------------------------
# 基本設定
# ------------------------------------------------------------------

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

THEMEPARKS_API = "https://api.themeparks.wiki/v1/entity"
OVERPASS_API = "https://overpass-api.de/api/interpreter"
VALHALLA_API = "https://valhalla1.openstreetmap.de/route"

NAME_FILE = BASE_DIR / "attraction_names.csv"
FAVORITES_FILE = BASE_DIR / "favorites.csv"
ICON_FILE = BASE_DIR / "icon_catalog.csv"
OFFICIAL_LINKS_FILE = BASE_DIR / "official_links.csv"

TYPE_ICONS = {
    "アトラクション": "🎡",
    "レストラン": "🍽️",
    "ショップ": "🛍️",
    "ランドマーク": "📍",
}

THRILL_ORDER = {
    "穏やか": 0,
    "軽いスリル": 1,
    "絶叫強め": 2,
}

STATUS_JA = {
    "OPERATING": "営業中",
    "DOWN": "一時休止",
    "CLOSED": "受付終了",
    "REFURBISHMENT": "休止中",
    "UNKNOWN": "情報なし",
}


# ThemeParks.wikiの東京ディズニー情報では、各アトラクションの
# 所属エリアが安定して返らないため、公式パーク区分に合わせて保持する。
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


# ------------------------------------------------------------------
# CSV・お気に入り
# attraction_names.csv / favorites.csv / icon_catalog.csv を扱う
# ------------------------------------------------------------------

@st.cache_data
def load_attraction_master():
    """日本語名・待機環境・絶叫度などの補助情報を読む。"""
    if not NAME_FILE.exists():
        return pd.DataFrame()

    return pd.read_csv(
        NAME_FILE,
        dtype={"entity_id": "string"},
    )


@st.cache_data
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


def change_favorite_icon(entity_id, icon):
    """お気に入りアイコンを変更する。"""
    favorites = load_favorites()
    entity_id = str(entity_id)

    if entity_id not in favorites:
        return

    favorites[entity_id] = icon
    save_favorites(favorites)
    st.rerun()


# ------------------------------------------------------------------
# API取得
# ThemeParks.wiki / 東京ディズニー公式 / OpenStreetMap を扱う
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
               'ショップ': {'イル・ポスティーノ・ステーショナリー': 'メディテレーニアンハーバー',
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





def contains_japanese(value):
    """ひらがな・カタカナ・漢字が含まれるか。"""
    return bool(
        re.search(
            r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]",
            str(value or ""),
        )
    )


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



OFFICIAL_LINKS_FILE = BASE_DIR / "official_links.csv"

# ------------------------------------------------------------------
# 東京ディズニー公式の個別詳細ページ
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
# ------------------------------------------------------------------
# 計算・表示情報
# GPS・距離・表示用情報の加工
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


def consume_scroll_target(anchor_id):
    """このアンカーへの移動予約があれば一度だけ実行する。"""
    if st.session_state.get("scroll_target") != anchor_id:
        return

    scroll_to_anchor(anchor_id)
    st.session_state.pop("scroll_target", None)


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


def official_url(park_name, facility_type):
    """施設種別に対応する東京ディズニー公式ページ。"""
    return PARKS[park_name]["official"].get(
        facility_type,
        PARKS[park_name]["official"]["ランドマーク"],
    )


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


# ------------------------------------------------------------------
# 徒歩ルート
# Valhalla APIを使ったパーク内徒歩ルート
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


# ------------------------------------------------------------------
# 地図
# Foliumで現在地・施設・ルートを描画
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


def make_overview_map(frame, location, favorites):
    """一覧確認用の小さい地図。"""
    disney_map = folium.Map(
        location=[
            location["latitude"],
            location["longitude"],
        ],
        zoom_start=16,
        control_scale=True,
        dragging=True,
        touch_zoom=True,
        double_click_zoom=True,
        box_zoom=True,
        keyboard=True,
        scroll_wheel_zoom=False,
    )

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

    for _, row in frame.head(60).iterrows():
        add_facility_marker(disney_map, row, favorites)

    return disney_map


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


# ------------------------------------------------------------------
# 画面
# ここからStreamlitのUIを組み立てる
# ------------------------------------------------------------------

st.markdown(
    '<div class="park-switch-label">PARK</div>',
    unsafe_allow_html=True,
)

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

category_search = ""
selected_area = "すべて"
cool_only = False
avoid_thrill = False
japanese_only = True
official_only = False

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


sort_mode = st.selectbox(
    "並べ替え",
    [
        "距離が近い順",
        "待ち時間が短い順",
        "距離＋待ち時間のバランス順",
    ],
)


search_word = ""


location_raw = gps_location_button(
    buttonText="現在地を取得"
)

location = normalize_location(location_raw)

if location is None:
    st.info(
        "「現在地を取得」を押して、"
        "ブラウザの位置情報を許可してください。"
    )
    st.stop()


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


attraction_df = pd.DataFrame(attraction_rows)
live_df = pd.DataFrame(live_rows)
master_df = load_attraction_master()

if attraction_df.empty:
    st.error("アトラクションを取得できませんでした。")
    st.stop()

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
attraction_df["状況"] = attraction_df["status"].map(
    lambda value: STATUS_JA.get(
        str(value).upper(),
        str(value),
    )
)

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

all_df = pd.concat(
    [attraction_df, poi_df],
    ignore_index=True,
    sort=False,
)

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

# 同名の施設や、ThemeParks.wikiとOSMの重複を整理
all_df = deduplicate_facilities(all_df)

# 公式個別ページの有無を一度だけ計算してカードでも再利用
official_lookup = {}
manual_links = load_official_links()

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
def lookup_restaurant_data(row):
    if row["type"] != "レストラン":
        return None

    return match_restaurant_info(
        row["name_ja"],
        restaurant_records,
    )


all_df["restaurant_info"] = all_df.apply(
    lookup_restaurant_data,
    axis=1,
)



all_df["has_official_detail"] = all_df[
    "official_info"
].map(bool)

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

# 絞り込み
display_df = all_df[
    all_df["type"].isin(facility_types)
].copy()

if category_page in {
    "🎢 アトラクション",
    "🍽 レストラン",
    "🛍 ショップ",
} and category_search.strip():
    query = category_search.strip()

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


# 選択中ルート
st.markdown(
    '<div id="route_section"></div>',
    unsafe_allow_html=True,
)
consume_scroll_target("route_section")

if route_target:
    st.subheader(f"🚶 {route_target['name_ja']}へ行く")

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

    with close_col:
        if st.button(
            "ルートを閉じる",
            use_container_width=True,
        ):
            st.session_state.pop("route_target", None)
            st.session_state["scroll_target"] = "page_status"
            st.rerun()


# 一覧地図は折りたたみ
with st.expander("🗺️ 施設の地図を見る", expanded=False):
    st.caption(
        "地図は指で移動・拡大できます。縦スクロールは地図の外側を触ってください。"
    )

    folium_static(
        make_overview_map(
            display_df,
            location,
            favorites,
        ),
        width=700,
        height=230,
    )


# タブ
def show_facility_cards(frame, key_prefix):
    """施設カードを表示する。"""
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
