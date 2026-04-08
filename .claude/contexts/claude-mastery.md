# Context: docs/knowledge/Claude_Mastery/

## 役割

Claude Code設定コレクション（everything-claude-code）。**読み取り専用ナレッジ。変更禁止。**

agents, commands, hooks, rules, skills の実例集として参照する。

---

## ディレクトリ構成

| ディレクトリ | 内容 |
|---|---|
| `agents/` | エージェント定義のサンプル集（29ファイル） |
| `commands/` | カスタムコマンドのサンプル集 |
| `hooks/` | フックスクリプトのサンプル集 |
| `rules/` | ルールファイルのサンプル集 |
| `skills/` | スキルパックのサンプル集 |
| `contexts/` | コンテキストファイルのサンプル集 |
| `mcp-configs/` | MCP設定サンプル |
| `scripts/ecc.js` | CLIエントリーポイント |
| `.env.example` | 環境変数テンプレート（ANTHROPIC_API_KEY等） |

---

## 参照タイミング

- `apps/auto-poster/.claude/` の設定（hooks/commands/rules）を改善するとき
- 新しいhook・command・agent・skillを作成するとき
- Claude Code設定のベストプラクティスを調べるとき
- MCP設定サンプルを参考にするとき

---

## 注意

- `node_modules/` はコピー時に除外済み（存在しない）
- 機能確認が必要な場合は元リポジトリを参照
- このディレクトリは変更しない。参照のみ。
