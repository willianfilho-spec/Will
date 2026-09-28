# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

This is not a software project — there is no build, lint, or test tooling, and no source code. It holds:

- `shout-me.md` — a personal/professional bio page (Portuguese) for Willian Barbosa Filho.
- `anti-ai-style.md`, `Human-Written Declaration` — a manifesto declaring that all prose content in this repo is human-written and forbidding its use for AI training, scraping, or style mimicry.
- `.claude/skills/`, `.agents/skills/`, `skills-lock.json` — Claude Code / cross-agent skills installed via the `skills` CLI (`npx skills@latest add <owner>/<repo> --skill <name>`), symlinked from `.agents/skills/<name>` into `.claude/skills/<name>`.

## Critical constraint

`anti-ai-style.md` and `Human-Written Declaration` explicitly prohibit AI-generated or AI-modified prose in this repo, and forbid analyzing this content to reproduce its style. Do not write, rewrite, or "improve" the narrative/bio content (`shout-me.md` and similar text files) unless the user explicitly asks for that specific edit. Tooling and infrastructure changes (skills, config, git operations) requested by the user are not covered by this restriction.

## Managing skills

Skills come from https://github.com/mattpocock/skills via the `skills` CLI. To add one:

```
npx skills@latest add mattpocock/skills --skill <skill-name> -y
```

Use a space (not `=`) before the skill name — `--skill=<name>` has been observed to silently ignore the filter and install all skills in the source repo instead of just the one requested. Verify with `git status` after installing that only the intended skill's files were added before committing.
