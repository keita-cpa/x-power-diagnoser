"""
メンエス界隈特化型 Xアカウントパワー＆太客度診断ツール
FastAPI バックエンド プロトタイプ

POST /api/diagnose
  - twitter_id と user_type を受け取り、5軸スコア + 称号を返す
  - 現フェーズはモックデータで動作（X API 未接続）
"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates

from app import llm
from app.mock_data import generate_mock_data
from app.models import DiagnoseRequest, DiagnoseResponse, ScoreBreakdown, ScoreExplanation
from app.ranking import determine_rank_and_title
from app.scoring import (
    algorithm_fitness,
    community_activity,
    engagement_rate,
    follower_influence,
    impression_power,
)

app = FastAPI(
    title="X アカウントパワー診断 API",
    description=(
        "メンエス界隈向け Xアカウントパワー＆太客度診断ツールのバックエンド。\n"
        "X公式オープンソースアルゴリズム（Earlybird重み）を用いたスコア計算を行う。"
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


@app.get("/", tags=["ui"], include_in_schema=False)
def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/api/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok", "message": "X アカウントパワー診断 API 稼働中"}


@app.post("/api/diagnose", response_model=DiagnoseResponse, tags=["diagnose"])
def diagnose(request: DiagnoseRequest) -> DiagnoseResponse:
    """
    Xアカウントのパワーと太客度を診断する。

    **入力**
    - `twitter_id`: X のユーザーID（@なし）
    - `user_type`: `therapist`（セラピスト）または `customer`（お客さん）

    **スコア軸（各20点 / 合計100点満点）**
    1. フォロワー影響力 — FF比補正つきフォロワー数評価
    2. インプレッション力 — 中央値ベースの拡散力
    3. アルゴリズム適合度 — X公式 Earlybird 重みで算出した戦闘力
    4. エンゲージメント率 — 業界平均比較
    5. 界隈アクティブ度 — メンエス界隈での存在感

    **注意**: 現バージョンはモックデータで動作します。
    """
    mock = generate_mock_data(request.twitter_id)

    s1, e1 = follower_influence.calc(mock)
    s2, e2 = impression_power.calc(mock)
    s3, e3 = algorithm_fitness.calc(mock)
    s4, e4 = engagement_rate.calc(mock)
    s5, e5 = community_activity.calc(mock)

    total = s1 + s2 + s3 + s4 + s5
    rank, title = determine_rank_and_title(total, request.user_type)

    breakdown = ScoreBreakdown(
        follower_influence=s1,
        impression_power=s2,
        algorithm_fitness=s3,
        engagement_rate=s4,
        community_activity=s5,
    )

    mode = llm.determine_mode(request.twitter_id)
    analytical_advice = llm.generate_analytical_advice(
        mode=mode,
        user_type=request.user_type,
        total_score=total,
        rank=rank,
        title=title,
        breakdown=breakdown,
    )

    return DiagnoseResponse(
        twitter_id=request.twitter_id,
        user_type=request.user_type,
        total_score=total,
        rank=rank,
        title=title,
        mode=mode,
        breakdown=breakdown,
        mock_data_used=mock,
        score_explanation=ScoreExplanation(
            follower_influence=e1,
            impression_power=e2,
            algorithm_fitness=e3,
            engagement_rate=e4,
            community_activity=e5,
        ),
        analytical_advice=analytical_advice,
    )
