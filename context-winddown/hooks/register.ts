// context-winddown: compaction on the agent's signal instead of mid-sprint.
//
// After each main-thread turn the mod reads the context size. At or above the
// wind-down threshold (CONTEXT_WINDDOWN_TOKENS, default 450000) it queues one
// prompt asking the agent to finish its current step, save state and call the
// ready_to_compact tool. The tool only sets a flag, because a compaction
// cannot run while a turn is running; when that turn completes the mod
// compacts the conversation. Automatic compaction stays as the backstop.
import type { Register } from 'claude-code'

const TOOL = 'ready_to_compact'
const DEFAULT_WINDDOWN_TOKENS = 450_000

const COMPACT_INSTRUCTIONS =
  'The agent saved its state to files before this compaction. Keep: the goal of the work, ' +
  'the paths of the state files it wrote, the last step completed and verified, the next step, ' +
  'and any question still waiting on the operator.'

const windDownPrompt = (tokens: number, threshold: number, tool: string) =>
  `[context-winddown] Context is at ${tokens} tokens, past the wind-down threshold of ${threshold}. ` +
  'Wind down now: finish and verify the step in progress but start no new work; save state the way ' +
  'your work protocol says (a heartbeat STATE file, memory, a handoff note); commit finished work if ' +
  `your protocol commits. Then call ${tool} and end your turn. The conversation is compacted when that turn ends.`

export const register: Register = on => {
  // Module variables: a reload resets them, which at worst re-sends the wind-down prompt once.
  let isPromptSent = false
  let isReady = false

  on('session.start', async ($, e, next) => {
    const result = await next(e)
    await $.tool.register({
      name: TOOL,
      description:
        'Call this once you have finished winding down for a context compaction (current step ' +
        'verified, state saved, finished work committed). The conversation is compacted when your ' +
        'current turn ends, so end the turn right after calling it.',
      inputSchema: { type: 'object', properties: {} },
      isDeferred: false,
    })
    return result
  })

  on('tool.call', { tool: `mcp__context-winddown__${TOOL}` }, () => {
    isReady = true
    return { result: 'ready', text: 'Compaction will run when this turn ends. End your turn now.' }
  })

  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    if (e.agentId !== undefined) return result

    if (isReady && !e.isAborted) {
      isReady = false
      // The turn is still closing inside this hook; compact once it has ended.
      $.clock.after(500, () => {
        void $.session.compact({ instructions: COMPACT_INSTRUCTIONS }).then(
          r => {
            if (r.skip === undefined) isPromptSent = false
            $.ui.log(`context-winddown: compaction ${r.skip === undefined ? `done (${r.tokensBefore ?? '?'} -> ${r.tokensAfter ?? '?'} tokens)` : `skipped: ${r.skip}`}`)
          },
          err => $.ui.log(`context-winddown: compaction failed: ${String(err)}`),
        )
      })
      return result
    }

    if (isPromptSent) return result
    const configured = Number(await $.env.get('CONTEXT_WINDDOWN_TOKENS'))
    const threshold = Number.isFinite(configured) && configured > 0 ? configured : DEFAULT_WINDDOWN_TOKENS
    const { context } = await $.session.usage()
    if ((context.tokens ?? 0) >= threshold) {
      isPromptSent = true
      void $.prompt.submit({ text: windDownPrompt(context.tokens ?? 0, threshold, `mcp__context-winddown__${TOOL}`) })
    }
    return result
  })
}
