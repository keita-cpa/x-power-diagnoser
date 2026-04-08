# Context: apps/power-diagnoser/

## 役割

メンエス界隈向けXアカウントパワー診断ツール。FastAPI + Gemini API。
Render (PaaS) にデプロイ。GitHubへのpushで自動デプロイされる。

---

## エントリーポイント

- **ローカル起動**: `uvicorn app.main:app --reload`
- **本番起動**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **ヘルスチェック**: `GET /api/health`
- **診断API**: `POST /api/diagnose`

---

## ファイル構成（重要ファイルのみ）

| ファイル | 役割 |
|---|---|
| `app/main.py` | ルーティング・DI・レスポンス組立 |
| `app/llm.py` | Gemini API呼び出し・ANGEL/DEVILモード |
| `app/models.py` | Pydanticモデル定義 |
| `app/ranking.py` | スコア→ランク変換 |
| `app/scoring/algorithm_fitness.py` | アルゴリズム適合度スコア |
| `app/scoring/community_activity.py` | コミュニティ活動スコア |
| `app/scoring/engagement_rate.py` | エンゲージメント率スコア |
| `app/scoring/follower_influence.py` | フォロワー影響力スコア |
| `app/scoring/impression_power.py` | インプレッション力スコア |
| `render.yaml` | Renderデプロイ設定 |
| `requirements.txt` | Python依存関係 |

---

## 環境変数

- `GEMINI_API_KEY`: Renderダッシュボードで設定。コードへの直書き厳禁。

## モデル

- `gemini-2.5-flash` — `app/llm.py` で定義。変更は要確認。

---

## スコアリング変更ルール

各 `scoring/` モジュールは `calc(mock_data) -> tuple[int, str]` を返す。
シグネチャを変えなければ他モジュールへの影響ゼロ。
変更後は `app/main.py` の呼び出し箇所を確認すること。

---

## デプロイ手順（Render）

1. `render.yaml` がRenderに接続済み
2. `main` ブランチにGitHubへpush → Renderが自動デプロイ
3. 環境変数はRenderダッシュボード（Environment）で手動設定
4. `GEMINI_API_KEY` は絶対にコードにハードコードしない

---

## 詳細ドキュメント

`apps/power-diagnoser/x_diagnoser_master.md` を参照
