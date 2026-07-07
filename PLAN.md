# 実装計画: 複数アカウント対応（マルチテナント化）

> ステータス: **基本承認済み（2026-06-14）**。実行順 = **第0部 OAuth2移行（先行）→ 第1部 マルチテナント化**。
> 決定: Q1 2層分割＆accounts構成 ✓ ／ Q2 keita移設 ✓ ／ **Q3 OAuth2を先に実施** ／ **Q4 ConoHaはアカウント別ディレクトリで分離**
> 作成: 2026-06-14 / 方式: **マルチテナント化**（1コードベース＋アカウント別プロファイル）/ 規模: **2〜3アカウント・別ジャンル**
>
> ⚠️ 次の着手ブロッカー: 第0部Phase1（X Developer Portal の OAuth2設定）は**あなたしかできない**。ここが済むまでトークン取得・検証は進められない（§OAuth参照）。

---

## 0. 方針
- コードは1本に保ち、**変わるのは「設定・データ・声・知識」だけ**を `accounts/<名前>/` に分離。
- アカウントは環境変数 **`XAUTO_ACCOUNT`** で切替（cronで指定）。**既定値 `keita`** で現行挙動を完全維持（後方互換）。
- 別ジャンルなのでペルソナ・知識ベースは**完全に新規**（共有しない）。

## 1. 目標アーキテクチャ
```
apps/auto-poster/
  *.py                      … 共通ロジック（修正は1回で全アカウントに反映）
  paths.py                  … 【新規・Claude作成】XAUTO_ACCOUNTを読み、データ/ペルソナのパスを解決
  accounts/
    keita/
      config.py             … 【保護・ユーザー管理】secrets＋ACCOUNT_PROFILE＋RAGパス（既存config.pyを移設）
      persona/gemini_gem_prompt_optimized_v3.md   … 声の単一ソース（現drafts/から移設）
      knowledge/            … 自動生成用ナレッジ（ジャンル別）
      data/{drafts,analytics,logs,outbox,raw_contents,config}/
      schedule.json
    <acct2>/                … 同じ構造（別ジャンル）
```

### 2層に分けるのが肝
| 層 | 担当 | 内容 |
|---|---|---|
| **secrets＋プロファイル＋知識パス** | **ユーザー**（config.pyはRead/Edit禁止＝ぼくは触れない） | 各 `accounts/<名前>/config.py` に当該アカウントのAPIキー・`ACCOUNT_PROFILE`・`RAG_DOCS_DIRS`/`AUTO_RAG_DIR`。`XAUTO_ACCOUNT` で読み分け |
| **データ/ペルソナ出力パス** | **Claude** | 新規 `paths.py` が `DATA_DIR`/`DRAFT_CSV`/`PERSONA_PROMPT`/`SCHEDULE_JSON` 等を解決。11スクリプトの `_BASE_DIR/data/...` を `from paths import ...` に置換 |

> なぜ分ける: config.py は保護ファイルでぼくが編集できない。secrets系はユーザー、パス系はぼく、と責任を割ると安全に進められる。両者は同じ `XAUTO_ACCOUNT` を見る。

## 2. リファクタ範囲（grep実測）
- `from config import ...`：8ファイル（auto_poster / x_poster / post_generator / sniper_radar / analyze_my_account / mini_bulk_generator / therapist_introducer / prompts）→ **secrets系は変更不要**（config.pyがアカウント対応すれば透過）。
- `_BASE_DIR = Path(__file__).parent` ＋ `/data/...`：11ファイル → **paths.py 経由に置換**（ここがぼくの主作業）。
- `ingest_raw_contents.py` の `DRAFTS_DIR` グロブ（v3探索）→ アカウントの `persona/` を見るよう変更。

## 3. 影響範囲（ファイル）
- 新規: `paths.py`、`accounts/keita/...`（移設）、`accounts/<acct2>/...`（雛形）
- 改修: 上記11 .py のパス参照、`ingest` のペルソナ探索、`deploy_to_conoha.sh`（アカウント別パス対応）、`.claude/settings.json`（deny拡張）、`.gitignore`（拡張）
- **ユーザー作業**: 各 `accounts/<名前>/config.py`（secrets）作成・`XAUTO_ACCOUNT` 対応、OAuth移行（任意・推奨）

## 4. フェーズ分解（各フェーズに検証ゲート）
- [ ] **Phase 0 足場**: `accounts/keita/` を作り、現 `data/`・`drafts/persona`・知識を移設。`paths.py` 作成。`XAUTO_ACCOUNT` 既定=keita
- [ ] **Phase 1 リファクタ＋パリティ確認**: 11スクリプトを paths.py 経由に。`/project:test-run`・各 `--dry-run` で**keitaが従来と完全に同一挙動**であることを確認（最重要ゲート）
- [ ] **Phase 2 secrets対応（ユーザー）**: config.py を `XAUTO_ACCOUNT` で読み分け。`accounts/keita/config.py` へ移設・keita鍵の動作確認
- [ ] **Phase 3 acct2雛形**: `accounts/<acct2>/` 構造を作成。ペルソナは「トーク履歴→声の指紋→v3」の**プロセスを再利用**して新規構築。知識ベースも新規。config.pyはユーザー
- [ ] **Phase 4 ConoHa**: アカウント別デプロイ先（例 `~/x-auto` / `~/x-auto-acct2`）＋cronに `XAUTO_ACCOUNT` 付与。`schedule.json`/CSV/ログが衝突しないこと
- [ ] 横断: `.gitignore`・settings deny を `accounts/*/config.py`・`accounts/*/data/*.csv`・`accounts/*/persona/`・`accounts/*/knowledge/` へ拡張

## 5. ConoHa設定（Phase 4詳細）
- デプロイ先をアカウント別に（`CONOHA_DEPLOY_PATH` を上書き）。
- cron例：`*/5 * * * * cd ~/x-auto-acct2 && XAUTO_ACCOUNT=acct2 PYTHONIOENCODING=utf-8 /usr/local/bin/python conoha_worker.py >> cron_run.log 2>&1`（prune も毎時・同様に）。
- Python 3.6.15互換厳守（paths.py も f-string/新型注釈を使わない）。

## 6. 重大リスクと対策
1. **ライブデータの移設事故（最重要）**: keita の本番 `stock_posts_draft.csv`・`schedule.json`・`posted_history.csv` はローカル＆**ConoHa側が正**。移設はバックアップ必須・Phase1のパリティ確認を通過するまでConoHa構造は変えない。サーバー側移設は最後（Phase4）に慎重に。
2. **凍結リスク**: 別ジャンル・別ペルソナなので協調自動化リスクは低めだが、**同一ConoHa IP**である点は残る。投稿時間を `schedule.json` でアカウント別にずらす／コンテンツ重複ゼロを徹底。同ジャンル展開時はIP分離を再検討。
3. **config.py保護との両立**: ぼくは config.py を読まない/書かない。secrets系はユーザーがPhase2で実施。ぼくはダミー無しでパス層のみ進める。
4. **コスト線形増**: QC/メタのAPIがアカウント数分。各 config に予算ガード。
5. **後方互換**: 既定 `XAUTO_ACCOUNT=keita`。Phase1完了時点で keita は1ミリも挙動が変わらないことを保証してから acct2 に進む。

## 7. 関連（先にやると効く）
- **OAuth 2.0移行（docs §8）**: 複数アカウントの認証管理が楽になる。スケール前提なら Phase2 前後で実施推奨（必須ではない／OAuth1.0aでも各アカウント可）。

## 8. 確認事項 → すべて回答済み
Q1 ✓ ／ Q2 ✓（移設可・パリティ＆バックアップ前提）／ Q3 = **OAuth2を先行** ／ Q4 = **ConoHa別ディレクトリで分離**。

---

# 第0部（先行）: X API OAuth 2.0（PKCE＋リフレッシュトークン）移行

> 基盤設計は `docs/MASTER_ARCHITECTURE.md §8` を踏襲。本PLANでは「Claude／ユーザーの分担」と「マルチテナント前提の設計」を補う。
> 目的: 永続キー4本（config.py平文常駐・無期限悪用リスク）→ 最小スコープ＋自動更新トークン基盤へ。多アカウントの認証管理も楽になる。

## 0-A. 担当の分担（重要）
| 区分 | 担当 |
|---|---|
| X Developer Portal の OAuth2設定（Confidential Client・コールバックURL・スコープ）| **あなた（必須・最初）** |
| 初回認可フロー（ブラウザでアプリ承認しトークン発行）の**実行** | **あなた**（対話操作。Claudeは実行しない） |
| `config.py` への client_id/secret 投入・トークン保存先の秘匿 | **あなた**（config.pyはRead/Edit禁止） |
| 認可フロー用スクリプト・**トークンマネージャ**（ロード→期限判定→自動リフレッシュ→原子的保存）の実装 | **Claude** |
| `x_poster.py`／`sniper_radar.py`／`analyze_my_account.py` の OAuth2UserHandler 改修 | **Claude** |
| 並行検証→本切替→旧キー失効 | 共同（失効操作はあなた） |

## 0-B. フェーズ（docs §8準拠・マルチテナント対応で補強）
- [ ] **A1 準備（あなた）**: Dev PortalでOAuth2 Confidential Client作成。スコープ `tweet.read` `tweet.write` `users.read` `offline.access`。コールバックURL（ローカル認可用、例 `http://127.0.0.1:8765/callback`）登録
- [ ] **A2 トークン基盤（Claude実装＋あなた実行）**: 初回認可スクリプト（PKCE・ローカル1回実行）＋トークンマネージャ。**リフレッシュトークンは使い捨て＝使うたびローテーション**するので、`tmp→rename` の**原子的保存**＋保存失敗時の再認可手順をセットで実装。トークンファイルは **`accounts/<名前>/secrets/` 配下・600権限・rsync除外・gitignore**（マルチテナント前提でアカウント別に保存）
- [ ] **A3 クライアント改修（Claude）**: `x_poster.py`／`sniper_radar.py`／`analyze_my_account.py` を tweepy OAuth2UserHandler ベースへ。トークンマネージャ経由でアクセストークンを供給
- [ ] **A4 切替（共同）**: 並行運用で投稿・リプライ・読み取りを検証 → 本切替 → 旧 OAuth1.0a キーを**あなたが失効**
- [ ] **検証必須**: 画像アップロード（v1.1 media/upload は OAuth1.0a依存）。v2メディアへ移行可否を確認し、**不可なら画像のみ OAuth1.0a を残すハイブリッド**（その鍵は権限最小化）

## 0-C. マルチテナント連携メモ
トークンマネージャは**トークンファイルのパスを引数/設定で受け取る**設計にし、第1部の `paths.py`（`accounts/<名前>/secrets/token.json` 等）と接続する。これによりOAuth2基盤が最初からアカウント別になる（第1部での作り直しを避ける）。

## 0-D. あなたへの「いますぐの一手」
第0部Phase A1（Dev Portal設定）が全体のブロッカーです。準備でき次第、A2のスクリプト雛形をClaudeが用意します。
**先に着手してよいClaude作業**: トークンマネージャ＋認可スクリプトの**雛形**（実鍵不要・パスは設定注入）。Dev Portal完了前でも書けるので、ご希望なら並行で進めます。
