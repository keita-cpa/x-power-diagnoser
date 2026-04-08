# x-auto — X自動投稿・永久機関システム マスタードキュメント

## 1. プロジェクトの目的と基本戦略

メンエス業界において、搾取されがちなセラピストを「法律と数字（税務）」の力で守る。
Keita_CPA（@Keita_CPA）を業界の絶対的な信頼のハブ（キングメーカー）として確立し、
自動生成・自動投稿・自動リプライ起案の「永久機関」を構築する。

* **努力の量ではなく「構造の美しさ」で勝つ：** 記事生成・ナレッジ管理・投稿のすべてをAIとPythonのシステムに完全委譲し、自身は「どの市場の歪みを狙うか」「どういう構造でバズを起こすか」の戦略設計に全神経を注ぐ。
* **業界の健全化と防衛：** 風営法・税法等のコンプライアンスを遵守し、違法行為（本番強要・脱税等）を論理的に排除することで、セラピストのキャリア（無形資産）と安全を守る。
* **RAGで複利を積む：** ナレッジ（knowledge.xlsx・txt群）が貯まるほど投稿の引き出しが増え、品質が上がる複利構造を持つ。

---

## 2. フォルダ体系・ファイル構成

システムは疎結合を保ち、不要なファイルは本番（ConoHa VPS）にデプロイしない。

```
x-auto/
 ├─ conoha_worker.py        # 自動投稿の司令塔（Cronで5分おきに実行・schedule.json管理）
 ├─ auto_poster.py          # 投稿のメイン処理（OGP画像生成・ツリー投稿・履歴移動）
 ├─ post_generator.py       # Gemini API呼び出し・RAG・QC審査の中枢
 ├─ mini_bulk_generator.py  # Excel→一括生成→CSV追記（対話型CLI）
 ├─ sniper_radar.py         # VIPアカウント監視・自動リプライ起案システム
 ├─ therapist_introducer.py # セラピスト紹介長文の自動生成エンジン（Markdown物理除去・二重紹介防止）
 ├─ x_poster.py             # X API（Tweepy v2/v1.1）との通信担当
 ├─ config.py               # APIキー等の設定ファイル・RAGパス定義 ※Read/Edit 絶対禁止
 ├─ prompts.py              # 自動投稿のAIプロンプト・カテゴリ・トーン定義（アルゴリズム最適化済み v3）
 ├─ x_auto_master.md        # プロジェクト設計書（本ドキュメント）
 ├─ tone_sample_01.txt      # 口調サンプル①（個人情報・deny保護・Read/Edit禁止）
 ├─ tone_sample_02.txt      # 口調サンプル②（個人情報・deny保護・Read/Edit禁止）
 ├─ key-*.pem               # ConoHa SSH秘密鍵（deny保護・.gitignore除外・chmod 600）
 ├─ schedule.json           # 自動生成される投稿スケジュール（ローカルのみ・本番非デプロイ）
 ├─ assets/                 # OGP画像・フォント置き場（auto_poster.pyが参照）
 │   ├─ base_image.jpg      # OGP画像のベース素材
 │   └─ font.otf            # 日本語フォント（画像タイトル描画用）
 ├─ data/
 │   ├─ drafts/
 │   │   └─ stock_posts_draft.csv   # 投稿ストック（8列CSV・最重要・削除厳禁）
 │   ├─ logs/
 │   │   ├─ posted_history.csv      # 投稿済み履歴（9列CSV）
 │   │   ├─ introductions_log.csv   # 紹介済みセラピスト履歴（二重紹介防止用）
 │   │   └─ scouted_targets.csv     # Sniper Radarのリプライ起案ストック
 │   └─ analytics/                  # 月次X Analytics CSVの出力・分析先
 ├─ drafts/                 # 紹介記事のMarkdownドラフト保存先（therapist_introducer出力）
 ├─ docs/                   # 企画書・完了済みPLAN.md等のドキュメント退避場所
 ├─ utils/                  # サポートツール群（migrate_csv.py等・再実行禁止スクリプト含む）
 ├─ 自動生成用ナレッジ/     # RAG用ソース（knowledge.xlsx・txt群）。config.pyのRAG_DOCS_DIRSで参照。
 └─ .claude/                # Claudeの「初期記憶」と「仮想チーム」の中核
     ├─ CLAUDE.md           # 司令塔・初期記憶。プロジェクト概要・ルール・失敗録を日々育てる。
     ├─ rules/              # 役割ごとに分割された追加マニュアル（coding-style・persona・security等）
     ├─ skills/             # 再利用可能な知識パック（SKILL.md等）。必要な時のみオンデマンドロード。
     ├─ commands/           # 定型タスク（/bulk-generate・/sniper-run等）のカスタムコマンド定義
     ├─ hooks/              # セッション開始/終了時やファイル保存時に自動発火するスクリプト群
     ├─ agents/             # 仮想社員エージェント定義（data-scientist・growth-hacker等）
     ├─ settings.json       # アクセス制御設定。allow/denyの層構造で権限を管理する。
     └─ settings.local.json # ローカル専用の上書き設定（本番・Gitには含めない）
```

---

## 3. システム詳細：4つのエンジン

### エンジン1：コンテンツ生成・RAGパイプライン（post_generator.py）

* **役割：** ナレッジ（knowledge.xlsx・txt群）を検索・注入し、税金・法律の知識をバズる投稿に変換する。
* **フロー：**
  ```
  knowledge.xlsx / txt群
       ↓ RAG（config.pyのRAG_DOCS_DIRS）
  post_generator.py
       ↓ Gemini gemini-3.1-pro-preview（長文生成・QC審査）
       ↓ Gemini gemini-3-flash-preview（タイトル・ALT・リプライ生成）
  stock_posts_draft.csv（8列CSV追記）
  ```
* **QC審査（3基準）：** 法令精度・暴言チェック・ファクト確認を `gemini-3.1-pro-preview` で実施。
* **拡張構想（SkillGraphs化）：** ナレッジを「取り込み → 分解 → 接続 → 検証」のパイプラインで自動構造化し、情報を線で繋ぐ自動ナレッジベースを構築する。ナレッジが貯まるほど引き出しが増える複利構造を目指す。

### エンジン2：X自動投稿システム（conoha_worker.py / auto_poster.py）

* **役割：** `stock_posts_draft.csv` から未投稿のものを全自動で定期配信する。
* **Cronフロー：**
  ```
  [ConoHa VPS Cron: 5分おきに実行]
       ↓
  conoha_worker.py（schedule.json で次回投稿時刻を管理）
       ↓ 投稿時刻に達したら
  auto_poster.py
       ↓ stock_posts_draft.csv から フォーマット=tweet・ステータス=空欄 の先頭1行を取得
       ↓ OGP画像生成（Pillow・assets/base_image.jpg・font.otf）
       ↓ x_poster.py → Tweepy v1（メディアアップロード）→ Tweepy v2（ツイート投稿）
       ↓ リプライ文があればツリー投稿（自己リプライ）
       ↓ ステータスを "posted" に更新 → posted_history.csv へ移動
  ```
* **スケジュール管理：** `schedule.json` に次回投稿時刻を記録。投稿後は時刻を更新する。

### エンジン3：VIPアカウント監視・自動リプライ起案（sniper_radar.py）

* **役割：** 対象セラピスト（VIP）の発信を定期監視し、AIがリプライ案を自動起案する。
* **フロー：**
  ```
  X API v2（対象アカウントの最新ポスト取得）
       ↓ 炎上リスク・無関係ポストをスクリーニング
       ↓ Gemini（140字以内のリプライ案を「等身大の専門家トーン」で生成）
       ↓ scouted_targets.csv に追記（取得日時・対象URL・ユーザー名・元ツイート・AIリプライ案）
  ```
* **運用：** 案は自動起案のみ。実際の投稿はKeita_CPAが確認・判断して手動で実施する。

### エンジン4：セラピスト自律型PRエンジン（therapist_introducer.py）

* **役割：** 対象セラピストの過去ポストをディープスキャンし、AIが極上の紹介長文を自動生成する。
* **技術仕様：**
  * **ノイズクレンジング：** URLや短文を物理的に排除してAIのハルシネーションを防ぐ。
  * **二重紹介ブロック：** `introductions_log.csv` を参照し重複をブロック（`--force` で強制突破可能）。
  * **スマートメンション＆Markdown物理除去：** 文中に `@ID` が無い場合のみ文末に自動付与。Xの表示崩れを防ぐため太字（`**`）や見出し（`#`）を強制排除。
  * **季節同期：** `datetime` で現在の季節を自動判定してGeminiに動的注入し、過去ポストの季節に引っ張られない書き出しを実現する。

---

## 4. Gemini モデルルーティング（コスト最適化設計）

| 用途 | モデル | 理由 |
|---|---|---|
| メイン長文生成（800〜1400字） | `gemini-3.1-pro-preview` | 法令・判例の正確な引用と深い洞察が必要 |
| QC品質審査（Big4監査人3基準） | `gemini-3.1-pro-preview` | ハルシネーション検出は最高精度で行う |
| 画像タイトル生成（15文字以内） | `gemini-3-flash-preview` | 軽量タスク。高速・低コストで十分 |
| ALTテキスト生成（100文字・LLMO対策） | `gemini-3-flash-preview` | 同上 |
| リプライ文生成 | `gemini-3-flash-preview` | 短文生成。コスト削減 |

**モデル変更禁止ルール：** Pro → Flash への格下げは法令誤引用リスクを高めるため禁止。変更前は必ず `client.models.list()` で利用可否を確認する。

---

## 5. CSV スキーマ（変更厳禁）

### stock_posts_draft.csv（8列・最重要）

| 列 | 列名 | 説明 |
|---|---|---|
| 1 | 管理ID | 一意識別子（例: CPA-001） |
| 2 | カテゴリ | POST_CATEGORIESのキーと一致 |
| 3 | フォーマット | `tweet` or `thread` |
| 4 | 投稿文 | 本文（最大280文字） |
| 5 | リプライ文 | スレッドの2番目の投稿（空欄可） |
| 6 | 画像タイトル | OGP画像のタイトル（15文字以内） |
| 7 | ALT | 画像のALTテキスト（100文字以内） |
| 8 | ステータス | 空欄=未投稿 / `posted`=投稿済み |

* 投稿対象: `フォーマット=tweet` かつ `ステータス=空欄` の最初の1行
* エンコーディング: `utf-8-sig`（BOM付きUTF-8・変更禁止）
* 列変更時は `mini_bulk_generator.py` と `auto_poster.py` の `FIELDNAMES` を必ず同期

---

## 6. ペルソナ：@Keita_CPA（二重人格マトリクス）

| 顔 | 別名 | トーン | 使用カテゴリ |
|---|---|---|---|
| 知的・冷静な専門家 | _TONE_EXPERT | 法令・判例を根拠に冷徹な事実を突きつける | ノウハウ、Q&A、防衛事例 |
| 熱血アニキ | _TONE_HOT | 「〜しろ！」の言い切り。感情を揺さぶる | マインド、リスク警告 |

**絶対ルール（全投稿共通）：**
* 一人称「ぼく」・二人称「あなた」（「お前」禁止）
* 完全標準語（関西弁禁止）
* Markdown太字（`**`）・本文内URL・絵文字 禁止
* ナレッジ外の数字・法令の捏造禁止（RAGの制約）

---

## 7. Harness Engineering：AIプロンプト哲学

AIのプロンプトに組み込んだ、営業色を完全排除した「純文学的エンタメ文章」の生成原則。

1. **共感ハック（人蕩し術）：** 対象者の自己重要感と群居衝動を満たし、主語を広げて読者を共犯者として巻き込む（「ぼくらみたいな〜」の固定フレーズは禁止・ゼロ生成）。
2. **センスの哲学（大人の渇望感）：** 意味より「間合い・ズレ・ディテール」を全肯定する。煽り営業を禁止し、内面からの渇望と大人の独占欲を静かに刺激する。
3. **大人の美学（愛あるツッコミ）：** 出だしはゆっくり、中盤で比較や感情、最後は滑走路を使った愛あるツッコミで落とす。プロへのリスペクトと大人の余韻で静かに終わる。
4. **季節感のリアルタイム同期：** 書き出しの情景は `datetime` で自動判定した現在の季節情報をGeminiに動的注入し、過去ポストの季節に引っ張られない。
5. **監視感の排除：** リプライ（顧客との会話）からのカギ括弧での直接引用は絶対禁止。態度・温度感の抽象化描写にとどめる。
6. **自然なID組み込み：** 対象者の @ID は文末に単体で置かず、第2〜3段落の主語として文章の中に1回だけ自然に織り込む。
7. **X最適化フォーマット：** 段落間に空白行を挿入し、1段落3〜4文を上限とする。箇条書き禁止。

---

## 8. インフラ・契約サービス

| カテゴリ | サービス |
|---|---|
| SNS | X Premium（@Keita_CPA） |
| AI基盤 | Gemini API（メインブレイン）、Claude Code（現場監督） |
| サーバー | ConoHa VPS（Python Cron実行基盤） |
| バージョン管理 | Git（作業前後にコミットして巻き戻し可能な状態を担保） |
| API | X API v2、SocialData API（将来）|

---

## 9. Claude Code 運用プロトコル（SOP）

1. **セキュリティ：** `config.py` は Read/Edit 絶対禁止。`settings.json` の `deny` リストで保護済み。APIキーはコード・ログ・コメントに絶対に書かない。
2. **プランモード先行：** 複数ファイルへの影響がある変更は `PLAN.md` を先に作成し、合意してから実装する（`.claude/rules/planning-with-files.md` 参照）。
3. **Gitの保険：** 作業前後には必ずコミットし、いつでも安全な状態に巻き戻せる状態を担保する。
4. **改善ループ：** エラー発生時はスタックトレースの最下行（根本原因）まで読み、対症療法ではなく根本解決を行う（`.claude/rules/superpowers.md` 参照）。
5. **コスト管理：** コンテキストが肥大化したら `/compact` や `/clear` でセッションを整理する。大規模処理は `agents/` のサブエージェントに並列委譲する。
6. **対話型スクリプトの自律実行禁止（APIコスト爆発防止）：** `mini_bulk_generator.py` のような `input()` を伴う対話型CLIスクリプトを、Claude Codeに `printf` やパイプ処理を使って強行突破（自律実行）させてはならない。意図しない選択肢（重いRAG資料の全読み込み等）が強制選択され、LLMのAPIコストが爆発する危険がある。弾薬補充などの対話型操作が必要なタスクは、必ず人間がPowerShell等の別ターミナルから手動で `python mini_bulk_generator.py` を実行し、目視で選択肢を選ぶこと。AIは実行のサポート（コマンドの提示など）に留めること。
