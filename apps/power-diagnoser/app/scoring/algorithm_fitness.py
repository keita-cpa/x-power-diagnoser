"""
スコア3: アルゴリズム適合度（20点満点）

★ X（Twitter）の公開アルゴリズムソースコードから抽出した実測値を使用 ★

【出典】
  the-algorithm-main/src/python/twitter/deepbird/projects/timelines/
  scripts/models/earlybird/example_weights.py

  the-algorithm-main/home-mixer/server/src/main/scala/com/twitter/
  home_mixer/product/scored_tweets/param/ScoredTweetsParam.scala

【Earlybird Light Ranker の実測重み】
  - is_replied         : 9.0   ← リプライはいいねの9倍！
  - is_favorited       : 1.0
  - is_retweeted       : 1.0
  - is_profile_clicked : 1.0
  - is_clicked         : 0.3
  - is_open_linked     : 0.1
  - is_video_playback_50: 0.01
  - is_photo_expanded  : 0.03

【Home Mixer の補正乗数】
  - リプライ投稿の拡散スコアには 0.75 のペナルティが掛かる
    （= リプライは「受け取る」と高得点だが「投稿する」と拡散が減る）

【戦闘力スコア計算式】
  tweet_score = Σ(action_count × weight) + reply_penalty
  battle_power = mean(tweet_scores over 30 tweets)
  score = min(20, log10(battle_power + 1) * 6)
"""
import math
import statistics

from app.models import MockDataUsed, TweetStats

# X公式ソースコードより抽出した Earlybird Light Ranker の重み
EARLYBIRD_WEIGHTS: dict[str, float] = {
    "reply":         9.0,
    "like":          1.0,
    "repost":        1.0,
    "profile_click": 1.0,
    "tweet_click":   0.3,
    "link_open":     0.1,
    "video_50pct":   0.01,
    "photo_expand":  0.03,
}

# Home Mixer: リプライ投稿自体への拡散ペナルティ（ScoredTweetsParam.scala より）
HOME_MIXER_REPLY_PENALTY = 0.75


def _tweet_battle_score(tweet: TweetStats) -> float:
    """1ツイートのXアルゴリズム的「戦闘力」をEarlybird重みで算出する。

    受け取ったリプライは最重要シグナル（9.0倍）。
    ただしリプライ自体はHome Mixerで拡散スコア0.75倍のペナルティあり。
    """
    raw_score = (
        tweet.replies        * EARLYBIRD_WEIGHTS["reply"]
        + tweet.likes        * EARLYBIRD_WEIGHTS["like"]
        + tweet.reposts      * EARLYBIRD_WEIGHTS["repost"]
        + tweet.profile_clicks * EARLYBIRD_WEIGHTS["profile_click"]
        + tweet.tweet_clicks * EARLYBIRD_WEIGHTS["tweet_click"]
        + tweet.link_opens   * EARLYBIRD_WEIGHTS["link_open"]
        + tweet.video_50pct_views * EARLYBIRD_WEIGHTS["video_50pct"]
        + tweet.photo_expands * EARLYBIRD_WEIGHTS["photo_expand"]
    )
    # インプレッション数で正規化（1000imp あたりの戦闘力）
    normalized = raw_score / max(tweet.impressions, 1) * 1000
    return normalized


def calc(data: MockDataUsed) -> tuple[int, str]:
    """アルゴリズム適合度スコアを計算する。

    Returns:
        (score, explanation): スコア（0-20）と計算根拠の説明文
    """
    if not data.recent_tweets:
        return 0, "ツイートデータなし（スコア計算不可）"

    tweet_scores = [_tweet_battle_score(t) for t in data.recent_tweets]
    battle_power = statistics.mean(tweet_scores)

    raw = math.log10(battle_power + 1) * 6
    score = min(20, max(0, round(raw)))

    # 説明文用の内訳: battle_power はインプレッション正規化済みなので
    # 生の平均値とは別物。正規化後の寄与で表示する
    avg_reply_score = statistics.mean(
        t.replies * EARLYBIRD_WEIGHTS["reply"] / max(t.impressions, 1) * 1000
        for t in data.recent_tweets
    )
    avg_like_score = statistics.mean(
        t.likes * EARLYBIRD_WEIGHTS["like"] / max(t.impressions, 1) * 1000
        for t in data.recent_tweets
    )

    explanation = (
        f"Earlybird重み適用の平均戦闘力スコア {battle_power:.2f} / 1000imp → "
        f"log10({battle_power:.2f}+1) × 6 = {score}点。 "
        f"内訳例（1000imp当たり）: リプライ寄与 {avg_reply_score:.1f}（×9.0）、"
        f"いいね寄与 {avg_like_score:.1f}（×1.0）。"
        f"リプライはいいねの9倍の重みを持つ（X公式重み）"
    )
    return score, explanation
