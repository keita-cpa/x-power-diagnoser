"""
prune_dead_posts.py -- 死にポスト自動クレンジングワーカー

dead_posts_queue.csv を読み込み、X API v2 でポストを削除する。
安全装置: 1回の実行につき最大 MAX_DELETIONS 件しか削除しない。
削除済み行はキューから除外し、pruned_log.txt に削除履歴を追記する。

Usage:
    python prune_dead_posts.py           # 最大2件を実際に削除
    python prune_dead_posts.py --dry-run # 削除対象を表示のみ（実削除なし）
"""

import sys
import csv
import argparse
import datetime
import pathlib

BASE_DIR   = pathlib.Path(__file__).parent
QUEUE_PATH = BASE_DIR / 'data' / 'analytics' / 'dead_posts_queue.csv'
LOG_PATH   = BASE_DIR / 'data' / 'analytics' / 'pruned_log.txt'

MAX_DELETIONS = 2
QUEUE_FIELDNAMES = ['ポストID', '日付', '本文先頭20文字']


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


def append_log(post_id, posted_at, text_preview, dry_run=False):
    """pruned_log.txt に削除履歴を1行追記する。"""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    mode_label = '[DRY-RUN]' if dry_run else '[DELETED]'
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    entry = (
        f'{timestamp} {mode_label} '
        f'ID={post_id} | '
        f'投稿日={posted_at} | '
        f'本文={text_preview}\n'
    )
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(entry)


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='死にポスト自動クレンジングワーカー (最大 {} 件/回)'.format(MAX_DELETIONS)
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

    print('[INFO] キュー件数: {}件 | 最大削除数: {}件/回'.format(len(queue), MAX_DELETIONS))

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

    targets   = queue[:MAX_DELETIONS]
    remaining = queue[MAX_DELETIONS:]
    failed    = []
    done_count = 0

    for row in targets:
        post_id   = row['ポストID'].strip()
        posted_at = row['日付'].strip()
        text_prev = row['本文先頭20文字'].strip()

        if args.dry_run:
            print('[DRY-RUN] 削除予定: ID={} | 投稿日={} | 本文={}'.format(
                post_id, posted_at, text_prev))
            append_log(post_id, posted_at, text_prev, dry_run=True)
            done_count += 1
        else:
            try:
                client.delete_tweet(id=post_id, user_auth=True)
                print('[OK] 削除完了: ID={} | 投稿日={} | 本文={}'.format(
                    post_id, posted_at, text_prev))
                append_log(post_id, posted_at, text_prev, dry_run=False)
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
