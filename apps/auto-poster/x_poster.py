import tweepy
from config import (
    X_API_KEY,
    X_API_SECRET,
    X_ACCESS_TOKEN,
    X_ACCESS_TOKEN_SECRET,
)


def get_client():
    client = tweepy.Client(
        consumer_key=X_API_KEY,
        consumer_secret=X_API_SECRET,
        access_token=X_ACCESS_TOKEN,
        access_token_secret=X_ACCESS_TOKEN_SECRET,
    )
    return client


def post_tweet(text):
    try:
        client = get_client()
        response = client.create_tweet(text=text, user_auth=True)
        tweet_id = response.data["id"]
        me = client.get_me()
        handle = me.data.username
        print(f"投稿成功: https://x.com/{handle}/status/{tweet_id}")
        return {"success": True, "tweet_id": tweet_id, "error": None}
    except tweepy.TooManyRequests:
        print("レート制限に達しました。15分後に再試行してください。")
        return {"success": False, "tweet_id": None, "error": "rate_limit"}
    except tweepy.Forbidden as e:
        print(f"投稿が拒否されました: {e}")
        return {"success": False, "tweet_id": None, "error": f"forbidden: {e}"}
    except Exception as e:
        print(f"エラー: {e}")
        return {"success": False, "tweet_id": None, "error": str(e)}


def post_reply(text, in_reply_to_tweet_id):
    """指定ツイートへのリプライを投稿する。"""
    try:
        client = get_client()
        response = client.create_tweet(
            text=text,
            in_reply_to_tweet_id=in_reply_to_tweet_id,
            user_auth=True,
        )
        tweet_id = response.data["id"]
        print(f"リプライ投稿成功: tweet_id={tweet_id}")
        return {"success": True, "tweet_id": tweet_id, "error": None}
    except tweepy.TooManyRequests:
        print("レート制限に達しました（リプライ）。")
        return {"success": False, "tweet_id": None, "error": "rate_limit"}
    except tweepy.Forbidden as e:
        print(f"リプライが拒否されました: {e}")
        return {"success": False, "tweet_id": None, "error": f"forbidden: {e}"}
    except Exception as e:
        print(f"リプライエラー: {e}")
        return {"success": False, "tweet_id": None, "error": str(e)}


if __name__ == "__main__":
    print("=" * 50)
    print("X API 接続テスト")
    print("=" * 50)
    try:
        client = get_client()
        me = client.get_me()
        print(f"認証成功: @{me.data.username} ({me.data.name})")
    except Exception as e:
        print(f"認証失敗: {e}")
        print("  config.py のAPIキーを確認してください")
