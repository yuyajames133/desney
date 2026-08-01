# Magic Park Navi CSS分離版

## ファイル
- app.py
- style.css
- official_links.csv
- requirements.txt
- attraction_names.csv
- favorites.csv
- icon_catalog.csv

## 公式リンクを追加する方法
official_links.csv に1行追加してください。

例:
東京ディズニーランド,アトラクション,施設名,https://www.tokyodisneyresort.jp/tdl/attraction/detail/数字/

CSVの施設名はアプリに表示される日本語名と合わせます。

## タイトル文字の修正
style.css の `.facility-title` が施設名の色を指定しています。

```css
.facility-title,
.facility-title * {
    color: #06284d !important;
    -webkit-text-fill-color: #06284d !important;
}
```
