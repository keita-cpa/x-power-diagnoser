"""PreToolUse hook: git commit 前のシークレット混入ガード。

CLAUDE.md「コミット前セキュリティチェック」の自動化版。
- ステージ済みファイルに .env / *.pem / config.py / tone_sample_* があればブロック
- --no-verify 付きの git commit をブロック（フック迂回の防止）
"""
import json
import re
import subprocess
import sys

SECRET_PATTERN = re.compile(
    r"\.env($|\.)|\.pem$|(^|/)config\.py$|tone_sample_.*\.txt$"
)


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))  # ensure_ascii=True (デフォルト): Windows cp932 コンソールでも壊れないASCII出力


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return
    command = data.get("tool_input", {}).get("command", "")
    if not re.search(r"\bgit\b[^|&;]*\bcommit\b", command):
        return

    if "--no-verify" in command:
        deny("--no-verify によるフック迂回は禁止されています（git hooks を尊重すること）")
        return

    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return  # gitリポジトリ外などは素通し
    staged_secrets = [
        f for f in result.stdout.splitlines() if SECRET_PATTERN.search(f)
    ]
    if staged_secrets:
        deny(
            "DANGER: シークレット検出。以下のファイルをステージから外してください: "
            + ", ".join(staged_secrets)
        )


if __name__ == "__main__":
    main()
