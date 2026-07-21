---
name: seam-proof-build
description: The through-build companion to /ground. Grounding turns assertions into verified knowledge BEFORE coding; this keeps that discipline running DURING the build - every load-bearing step is proven by a real run that could fail, at the seam, the moment construction reaches it. Six moves: prove the keystone seam with a throwaway before formalizing, probe generality to find where a claim stops being true, negative-control every gate so a pass means something, verify each seam bottom-up in isolation, re-prove any seam you change, and prove operational/security seams too - by proxy if you cannot run them (author the check, hand it to whoever can, gate on the result; a security boundary must be shown to fail closed). Invoke when building a multi-layer feature, wiring a new subsystem, or standing up anything with a containment/security boundary.
---

# /seam-proof-build - keep grounding alive through construction

`/ground` stops the agent guessing about the code before it writes. Its own text
scopes it to the **pre-implementation** pass. But the same failure - stating an
inference as a fact without checking - re-enters the moment coding starts, wearing
build-shaped clothes: "the supervisor returns the right shape" (never run),
"Firefox gets past the wall" (tried once, on one URL), "the containment test
passes" (never checked it can fail), "the refactor is harmless" (the proven test
was never re-run against the new code). Each is a claim the build rests on, and
each is verifiable by a single command that either passes or fails.

This skill is the discipline of firing that command **at the moment the build
reaches the claim**, not at the end. It is a self-walked discipline, not a harness
guarantee. Every move below was compiled from a real build session, not derived
from principle.

## The core rule

A build is a sequence of load-bearing steps. **No step is "done" on the strength
of reading the code you just wrote.** A step is done when a command you ran - one
that was capable of failing - passed. "Looks right," "should work," and "the types
line up" are not done. The only termination signal for a step is a green run of a
check that could have gone red.

## The six moves

### 1. Prove the keystone seam with a throwaway, before you formalize

Before writing production files for a new architecture, find the single seam the
whole design rests on and prove it with a minimal disposable prototype. If the
architecture is wrong, you learn it at prototype cost, not after nine files exist
and one of them is load-bearing on a false assumption.

- Real incident: a browser tool's whole design rested on "a warm browser process
  can serve rendered-DOM snapshots over a Unix socket." Before any real file, a
  ~90-line throwaway supervisor+client proved exactly that - warm reuse, the socket
  protocol both directions, and DOM-to-markdown - in one run. Only then were the
  real files written, against a seam that was now known-good instead of hoped-good.
- The prototype is disposable on purpose. Its job is to move one architectural
  claim from "should hold" to "held, here is the output," as cheaply as possible.

### 2. Probe generality - find where the claim STOPS being true

A capability confirmed on one input is an anecdote, and an anecdote quietly
generalized into "it works" is the same inference-as-fact failure in build form.
Run varied real inputs specifically to find the boundary - the case where it
breaks - because the boundary is the finding that changes the spec.

- Real incident: "Firefox renders pages the blocked engine couldn't." Tested on
  one site, that reads as a general bypass. Tested on four varied real sites, the
  truth appeared: it renders three JS-heavy apps fine and is stopped cold by a
  fourth site's behavioral challenge. The capability is real but BOUNDED, and the
  bound (not the success) is what the spec had to record and what stopped the tool
  from overclaiming.
- Pick inputs that stress different axes, and include at least one you expect
  might fail. A generality probe that only tries easy cases is move 3's failure
  wearing a different mask.

### 3. Negative-control every gate - prove the test can fail

A gate that cannot fail is not a gate; a green from it is theater. Before you
trust a check as a gate, run it against the exact condition it exists to catch and
confirm it goes RED. Only a test you have watched fail is evidence when it passes.

- Real incident: an SSRF containment gate is meant to prove a sandboxed process
  cannot reach internal services. Run it as-is (no sandbox yet) and it correctly
  FAILED - it flagged the reachable gateway and exited non-zero. That failure is
  what certifies the gate detects a real hole; without seeing it fail, its later
  pass under containment would prove nothing.
- This is the highest-value move for anything security- or correctness-critical,
  because a rubber-stamp gate is worse than no gate: it manufactures false
  confidence at exactly the boundary where you most need the truth.

### 4. Verify each seam bottom-up, in isolation, before stacking the next

Decompose the build into seams and prove each at its own boundary before composing
them. When the end-to-end run later breaks, the break localizes to the one seam you
had not yet turned green, instead of forcing a hunt across the whole stack.

- Real incident, the seam ladder for a contained browser tool: engine renders
  standalone -> supervisor round-trip over the socket -> full client-to-lib
  end-to-end -> containment gate -> [gateway dispatch, deferred behind an operator
  step]. Each rung was a real run, green before the next was stacked. The one rung
  that could not be tested without a privileged operator step was named as blocked,
  not silently assumed.
- A seam you genuinely cannot exercise yet (needs a credential, a privileged
  account, external hardware) is not a seam you get to assume. Name it blocked, say
  what run will prove it, and gate the dependent work on that run - never let an
  unrun seam ride to "done" on the back of the green ones (see the freeze-gate and
  build-stint disciplines for the same rule at other boundaries).

### 5. Re-prove any seam you change

A green test certifies the code it ran against. The instant you edit that code -
even a rename, an import reorder, a "harmless" refactor - the certification is
stale until you re-run. Carrying an old pass forward across a change is inference-
as-fact with a time delay.

- Real incident: a proven supervisor seam had its import block refactored for
  house style after it was already green. The refactor touched exactly the loading
  path the seam depended on, so the end-to-end run was fired again - it passed, but
  it was not allowed to be assumed. A refactor that "obviously" preserves behavior
  is precisely the kind of claim this whole discipline exists to make you check.

### 6. Operational and security seams get proven too - by proxy if you cannot run them

A privileged command, a deploy step, a reboot / reload / crash transition, a
service dependency, a persistence guarantee - each is a seam, even though none of
them looks like code. Two failures hide here, and both are lethal for a security
boundary:

- **They get mis-filed as "instructions," not seams,** so they never enter the
  frame at all. If an action changes system state, it is a seam - `systemctl
  restart <x>`, an `enable`, a firewall reload, "does it survive a reboot." Name it
  as one.
- **The ones you personally cannot run get written as confident steps.** No sudo,
  needs a reboot, needs another machine - the obligation does not disappear, it
  CONVERTS: author the exact check plus its pass/fail criterion, hand it to whoever
  can run it, and gate the dependent work on the returned result. A runbook line
  that says "run X" with no verification attached is an assumed seam wearing an
  instruction's clothes. Every privileged step ships with its own proof-command and
  expected output. The seams you cannot run get MORE rigor, not a pass - they are
  usually the highest-risk ones precisely because no green check on your machine
  ever touches them.

For a security boundary, the mandatory seam is the FAILURE mode, not the happy
path - this is move 3 (negative-control) pointed at the deployment instead of the
test. Put the system in the container-absent state (the service up with its
containment removed) and prove the contained process refuses to run. "It is
contained when containment is loaded" is not the claim that matters; "it cannot run
when containment is absent" is.

- Real incident: a browser sandbox passed every functional gate - render-proof
  green, SSRF containment gate green, full suite green - and was still FAIL-OPEN.
  Its containment (an nftables table) had been loaded by a privileged command that
  was never grounded for blast radius, so the same command also silently switched on
  an unrelated dormant firewall table and cut the host's own API egress. Worse: the
  browser service was enabled to start at boot while its containment was NOT, and the
  unit declared no dependency on it - so the next reboot would bring up an
  untrusted-JS renderer with no network containment at all. Every seam that would
  have caught this was one the builder could not run himself (what the privileged
  command does to global state; what persists across a reboot; does the contained
  process refuse to start when the container is gone) - and each was written as a
  runbook instruction instead of an operator-run, gated check. The functional seams,
  all runnable, were proven exhaustively; the operational and fail-closed seams, none
  runnable by the builder, were assumed. The boundary shipped green and open.

## How it composes with the other disciplines

- `/ground` runs first and owns the pre-code pass (assertions about the wiring ->
  verified before writing). This skill is its continuation once code exists.
- The verification-claim gate (a Stop hook) is the harness backstop for the core
  rule here: it fires when the agent says "verified" without a run. This skill is
  the agent-side discipline that keeps the hook from ever needing to.
- `experiment-freeze-gate` and `delegated-build-stint` guard other seams (a design
  against itself; a delegation handoff). The shared law across all four: a claim is
  not done until something that could have failed didn't.

## Termination

The build is done when every load-bearing step has a green run of a check that
could have gone red, every generality bound is recorded, every gate has been
watched to fail once, every seam changed after its proof has been re-proven, every
operational and privileged step has either been run or handed off as an authored,
gated check, and every security boundary has been shown to fail closed. An empty
"asserted-but-unrun" column is the only done - and for a security boundary,
"asserted-but-unrun" explicitly includes the seams you could not run yourself, not
just the ones you forgot. Those are the ones that ship green and open.
