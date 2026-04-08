"""
スコア2: インプレッション力（20点満点）

ロジック:
- バズツイートによる外れ値に引きずられないよう、直近30ツイートの
  インプレッション数の「中央値」を使用する（平均ではなく）。
- 中央値を対数スケールで評価する。

式:
  median_imp = median(tweet.impressions for tweet in recent_tweets)
  score = min(20, log10(median_imp + 1) * 4)
"""
import math
import statistics

from app.models import MockDataUsed


def calc(data: MockDataUsed) -> tuple[int, str]:
    """インプレッション力スコアを計算する。

    Returns:
        (score, explanation): スコア（0-20）と計算根拠の説明文
    """
    if not data.recent_tweets:
        return 0, "ツイートデータなし（スコア計算不可）"

    impressions = [t.impressions for t in data.recent_tweets]
    median_imp = statistics.median(impressions)
    raw = math.log10(median_imp + 1) * 4
    score = min(20, max(0, round(raw)))

    explanation = (
        f"直近30ツイートの中央値インプレッション {median_imp:,.0f} → "
        f"log10({median_imp:,.0f}+1) × 4 = {score}点 "
        f"（外れ値除去のため中央値を使用）"
    )
    return score, explanation
