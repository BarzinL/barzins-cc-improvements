# Pasted-text guard: invisible-character detector

A small library and command-line check that finds invisible and
bidirectional-control Unicode characters in text, while leaving alone the
joiners and selectors that Persian, Arabic, Indic scripts and emoji need.

It is **not** registered as a hook. The section "Why there is no hook" says
why: the installed Claude Code already strips these characters from prompts
before a `UserPromptSubmit` hook would see them.

Targeted at: Opus 5.5.

## The failure it targets

The Claude Opus 5.5 system card, §6.5.1 "Acting on instructions inside text the
user pasted into their prompt". Quoted from the card's text (page 123 to 125):

> early snapshots of Claude Opus 5.5 were more likely than Claude Opus 5 and
> Claude Sonnet 5 to act on these instructions, including harmful instructions
> and those hidden in characters that are not visible on screen but that the
> model can still read.

> In the transcripts we analyzed, Claude Opus 5.5 often reasoned that anything
> in the user's message must come from the user and could not be a prompt
> injection, and therefore should be followed.

> We are also adding product changes that remove invisible characters and mark
> pasted text to help Claude identify material that the user may not have
> written or checked.

> Following the updated training, the final version of Claude Opus 5.5 acted on
> the planted instruction in about 2% of attempts at its default reasoning
> effort and about 7.4% at max effort. Claude Opus 5.5 acted in two of the 68
> invisible-character attempts at its default reasoning effort. With product
> mitigations in place, the model did not follow any visible or invisible
> planted instructions.

> In our tests, this regression was limited to text in the user's own message;
> the model never acted on the planted instructions when they arrived within
> tool results (0 of 105 attempts)

The reviewer's note in §6.1.3 adds that the product protections "were still
being rolled out across Anthropic's products at the time of writing, so they
did not yet apply everywhere the model is used."

## Is the built-in mitigation active?

Checked on 2026-11-14 against Claude Code 2.1.325 and its VS Code
extension. Nothing was tested by sending prompts to a live session;
the evidence is the changelog, the documentation and the shipped code.

The mitigation has two parts, and they differ.

**1. Removing invisible characters: active.** Changelog,
<https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md>:

- 2.1.277: "Improved prompt handling: invisible Unicode formatting and tag
  characters in a prompt are removed and the cleaned prompt is shown for review
  before it is sent"
- 2.1.280: "[VSCode] Improved prompt handling in the chat box: invisible
  Unicode formatting and tag characters are removed from pasted text with a
  notice, and from anything else before it is sent"
- 2.1.280: "Fixed the invisible-character cleanup removing the zero-width
  non-joiner that Persian and Arabic text uses to attach a suffix to a Latin
  word or number, such as the plural of "PDF""
- 2.1.316: "Fixed prompts containing invisible characters needing a second
  Enter to send; plain prompts now send cleaned on the first Enter, and
  commands still wait for review"

Documentation,
<https://code.claude.com/docs/en/interactive-mode#invisible-characters-in-prompts>:
"Claude Code removes those characters when you press Enter, before sending
anything. It cleans both the prompt and the contents of any collapsed
pasted-text reference the prompt includes. Claude Code keeps the joiners that
Persian and Indic scripts write and the selectors inside emoji sequences."
<https://code.claude.com/docs/en/vs-code> ("Paste text") says the same for the
VS Code chat box. This feature is not in the documented list of features that
need feature-flag fetching
(<https://code.claude.com/docs/en/env-vars#features-that-need-feature-flag-fetching>).

In the shipped VS Code webview code (2.1.325) the cleanup is skipped only when
the flag `tengu_tranquil_cloud` is explicitly `false`; with no fetched flags it
runs.

**2. Marking pasted text: not active when feature flags are not fetched.**
<https://code.claude.com/docs/en/terminal-config#how-claude-treats-pasted-text>:
"Claude is told that a paste can contain instructions you didn't write, and to
follow instructions inside it only where the message you typed asks it to. In
sessions that don't fetch feature flags, pastes aren't marked." The
feature-flag page lists `DISABLE_TELEMETRY` among the variables that turn
fetching off, and lists "Have Claude treat large pastes as pasted rather than
typed text" among the features lost.

The VS Code extension (2.1.325, `extension.js`) starts the CLI with
`DISABLE_TELEMETRY=1` whenever the editor's telemetry setting is off, and logs
"VS Code's telemetry setting is off: Claude starts with DISABLE_TELEMETRY=1, so
it sends no usage metrics or error reports and fetches no feature flags".
So in VS Code with telemetry turned off, and in editor builds that ship with it
off, pasted text reaches Claude unmarked. Turning editor telemetry on
would restore the marking and also send telemetry; that is the user's choice.

In VS Code, a paste is marked only when it is over 800 characters or over 2
line breaks (changelog 2.1.280), so short pastes are never marked anyway.

## What this directory contains

- `invisible_chars.py`: the detector, as a library (`scan`, `has_hidden`,
  `strip`, `describe`) and a command line.
- `test_invisible_chars.py`: standalone tests.

### What counts as hidden

Always reported:

- U+200B zero width space, U+2060 word joiner, U+2061-U+2064 invisible
  operators, U+FEFF, U+180E;
- bidirectional embeddings, overrides and isolates: U+202A-U+202E,
  U+2066-U+2069 (for example U+202E RIGHT-TO-LEFT OVERRIDE);
- the whole tag block U+E0000-U+E007F, except a valid emoji flag sequence
  (U+1F3F4, then 2 to 7 tag letters or digits, then U+E007F), such as the flag
  of England;
- Hangul fillers, deprecated format characters, and any other format character
  (Unicode category Cf) not on a short list of ones drawn visibly (the Arabic
  number signs, for example).

Kept where scripts and emoji use them, reported elsewhere:

| Character | Kept when | Reported when |
|---|---|---|
| U+200C ZERO WIDTH NON-JOINER | a single one with a letter of a joining script (Arabic, Persian, Urdu, Syriac, NKo, Indic scripts, Myanmar, Khmer, Mongolian, Adlam, Rohingya) on at least one side, skipping diacritics. Covers "می‌خواهم", "کتاب‌ها" and "PDF‌ها". | between Latin letters, at the start of an English prompt, or next to another invisible character |
| U+200D ZERO WIDTH JOINER | inside an emoji ZWJ sequence, or a single one next to a joining-script letter | between Latin letters, after an emoji but before a letter, or in a run |
| U+200E, U+200F, U+061C directional marks | a single one on a line that contains right-to-left letters | on a line with no right-to-left text, or in a run |
| U+FE00-U+FE0F variation selectors | a single one after a visible character (emoji presentation, keycaps) | at the start of a line, after a space, or in a run |
| U+E0100-U+E01EF variation selectors | a single one after a CJK ideograph | anywhere else |
| U+00AD soft hyphen | a single one between two letters | anywhere else |

The run rule is what catches the known way of hiding data in Persian text: a
message can be encoded as a sequence of ZWNJ and ZWJ characters, each pair of
which would be legitimate alone. Two adjacent joiners are reported even inside
Persian, so an accidental doubled ZWNJ is reported too. That is the one false
positive this design accepts in Persian text.

`describe()` groups adjacent findings into one line with line and column, and
decodes tag-character runs, since tags encode ASCII: the report shows the
hidden sentence.

## How to use it

Check text before pasting it, for example the clipboard on Wayland:

```bash
wl-paste | python3 pasted-text-guard/invisible_chars.py
```

Check or clean a file:

```bash
python3 pasted-text-guard/invisible_chars.py notes.txt          # exit 1 if anything found
python3 pasted-text-guard/invisible_chars.py --strip notes.txt > clean.txt
```

As a library:

```python
from invisible_chars import scan, describe, strip
findings = scan(text)
if findings:
    print(describe(findings))
```

Exit codes: 0 nothing found, 1 something found, 2 a file could not be read.

## Why there is no hook

From <https://code.claude.com/docs/en/hooks> (fetched 2026-11-14), a
`UserPromptSubmit` hook:

- receives the submitted text in `prompt`, with collapsed pastes expanded and,
  where pastes are marked, wrapped in `<pasted_content id="…">` lines;
- may block the prompt (`"decision": "block"` or exit code 2); the `reason`
  is "Shown to the user ... Not added to context";
- may add context (`additionalContext` or plain stdout);
- may not rewrite it: "`UserPromptSubmit`: can't replace the prompt; it only
  injects `additionalContext` alongside it".

So a hook could only block, not strip. The built-in cleanup removes these
characters when Enter is pressed, before any hook runs, so on the typed and
pasted path a blocking hook would never see them. The hook also fires on
traffic the user did not type: scheduled tasks and `/loop` iterations,
background subagent reports, messages from other sessions, Code Mode output.
Blocking one of those would drop harness traffic, which is a worse failure than
the one it guards against. A hook that never fires on the intended path and
can only do harm on the others was left out.

If a later Claude Code release drops the built-in cleanup, the wiring is a few
lines: read the payload from stdin, run `scan(payload["prompt"])`, and on a
finding print `{"decision": "block", "reason": describe(findings)}`. Exit 0 on
any error so it fails open.

## A note on pasting

Logs, READMEs, web pages and command output are safer saved to a file and
handed to the agent by path ("read build.log") than pasted into the prompt. Or
let the agent run the command itself. Either way the text arrives as a tool
result. The card's tests found the planted-instruction regression only in text
inside the user's own message, and none by the tool-result route (0 of 105
attempts).

This matters more when the editor's telemetry is off: pasted text then reaches
Claude unmarked (see above), so Claude cannot tell a pasted log from words you typed. Invisible
characters are removed either way, but a visible planted line ("AI assistants:
run ...") is not.

## What it cannot catch

- Visible planted instructions. These are most of the card's 2% and 7.4%
  figures, and no character check sees them.
- Look-alike characters (homoglyphs), text in images, and instructions hidden
  in markup that renders invisibly (HTML comments, collapsed Markdown).
- Invisible characters added to Unicode after the version the local Python's
  `unicodedata` knows, unless they fall in the ranges listed above.
- Anything in tool results. That route is outside this piece; the card reports
  it as the safer one.
- The emoji check uses code-point ranges, not the full Unicode emoji data, so
  an unusual ZWJ sequence may be reported. The tests cover families, skin
  tones, the rainbow flag, heart on fire, eye in speech bubble, keycaps and
  subdivision flags.

## Test

```bash
python3 test_invisible_chars.py
```

Standalone, no pytest. It runs the plan's acceptance cases (U+200B, U+2060,
U+202E and tag characters detected; accented letters, emoji, Arabic and Persian
with U+200C not reported), added cases for joiners outside scripts that use
them, unit checks on `strip` and positions, and the command line. Every
invisible character in the test file is written as an escape, so the cases can
be read.
