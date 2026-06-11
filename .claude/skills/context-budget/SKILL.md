---
name: context-budget
description: モノレポ全体のClaude Codeコンテキスト消費（CLAUDE.mdチェーン・contexts・skills・agents・rules・commands）を監査し、トークン削減提案を優先度付きで出力する。設定追加後・セッションが重いと感じた時・MASTER_ARCHITECTURE §5.3 の定期リファクタリング時に使用。
---

# Skill: context-budget — コンテキスト予算監査

## 自動参照タイミング
- `.claude/` 配下に skill / agent / command / rule を追加・変更した直後
- セッションの応答品質が落ちた・コンテキストが圧迫されていると感じた時
- MASTER_ARCHITECTURE.md §5.3「継続的リファクタリング」の定期実行時
- MCPサーバーの追加を検討する時（事前の空き容量確認）

---

## 1. 監査対象（本モノレポ固有のパス）

| 種別 | パス | ロード方式 | 警告閾値 |
|---|---|---|---|
| CLAUDE.mdチェーン | `CLAUDE.md` + `apps/auto-poster/CLAUDE.md` | 常時ロード | 合計300行 |
| コンテキスト | `.claude/contexts/*.md`（4ファイル） | 参照時のみ | 各100行 |
| ルートSkills | `.claude/skills/*/SKILL.md` | 起動時のみ（descriptionは常時） | 各400行 |
| ルートAgents | `.claude/agents/*.md` | 起動時のみ（descriptionは常時） | 各200行 |
| アプリSkills | `apps/auto-poster/.claude/skills/*/SKILL.md` | 同上 | 各400行 |
| アプリAgents | `apps/auto-poster/.claude/agents/*.md` | 同上 | 各200行 |
| アプリRules | `apps/auto-poster/.claude/rules/*.md` | 参照時のみ | 各150行 |
| Commands | `apps/auto-poster/.claude/commands/*.md` | 呼び出し時のみ | 監査対象外（注1） |
| MCP | `.mcp.json`（存在すれば） | 常時ロード | ツール1個 ≒ 500トークン |

**注1**: コマンドは呼び出し時のみロードされるため行数が多くても常時コストはゼロ。
監査対象は「常時ロードされるもの」と「description（frontmatter）」を優先する。

---

## 2. トークン推定式

- 散文（日本語含む）: `単語数 × 1.3`（日本語は `文字数 ÷ 2` で近似）
- コード主体ファイル: `文字数 ÷ 4`
- MCPツールスキーマ: `ツール数 × 500`

計測はPythonワンライナーで行う（LLMに数えさせない — マルチAIの掟）:

```bash
python -c "
import glob, os
for p in glob.glob('.claude/**/*.md', recursive=True) + glob.glob('apps/*/.claude/**/*.md', recursive=True) + ['CLAUDE.md', 'apps/auto-poster/CLAUDE.md']:
    if os.path.isfile(p):
        s = open(p, encoding='utf-8').read()
        print(f'{len(s)//2:>6} tok {sum(1 for _ in open(p, encoding=\"utf-8\")):>5} 行  {p}')
" | sort -rn
```

---

## 3. 分類と判定

| バケット | 基準 | アクション |
|---|---|---|
| 常時必要 | CLAUDE.mdから参照されている / アクティブなコマンドの裏付け | 維持 |
| 時々必要 | 特定作業時のみ参照（contexts, rules） | オンデマンド維持（現状の設計） |
| 不要候補 | どこからも参照されない / 内容が他と重複 | 削除 or 統合を提案 |

**重複検出の重点ペア**（過去に重複が発生しやすい箇所）:
- `apps/auto-poster/.claude/rules/model-routing.md` ⇔ `skills/gemini-api/SKILL.md`（ルーティング表・コスト表）
- `apps/auto-poster/CLAUDE.md` ⇔ `rules/persona.md`（ペルソナ要約）
- ルート `CLAUDE.md` ⇔ `.claude/contexts/*.md`（構成説明）

---

## 4. レポート形式

```
Context Budget Report — x-integrated-platform
═══════════════════════════════════════
常時ロード合計: ~X,XXX トークン（CLAUDE.mdチェーン + descriptions + MCP）
オンデマンド合計: ~XX,XXX トークン（skills/agents/rules/contexts）

┌──────────────────┬──────┬─────────┐
│ 種別             │ 数   │ トークン │
├──────────────────┼──────┼─────────┤
│ CLAUDE.mdチェーン │ 2    │ ~X,XXX  │
│ Skills (root+app) │ N    │ ~X,XXX  │
│ Agents            │ N    │ ~X,XXX  │
│ Rules / Contexts  │ N    │ ~X,XXX  │
└──────────────────┴──────┴─────────┘

⚠ 検出した問題（削減額順）:
1. [問題] → 約X,XXXトークン削減可能
2. ...

推奨アクション Top 3
```

---

## 5. ベストプラクティス

- **descriptionは常時コスト**: agent/skillが一度も起動されなくてもfrontmatterのdescriptionは毎セッションロードされる。30語超は要約する
- **MCPが最大のレバー**: ツール30個のサーバー1つで全skillsの合計を超える。CLIで代替できるMCP（gh, git等）は導入しない
- **変更のたびに監査**: skill/agent追加後にこのスキルを1回実行し、肥大化を早期検出する
- **削除提案は実行しない**: レポートで提案し、ユーザー承認後に削除する
