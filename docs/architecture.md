# X戦闘力診断ツール（x-power-diagnoser）マスタードキュメント

## 1. プロジェクトの目的と基本戦略

メンエス界隈のセラピスト・お客さん（太客）のXアカウントを5軸でスコアリングし、**ランク（S〜D）と大喜利的称号**を返すエンタメ型Webアプリ。

* **ギャップ戦略：** Big4出身の公認会計士「Keita_CPA」が、TikTok・ギャル語を真顔で多用して専門的分析を語るというシュールなギャップをAIキャラクターの核とする。会計用語×ギャルマインドの衝突こそがシェア・バズの起爆剤。
* **シェア設計：** 結果画面（称号＋スコーダーチャート）はスクショ映えを最優先に設計し、SNS拡散→Keita_CPAへの流入を促す構造。
* **エンタメ×CTA：** 診断結果でKeita_CPAのXアカウントへ誘導するCTAを配置し、インフルエンサーとしての認知拡大に直結させる。

---

## 2. フォルダ体系・ファイル構成

```
x-power-diagnoser/
 ├─ app/
 │   ├─ __init__.py
 │   ├─ main.py              # FastAPIエントリーポイント。ルーティング・DI・レスポンス組立
 │   ├─ llm.py               # Gemini APIクライアント。ANGEL/DEVILモード判定 + プロンプト管理
 │   ├─ models.py            # Pydanticモデル定義（Request / Response / ScoreBreakdown等）
 │   ├─ ranking.py           # スコア→ランク（S/A/B/C/D）・称号変換テーブル
 │   ├─ mock_data.py         # X API未接続フェーズ用のモックデータ生成（twitter_id依存の疑似乱数）
 │   ├─ scoring/
 │   │   ├─ __init__.py
 │   │   ├─ follower_influence.py   # フォロワー影響力（FF比補正つきフォロワー数評価）
 │   │   ├─ impression_power.py     # インプレッション力（中央値ベースの拡散力）
 │   │   ├─ algorithm_fitness.py    # アルゴリズム適合度（X公式Earlybird重みによる戦闘力）
 │   │   ├─ engagement_rate.py      # エンゲージメント率（業界平均比較）
 │   │   └─ community_activity.py  # 界隈アクティブ度（メンエス界隈での存在感）
 │   └─ templates/
 │       └─ index.html       # フロントエンド単一ページ（Jinja2テンプレート / Chart.js / html2canvas）
 ├─ render.yaml              # Renderデプロイ設定（uvicorn起動・GEMINI_API_KEY環境変数）
 ├─ requirements.txt         # Python依存関係（FastAPI, uvicorn, Pydantic, google-genai, Jinja2）
 ├─ .gitignore
 └─ x_diagnoser_master.md   # 本ドキュメント
```

---

## 3. アーキテクチャ詳細

### 3-1. バックエンド（FastAPI）

| エンドポイント | メソッド | 役割 |
|---|---|---|
| `/` | GET | `index.html` をJinja2でレンダリング |
| `/api/health` | GET | ヘルスチェック |
| `/api/diagnose` | POST | 診断メイン処理（スコア計算→LLM→レスポンス） |

**診断フロー（`app/main.py`）：**
1. `DiagnoseRequest`（twitter_id, user_type）を受信
2. `mock_data.generate_mock_data()` でX APIの代替データを生成
3. 5つのスコアリングモジュールを並列実行し、0〜20点を各軸で算出（合計100点満点）
4. `ranking.determine_rank_and_title()` でランクと称号を決定
5. `llm.generate_analytical_advice()` でGemini APIを呼び出し、Keita_CPAキャラクターのアドバイスを生成
6. `DiagnoseResponse` を返却

### 3-2. スコアリング（`app/scoring/`）

各モジュールは `calc(mock_data) -> tuple[int, str]`（スコア, 説明文）を返すシンプルなインターフェースを持つ。

| 軸 | ファイル | 評価ロジックの核 |
|---|---|---|
| フォロワー影響力 | `follower_influence.py` | FF比補正つきフォロワー数の対数スケール評価 |
| インプレッション力 | `impression_power.py` | 直近30ツイートのインプレッション中央値 |
| アルゴリズム適合度 | `algorithm_fitness.py` | X公式Earlybird重みによる加重スコア |
| エンゲージメント率 | `engagement_rate.py` | (いいね+RT+リプ) / インプレッションの業界平均比較 |
| 界隈アクティブ度 | `community_activity.py` | 界隈キーワード使用率 × 界隈アカウントとのインタラクション率 |

### 3-3. LLMプロンプトエンジニアリング（`app/llm.py`）

**キャラクター設計（_PERSONA）：**
Big4出身の公認会計士が、なぜか2026年最新のTikTok・ギャル語を真顔で多用する——このギャップがコンセプトの核。会計・財務の専門用語を用いた分析と、ギャルマインド全開のコメントを交互に繰り出すことで、スクショしたくなるシュールな文章を生成する。

**ANGEL / DEVILモード：**
- `twitter_id` のSHA-256ダイジェスト最終バイトの偶奇で決定論的に振り分け（同じIDには常に同じモード）。
- **ANGEL**：強み軸を根拠に全肯定・称賛。`temperature=0.75`
- **DEVIL**：弱み軸を根拠に愛あるツッコミで指摘。`temperature=0.70`

**出力制御（プロンプト設計上の重要制約）：**
- スコアの生数値・計算式・内訳は**出力絶対禁止**。AIには定性的な解釈のみを許可する。
- Markdown記法（`**`や`#`）の出力禁止。
- ギャルスラングの積極使用リスト（メロい, えぐち, 確定演出, ほんmoney 等）と使用禁止リスト（マジ卍, ぴえん 等の死語）をシステムプロンプトに組み込む。
- 出力テンプレートを厳格に指定（15〜25文字のキャッチコピー→解説150〜200文字→`╰ᘏᗢ ☕︎`で締め）。
- `max_output_tokens=3000`, `thinking_budget=0`（思考トークン節約）で安定出力を担保。
- fallbackあり：APIキー未設定・エラー時もエンドポイント全体は死なない。

**モデル：** `gemini-2.5-flash`

### 3-4. フロントエンド（`app/templates/index.html`）

単一HTMLファイルにフロントエンドのすべてを集約するSPA構成。

- **Chart.js**：診断結果の5軸スコアをレーダーチャートで可視化
- **html2canvas**：結果カードをPNG化してSNSシェア機能を実現
- **Jinja2**：FastAPIから`TemplateResponse`として配信

---

## 4. インフラ・デプロイ（Render）

**`render.yaml` 定義：**
```yaml
services:
  - type: web
    name: x-power-diagnoser
    env: python
    buildCommand: "pip install -r requirements.txt"
    startCommand: "uvicorn app.main:app --host 0.0.0.0 --port $PORT"
    envVars:
      - key: GEMINI_API_KEY
        sync: false  # Renderダッシュボードで手動設定
```

- PaaS（Render）にデプロイ。VPS・Cronは使用しない。
- `GEMINI_API_KEY` はRenderの環境変数として管理。コード・Gitには**絶対に含めない**。
- コールドスタート対策：Free Planではスリープあり。有料Planへの移行を検討時は`startCommand`変更不要。

---

## 5. 依存関係（`requirements.txt`）

| パッケージ | バージョン | 用途 |
|---|---|---|
| `fastapi` | 0.115.12 | Webフレームワーク |
| `uvicorn[standard]` | 0.34.0 | ASGIサーバー |
| `python-multipart` | 0.0.20 | フォームデータ対応 |
| `pydantic` | 2.11.1 | バリデーション・モデル定義 |
| `jinja2` | 3.1.6 | HTMLテンプレートエンジン |
| `google-genai` | 1.10.0 | Gemini API クライアント |

---

## 6. 現フェーズの制約と今後のロードマップ

### 現状（モックフェーズ）
- X APIは未接続。`mock_data.py` が `twitter_id` を元にしたシード値で疑似的なデータを生成する。
- 診断結果は同一IDに対して常に同じ（決定論的モック）。

### ロードマップ
1. **X API v2接続**：`/users/by/username/{username}` および `/users/:id/tweets` でリアルデータ取得に移行。`mock_data.py` を `x_api_client.py` に置き換え。
2. **シェア画像のOGP最適化**：html2canvasで生成したPNG画像のサーバーサイド保存・OGP設定。
3. **診断履歴のDB保存**：Supabase（PostgreSQL）に診断結果を蓄積し、ランキング機能を追加。
4. **チャットボット連携**：診断後にKeita_CPAのナレッジベースへ誘導するPWA対応チャット機能。

---

## 7. Claude Code 運用プロトコル（本プロジェクト向け）

1. **スコアリングの変更**：各 `scoring/` モジュールは独立しており、`calc()` の戻り値シグネチャを変えない限り他に影響しない。変更後は `app/main.py` の呼び出し箇所を必ず確認する。
2. **プロンプト変更**：`app/llm.py` の `SYSTEM_PROMPT_ANGEL/DEVIL` を変更する場合、スラングリストの整合性（積極使用推奨 vs 絶対禁止）を維持する。称号テーブル（`ranking.py`）との世界観を統一すること。
3. **環境変数**：`GEMINI_API_KEY` は `.env` で管理し、コードに直書きしない。Renderには手動設定。
4. **Gitワークフロー**：`feat / fix / refactor / chore` の conventional commits。本番 `main` ブランチへの直pushは許可するが、破壊的変更前は必ずコミットして巻き戻せる状態を確保する。
5. **コスト管理**：`thinking_budget=0` を維持してGeminiの思考トークン消費を抑制する。出力文字数が膨らむ場合は `max_output_tokens` を調整する前にシステムプロンプトのテンプレート制約を見直す。

---

## 8. 最新Xアルゴリズムへの適合方針

本ツールのスコアリングおよび運用アドバイスは、Xアルゴリズムの最新動向を踏まえた以下の方針に基づいて設計・更新すること。

### 8-1. 滞在時間（Read Time）の重視
Xは2024年以降、ツイートを開いて読み続ける時間（Read Time / Dwell Time）をランキングの主要シグナルとして強化している。
- **運用方針**：短い文章より「読ませる」コンテンツ（長文・連ツイ・画像付き解説）を評価軸に加える。
- **スコアリング反映**：`algorithm_fitness.py` のウェイト調整時は、エンゲージメント数だけでなく「読まれる構造か」も考慮する。

### 8-2. リプライによる会話の評価
リプライで会話が発生した投稿はXアルゴリズムに「コミュニティ活性化」として認識され、タイムライン優位性が上昇する。
- **運用方針**：フォロワーへの積極的な問いかけ（質問ポスト・アンケート）でリプライ誘発を狙う。
- **スコアリング反映**：`community_activity.py` の評価軸において、界隈内リプライ率を重要指標として維持する。

### 8-3. 外部リンクの冷遇
外部URLを本文に含む投稿は視認性が最大8倍低下する（_ALGORITHM_FACTS ファクト① 参照）。
- **運用方針**：URLはリプライや引用ポストに分離する。本文にはテキストと画像のみを置く。

---

## 9. アカウント凍結リスクと安全対策

自動投稿・自動リプライ運用時は以下のリスクと対策を必ず遵守すること。

### 9-1. 凍結（サスペンド）リスクの高い行為
| リスク行為 | Xアルゴリズム上の問題 |
|---|---|
| 短時間に大量ポスト（連投） | Author Diversityペナルティ（最大75%減衰）＋スパム判定(pSpam)上昇 |
| 同文・類似文の重複投稿 | 重複コンテンツとしてシャドウバン・凍結の引き金 |
| 大量フォロー・フォロー解除の繰り返し | FF比悪化によるpSpam上昇 |
| 無関係ハッシュタグの乱用 | スパム判定直結 |

### 9-2. 必須安全対策：Dry Run（人間による事前確認）
**`apps/auto-poster/` を使った自動投稿・自動リプライは、必ずDry Runを挟んでから本番実行すること。**

```bash
# Dry Runで投稿内容を事前確認（実際には送信しない）
python apps/auto-poster/main.py --dry-run

# 人間が内容を確認・承認後に本番実行
python apps/auto-poster/main.py
```

- Dry Run出力（CSV・ログ）を必ず目視確認し、重複・不審な内容がないかチェックする。
- 1日あたりの投稿上限（自主規制）を設け、短時間集中投稿を避ける。
- 自動リプライは1ツイートに対して1回のみとし、繰り返しリプライを禁止する。
