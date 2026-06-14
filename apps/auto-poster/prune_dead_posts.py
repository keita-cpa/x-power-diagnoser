"""
prune_dead_posts.py -- 死にポスト自動クレンジングワーカー

dead_posts_queue.csv を読み込み、X API v2 でポストを削除する。
判定しきい値は monthly-analytics.md の Step 5（キュー生成側）にある。本ワーカーは
キューを実行（削除）する側で、削除直前の最終安全装置を担う。

安全装置（多層）:
- MAX_DELETIONS : 1回の実行で削除する上限（毎時Cron＝毎時最大2件）
- DAILY_CAP     : 1日（暦日）の削除上限。pruned_log.txt の当日[DELETED]件数で判定し暴走を防ぐ
- WHITELIST     : 本文先頭にラベルを含むエバーグリーン投稿は削除直前にスキップ（Step5の全文判定の二重防御）
削除済み行はキューから除外し、pruned_log.txt に履歴を追記する。削除は不可逆のため安全側に倒す。

Usage:
    python prune_dead_posts.py           # 最大 MAX_DELETIONS 件を実際に削除（DAILY_CAP内）
    python prune_dead_posts.py --dry-run # 削除対象を表示のみ（実削除なし）

注意: ConoHa WING の Python 3.6.15 で動かすため f-string・新しい型注釈は使わないこと。
"""

import sys
import csv
import argparse
import datetime
import pathlib

BASE_DIR   = pathlib.Path(__file__).parent
QUEUE_PATH = BASE_DIR / 'data' / 'analytics' / 'dead_posts_queue.csv'
LOG_PATH   = BASE_DIR / 'data' / 'analytics' / 'pruned_log.txt'

MAX_DELETIONS = 2      # 1回（毎時Cron）あたりの削除上限
DAILY_CAP     = 6      # 1暦日あたりの削除上限（不具合時の暴走防止）
QUEUE_FIELDNAMES = ['ポストID', '日付', '本文先頭20文字']

# エバーグリーン保護: 本文（先頭20字）にこれらを含む投稿は削除しない。
# Step 5（全文判定）を通り抜けた場合の最終フェイルセーフ。monthly-analytics.md Step 5 と同期すること。
WHITELIST = ['【保存版】', '緊急レポート', '保存推奨', '完全版', '報告書']


# ---------------------------------------------------------------------------
# ヘルパー関数
# ---------------------------------------------------------------------------

def load_queue():
    """dead_posts_queue.csv を読み込んで行リストを返す。ファイルがなければ空リスト。"""
    if not QUEUE_PATH.exists():
        return []
    with open(QUEUE_PATH, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def save_queue(rows):
    """行リストを dead_posts_queue.csv へ上書き保存する。"""
    with open(QUEUE_PATH, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=QUEUE_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def append_log(post_id, posted_at, text_preview, label='[DELETED]'):
    """pruned_log.txt に履歴を1行追記する。label例: [DELETED] / [DRY-RUN] / [SKIP-WHITELIST]"""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    entry = (
        '{ts} {label} ID={pid} | 投稿日={pa} | 本文={tp}\n'.format(
            ts=timestamp, label=label, pid=post_id, pa=posted_at, tp=text_preview)
    )
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(entry)


def count_today_deletions():
    """pruned_log.txt から「本日（暦日）の実削除[DELETED]件数」を数える。DAILY_CAP判定用。"""
    if not LOG_PATH.exists():
        return 0
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    n = 0
    with open(LOG_PATH, encoding='utf-8') as f:
        for line in f:
            if line.startswith(today) and '[DELETED]' in line:
                n += 1
    return n


def is_whitelisted(text_preview):
    """本文先頭にホワイトリスト語を含むか（最終フェイルセーフ）。"""
    return any(w in text_preview for w in WHITELIST)


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='死にポスト自動クレンジングワーカー (毎回最大{}件 / 日次上限{}件)'.format(
            MAX_DELETIONS, DAILY_CAP)
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='実削除なし。削除対象をコンソール表示して pruned_log.txt に [DRY-RUN] として記録する',
    )
    args = parser.parse_args()

    queue = load_queue()
    if not queue:
        print('[INFO] dead_posts_queue.csv が空またはファイルが存在しません。')
        print('       /project:monthly-analytics の Step 5 を先に実行してください。')
        return

    print('[INFO] キュー件数: {}件 | 毎回上限: {}件 | 日次上限: {}件'.format(
        len(queue), MAX_DELETIONS, DAILY_CAP))

    # --- 最終フェイルセーフ1: ホワイトリスト除去（Step5の全文判定の二重防御）---
    protected = [r for r in queue if is_whitelisted(r.get('本文先頭20文字', ''))]
    if protected:
        for r in protected:
            print('[SKIP-WHITELIST] 保護対象のためスキップ: ID={} | 本文={}'.format(
                r.get('ポストID', '').strip(), r.get('本文先頭20文字', '').strip()))
            append_log(r.get('ポストID', '').strip(), r.get('日付', '').strip(),
                       r.get('本文先頭20文字', '').strip(), label='[SKIP-WHITELIST]')
        # 保護対象はキューから恒久除外（再試行しない）
        queue = [r for r in queue if r not in protected]
        if not args.dry_run:
            save_queue(queue)
    if not queue:
        print('[INFO] ホワイトリスト除外後、削除対象は残っていません。')
        return

    # --- 最終フェイルセーフ2: 日次上限（DAILY_CAP）---
    today_deleted = count_today_deletions()
    daily_remaining = max(0, DAILY_CAP - today_deleted)
    allowed = min(MAX_DELETIONS, daily_remaining)
    print('[INFO] 本日の実削除: {}件 / 日次残り: {}件 → 今回の許容削除数: {}件'.format(
        today_deleted, daily_remaining, allowed))
    if allowed == 0:
        print('[INFO] 日次上限 DAILY_CAP={} に到達。今回は削除せずキューを据え置きます。'.format(DAILY_CAP))
        return

    # クライアント初期化（dry-run 時はスキップ）
    client = None
    if not args.dry_run:
        try:
            from x_poster import get_client
            client = get_client()
        except Exception as e:
            print('[ERROR] X API クライアント初期化失敗: {}'.format(e))
            print('        config.py の X_API_KEY / X_ACCESS_TOKEN を確認してください。')
            sys.exit(1)

    targets   = queue[:allowed]
    remaining = queue[allowed:]
    failed    = []
    done_count = 0

    for row in targets:
        post_id   = row['ポストID'].strip()
        posted_at = row['日付'].strip()
        text_prev = row['本文先頭20文字'].strip()

        if args.dry_run:
            print('[DRY-RUN] 削除予定: ID={} | 投稿日={} | 本文={}'.format(
                post_id, posted_at, text_prev))
            append_log(post_id, posted_at, text_prev, label='[DRY-RUN]')
            done_count += 1
        else:
            try:
                client.delete_tweet(id=post_id, user_auth=True)
                print('[OK] 削除完了: ID={} | 投稿日={} | 本文={}'.format(
                    post_id, posted_at, text_prev))
                append_log(post_id, posted_at, text_prev, label='[DELETED]')
                done_count += 1
            except Exception as e:
                print('[ERROR] 削除失敗 (次回リトライ): ID={} | {}'.format(post_id, e))
                failed.append(row)

    # キュー更新（dry-run 時はファイル変更なし）
    if not args.dry_run:
        new_queue = failed + remaining
        save_queue(new_queue)
        print('[INFO] キュー残: {}件'.format(len(new_queue)))

    mode = 'DRY-RUN' if args.dry_run else '削除'
    print('[DONE] {}: {}件処理'.format(mode, done_count))


if __name__ == '__main__':
    main()
