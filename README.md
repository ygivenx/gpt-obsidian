# gpt-obsidian

Convert ChatGPT exports (ZIP or extracted folder) into an Obsidian vault with incremental re-import, informative summaries, OpenAI-powered tagging, topic backlinks, Bases views, monthly indexes, and import reports.

## Features

- Imports from ZIP or extracted export folders.
- Supports `conversations.json` and split shards (`conversations-000.json`, etc.).
- One note per conversation at `Chats/YYYY/MM/<slug>--<conversation_id>.md`.
- Attachment extraction to `Assets/ChatGPT/<conversation_id>/...`.
- Incremental upsert state at `.gpt-obsidian/index.json`.
- Informative sections: At a Glance, Decisions, Actions, Questions, Topic Tags.
- Topic hub notes with backlinks at `Topics/...`.
- Monthly index notes at `Indexes/ChatGPT/YYYY-MM.md`.
- Import reports at `Reports/ChatGPT Imports/*.md|*.json`.
- Obsidian Bases files at `Bases/Chat Conversations.base` and `Bases/Topics.base`.

## Install

```bash
uv sync
```

## Import

```bash
uv run gpt-obsidian import \
  --input /path/to/chatgpt-export \
  --vault /path/to/your-obsidian-vault
```

### Summary + Tag providers

- Summary provider: `--summary-provider {heuristic,openai}`
- Summary model: `--summary-model <model>` (required for `openai`)
- Tag provider: `--tag-provider {heuristic,openai}`
- Tag model: `--tag-model <model>` (required for `openai`)

Example (OpenAI summaries + OpenAI tags):

```bash
uv run gpt-obsidian import \
  --input <path-to-backup-dir or zip> \
  --vault <obsidian-vault-path> \
  --summary-provider openai \
  --summary-model gpt-4o-mini \
  --tag-provider openai \
  --tag-model gpt-4o
```

`.env` support: if project-root `.env` contains `OPENAI_API_KEY=...`, it is loaded automatically.

## Useful flags

- `--force` re-render all chats
- `--dry-run` no writes
- `--since YYYY-MM-DD`
- `--summary-max-bullets 5`
- `--enable-topic-tags` / `--disable-topic-tags`
- `--topic-tag-limit 8`
- `--generate-indexes` / `--disable-indexes`
- `--generate-bases` / `--disable-bases`
- `--report-dir "Reports/ChatGPT Imports"`
- `--report-format {md,json,both}`
- `--cost-estimate` print rough OpenAI cost estimate before import
- `--batch-size N` process insight generation in parallel batches (default: `1`)

`--cost-estimate` currently has built-in pricing for:

- `gpt-5-nano`, `gpt-5-mini`, `gpt-5`
- `gpt-4o`, `gpt-4o-mini`

## Output layout

- Conversations: `Chats/YYYY/MM/...`
- Attachments: `Assets/ChatGPT/<conversation_id>/...`
- Topic hubs: `Topics/<Namespace>/<topic>.md`
- Monthly indexes: `Indexes/ChatGPT/YYYY-MM.md`
- Reports: `Reports/ChatGPT Imports/...`
- Bases views: `Bases/Chat Conversations.base`, `Bases/Topics.base`

## Tags and backlinks

Generated chat notes include both:

- plain topic tags (e.g. `transformers`) for search/filtering
- wikilinks to topic hub notes (e.g. `[[Topics/transformers|transformers]]`) for clean graph/backlinks

## Doctor / Sync

```bash
uv run gpt-obsidian doctor --input /path/to/export --vault /path/to/vault
uv run gpt-obsidian init-sync --vault /path/to/vault --remote <git-remote>
```

## Development

```bash
uv run python -m unittest discover -s tests -v
```
