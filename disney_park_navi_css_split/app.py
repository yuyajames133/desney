import json
import math
import time
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
from bs4 import BeautifulSoup
from streamlit_folium import folium_static
from streamlit_gps_location import gps_location_button
from datetime import date, datetime



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
                "https://www.tokyodisneyresort.jp/tdl/monthly/stop.html",
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


# ------------------------------------------------------------------
# CSV・お気に入り
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
    """ThemeParks.wikiから営業状況と待ち時間を取る。"""
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

        rows.append(
            {
                "entity_id": str(
                    item.get("id") or item.get("entityId")
                ),
                "status": item.get("status", "UNKNOWN"),
                "wait_time": standby.get("waitTime"),
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
      nwr["tourism"="attraction"]
          ({south},{west},{north},{east});
      nwr["building"="castle"]
          ({south},{west},{north},{east});
      nwr["man_made"~"tower|lighthouse"]
          ({south},{west},{north},{east});
      nwr["historic"]
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
            poi_type = "ランドマーク"

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

@st.cache_data
def load_official_links():
    """
    施設名と公式個別ページをCSVから読む。
    自動取得に失敗しても、このCSVに追加すれば確実にリンクできる。
    """
    if not OFFICIAL_LINKS_FILE.exists():
        return {}

    df = pd.read_csv(OFFICIAL_LINKS_FILE, dtype=str).fillna("")
    required = {"park", "type", "name_ja", "official_url"}

    if not required.issubset(df.columns):
        return {}

    links = {}

    for _, row in df.iterrows():
        key = (
            row["park"].strip(),
            row["type"].strip(),
            normalize_name(row["name_ja"]),
        )
        url = row["official_url"].strip()

        if url:
            links[key] = {
                "name": row["name_ja"].strip(),
                "normalized": normalize_name(row["name_ja"]),
                "url": url,
                "source": "csv",
            }

    return links


# ------------------------------------------------------------------
# 東京ディズニー公式の個別詳細ページ
# ------------------------------------------------------------------

def normalize_name(value):
    """施設名の記号差を吸収して照合する。"""
    value = unicodedata.normalize("NFKC", str(value or "")).lower()
    value = value.replace("ヴ", "ブ")
    value = re.sub(
        r"[\s　・･'\"“”‘’()（）\[\]【】\-‐‑–—~〜!！?？:：,，.。]",
        "",
        value,
    )

    value = value.replace("ウ", "ブ")
    value = value.replace("･", "・")
    value = value.replace("/", "・")

    value = re.sub(
        r"[\s　・･'\"“”‘’()（）\[\]【】"
        r"\-‐-–—~〜!！?？:：,，.。]",
        "",
        value,
    )
     
    return value

@st.cache_data(ttl=60)
def load_official_links():
    if not OFFICIAL_LINKS_FILE.exists():
        return {}

    df = pd.read_csv(
        OFFICIAL_LINKS_FILE,
        dtype=str,
    ).fillna("")

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
        "🗺 マップ",
        "••• その他",
    ],
    horizontal=True,
    label_visibility="collapsed",
    key="main_category_page",
)

category_to_types = {
    "🎢 アトラクション": ["アトラクション"],
    "🍽 レストラン": ["レストラン"],
    "🛍 ショップ": ["ショップ"],
    "🗺 マップ": [
        "アトラクション",
        "レストラン",
        "ショップ",
        "ランドマーク",
    ],
    "••• その他": [
        "アトラクション",
        "レストラン",
        "ショップ",
        "ランドマーク",
    ],
}

facility_types = category_to_types[category_page]

sort_mode = st.selectbox(
    "並べ替え",
    [
        "距離が近い順",
        "待ち時間が短い順",
        "距離＋待ち時間のバランス順",
    ],
)

cool_only = False
avoid_thrill = False
japanese_only = True
official_only = False

if category_page == "••• その他":
    with st.expander("絞り込み・並べ替え設定", expanded=True):
        filter_col1, filter_col2 = st.columns(2)

        with filter_col1:
            cool_only = st.checkbox(
                "🧊 涼しいスポット候補",
                value=False,
            )

        with filter_col2:
            avoid_thrill = st.checkbox(
                "😱 絶叫強めを除外",
                value=False,
            )

        clean_col1, clean_col2 = st.columns(2)

        with clean_col1:
            japanese_only = st.checkbox(
                "🇯🇵 日本語名の施設だけ",
                value=True,
                help="英語名しか登録されていない施設を一覧から除外します。",
            )

        with clean_col2:
            official_only = st.checkbox(
                "🏰 公式詳細がある施設だけ",
                value=True,
                help=(
                    "東京ディズニー公式の個別詳細ページを"
                    "確認できた施設だけ表示します。"
                ),
            )


search_word = ""

max_results = st.slider(
    "表示件数",
    min_value=10,
    max_value=80,
    value=30,
    step=10,
)

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

if not live_df.empty:
    attraction_df = attraction_df.merge(
        live_df,
        on="entity_id",
        how="left",
    )
else:
    attraction_df["status"] = "UNKNOWN"
    attraction_df["wait_time"] = pd.NA

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
    """CSVから公式個別ページを探す。"""
    facility_type = (row["type"])
    target = normalize_name(row["name_ja"])

    if facility_type not in {
        "アトラクション",
        "レストラン",
        "ショップ",
    }:
        return None

    #　完全一致
    exact = manual_links.get(
        (
            park_name,
            facility_type,
            target,
        )
    )

    if exact:
        return exact

    #　同じパーク・同じ種類の中から表記揺れを探す
    candidates = [
        data
        for (csv_park, csv_type, _), data
        in manual_links.items()
        if (
            csv_park == park_name
            and csv_type == facility_type
        )
    ]

    best = None
    best_score = 0.0

    for candidate in candidates:
        candidate_name = candidate["normalized"]

        if not candidate_name:
            continue

        if (
            target in candidate_name
            or candidate_name in target
        ):
            score = 0.95
        else:
            score = SequenceMatcher(
                None,
                target,
                candidate_name,
            ).ratio()

        if best_score < 0.86:
            return None

        return best


    all_df["has_official_detail"] = all_df[
        "official_info"
    ].map(bool)

    # レストランショップは、
    # 公式個別ページがあるパーク内施設だけ表示する
    food_shop_mask = all_df["type"].isin(
        [
            "レストラン",
            "ショップ",
        ]
    )

    all_df = all_df[
        (~food_shop_mask)
        | all_df["has_official_detail"]
    ].copy()

    target = normalize_name(row["name_ja"])

    manual = manual_links.get(
        (park_name, facility_type, target)
    )
    if manual:
        return manual

    exact = official_lookup.get(
        (facility_type, target)
    )

    if exact:
        return exact

    entries = [
        entry
        for (entry_type, _), entry
        in official_lookup.items()
        if entry_type == facility_type
    ]

    if not entries:
        return None

    score, best = max(
        (
            official_match_score(
                target,
                entry["normalized"],
            ),
            entry,
        )
        for entry in entries
    )

    return best if score >= 0.84 else None

all_df["official_info"] = all_df.apply(
    lookup_official,
    axis=1,
)
all_df["has_official_detail"] = all_df[
    "official_info"
].map(bool)

# 絞り込み
display_df = all_df[
    all_df["type"].isin(facility_types)
].copy()

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

display_df = display_df.head(max_results).reset_index(drop=True)

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
    "🗺 マップ": "🗺 パークマップ",
    "••• その他": "••• その他・検索・行きたい",
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
            st.session_state["current_spot"] = dict(route_target)
            st.session_state.pop("route_target", None)
            st.rerun()

    with close_col:
        if st.button(
            "ルートを閉じる",
            use_container_width=True,
        ):
            st.session_state.pop("route_target", None)
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
                    info_parts.append(wait_text)
                    info_parts.append(row.get("状況", "情報なし"))

                wait_badge = ""
                if row["type"] == "アトラクション":
                    wait_badge = (
                        f'<span class="badge badge-wait">{wait_text}</span>'
                    )

                st.markdown(
                    f"""
                    {wait_badge}
                    <span class="badge">{row["type"]}</span>
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
                    st.write(
                        f"💴 価格：{details['price']}　"
                        f"🕒 営業時間：{details['opening_hours']}"
                    )

                elif row["type"] == "ショップ":
                    shop_kind = (
                        (row.get("osm_tags") or {}).get("shop")
                        or "情報なし"
                    )
                    st.write(f"🛍️ ショップ種別：{shop_kind}")

                if row.get("cool_spot"):
                    st.write("🧊 涼しいスポット候補")

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
                    st.session_state["current_spot"] = dict(spot_payload)
                    st.rerun()

            with action2:
                if st.button(
                    "🚶 行く",
                    key=f"{key_prefix}_route_{entity_id}_{index}",
                    type="primary",
                    use_container_width=True,
                ):
                    st.session_state["route_target"] = dict(spot_payload)
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


if category_page == "••• その他":
    search_section, favorite_section, landmark_section = st.tabs(
        [
            "🔎 検索",
            f"⭐ 行きたい（{len(favorites)}）",
            "📍 ランドマーク",
        ]
    )

    with search_section:
        st.markdown("### 🔎 行きたい場所を検索")

        query = st.text_input(
            "検索",
            placeholder="施設名・料理・ジャンルを入力",
            label_visibility="collapsed",
            key="facility_search",
        )

        target_types = st.multiselect(
            "検索対象",
            [
                "アトラクション",
                "レストラン",
                "ショップ",
                "ランドマーク",
            ],
            default=[
                "アトラクション",
                "レストラン",
                "ショップ",
                "ランドマーク",
            ],
            key="search_types",
        )

        result_df = all_df[
            all_df["type"].isin(target_types)
        ].copy()

        if query.strip():
            def build_search_text(row):
                details = poi_details(row)
                tags = row.get("osm_tags") or {}
                return " ".join(
                    str(value)
                    for value in [
                        row.get("name_ja", ""),
                        row.get("name_en", ""),
                        row.get("type", ""),
                        row.get("queue_type", ""),
                        row.get("thrill_level", ""),
                        details.get("cuisine", ""),
                        details.get("style", ""),
                        tags.get("shop", ""),
                        "涼しい" if row.get("cool_spot") else "",
                    ]
                )

            result_df["_search"] = result_df.apply(
                build_search_text,
                axis=1,
            )
            result_df = result_df[
                result_df["_search"].str.contains(
                    query.strip(),
                    case=False,
                    na=False,
                )
            ]

        if japanese_only:
            result_df = result_df[
                result_df["has_japanese_name"]
            ]

        if official_only:
            result_df = result_df[
                result_df["has_official_detail"]
            ]

        result_df = deduplicate_facilities(
            result_df
        ).sort_values(
            ["distance_m", "wait_time"],
            na_position="last",
        ).head(40).reset_index(drop=True)

        if not query.strip():
            st.info("施設名、カレー、カフェ、城、涼しい、などで検索できます。")
        elif result_df.empty:
            st.warning("該当する施設が見つかりませんでした。")
        else:
            show_facility_cards(
                result_df,
                key_prefix="search",
            )


    with favorite_section:
        favorite_df = all_df[
            all_df["entity_id"]
            .astype(str)
            .isin(favorites.keys())
        ].copy()

        if favorite_df.empty:
            st.info("まだお気に入りがありません。")

        else:
            favorite_df["distance_m"] = favorite_df.apply(
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

            favorite_df["official_url"] = favorite_df["type"].map(
                lambda facility_type:
                    official_url(park_name, facility_type)
            )

            favorite_df = deduplicate_facilities(
                favorite_df
            ).sort_values("distance_m")

            show_facility_cards(
                favorite_df.reset_index(drop=True),
                key_prefix="favorite",
            )


    with landmark_section:
            landmark_df = all_df[
                all_df["type"] == "ランドマーク"
            ].copy()

            landmark_df = landmark_df.sort_values(
                "distance_m"
            ).head(50).reset_index(drop=True)

            if landmark_df.empty:
                st.info("ランドマーク情報がありません。")
            else:
                show_facility_cards(
                    landmark_df,
                    key_prefix="landmark",
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
