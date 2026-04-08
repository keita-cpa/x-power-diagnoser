"""
スコア5: 界隈アクティブ度（20点満点）

ロジック:
- メンエス界隈での「存在感」を3つの指標で評価する。
  1. 直近7日間の投稿頻度（1日1-5投稿が理想）
  2. 界隈キーワード（#メンエス等）の使用率
  3. 界隈アカウントとのインタラクション率

式:
  post_score   = min(7, posts_last_7days / 7) * 7     # 最大7点
  keyword_score = community_keyword_rate * 7           # 最大7点
  interact_score = community_interaction_rate * 6      # 最大6点
  total = post_score + keyword_score + interact_score  # 最大20点
"""
from app.models import MockDataUsed


def calc(data: MockDataUsed) -> tuple[int, str]:
    """界隈アクティブ度スコアを計算する。

    Returns:
        (score, explanation): スコア（0-20）と計算根拠の説明文
    """
    # 1日1投稿（週7回）を基準とし、それ以上は頭打ち
    post_score = min(7.0, data.posts_last_7days / 7.0) * 7
    keyword_score = data.community_keyword_rate * 7
    interact_score = data.community_interaction_rate * 6

    score = min(20, max(0, round(post_score + keyword_score + interact_score)))

    explanation = (
        f"投稿頻度スコア {post_score:.1f}（週{data.posts_last_7days}投稿）+ "
        f"キーワード使用率スコア {keyword_score:.1f}（{data.community_keyword_rate*100:.0f}%）+ "
        f"界隈インタラクションスコア {interact_score:.1f}（{data.community_interaction_rate*100:.0f}%）"
        f" = {score}点"
    )
    return score, explanation
