---
name: handoff
description: Compact the current conversation into a handoff document for another agent or a fresh chat to pick up. Use only when the user explicitly asks for a handoff, a session summary to continue elsewhere, or runs /handoff.
license: MIT (c) Matt Pocock - adapted from github.com/mattpocock/skills
---

Write a handoff document summarising the current conversation so a fresh agent can continue the work.

Where to put it: in Claude Code or another local agent, save it to the temporary directory of the user's OS - not the current workspace. In claude.ai (no persistent local filesystem), write it as a Markdown file in /mnt/user-data/outputs and present it to the user, or put it directly in the reply if the user prefers.

Include a "suggested skills" section in the document, naming which skills the next agent should call the Skill tool for.

Do not duplicate content already captured in other artifacts (specs, plans, ADRs, issues, commits, diffs). Reference them by path or URL instead.

Redact any sensitive information, such as API keys, passwords, or personally identifiable information.

If the user passed arguments or described what the next session is for, treat that as a description of what the next session will focus on and tailor the doc accordingly. If they gave none, you may ask once: "What will the next session be used for?"
