# Context: docs/knowledge/X_Algorithm/

## 役割

X（旧Twitter）の公式オープンソース推薦アルゴリズム。**読み取り専用ナレッジ。変更禁止。**

### 参照する主な目的

1. `apps/auto-poster/prompts.py` の最適化（アルゴリズムが評価するシグナルの把握）
2. `apps/power-diagnoser/app/scoring/algorithm_fitness.py` のスコアリング根拠確認
3. ランキングシグナル・フィーチャーの調査

---

## 主要サブプロジェクト

| ディレクトリ | 言語 | 内容 |
|---|---|---|
| `the-algorithm-main/` | Scala/Java | メインタイムラインランキング（最重要） |
| `home-mixer/` | Scala | ホームタイムライン合成 |
| `cr-mixer/` | Scala | 候補ツイート取得 |
| `ann/` | — | 近似最近傍探索 |
| `follow-recommendations-service/` | Scala | フォロー推薦 |
| `navi/` | Rust | MLモデルサービング |
| `timelines/` | Scala | タイムライン処理 |
| `src/` | Scala/Java | コアユーティリティ |

---

## 最初に参照すべき重要ファイル

1. `docs/knowledge/X_Algorithm/README.md` — アーキテクチャ概要
2. `docs/knowledge/X_Algorithm/RETREIVAL_SIGNALS.md` — ランキングシグナル一覧
3. `docs/knowledge/X_Algorithm/the-algorithm-main/` — メインロジック

---

## 参照タイミング

- auto-posterの投稿フォーマット・プロンプトを最適化する前
- power-diagnoserのアルゴリズム適合度スコアの根拠を調べるとき
- 「なぜこのツイートがバズるか」の技術的根拠を確認するとき

---

## 注意

このディレクトリは変更しない。参照のみ。
元のソース: X社公式オープンソースリポジトリ
