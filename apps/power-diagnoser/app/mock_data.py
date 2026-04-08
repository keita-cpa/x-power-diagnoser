"""
モックデータ生成モジュール。

twitter_id を random seed として使うことで、同じIDに対して
常に同じダミーデータが返る（再現性あり）。
"""
import hashlib
import math
import random

from app.models import MockDataUsed, TweetStats


def _seed_from_id(twitter_id: str) -> int:
    """twitter_id から決定論的な整数シードを生成する。"""
    digest = hashlib.sha256(twitter_id.encode()).hexdigest()
    return int(digest[:8], 16)


def _generate_tweet_stats(rng: random.Random, base_impressions: int) -> TweetStats:
    """1ツイート分のエンゲージメント統計をランダム生成する。"""
    impressions = max(1, int(rng.gauss(base_impressions, base_impressions * 0.4)))
    er = rng.uniform(0.005, 0.08)  # エンゲージメント率 0.5%-8%

    total_eng = max(0, int(impressions * er))
    likes = int(total_eng * rng.uniform(0.5, 0.7))
    reposts = int(total_eng * rng.uniform(0.1, 0.2))
    replies = max(0, total_eng - likes - reposts)

    profile_clicks = max(0, int(impressions * rng.uniform(0.002, 0.02)))
    tweet_clicks = max(0, int(impressions * rng.uniform(0.01, 0.05)))
    link_opens = max(0, int(impressions * rng.uniform(0.001, 0.015)))
    video_50pct = max(0, int(impressions * rng.uniform(0.0, 0.03)))
    photo_expands = max(0, int(impressions * rng.uniform(0.005, 0.04)))

    return TweetStats(
        likes=likes,
        reposts=reposts,
        replies=replies,
        profile_clicks=profile_clicks,
        tweet_clicks=tweet_clicks,
        link_opens=link_opens,
        video_50pct_views=video_50pct,
        photo_expands=photo_expands,
        impressions=impressions,
    )


def generate_mock_data(twitter_id: str) -> MockDataUsed:
    """twitter_id に基づいた再現性あるモックデータを生成する。"""
    rng = random.Random(_seed_from_id(twitter_id))

    # フォロワー / フォロー（対数スケールで分布）
    followers = int(10 ** rng.uniform(math.log10(500), math.log10(50_000)))
    following = int(rng.uniform(100, min(followers * 2, 2_000)))
    ff_ratio = round(followers / max(following, 1), 3)

    # 直近30ツイートのインプレッション基準値（フォロワー数の5%-30%）
    base_imp = int(followers * rng.uniform(0.05, 0.30))
    recent_tweets = [_generate_tweet_stats(rng, base_imp) for _ in range(30)]

    posts_last_7days = rng.randint(3, 35)
    community_keyword_rate = round(rng.uniform(0.20, 0.90), 3)
    community_interaction_rate = round(rng.uniform(0.10, 0.80), 3)

    return MockDataUsed(
        followers=followers,
        following=following,
        ff_ratio=ff_ratio,
        recent_tweets=recent_tweets,
        posts_last_7days=posts_last_7days,
        community_keyword_rate=community_keyword_rate,
        community_interaction_rate=community_interaction_rate,
    )
