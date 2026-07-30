import math
import time
from pathlib import Path

import folium
import pandas as pd
import requests
import streamlit as st
from streamlit_folium import folium_static
from streamlit_gps_location import gps_location_button


st.set_page_config(
    page_title="ディズニー 距離・待ち時間検索",
    page_icon="🏰",
)

st.title("🏰 ディズニー 距離・待ち時間検索")

PARKS = {
    "東京ディズニーランド":
        "3cc919f1-d16d-43e0-8c3f-1dd269bd1a42",
    "東京ディズニーシー":
        "67b290d5-3478-4f23-b601-2f8fb71ba803",
}

API = "https://api.themeparks.wiki/v1/entity"
NOMINATIM_API = "https://nominatim.openstreetmap.org/search"

NAME_FILE = Path(__file__).with_name("attraction_names.csv")
FAVORITES_FILE = Path(__file__).with_name("favorites.csv")

ICON_FILE = Path(__file__).with_name("icon_catalog.csv")


@st.cache_data
def get_icon_catalog():
    """カテゴリ分けされたアイコン一覧をCSVから読む。"""
    return pd.read_csv(
        ICON_FILE,
        dtype=str,
    ).drop_duplicates("icon")


ICON_CATALOG = get_icon_catalog()
ICON_OPTIONS = ICON_CATALOG["icon"].tolist()

ICON_NAMES = dict(
    zip(
        ICON_CATALOG["icon"],
        ICON_CATALOG["name"],
    )
)

ICON_CATEGORIES = dict(
    zip(
        ICON_CATALOG["icon"],
        ICON_CATALOG["category"],
    )
)

CATEGORY_OPTIONS = (
    ICON_CATALOG["category"]
    .drop_duplicates()
    .tolist()
)

ICONS_BY_CATEGORY = {
    category: (
        ICON_CATALOG.loc[
            ICON_CATALOG["category"] == category,
            "icon",
        ].tolist()
    )
    for category in CATEGORY_OPTIONS
}


@st.cache_data
def get_japanese_names():
    """施設ID・日本語名・専用アイコンをCSVから読む。"""
    return pd.read_csv(
        NAME_FILE,
        usecols=[
            "entity_id",
            "name_ja",
            "icon",
            "queue_type",
            "queue_icon",
            "weather_note",
            "thrill_level",
            "thrill_icon",
            "thrill_note",
        ],
    )


def load_favorites():
    """
    お気に入りをCSVから読み込む。

    戻り値：
    {施設ID: 選択中のアイコン}
    """
    if not FAVORITES_FILE.exists():
        return {}

    try:
        favorite_df = pd.read_csv(
            FAVORITES_FILE,
            dtype={
                "entity_id": "string",
                "icon": "string",
            },
        )
    except (OSError, pd.errors.EmptyDataError):
        return {}

    if "entity_id" not in favorite_df.columns:
        return {}

    # 旧版CSVにicon列がなくても引き継げる
    if "icon" not in favorite_df.columns:
        favorite_df["icon"] = "⭐"

    favorites = {}

    for _, row in favorite_df.iterrows():
        entity_id = str(row["entity_id"])
        icon = str(row["icon"]) if pd.notna(row["icon"]) else "⭐"

        if icon not in ICON_OPTIONS:
            icon = "⭐"

        favorites[entity_id] = icon

    return favorites


def save_favorites(favorites):
    """施設IDと選択アイコンをCSVへ保存する。"""
    rows = [
        {
            "entity_id": entity_id,
            "icon": icon,
        }
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


def toggle_favorite(entity_id, default_icon, favorites):
    """☆で追加、★で解除する。"""
    entity_id = str(entity_id)
    updated = dict(favorites)

    if entity_id in updated:
        del updated[entity_id]
    else:
        icon = str(default_icon)

        if icon not in ICON_OPTIONS:
            icon = "⭐"

        updated[entity_id] = icon

    save_favorites(updated)
    st.rerun()


def update_favorite_icon(entity_id, selected_icon, favorites):
    """ユーザーが選んだアイコンを保存する。"""
    entity_id = str(entity_id)

    if entity_id not in favorites:
        return

    if selected_icon not in ICON_OPTIONS:
        return

    updated = dict(favorites)
    updated[entity_id] = selected_icon
    save_favorites(updated)
    st.rerun()


@st.cache_data(ttl=3600)
def get_attractions(park_id):
    """施設名・ID・座標をAPIから取得する。"""
    response = requests.get(
        f"{API}/{park_id}/children",
        timeout=15,
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

        rows.append({
            "entity_id": item.get("id") or item.get("entityId"),
            "name": item.get("name", "名称不明"),
            "lat": lat,
            "lon": lon,
        })

    return rows


@st.cache_data(ttl=300)
def get_live_data(park_id):
    """営業状態と待ち時間をAPIから取得する。"""
    response = requests.get(
        f"{API}/{park_id}/live",
        timeout=15,
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

        rows.append({
            "entity_id": item.get("id") or item.get("entityId"),
            "status": item.get("status", "UNKNOWN"),
            "wait_time": standby.get("waitTime"),
        })

    return rows



@st.cache_data(ttl=604800)
def get_park_boundaries():
    """
    OpenStreetMapのNominatimから、
    ランドとシーのポリゴン輪郭を取得する。

    取得結果は7日間キャッシュする。
    """
    boundaries = {}

    search_names = {
        "東京ディズニーランド":
            "東京ディズニーランド, 浦安市, 千葉県, 日本",
        "東京ディズニーシー":
            "東京ディズニーシー, 浦安市, 千葉県, 日本",
    }

    headers = {
        "User-Agent":
            "DisneyDistanceWaitPrototype/1.0"
    }

    for index, (park, query) in enumerate(
        search_names.items()
    ):
        # 公開Nominatimの負荷を避けるため1秒以上空ける
        if index:
            time.sleep(1.1)

        response = requests.get(
            NOMINATIM_API,
            params={
                "q": query,
                "format": "jsonv2",
                "polygon_geojson": 1,
                "limit": 5,
                "countrycodes": "jp",
                "accept-language": "ja",
                "viewbox":
                    "139.865,35.645,139.905,35.615",
                "bounded": 1,
            },
            headers=headers,
            timeout=20,
        )
        response.raise_for_status()

        for item in response.json():
            geometry = item.get("geojson") or {}

            if geometry.get("type") not in {
                "Polygon",
                "MultiPolygon",
            }:
                continue

            display_name = str(
                item.get("display_name", "")
            )

            if (
                park in display_name
                or "Disneyland" in display_name
                or "DisneySea" in display_name
            ):
                boundaries[park] = geometry
                break

    return boundaries


def geometry_points(geometry):
    """GeoJSON内の全緯度・経度を取り出す。"""
    points = []

    def walk(value):
        if not isinstance(value, list) or not value:
            return

        if (
            len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            # GeoJSONは経度、緯度の順
            points.append([value[1], value[0]])
            return

        for child in value:
            walk(child)

    walk(geometry.get("coordinates", []))
    return points


def add_park_boundaries(disney_map, boundaries):
    """
    OSMの輪郭を加工せず、そのまま地図へ描画する。
    """
    styles = {
        "東京ディズニーランド": "#059669",
        "東京ディズニーシー": "#2563eb",
    }

    all_points = []

    for park, geometry in boundaries.items():
        color = styles[park]
        selected = park == park_name

        feature = {
            "type": "Feature",
            "properties": {
                "park_name": park,
            },
            "geometry": geometry,
        }

        folium.GeoJson(
            data=feature,
            name=park,
            style_function=(
                lambda feature,
                color=color,
                selected=selected: {
                    "color": color,
                    "weight": 5 if selected else 3,
                    "opacity": 1,
                    "fill": True,
                    "fillColor": color,
                    "fillOpacity":
                        0.16 if selected else 0.07,
                }
            ),
            highlight_function=(
                lambda feature,
                color=color: {
                    "color": color,
                    "weight": 7,
                    "fillOpacity": 0.22,
                }
            ),
            tooltip=folium.GeoJsonTooltip(
                fields=["park_name"],
                aliases=[""],
                labels=False,
                sticky=True,
            ),
        ).add_to(disney_map)

        all_points.extend(
            geometry_points(geometry)
        )

    if all_points:
        disney_map.fit_bounds(
            all_points,
            padding=(20, 20),
        )

    legend = """
    <div style="
        position:fixed;
        top:12px;
        right:12px;
        z-index:9999;
        background:rgba(255,255,255,.95);
        padding:8px 11px;
        border-radius:8px;
        box-shadow:0 2px 7px rgba(0,0,0,.25);
        font-size:13px;
    ">
        <div>
            <span style="color:#059669;">■</span>
            ランド
        </div>
        <div>
            <span style="color:#2563eb;">■</span>
            シー
        </div>
        <div style="
            font-size:11px;
            color:#666;
            margin-top:3px;
        ">
            太い輪郭＝選択中
        </div>
    </div>
    """

    disney_map.get_root().html.add_child(
        folium.Element(legend)
    )


def distance_m(lat1, lon1, lat2, lon2):
    """現在地から施設までの直線距離を計算する。"""
    radius = 6_371_000

    lat1, lon1, lat2, lon2 = map(
        math.radians,
        [lat1, lon1, lat2, lon2],
    )

    d_lat = lat2 - lat1
    d_lon = lon2 - lon1

    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(d_lon / 2) ** 2
    )

    return radius * 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a),
    )


def normalize_location(value):
    """GPS部品の返却形式から緯度・経度を取り出す。"""
    if not isinstance(value, dict):
        return None

    for candidate in [
        value,
        value.get("coords"),
        value.get("location"),
    ]:
        if not isinstance(candidate, dict):
            continue

        if (
            candidate.get("latitude") is not None
            and candidate.get("longitude") is not None
        ):
            return candidate

    return None


STATUS = {
    "OPERATING": "営業中",
    "DOWN": "一時休止",
    "CLOSED": "受付終了",
    "REFURBISHMENT": "休止中",
    "UNKNOWN": "情報なし",
}


park_name = st.selectbox("パーク", list(PARKS))

sort_type = st.radio(
    "並べ替え",
    ["距離が近い順", "待ち時間が短い順"],
    horizontal=True,
)

open_only = st.checkbox("営業中だけ表示")

queue_filter = st.selectbox(
    "待機列の環境",
    [
        "すべて",
        "雨を避けやすい",
        "屋内",
        "屋根あり",
        "一部屋根あり",
        "屋外",
        "不明",
    ],
)

st.caption(
    "待機列環境は実用上の目安です。"
    "混雑時の列の延長や運営変更で変わる場合があります。"
)

thrill_filter = st.selectbox(
    "絶叫レベル",
    [
        "すべて",
        "絶叫強めを除外",
        "軽いスリルも除外",
        "絶叫強めだけ",
        "軽いスリルだけ",
        "穏やかだけ",
    ],
)

st.caption(
    "絶叫レベルは公式の「スピード／スリルあり」を参考にした"
    "実用上の目安です。感じ方には個人差があります。"
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


try:
    park_boundaries = get_park_boundaries()

    place_df = pd.DataFrame(
        get_attractions(PARKS[park_name]),
        columns=["entity_id", "name", "lat", "lon"],
    )

    live_df = pd.DataFrame(
        get_live_data(PARKS[park_name]),
        columns=["entity_id", "status", "wait_time"],
    )

except requests.RequestException as error:
    st.error(f"API接続エラー：{error}")
    st.stop()


if len(park_boundaries) < 2:
    st.warning(
        "パークの輪郭を取得できませんでした。"
        "アトラクション一覧はそのまま利用できます。"
    )


if place_df.empty:
    st.error("座標付きアトラクションを取得できませんでした。")
    st.stop()


df = (
    place_df
    .merge(
        get_japanese_names(),
        on="entity_id",
        how="left",
    )
    .merge(
        live_df,
        on="entity_id",
        how="left",
    )
)

df["name_ja"] = df["name_ja"].fillna(df["name"])
df["icon"] = df["icon"].fillna("🎡")
df["queue_type"] = df["queue_type"].fillna("不明")
df["queue_icon"] = df["queue_icon"].fillna("❓")
df["weather_note"] = df["weather_note"].fillna("要確認")
df["thrill_level"] = df["thrill_level"].fillna("穏やか")
df["thrill_icon"] = df["thrill_icon"].fillna("🙂")
df["thrill_note"] = df["thrill_note"].fillna(
    "大きな絶叫要素なし"
)

missing_df = df[df["name_ja"] == df["name"]]

if not missing_df.empty:
    st.warning(
        f"日本語名が未登録の施設が"
        f"{len(missing_df)}件あります。"
    )

    with st.expander("未登録施設を確認"):
        st.dataframe(
            missing_df[["entity_id", "name"]],
            hide_index=True,
        )


df["distance_m"] = df.apply(
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

df["wait_time"] = pd.to_numeric(
    df["wait_time"],
    errors="coerce",
).astype("Int64")

df["status"] = df["status"].fillna("UNKNOWN")
df["状況"] = df["status"].map(
    lambda value: STATUS.get(
        str(value).upper(),
        value,
    )
)

favorites = load_favorites()

df["お気に入り"] = (
    df["entity_id"]
    .astype(str)
    .isin(favorites.keys())
)

# お気に入りはユーザーが選んだアイコンを優先する
df["favorite_icon"] = df.apply(
    lambda row: favorites.get(
        str(row["entity_id"]),
        row["icon"],
    ),
    axis=1,
)

if open_only:
    df = df[
        df["status"].str.upper() == "OPERATING"
    ]

if queue_filter == "雨を避けやすい":
    df = df[
        df["queue_type"].isin(["屋内", "屋根あり"])
    ]
elif queue_filter != "すべて":
    df = df[
        df["queue_type"] == queue_filter
    ]

if thrill_filter == "絶叫強めを除外":
    df = df[
        df["thrill_level"] != "絶叫強め"
    ]
elif thrill_filter == "軽いスリルも除外":
    df = df[
        df["thrill_level"] == "穏やか"
    ]
elif thrill_filter == "絶叫強めだけ":
    df = df[
        df["thrill_level"] == "絶叫強め"
    ]
elif thrill_filter == "軽いスリルだけ":
    df = df[
        df["thrill_level"] == "軽いスリル"
    ]
elif thrill_filter == "穏やかだけ":
    df = df[
        df["thrill_level"] == "穏やか"
    ]

if sort_type == "距離が近い順":
    df = df.sort_values("distance_m")
else:
    df = df.sort_values(
        ["wait_time", "distance_m"],
        na_position="last",
    )

df = df.reset_index(drop=True)
df["rank"] = df.index + 1


def wait_text(row):
    """待ち時間の表示文字を作る。"""
    if pd.isna(row["wait_time"]):
        return "情報なし"

    return f'{int(row["wait_time"])}分'


def make_map(map_df):
    """
    通常施設は赤いマーカー、
    お気に入りだけ専用絵文字マーカーで表示する。
    """
    disney_map = folium.Map(
        location=[
            location["latitude"],
            location["longitude"],
        ],
        zoom_start=16,
        control_scale=True,
    )

    # OSMに登録されたパーク輪郭をそのまま描画
    add_park_boundaries(
        disney_map,
        park_boundaries,
    )

    folium.Marker(
        location=[
            location["latitude"],
            location["longitude"],
        ],
        tooltip="現在地",
        popup="現在地",
        icon=folium.Icon(
            color="blue",
            icon="user",
        ),
    ).add_to(disney_map)

    for _, row in map_df.iterrows():
        favorite = bool(row["お気に入り"])
        icon_text = row["favorite_icon"] if favorite else ""
        display_name = (
            f'{icon_text} {row["name_ja"]}'
            if favorite
            else row["name_ja"]
        )

        popup_text = f"""
        <b>{display_name}</b><br>
        直線距離：{row["distance_m"]}m<br>
        待ち時間：{wait_text(row)}<br>
        待機列：{row["queue_icon"]} {row["queue_type"]}<br>
        天候：{row["weather_note"]}<br>
        絶叫度：{row["thrill_icon"]} {row["thrill_level"]}<br>
        注意：{row["thrill_note"]}<br>
        状況：{row["状況"]}
        """

        if favorite:
            marker_icon = folium.DivIcon(
                html=f"""
                <div style="
                    width:38px;
                    height:38px;
                    border-radius:50%;
                    background:white;
                    border:3px solid #f5b301;
                    box-shadow:0 2px 6px rgba(0,0,0,.35);
                    font-size:23px;
                    line-height:32px;
                    text-align:center;
                ">{icon_text}</div>
                """,
                icon_size=(38, 38),
                icon_anchor=(19, 19),
            )
        else:
            marker_icon = folium.Icon(
                color="red",
                icon="info-sign",
            )

        folium.Marker(
            location=[row["lat"], row["lon"]],
            tooltip=display_name,
            popup=folium.Popup(
                popup_text,
                max_width=300,
            ),
            icon=marker_icon,
        ).add_to(disney_map)

    return disney_map


def show_cards(card_df, key_prefix):
    """
    通常施設：名前・待ち時間・☆
    お気に入り：選択式アイコン・名前・待ち時間・★
    """
    for _, row in card_df.iterrows():
        favorite = bool(row["お気に入り"])
        entity_id = str(row["entity_id"])

        with st.container(border=True):
            icon_col, name_col, wait_col, star_col = st.columns(
                [1.35, 4.15, 1.2, 0.8],
                vertical_alignment="center",
            )

            # お気に入りだけ、押すと大量のアイコンから選べる
            if favorite:
                current_icon = row["favorite_icon"]

                if current_icon not in ICON_OPTIONS:
                    current_icon = "⭐"

                current_category = ICON_CATEGORIES.get(
                    current_icon,
                    CATEGORY_OPTIONS[0],
                )

                with icon_col.popover(
                    f"{current_icon} 変更",
                    use_container_width=True,
                    help="アイコンをカテゴリから選択",
                ):
                    selected_category = st.selectbox(
                        "カテゴリ",
                        CATEGORY_OPTIONS,
                        index=CATEGORY_OPTIONS.index(
                            current_category
                        ),
                        key=(
                            f"icon_category_"
                            f"{key_prefix}_{entity_id}"
                        ),
                    )

                    category_icons = ICONS_BY_CATEGORY[
                        selected_category
                    ]

                    icon_state_key = (
                        f"icon_value_"
                        f"{key_prefix}_{entity_id}"
                    )

                    if (
                        icon_state_key not in st.session_state
                        or st.session_state[icon_state_key]
                        not in category_icons
                    ):
                        st.session_state[icon_state_key] = (
                            current_icon
                            if current_icon in category_icons
                            else category_icons[0]
                        )

                    selected_icon = st.selectbox(
                        "アイコン",
                        category_icons,
                        format_func=lambda icon: (
                            f"{icon}  "
                            f"{ICON_NAMES.get(icon, '')}"
                        ),
                        key=icon_state_key,
                    )

                    st.caption(
                        f"{len(ICON_OPTIONS)}種類から選択できます。"
                    )

                    if st.button(
                        "このアイコンにする",
                        key=(
                            f"save_icon_"
                            f"{key_prefix}_{entity_id}"
                        ),
                        use_container_width=True,
                    ):
                        update_favorite_icon(
                            entity_id,
                            selected_icon,
                            favorites,
                        )
            else:
                icon_col.write("")

            name_col.markdown(
                f"**{row['name_ja']}**  \n"
                f"{row['distance_m']}m・{row['状況']}  \n"
                f"{row['queue_icon']} {row['queue_type']}・"
                f"{row['weather_note']}  \n"
                f"{row['thrill_icon']} {row['thrill_level']}・"
                f"{row['thrill_note']}"
            )

            wait_col.markdown(
                f"**{wait_text(row)}**"
            )

            clicked = star_col.button(
                "★" if favorite else "☆",
                key=f"{key_prefix}_{entity_id}",
                help=(
                    "お気に入りから外す"
                    if favorite
                    else "お気に入りに追加"
                ),
                use_container_width=True,
            )

            if clicked:
                toggle_favorite(
                    entity_id,
                    row["icon"],
                    favorites,
                )



favorite_count = int(df["お気に入り"].sum())

all_tab, favorite_tab = st.tabs([
    "すべて",
    f"お気に入り（{favorite_count}）",
])


with all_tab:
    st.subheader("アトラクション一覧")
    st.caption(
        "☆でお気に入り登録後、左のアイコンを押すとカテゴリ別に選べます。"
    )

    show_cards(
        df,
        key_prefix=f"all_{park_name}",
    )

    st.subheader("パークマップ")
    st.caption(
        "緑がランド、青がシーです。"
        "OpenStreetMapに登録された輪郭を"
        "そのまま表示しています。"
    )

    folium_static(
        make_map(df),
        width=900,
        height=600,
    )


with favorite_tab:
    favorite_df = df[
        df["お気に入り"]
    ].copy()

    if favorite_df.empty:
        st.info(
            "まだお気に入りがありません。"
            "「すべて」タブの☆を押してください。"
        )
    else:
        st.subheader("お気に入り一覧")

        show_cards(
            favorite_df,
            key_prefix=f"favorite_{park_name}",
        )

        st.subheader("お気に入りマップ")
        st.caption(
            "緑がランド、青がシーです。"
            "OpenStreetMapの輪郭データを使用しています。"
        )

        folium_static(
            make_map(favorite_df),
            width=900,
            height=600,
        )


st.caption(
    f"施設：{len(place_df)}件／"
    f"ライブ情報：{len(live_df)}件"
)

st.caption(
    "待機列環境はCSVに保存した目安です。"
    "実際の列は混雑・工事・運営状況で変わる場合があります。"
)

st.caption(
    "絶叫レベルは公式の特徴表示を参考に、"
    "強め・軽め・穏やかへ分けた目安です。"
)

st.markdown(
    "施設・待ち時間："
    "[ThemeParks.wiki](https://www.themeparks.wiki/)　"
    "地図・パーク輪郭："
    "[OpenStreetMap contributors]"
    "(https://www.openstreetmap.org/copyright)"
)
