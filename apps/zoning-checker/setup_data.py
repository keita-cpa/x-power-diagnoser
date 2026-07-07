"""
setup_data.py -- 国土数値情報GMLを前処理してpickleに変換する（初回のみ実行）

【事前準備】
1. https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A29-v2_1.html を開く
2. 対象都道府県の A29-19_XX_GML.zip をダウンロード（令和元年版推奨）
3. このスクリプトと同じ階層の data/zoning/ に解凍して配置
4. python setup_data.py --pref 13  （13=東京都）

【自動DL】
python setup_data.py --download 13  で DL+解凍+前処理を一括実行

【都道府県コード主要一覧】
01=北海道 / 13=東京 / 14=神奈川 / 23=愛知 / 26=京都 / 27=大阪 / 28=兵庫 / 40=福岡 / 47=沖縄
"""

import sys
import io
import os
import glob
import json
import urllib.request
import zipfile
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import pickle
import xml.etree.ElementTree as ET
import argparse
from pathlib import Path
from shapely.geometry import Polygon, shape

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data" / "zoning"
PICKLE_PATH = DATA_DIR / "zoning_data.pkl"

NS = {
    "ksj": "http://nlftp.mlit.go.jp/ksj/schemas/ksj-app",
    "gml": "http://www.opengis.net/gml/3.2",
    "xlink": "http://www.w3.org/1999/xlink",
}

# 用途地域コード -> (名称, エステ可否, 備考)
YOTO_CODE_MAP = {
    "101": ("第一種低層住居専用地域",   "NG",     "商業施設・店舗は原則不可"),
    "102": ("第二種低層住居専用地域",   "条件付き", "床面積150m2以下の店舗のみ可"),
    "103": ("第一種中高層住居専用地域", "NG",     "店舗は2F以下かつ500m2以下のみ"),
    "104": ("第二種中高層住居専用地域", "条件付き", "床面積1,500m2以下の店舗は可"),
    "105": ("第一種住居地域",           "条件付き", "床面積3,000m2以下の店舗は可"),
    "106": ("第二種住居地域",           "OK",     "制限なし（大規模施設は要確認）"),
    "107": ("準住居地域",               "OK",     "制限なし"),
    "108": ("田園住居地域",             "NG",     "農地・住居以外は原則不可"),
    "111": ("近隣商業地域",             "OK",     "制限なし"),
    "112": ("商業地域",                 "OK",     "制限なし"),
    "121": ("準工業地域",               "OK",     "制限なし"),
    "122": ("工業地域",                 "NG",     "サービス業は原則不可"),
    "123": ("工業専用地域",             "NG",     "工業施設のみ"),
}


def parse_pos_list(pos_text: str) -> list[tuple[float, float]]:
    """
    gml:posList のテキストを (lon, lat) タプルのリストに変換する。
    国土数値情報GMLは lat lon 交互の順で記録されている。
    """
    vals = [float(v) for v in pos_text.strip().split()]
    # lat lon lat lon ... -> (lon, lat) に変換（shapely は (x=lon, y=lat)）
    coords = [(vals[i + 1], vals[i]) for i in range(0, len(vals) - 1, 2)]
    return coords


def parse_gml_file(gml_path: str) -> list[dict]:
    """
    GMLファイルをパースしてポリゴンリストを返す。
    各要素: {"code": str, "name": str, "polygon": Polygon}
    """
    tree = ET.parse(gml_path)
    root = tree.getroot()

    # id -> ポリゴン座標 のマップを先に構築
    area_coords: dict[str, list] = {}
    for area_elem in root.iter("{http://nlftp.mlit.go.jp/ksj/schemas/ksj-app}A29_Area"):
        gml_id = area_elem.get("{http://www.opengis.net/gml/3.2}id")
        if not gml_id:
            continue
        pos_list_elem = area_elem.find(
            ".//{http://www.opengis.net/gml/3.2}posList"
        )
        if pos_list_elem is not None and pos_list_elem.text:
            area_coords[gml_id] = parse_pos_list(pos_list_elem.text)

    # A29 要素（用途地域属性）を走査してポリゴンと結合
    results = []
    for a29_elem in root.iter("{http://nlftp.mlit.go.jp/ksj/schemas/ksj-app}A29"):
        # 用途地域コード（ksj:area 子要素内にあるため再帰検索）
        code_elem = a29_elem.find(
            ".//{http://nlftp.mlit.go.jp/ksj/schemas/ksj-app}A29_003"
        )
        code = (code_elem.text or "").strip() if code_elem is not None else ""

        # 面参照
        loc_elem = a29_elem.find(
            "{http://nlftp.mlit.go.jp/ksj/schemas/ksj-app}location"
        )
        if loc_elem is None:
            continue
        href = loc_elem.get("{http://www.w3.org/1999/xlink}href", "").lstrip("#")
        coords = area_coords.get(href)
        if not coords or len(coords) < 3:
            continue

        try:
            poly = Polygon(coords)
        except Exception:
            continue
        if not poly.is_valid:
            poly = poly.buffer(0)  # 自己交差修正

        name, _, _ = YOTO_CODE_MAP.get(code, (f"コード{code}", "?", ""))
        results.append({"code": code, "name": name, "polygon": poly})

    return results


YOTO_NAME_TO_CODE = {v[0]: k for k, v in YOTO_CODE_MAP.items()}

REFERER = "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A29-v2_1.html"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def parse_geojson_file(geojson_path: str) -> list[dict]:
    """GeoJSONファイルをパースしてポリゴンリストを返す（GML令和元年版対応）。"""
    with open(geojson_path, encoding="utf-8") as f:
        data = json.load(f)

    results = []
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        name = props.get("A29_005") or ""
        code = YOTO_NAME_TO_CODE.get(name, "")
        if not code:
            continue
        try:
            poly = shape(feat["geometry"])
        except Exception:
            continue
        if not poly.is_valid:
            poly = poly.buffer(0)
        yname, _, _ = YOTO_CODE_MAP.get(code, (name, "?", ""))
        results.append({"code": code, "name": yname, "polygon": poly})
    return results


def download_pref(pref_code: str) -> None:
    """都道府県コードのGMLをDLして data/zoning/ に解凍する。"""
    pref_int = int(pref_code)
    zip_name = f"A29-19_{pref_int:02d}_GML.zip"
    url = f"https://nlftp.mlit.go.jp/ksj/gml/data/A29/A29-19/{zip_name}"
    zip_path = DATA_DIR / zip_name

    print(f"[DL] {zip_name} ...")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": REFERER})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as r, open(zip_path, "wb") as f:
            total = int(r.headers.get("Content-Length", 0))
            done = 0
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                pct = done / total * 100 if total else 0
                print(f"  {pct:5.1f}%  {done/1024/1024:.1f}/{total/1024/1024:.1f}MB", end="\r", flush=True)
    except Exception as e:
        print(f"\n[ERROR] DL失敗: {e}")
        sys.exit(1)
    print(f"\n[OK] DL完了 ({time.time()-t0:.1f}秒)")

    print("[UNZIP] 解凍中...")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(DATA_DIR)
    print("[OK] 解凍完了")


def main() -> None:
    parser = argparse.ArgumentParser(description="国土数値情報GMLを前処理してpickleに変換")
    parser.add_argument("--pref", type=str, default="", help="都道府県コード（例: 13）")
    parser.add_argument("--download", type=str, default="", help="DL+解凍+前処理を一括実行（例: --download 13）")
    args = parser.parse_args()

    pref = args.download or args.pref

    if args.download:
        download_pref(args.download)

    # GeoJSONファイルを優先して探す
    geojson_files = glob.glob(str(DATA_DIR / "**" / "*.geojson"), recursive=True)
    # XMLフォールバック（テスト用・旧版GML）
    xml_files = glob.glob(str(DATA_DIR / "**" / "*.xml"), recursive=True)

    if pref:
        pref_int = int(pref)
        geojson_files = [f for f in geojson_files if f"_{pref_int:02d}" in f or f"_{pref}" in f]
        xml_files = [f for f in xml_files if f"_{pref_int:02d}_" in os.path.basename(f) or pref in f]

    all_polys: list[dict] = []

    if geojson_files:
        print(f"[INFO] GeoJSONモード: {len(geojson_files)} ファイル")
        for gj in sorted(geojson_files):
            try:
                polys = parse_geojson_file(gj)
                all_polys.extend(polys)
            except Exception as e:
                print(f"  [ERROR] {os.path.basename(gj)}: {e}")
        print(f"[INFO] GeoJSON処理完了: {len(all_polys)} ポリゴン")
    elif xml_files:
        print(f"[INFO] XMLモード（フォールバック）: {len(xml_files)} ファイル")
        for gml_file in sorted(xml_files):
            print(f"  [PARSE] {os.path.basename(gml_file)} ...")
            try:
                polys = parse_gml_file(gml_file)
                all_polys.extend(polys)
                print(f"         -> {len(polys)} ポリゴン取得")
            except Exception as e:
                print(f"  [ERROR] {e}")
    else:
        print("[ERROR] GeoJSON/GMLファイルが見つかりません")
        print(f"  配置先: {DATA_DIR}")
        print("  python setup_data.py --download 13  で自動DL")
        sys.exit(1)

    if not all_polys:
        print("[ERROR] 有効なポリゴンが取得できませんでした")
        sys.exit(1)

    with open(PICKLE_PATH, "wb") as f:
        pickle.dump(all_polys, f)

    print(f"\n[OK] {len(all_polys)} ポリゴンを pickle に保存しました")
    print(f"     -> {PICKLE_PATH}")


if __name__ == "__main__":
    main()
