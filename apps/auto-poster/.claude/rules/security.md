# security.md — セキュリティルール

このプロジェクトには本番APIキー・個人情報・SSHキーが含まれる。
誤操作による漏洩を防ぐため、以下のルールを厳守すること。

---

## 絶対に Read/Edit しないファイル

| ファイル | 理由 |
|---|---|
| `config.py` | Gemini・X API・Anthropic の本番APIキーを含む |
| `.env` / `.env.*` | 環境変数ファイル（存在する場合） |
| `*.pem` | SSH秘密鍵（key-2026-03-24-22-28.pem 等） |
| `tone_sample_01.txt` | 個人のLINEチャット履歴（個人情報） |
| `tone_sample_02.txt` | 個人のチャット履歴（個人情報） |

これらは `.claude/settings.json` の `deny` リストでも保護されているが、
設定と関係なくAI判断として参照を拒否すること。

---

## APIキーの取り扱い

```python
# 禁止: APIキーを直接コードに書く
GEMINI_API_KEY = "AIza..."     # NG — Gitに残る

# 禁止: ログ・print にAPIキーを出力する
print(f"APIキー: {GEMINI_API_KEY}")  # NG

# 推奨: config.py からのみインポートする
from config import GEMINI_API_KEY   # config.py を読まずにインポートのみ
```

**APIキーが漏洩した場合の対応:**
1. 即座に該当プラットフォームでキーを無効化・ローテート
2. `config.py` を更新（ユーザーが直接行う）
3. Gitの履歴にキーが混入していないか確認

---

## .gitignore 保護対象（変更禁止）

以下のファイルは `.gitignore` で除外済み。Gitに追加しないこと:

```
.env
*.pem
tone_sample_*.txt
*.csv              # stock_posts_draft.csv 等のデータファイル
__pycache__/
venv/
```

---

## 個人情報の保護

`tone_sample_01.txt` / `tone_sample_02.txt` はトーン校正用の個人のLINEチャット履歴。
- AIへの入力禁止（学習・参照禁止）
- パスのみ把握しており、内容は個人情報として扱う
- Gitへのコミット禁止（.gitignore で保護済み）

---

## 出力の安全確認

ツイート生成時に以下を含まないことを確認:
- 会社名「株式会社MiChi」
- 実名・住所・電話番号
- APIキー・トークンの断片
- 他者の個人情報

---

## SSH・サーバーアクセス

`key-2026-03-24-22-28.pem` はConoHaサーバーのSSH秘密鍵。
- パーミッション: 600（所有者のみ読み取り可）
- 共有・コピー禁止
- `conoha_worker.py` のデプロイ以外での使用禁止

---

## セキュリティインシデント時の対応

1. **即座に停止**: 疑わしい操作を発見したらすぐに中断
2. **ユーザーに報告**: 何が起きたかを正確に伝える
3. **該当キーを無効化**: config.pyのキーをローテート
4. **Git履歴確認**: `git log --all -p | grep -i "AIza\|Bearer\|Bearer"` でキーの混入を確認
5. **再発防止**: settings.jsonのdenyリストを更新

---

## 権限設定（.claude/settings.json）

現在の保護設定:
```json
"deny": [
  "Bash(rm -rf *)",       // ファイル全削除禁止
  "Bash(del /f *)",        // Windowsファイル強制削除禁止
  "Bash(git push *)",      // 全push禁止（確認必須）
  "Read(config.py)",       // APIキー漏洩防止
  "Edit(config.py)",       // 同上
  "Read(.env*)",           // 環境変数ファイル保護
  "Edit(.env*)",           // 同上
  "Read(tone_sample*)",    // 個人情報保護
  "Edit(tone_sample*)",    // 同上
  "Read(*.pem)",           // SSHキー保護
  "Edit(*.pem)"            // 同上
]
```
