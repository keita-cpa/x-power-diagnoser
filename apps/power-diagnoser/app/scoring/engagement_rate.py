"""
スコア4: エンゲージメント率（20点満点）

ロジック:
- 標準エンゲージメント率 = (likes + reposts + replies) / impressions × 100
- 業界平均は1-3%とされるため、これを基準に相対スコア化する。
- 5%以上で満点に近い評価。

式:
  er = (likes + reposts + replies) / impressions * 100  # %
  score = min(20, er / 5.0 * 20)
"""
import statistics

from app.models import MockDataUsed


def calc(data: MockDataUsed) -> tuple[int, str]:
    """エンゲージメント率スコアを計算する。

    Returns:
        (score, explanation): スコア（0-20）と計算根拠の説明文
    """
    if not data.recent_tweets:
        return 0, "ツイートデータなし（スコア計算不可）"

    er_values = []
    for t in data.recent_tweets:
        total_eng = t.likes + t.reposts + t.replies
        er = total_eng / max(t.impressions, 1) * 100
        er_values.append(er)

    median_er = statistics.median(er_values)
    # 5% で満点（20点）、業界平均~2%で8点相当
    raw = median_er / 5.0 * 20
    score = min(20, max(0, round(raw)))

    explanation = (
        f"中央値エンゲージメント率 {median_er:.2f}%（業界平均1-3%）→ "
        f"{median_er:.2f}% ÷ 5.0% × 20 = {score}点"
    )
    return score, explanation
