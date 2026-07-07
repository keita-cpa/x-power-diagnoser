"""
download_all_prefs.py -- 全国47都道府県のGMLデータを一括DL・解凍する

【使い方】
    python download_all_prefs.py              # 全都道府県DL（未DL分のみ）
    python download_all_prefs.py --rebuild    # DL後にpickle再生成まで一括実行
    python download_all_prefs.py --skip 13   # 指定コードをスキップ（複数可: --skip 13 14）
    python download_all_prefs.py --only 26 27 40  # 指定コードのみDL

【所要時間目安】
    DL: 都道府県1件 = 数〜60秒（ファイルサイズによる）
    全国合計: 30〜60分（回線速度による）

【ディスク容量目安】
    ZIPで合計 500MB〜2GB 程度
"""

import sys
import io
import os
import time
import urllib.request
import urllib.error
import zipfile
import argparse
import subprocess
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data" / "zoning"

REFERER = "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A29-v2_1.html"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# 令和元年版 URL テンプレート
URL_TEMPLATE = "https://nlftp.mlit.go.jp/ksj/gml/data/A29/A29-19/A29-19_{code}_GML.zip"

PREFS = {
    "01": "北海道",
    "02": "青森県",
    "03": "岩手県",
    "04": "宮城県",
    "05": "秋田県",
    "06": "山形県",
    "07": "福島県",
    "08": "茨城県",
    "09": "栃木県",
    "10": "群馬県",
    "11": "埼玉県",
    "12": "千葉県",
    "13": "東京都",
    "14": "神奈川県",
    "15": "新潟県",
    "16": "富山県",
    "17": "石川県",
    "18": "福井県",
    "19": "山梨県",
    "20": "長野県",
    "21": "岐阜県",
    "22": "静岡県",
    "23": "愛知県",
    "24": "三重県",
    "25": "滋賀県",
    "26": "京都府",
    "27": "大阪府",
    "28": "兵庫県",
    "29": "奈良県",
    "30": "和歌山県",
    "31": "鳥取県",
    "32": "島根県",
    "33": "岡山県",
    "34": "広島県",
    "35": "山口県",
    "36": "徳島県",
    "37": "香川県",
    "38": "愛媛県",
    "39": "高知県",
    "40": "福岡県",
    "41": "佐賀県",
    "42": "長崎県",
    "43": "熊本県",
    "44": "大分県",
    "45": "宮崎県",
    "46": "鹿児島県",
    "47": "沖縄県",
}

MAX_RETRIES = 3
RETRY_WAIT = 5


def already_downloaded(code: str) -> bool:
    """ZIPまたは解凍済みフォルダが存在するか確認する。"""
    zip_path = DATA_DIR / f"A29-19_{code}_GML.zip"
    dir_path = DATA_DIR / f"A29-19_{code}"
    return zip_path.exists() or dir_path.exists()


def download_pref(code: str, name: str) -> bool:
    """1都道府県をDLして解凍する。成功したらTrue。"""
    url = URL_TEMPLATE.format(code=code)
    zip_path = DATA_DIR / f"A29-19_{code}_GML.zip"

    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": REFERER})
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=180) as r, open(zip_path, "wb") as f:
                total = int(r.headers.get("Content-Length", 0))
                done = 0
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    pct = done / total * 100 if total else 0
                    mb_done = done / 1024 / 1024
                    mb_total = total / 1024 / 1024 if total else 0
                    print(f"  {pct:5.1f}%  {mb_done:.1f}/{mb_total:.1f}MB", end="\r", flush=True)
            elapsed = time.time() - t0
            size_mb = zip_path.stat().st_size / 1024 / 1024
            print(f"  [OK] {size_mb:.1f}MB  ({elapsed:.1f}秒)          ")
            break

        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"  [SKIP] 404 - 令和元年版データなし（{name}）")
                return False
            if attempt < MAX_RETRIES - 1:
                print(f"  [RETRY {attempt+1}/{MAX_RETRIES}] HTTP {e.code} → {RETRY_WAIT}秒後に再試行...")
                time.sleep(RETRY_WAIT)
            else:
                print(f"  [ERROR] HTTP {e.code} - {name} のDL失敗（{MAX_RETRIES}回）")
                return False

        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                print(f"  [RETRY {attempt+1}/{MAX_RETRIES}] {e} → {RETRY_WAIT}秒後に再試行...")
                time.sleep(RETRY_WAIT)
            else:
                print(f"  [ERROR] {name} のDL失敗: {e}")
                if zip_path.exists():
                    zip_path.unlink()
                return False

    # 解凍
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(DATA_DIR)
    except Exception as e:
        print(f"  [ERROR] 解凍失敗: {e}")
        return False

    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="全国GMLデータ一括DL")
    parser.add_argument("--rebuild", action="store_true", help="DL後にpickle再生成まで実行")
    parser.add_argument("--skip", nargs="+", default=[], metavar="CODE", help="スキップする都道府県コード（例: --skip 13）")
    parser.add_argument("--only", nargs="+", default=[], metavar="CODE", help="このコードのみDL（例: --only 26 27）")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    targets = list(PREFS.keys())
    if args.only:
        targets = [c.zfill(2) for c in args.only]
    skip_set = {c.zfill(2) for c in args.skip}

    total = len(targets)
    done_count = 0
    skip_count = 0
    fail_list: list[str] = []
    not_found_list: list[str] = []

    print(f"[START] 対象: {total} 都道府県")
    print(f"        保存先: {DATA_DIR}")
    print()

    t_start = time.time()

    for i, code in enumerate(targets, 1):
        name = PREFS.get(code, f"コード{code}")

        if code in skip_set:
            print(f"[{i:2d}/{total}] {name}({code}) ... SKIP（--skip指定）")
            skip_count += 1
            continue

        if already_downloaded(code):
            print(f"[{i:2d}/{total}] {name}({code}) ... 済（スキップ）")
            skip_count += 1
            continue

        print(f"[{i:2d}/{total}] {name}({code}) DL中...")
        ok = download_pref(code, name)

        if ok:
            done_count += 1
        else:
            # 404 = データなし（正常）か DLエラーかを区別
            zip_path = DATA_DIR / f"A29-19_{code}_GML.zip"
            if not zip_path.exists():
                not_found_list.append(f"{code}:{name}")
            else:
                fail_list.append(f"{code}:{name}")

        # サーバー負荷軽減のため少し待つ
        if i < total:
            time.sleep(1)

    elapsed_total = time.time() - t_start
    print()
    print("=" * 60)
    print(f"[完了] 所要時間: {elapsed_total/60:.1f}分")
    print(f"  DL成功:   {done_count} 件")
    print(f"  スキップ: {skip_count} 件（DL済みまたは除外）")
    if not_found_list:
        print(f"  データなし（404）: {len(not_found_list)} 件")
        for s in not_found_list:
            print(f"    - {s}")
    if fail_list:
        print(f"  DL失敗: {len(fail_list)} 件")
        for s in fail_list:
            print(f"    - {s}")
    print("=" * 60)

    if args.rebuild:
        print()
        print("[REBUILD] pickle再生成を開始します...")
        result = subprocess.run(
            [sys.executable, str(BASE_DIR / "setup_data.py")],
            capture_output=False,
        )
        if result.returncode == 0:
            print("[OK] pickle再生成完了")
        else:
            print("[ERROR] pickle再生成に失敗しました")
            print("  手動で: python setup_data.py")


if __name__ == "__main__":
    main()
