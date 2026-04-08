"""
ランク・称号判定モジュール。

スコアに応じたランク（S/A/B/C/D）と user_type 別の称号を返す。
2025〜2026年トレンドの若者言葉に全振りした大喜利的称号で
ユーザーのスクショ・シェア欲を刺激する設計。
"""
from typing import Literal

UserType = Literal["therapist", "customer"]

# (min_score, rank, title)  — 降順で評価する
_THERAPIST_TITLES: list[tuple[int, str, str]] = [
    (92, "S", "圧倒的メロいカリスマ確定演出"),
    (80, "S", "ギャルマインド全開の覇者"),
    (68, "A", "えぐちすぎてバグる成長株"),
    (55, "A", "キャパいのに伸びてる天才肌"),
    (42, "B", "風呂キャンしながら中堅維持"),
    (30, "C", "メンブレ寸前の頑張り屋"),
    (16, "C", "しゃばいインプレゾンビ予備軍"),
    (0,  "D", "好きすぎて滅んだ底辺案件"),
]

_CUSTOMER_TITLES: list[tuple[int, str, str]] = [
    (92, "S", "沼りすぎてキャパい最上位太客"),
    (80, "S", "ほんmoneyバグらせすぎの強者"),
    (68, "A", "蛙化現象に抗う優良常連"),
    (55, "A", "ギャルマインドで通い続ける勢"),
    (42, "B", "わかりみあるが財布がメンブレ"),
    (30, "C", "えぐちを感じつつも足が遠のく"),
    (16, "C", "しゃばい頻度でメンブレしがち"),
    (0,  "D", "好きすぎて滅んだ幻の太客"),
]


def determine_rank_and_title(
    total_score: int, user_type: UserType
) -> tuple[Literal["S", "A", "B", "C", "D"], str]:
    """スコアとユーザータイプからランクと称号を返す。

    Returns:
        (rank, title)
    """
    table = _THERAPIST_TITLES if user_type == "therapist" else _CUSTOMER_TITLES
    for threshold, rank, title in table:
        if total_score >= threshold:
            return rank, title  # type: ignore[return-value]
    return "D", table[-1][2]
