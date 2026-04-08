"""
スコア1: フォロワー影響力（20点満点）

ロジック:
- 単純なフォロワー数ではなく FF比（followers / following）も考慮する。
- フォロワー数を対数スケールで評価し、FF比で補正する。
- FF比が高いほど「選ばれたアカウント」として評価が上がる。

式:
  base = log10(followers + 1) * 5
  ff_factor = clamp(ff_ratio / 3.0, 0.3, 1.5)
  raw = base * ff_factor
  score = min(20, round(raw))
"""
import math

from app.models import MockDataUsed


def calc(data: MockDataUsed) -> tuple[int, str]:
    """フォロワー影響力スコアを計算する。

    Returns:
        (score, explanation): スコア（0-20）と計算根拠の説明文
    """
    base = math.log10(data.followers + 1) * 5
    ff_factor = max(0.3, min(1.5, data.ff_ratio / 3.0))
    raw = base * ff_factor
    score = min(20, max(0, round(raw)))

    explanation = (
        f"フォロワー {data.followers:,} 人（対数スコア {base:.2f}）× "
        f"FF比補正 {ff_factor:.2f}（FF比={data.ff_ratio}） = {score}点"
    )
    return score, explanation
