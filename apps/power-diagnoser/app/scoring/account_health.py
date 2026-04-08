"""
スコア6: アカウント健全度（凍結・シャドウバンリスク）（20点満点）

高スコア = 健全（リスク低）
低スコア = 高リスク（シャドウバン・凍結に近い状態）

X公式アルゴリズムおよびガイドラインに基づく減点基準:

1. FF比の異常（フォロー過多）→ pSpam（スパムスコア）上昇
   - FF比 < 1.0（フォローがフォロワーを上回る）はスパム判定の主要シグナル
   - Xの Safety Filter はFF比を Tweepcred（信頼スコア）の構成要素として評価する

2. 外部リンク含有率の高さ → スパム誘導・外部流出判定
   - Xアルゴリズムは外部リンク投稿の拡散スコアを大幅に削減する
   - 高頻度のリンク投稿はスパム誘導パターンとして pSpam を押し上げる

3. 類似文面のリプライ連投 → bot判定・Author Diversity 違反
   - 同一パターンのリプライ繰り返しは自動化ツール（bot）の挙動とみなされる
   - Home Mixer の Author Diversity フィルタがアカウント全体の露出を削減する

式:
  ff_score   = 0〜7点（FF比が高いほど加点）
  link_score = 0〜7点（外部リンク率が低いほど加点）
  reply_score = 0〜6点（類似リプライ率が低いほど加点）
  total = ff_score + link_score + reply_score  # 最大20点
"""
from app.models import MockDataUsed


def calc(data: MockDataUsed) -> tuple[int, str]:
    """アカウント健全度スコアを計算する。

    Returns:
        (score, explanation): スコア（0-20）と計算根拠の説明文
    """
    # ── FF比スコア（0〜7点）──────────────────────────────────────────────────
    # FF比 = followers / following
    # 高いほどフォロワーに「選ばれた」アカウント → pSpam 低
    ff = data.ff_ratio
    if ff >= 2.0:
        ff_score = 7
        ff_note = "良好（pSpam低リスク）"
    elif ff >= 1.0:
        ff_score = 4
        ff_note = "要注意（フォロー過多気味）"
    elif ff >= 0.5:
        ff_score = 2
        ff_note = "危険（pSpam上昇圏）"
    else:
        ff_score = 0
        ff_note = "高リスク（pSpam急上昇・凍結圏）"

    # ── 外部リンク含有率スコア（0〜7点）────────────────────────────────────────
    # 外部リンクを多用するほどスパム誘導と判定される
    lr = data.external_link_rate
    if lr <= 0.10:
        link_score = 7
        link_note = "良好"
    elif lr <= 0.25:
        link_score = 4
        link_note = "要注意（拡散スコア低下中）"
    elif lr <= 0.45:
        link_score = 2
        link_note = "危険（スパム誘導判定圏）"
    else:
        link_score = 0
        link_note = "高リスク（スパム確定パターン）"

    # ── 類似リプライ連投率スコア（0〜6点）──────────────────────────────────────
    # 同一パターンのリプライ連投はbot判定・Author Diversity 違反
    rr = data.similar_reply_rate
    if rr <= 0.10:
        reply_score = 6
        reply_note = "良好"
    elif rr <= 0.25:
        reply_score = 3
        reply_note = "要注意（bot類似パターン検知）"
    elif rr <= 0.40:
        reply_score = 1
        reply_note = "危険（Author Diversity 減衰中）"
    else:
        reply_score = 0
        reply_note = "高リスク（bot判定・シャドウバン圏）"

    score = min(20, max(0, ff_score + link_score + reply_score))

    explanation = (
        f"FF比スコア {ff_score}/7（FF比={data.ff_ratio:.2f}、{ff_note}）"
        f" + 外部リンク率スコア {link_score}/7（{data.external_link_rate*100:.0f}%、{link_note}）"
        f" + 類似リプライ率スコア {reply_score}/6（{data.similar_reply_rate*100:.0f}%、{reply_note}）"
        f" = {score}点"
    )
    return score, explanation
