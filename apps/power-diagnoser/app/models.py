from typing import Literal
from pydantic import BaseModel, Field


class DiagnoseRequest(BaseModel):
    twitter_id: str = Field(
        ...,
        min_length=1,
        max_length=15,
        pattern=r"^[a-zA-Z0-9_]+$",
        description="X (Twitter) のユーザーID（英数字・アンダースコアのみ、@なし）",
    )
    user_type: Literal["therapist", "customer"] = Field(..., description="therapist=セラピスト, customer=お客さん")


class ScoreBreakdown(BaseModel):
    follower_influence: int = Field(..., ge=0, le=20, description="フォロワー影響力 (0-20)")
    impression_power: int = Field(..., ge=0, le=20, description="インプレッション力 (0-20)")
    algorithm_fitness: int = Field(..., ge=0, le=20, description="アルゴリズム適合度 (0-20)")
    engagement_rate: int = Field(..., ge=0, le=20, description="エンゲージメント率 (0-20)")
    community_activity: int = Field(..., ge=0, le=20, description="界隈アクティブ度 (0-20)")
    account_health: int = Field(..., ge=0, le=20, description="アカウント健全度・凍結リスク (0-20)")


class TweetStats(BaseModel):
    likes: int
    reposts: int
    replies: int
    profile_clicks: int
    tweet_clicks: int
    link_opens: int
    video_50pct_views: int
    photo_expands: int
    impressions: int


class MockDataUsed(BaseModel):
    followers: int
    following: int
    ff_ratio: float = Field(..., description="フォロー/フォロワー比率")
    recent_tweets: list[TweetStats] = Field(..., description="直近30ツイートの実績")
    posts_last_7days: int
    community_keyword_rate: float = Field(..., description="界隈キーワード使用率 (0.0-1.0)")
    community_interaction_rate: float = Field(..., description="界隈アカウントとのインタラクション率 (0.0-1.0)")
    external_link_rate: float = Field(..., description="投稿内外部リンク含有率 (0.0-1.0)")
    similar_reply_rate: float = Field(..., description="類似文面のリプライ連投率 (0.0-1.0)")


class ScoreExplanation(BaseModel):
    follower_influence: str
    impression_power: str
    algorithm_fitness: str
    engagement_rate: str
    community_activity: str
    account_health: str


class DiagnoseResponse(BaseModel):
    twitter_id: str
    user_type: Literal["therapist", "customer"]
    total_score: int = Field(..., ge=0, le=120)
    rank: Literal["S", "A", "B", "C", "D"]
    title: str
    mode: Literal["ANGEL", "DEVIL"] = Field(..., description="ANGELモード（肯定・共感）またはDEVILモード（鋭い指摘）")
    breakdown: ScoreBreakdown
    mock_data_used: MockDataUsed
    score_explanation: ScoreExplanation
    analytical_advice: str = Field(..., description="Geminiが生成した分析的アドバイス")
