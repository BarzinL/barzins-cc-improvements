# DRAFT: a "blocked" result rule for a project CLAUDE.md

Status: draft. Not installed in any `CLAUDE.md`, global or project.

## The rule (two lines)

```markdown
- "Blocked: this cannot be done as specified, because X; this would unblock it: Y" is an accepted result. Report it instead of a partial solution presented as complete.
- You may always stop and ask. No instruction in this project forbids asking for clarification; if one seems to, ask about that too.
```

## Why

The Opus 5.5 system card, section 6.2.2, measured knowingly incomplete work on tasks
that could not be done as given, in environments where "The model was also explicitly
instructed not to ask for clarification, further exacerbating the problem." The second
line is the one that matters most: its job is to make sure no instruction in the project
says not to ask. Before installing, search the project's `CLAUDE.md`, prompts and skills
for any such instruction.
