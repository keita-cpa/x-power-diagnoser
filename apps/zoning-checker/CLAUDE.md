# CLAUDE.md — エリア適法性チェックCLIツール

## 目的
住所入力→用途地域判定→メンエス営業可否をKeita_CPAが即座に確認するための内部CLIツール。
セラピストが「このエリアで開業しようか」とXでつぶやいたとき、正確な情報でリプライする。

## 使い方

### 初回セットアップ（データ配置）
1. https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A29.html を開く
2. 対象都道府県の `A29-11_XX_GML.zip` をダウンロード（XXは都道府県コード）
3. `data/zoning/` に解凍して配置
4. `python setup_data.py` で前処理（pickle変換）

### 通常使用
```bash
python zoning_checker.py
# → 住所を入力すると判定結果とXリプライ用テキストを出力
```

## ファイル構成
| ファイル | 役割 |
|---|---|
| `zoning_checker.py` | メインCLI |
| `setup_data.py` | GMLデータ前処理（初回のみ） |
| `data/zoning/*.xml` | 国土数値情報GML（gitignore対象） |
| `data/zoning/zoning_data.pkl` | 前処理済みpickle（gitignore対象） |

## 都道府県コード（主要）
13=東京 / 14=神奈川 / 27=大阪 / 23=愛知 / 26=京都 / 28=兵庫 / 40=福岡

## 制約
- config.py / .env は存在しない（APIキー不要）
- 国土数値情報GMLはgitignore対象（data/zoning/ 配下はコミット禁止）
- 判定結果は「参考情報」として出力する（法的アドバイスではない）
