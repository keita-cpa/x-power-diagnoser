# /project:introduce-therapist -- セラピスト紹介長文ポスト生成

指定したXアカウントのプロフィール・直近ポスト・リプライを取得し、
5段構成の紹介長文ポストを `therapist_introducer.py` で生成してターミナルに出力する。

**引数**: `$ARGUMENTS` に `@username` を渡すこと（@ あり・なし両方対応）

---

## 事前確認

実行前に対象アカウントと構文を確認する:

```bash
cd C:/Users/yotak/Documents/x-auto
venv/Scripts/python -m py_compile therapist_introducer.py && echo "[OK] 構文チェック通過"
```

X APIのレート制限状況を確認する（直近15分以内にsniper_radar.pyを実行した場合は注意）:

```bash
venv/Scripts/python -c "
import sys
target = '$ARGUMENTS'.lstrip('@') or '（引数未指定）'
sys.stdout.buffer.write(f'対象アカウント: @{target}\n'.encode('utf-8'))
sys.stdout.buffer.write(b'X API: Bearer Tokenは動的生成のため事前確認不要\n')
sys.stdout.buffer.write(b'注意: sniper_radar.py直後の実行はレート制限に注意\n')
"
```

---

## 実行

```bash
cd C:/Users/yotak/Documents/x-auto
venv/Scripts/python therapist_introducer.py $ARGUMENTS
```

---

## 実行後の確認

生成された紹介文の品質を以下の観点で確認すること:

1. 5段構成が守られているか
   - [ ] フックの偽装: 「たまたま」等の偶然感がある
   - [ ] ささいな細部: ありきたりでない具体的な気づきがある
   - [ ] 行動に落とし込んだ称賛: 引き抜き感がない圧倒的な称賛がある
   - [ ] ハードボイルドな結び: 自分の日常に戻るクールな終わり方
   - [ ] CTA ゼロ: フォロー/いいね/DM等の誘導が一切ない

2. 禁止事項チェック
   - [ ] 「知らんけど」が含まれていない
   - [ ] 「過去のポストを読んだ」等の監視明言がない
   - [ ] Markdownの太字（`**`）が含まれていない
   - [ ] URLが含まれていない
   - [ ] 引き抜き・スカウトを匂わせる表現がない

3. 文字数確認（出力の最終行に表示される）

---

## エラー時の対処

| エラー | 対処 |
|---|---|
| `401 Unauthorized` | X API認証エラー。`config.py` の X_API_KEY / X_API_SECRET をユーザーに確認依頼 |
| `429 Too Many Requests` | X APIレート制限。15分待ってから再実行 |
| `ユーザーが見つかりません` | @username のスペルを確認。アカウント削除・非公開の可能性あり |
| `非公開アカウント` | 投稿0件の場合、プロフィール文のみで生成。品質低下の可能性あり |
| `404 NOT_FOUND` (Geminiモデル) | `.claude/rules/model-routing.md` の廃止対応手順を参照 |
| `Gemini API失敗（3回）` | ネットワーク・Gemini APIの障害。しばらく待ってから再実行 |
| `引数未指定` | `python therapist_introducer.py @username` の形式で実行 |

---

## 注意事項

- 出力はターミナルのみ（CSVへの保存なし）
- 投稿は出力テキストを手動でコピーしてX Premium長文ポストとして投稿する
- X Article（記事）形式ではなく通常の長文ポスト（プレミアム会員向け拡張文字数）として使用する
- `sniper_radar.py` の直後に実行するとX APIレート制限（15リクエスト/15分）に達する可能性がある
- 生成品質が低い場合はそのまま再実行（temperature=0.9のため毎回異なる結果が得られる）
