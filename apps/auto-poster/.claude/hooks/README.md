# hooks/

セッション開始・終了時やファイル保存時に自動発火するスクリプト群を置く場所。

## 設定方法

`.claude/settings.json` の `hooks` セクションに定義する。

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [{ "type": "command", "command": "bash .claude/hooks/pre_save.sh" }]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [{ "type": "command", "command": "bash .claude/hooks/post_save.sh" }]
      }
    ]
  }
}
```

## 主なユースケース

- `post_save.sh` : `.py` ファイル編集後に自動で構文チェック（`py_compile`）
- `pre_commit.sh` : コミット前にセキュリティスキャン
- `session_start.sh` : セッション開始時に `schedule.json` の状態を表示
