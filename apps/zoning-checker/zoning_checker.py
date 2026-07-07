"""
zoning_checker.py -- エリア適法性チェックCLI（Keita_CPA専用内部ツール）

【使い方】
    python zoning_checker.py
    python zoning_checker.py --address "東京都渋谷区桜丘町26-1"

【事前準備】
    setup_data.py でGMLデータを前処理しておくこと（初回のみ）

【X リプライ活用フロー】
    セラピストが「このエリアで開業しようか」とつぶやく
    → このツールで判定
    → 結果テキストをXリプライで返す
    → リプライ×5シグナル + 頼れる専門家ギャップ = DM相談への導線
"""

import sys
import io
import os
import pickle
import json
import argparse
import urllib.request
import urllib.parse
from pathlib import Path
from shapely.geometry import Point

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE_DIR = Path(__file__).parent
PICKLE_PATH = BASE_DIR / "data" / "zoning" / "zoning_data.pkl"

GSI_GEOCODE_URL = "https://msearch.gsi.go.jp/address-search/AddressSearch?q={}"

# 用途地域コード -> (名称, 判定, 備考)
YOTO_CODE_MAP = {
    "101": ("第一種低層住居専用地域",   "NG",     "店舗の建築が原則不可"),
    "102": ("第二種低層住居専用地域",   "条件付き", "床面積150m2以下の店舗のみ可（テナントの場合は建物用途も要確認）"),
    "103": ("第一種中高層住居専用地域", "NG",     "店舗は2F以下かつ500m2以下のみ（実質困難）"),
    "104": ("第二種中高層住居専用地域", "条件付き", "床面積1,500m2以下の店舗は可"),
    "105": ("第一種住居地域",           "条件付き", "床面積3,000m2以下の店舗は可（多くのサロンは対象内）"),
    "106": ("第二種住居地域",           "OK",     "店舗の規模制限なし"),
    "107": ("準住居地域",               "OK",     "店舗の規模制限なし"),
    "108": ("田園住居地域",             "NG",     "農地・住居以外は原則不可"),
    "111": ("近隣商業地域",             "OK",     "制限なし"),
    "112": ("商業地域",                 "OK",     "制限なし"),
    "121": ("準工業地域",               "OK",     "制限なし"),
    "122": ("工業地域",                 "NG",     "サービス業は原則不可"),
    "123": ("工業専用地域",             "NG",     "工業施設のみ可"),
}

VERDICT_LABELS = {
    "OK":     "[OK]     問題なし",
    "条件付き": "[条件付き] 規模・条件を確認",
    "NG":     "[NG]     原則不可",
    "?":      "[?]      判定不能（データ未収録エリア）",
}


def geocode(address: str) -> tuple[float, float] | None:
    """住所→(lon, lat)。国土地理院ジオコーディングAPI使用（登録不要・無料）。"""
    encoded = urllib.parse.quote(address)
    url = GSI_GEOCODE_URL.format(encoded)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ZoningChecker/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        if data:
            lon, lat = data[0]["geometry"]["coordinates"]
            return float(lon), float(lat)
    except Exception as e:
        print(f"  [ERROR] ジオコーディング失敗: {e}")
    return None


def load_zoning_data() -> list[dict] | None:
    """前処理済みpickleをロードする。"""
    if not PICKLE_PATH.exists():
        return None
    with open(PICKLE_PATH, "rb") as f:
        return pickle.load(f)


def find_zone(lon: float, lat: float, polys: list[dict]) -> dict | None:
    """緯度経度→用途地域ポリゴンのpoint-in-polygon判定。"""
    pt = Point(lon, lat)
    for item in polys:
        try:
            if item["polygon"].contains(pt):
                return item
        except Exception:
            continue
    return None


def build_reply_text(address: str, zone_name: str, verdict: str, note: str) -> str:
    """Xリプライ用の短文テキストを生成する（140文字以内を目安）。"""
    verdict_map = {"OK": "問題なし", "条件付き": "条件付きで可", "NG": "原則不可", "?": "判定不能"}
    v_label = verdict_map.get(verdict, verdict)

    if verdict == "OK":
        return (
            f"このエリアは {zone_name} です。"
            f"エステ・サロン系の営業は建築基準法上 {v_label} の区域になります。"
            f"ただしテナントの建物用途や消防法・条例の確認は別途必要ですので、"
            f"入居前に確認しておくと安心ですよ。"
        )
    elif verdict == "条件付き":
        return (
            f"このエリアは {zone_name} です。"
            f"{note}"
            f"建物の規模次第では営業できますが、テナント契約前に行政窓口への確認をおすすめします。"
        )
    else:  # NG or ?
        return (
            f"このエリアは {zone_name} です。"
            f"{note}"
            f"詳細は行政窓口（建築指導課等）への確認が必要ですが、参考まで。"
        )


def check(address: str, polys: list[dict] | None) -> None:
    """メイン判定処理。"""
    print(f"\n住所: {address}")
    print("-" * 60)

    # 1. ジオコーディング
    result = geocode(address)
    if result is None:
        print("[ERROR] 住所の緯度経度が取得できませんでした（住所を確認してください）")
        return
    lon, lat = result
    print(f"座標: 緯度 {lat:.6f}, 経度 {lon:.6f}")

    # 2. 用途地域判定
    if polys is None:
        print("[WARNING] zoning_data.pkl が見つかりません")
        print("          python setup_data.py を実行してデータを前処理してください")
        print("          （国土数値情報GMLのDL手順は CLAUDE.md 参照）")
        print()
        print("[参考] 座標の取得には成功しています")
        print(f"       Google Maps等で用途地域を手動確認してください:")
        print(f"       https://www.google.com/maps/search/?api=1&query={lat},{lon}")
        return

    zone = find_zone(lon, lat, polys)

    if zone is None:
        verdict = "?"
        zone_name = "データ未収録（未整備区域または市街化調整区域の可能性）"
        note = "このエリアのデータがありません。市区町村の都市計画課に確認してください。"
    else:
        code = zone["code"]
        zone_name, verdict, note = YOTO_CODE_MAP.get(code, (zone["name"], "?", ""))

    # 3. 結果出力
    label = VERDICT_LABELS.get(verdict, f"[{verdict}]")
    print(f"用途地域: {zone_name}")
    print(f"判定:     {label}")
    if note:
        print(f"備考:     {note}")

    # 4. Xリプライ用テキスト
    reply = build_reply_text(address, zone_name, verdict, note)
    print()
    print("=" * 60)
    print("[X リプライ用テキスト（コピーして使用）]")
    print("=" * 60)
    print(reply)
    print("=" * 60)
    print(f"文字数: {len(reply)}字")
    print()
    print("【免責】建築基準法の用途地域判定に基づく参考情報です。")
    print("        テナントの建物用途・都道府県条例・消防法等は別途確認が必要です。")
    print("        最終判断は行政書士・建築士等への相談をおすすめします。")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="メンエス営業エリア適法性チェック（用途地域判定）"
    )
    parser.add_argument("--address", type=str, default="", help="判定する住所（省略で対話入力）")
    args = parser.parse_args()

    polys = load_zoning_data()
    if polys:
        print(f"[OK] {len(polys)} ポリゴンロード完了")
    else:
        print("[WARNING] 用途地域データ未ロード（setup_data.py を事前に実行してください）")

    if args.address:
        check(args.address, polys)
        return

    # 対話モード
    print()
    print("エリア適法性チェック（用途地域判定）")
    print("住所を入力してください（q で終了）")
    print()
    while True:
        try:
            address = input("住所 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n終了します")
            break
        if not address:
            continue
        if address.lower() == "q":
            break
        check(address, polys)


if __name__ == "__main__":
    main()
