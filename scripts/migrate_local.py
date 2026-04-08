#!/usr/bin/env python3
"""
scripts/migrate_local.py

4つのソースプロジェクトをモノレポにコピー統合するスクリプト。
元ファイルは変更しない（コピーのみ）。
冪等性あり: dirs_exist_ok=True により何度でも安全に再実行可能。

使用法:
    python scripts/migrate_local.py --dry-run   # プレビュー（推奨: 最初に実行）
    python scripts/migrate_local.py             # 実行
"""

import argparse
import shutil
import sys
from pathlib import Path

# ── パス定義 ──────────────────────────────────────────────────
MONOREPO_ROOT = Path(__file__).parent.parent
DOCUMENTS = Path.home() / "Documents"

# ── 標準除外パターン（全ジョブ共通）─────────────────────────
_STANDARD_IGNORE = shutil.ignore_patterns(
    "venv", ".venv", "env", "ENV",
    "node_modules",
    ".env",
    "*.pem",
    "__pycache__", "*.pyc", "*.pyo", "*.pyd",
    ".git",
    "schedule.json",
    "settings.local.json",
    "*.log",
)


def _claude_mastery_ignore(src_dir: str, names: list[str]) -> set[str]:
    """
    claude-mastery ジョブ専用の ignore 関数。
    .env.example は安全なのでコピー対象に含める。
    .env（本物）は除外する。
    """
    ignore_set = set(_STANDARD_IGNORE(src_dir, names))
    # .env.example が除外されていたら戻す
    if ".env.example" in ignore_set:
        ignore_set.discard(".env.example")
    # .env（本物）は除外
    if ".env" in names:
        ignore_set.add(".env")
    # node_modules は大きいので除外
    if "node_modules" in names:
        ignore_set.add("node_modules")
    return ignore_set


# ── コピージョブ定義 ──────────────────────────────────────────
COPY_JOBS = [
    {
        "label": "power-diagnoser",
        "src": DOCUMENTS / "x-power-diagnoser",
        "dst": MONOREPO_ROOT / "apps" / "power-diagnoser",
        "ignore": _STANDARD_IGNORE,
    },
    {
        "label": "auto-poster",
        "src": DOCUMENTS / "x-auto",
        "dst": MONOREPO_ROOT / "apps" / "auto-poster",
        "ignore": _STANDARD_IGNORE,
    },
    {
        "label": "x-algorithm",
        "src": DOCUMENTS / "x-algorithm",
        "dst": MONOREPO_ROOT / "docs" / "knowledge" / "X_Algorithm",
        "ignore": _STANDARD_IGNORE,
    },
    {
        "label": "claude-mastery",
        "src": DOCUMENTS / "everything-claude-code",
        "dst": MONOREPO_ROOT / "docs" / "knowledge" / "Claude_Mastery",
        "ignore": _claude_mastery_ignore,
    },
]

# ── セキュリティ検証: これらがコピー先に存在したら即終了 ─────
FORBIDDEN_PATTERNS = [".env", "*.pem", "venv", "node_modules"]


def safety_check(dst: Path, label: str) -> None:
    """コピー後にシークレット・除外対象がコピー先に混入していないか検証。"""
    violations = []
    for pattern in FORBIDDEN_PATTERNS:
        # .env.example は許可（.env のみ禁止）
        found = [
            p for p in dst.glob(f"**/{pattern}")
            if p.name != ".env.example"
        ]
        violations.extend(found)

    if violations:
        print(f"\n[SECURITY ERROR] 禁止ファイルが {label} のコピー先に混入しました:")
        for v in violations:
            print(f"  {v}")
        print("\n移行を中断します。コピー先を手動で確認してください:")
        print(f"  {dst}")
        sys.exit(1)


def run_job(job: dict, dry_run: bool) -> None:
    src: Path = job["src"]
    dst: Path = job["dst"]
    label: str = job["label"]
    ignore_fn = job["ignore"]

    if not src.exists():
        print(f"[SKIP] ソースが存在しません: {src}")
        return

    if dry_run:
        print(f"[DRY-RUN] {label}")
        print(f"         src: {src}")
        print(f"         dst: {dst}")
        # dry-run では実際には何もしない
        return

    print(f"[COPY] {label}: {src} -> {dst}")
    shutil.copytree(
        src,
        dst,
        ignore=ignore_fn,
        dirs_exist_ok=True,  # 冪等性: 既存ディレクトリへの上書きコピーを許可
    )
    safety_check(dst, label)
    print(f"[OK]   {label} コピー完了")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="4プロジェクトをモノレポにコピー統合します",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  python scripts/migrate_local.py --dry-run   # まずプレビューで確認
  python scripts/migrate_local.py             # 実行
        """,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際にはコピーせず、何が行われるかを表示する",
    )
    args = parser.parse_args()

    if args.dry_run:
        print("=" * 60)
        print("[DRY-RUN モード] ファイルの変更は行いません")
        print("=" * 60)

    for job in COPY_JOBS:
        run_job(job, args.dry_run)

    if args.dry_run:
        print("\n[DRY-RUN 完了] 上記の内容を確認後、--dry-run なしで再実行してください")
    else:
        print("\n[DONE] 移行完了")
        print("\nセキュリティ検証コマンド（結果がゼロ件であることを確認）:")
        print('  find /c/Projects/x-integrated-platform -name ".env" -not -name ".env.example"')
        print('  find /c/Projects/x-integrated-platform -name "*.pem"')
        print('  find /c/Projects/x-integrated-platform -name "venv" -type d')
        print('  find /c/Projects/x-integrated-platform -name "node_modules" -type d')


if __name__ == "__main__":
    main()
