---
name: deneuralyzer
description: The after-ship companion to /seam-proof-build. Once a pipeline runs on real inputs, every stop, near miss or hand correction is a training example, and the code is the model being trained - explicit, inspectable rules instead of weights. Six moves - record each stop as a fixture instead of fixing it in place, name the class it is an instance of and fix the class at its owner, move the check to the earliest cheap stage (a preflight against the real target), make every classifier total with an explicit "unknown" that routes to a proposer and a human confirmation whose answer is stored as a rule, measure generalization on inputs not seen before rather than on the input the fix came from, and keep operating sessions separate from building sessions. Invoke when a working pipeline keeps hitting "hiccups" on real inputs, when a fix is about to be a special case, or when deciding whether the system is getting better or only bigger.
---

# /deneuralyzer - make each failure generalize

A pipeline that runs on real inputs (documents to parse, feeds to ingest, pages to
read, records to reconcile) meets inputs its author did not foresee. Each one
shows up as a stop, a near miss, or a person correcting the output by hand. The
usual response is a patch at the point where it showed up: one more pattern, one
more special case, one more source-specific rule. Each patch is correct and the
system still fails on the next unforeseen input, because a patch encodes the
example, not the class.

The reframe: **the code is a model being trained, and each failure is a labelled
training example.** What a neural network would learn from many examples, the
system learns as explicit rules - which keeps it inspectable, but means the
author has to do the generalizing a gradient would otherwise do. The test of a
change is the same as for a model: does it improve behaviour on inputs it was not
fitted to? A change that removes a failure only on the input it came from is
memorization. A change that removes it on inputs never seen is a mechanism.

Every move below was compiled from a real pipeline that reads structured inputs from
many external sources and acts on them, whose runs kept stopping on sources it had
not met before.

## The six moves

### 1. Record the stop as a fixture; do not fix it where it happened

When an operating run fails, the cheapest-feeling move is to patch the output
(edit the generated file, type the answer by hand) and keep going. Do that to
finish the run if you must, but the stop itself goes into a defect list with the
input, the command and the output, and later into a fixture that the fix must
handle. The fixture is the training example; without it the next fix has nothing
to generalize from and nothing to be tested against.

- Real incident: a source's API named three fields in one record (`CamelCase`
  identifiers) while the interface the pipeline acted on showed them under different
  wording. The run stopped on the join. The keys were fixed by hand to finish that
  item; the mismatch went into the defect list as a fixture.

### 2. Name the class, fix it at its owner

For each fixture, ask what it is an instance of and which part of the system owns
that class of decision. Write the fix there, so every member of the class gets it.
List the per-case fixes you were about to make and check whether each is a
special case of one mechanism; if so, build the mechanism and keep the cases as
its tests.

- Real incident: three stops in one day - an item dropped while a file was
  assembled by hand, an optional free-text field left empty because "optional" was
  treated as a decision, and the naming mismatch above. The first proposed fixes were
  three cases (a naming rule, a mode change for one kind, one more regex). They are
  instances of two mechanisms: each item needs one identity checked against the real
  target, and each item needs a decision with no silent fall-through.
- Check the diagnosis against the code before writing it down. The first
  diagnosis here ("there is no policy table") was wrong: the kinds already carried
  the policy, and the gap was the fall-through for items no kind decided. The
  fix moved from "build a table" to "make the existing one total".

### 3. Move the check to the earliest cheap stage

Failures found at the most expensive stage (a visible run with a person waiting,
a production write, a sent message) cost a round trip each. Find the earliest
point where the real target can be checked without side effects and check the
whole plan against it there: a preflight. A preflight compares the plan with the
target directly, so it catches failure classes nobody predicted, which a list of
known pitfalls cannot.

- Real incident: every stop surfaced at the last stage, with a person watching.
  The general fix is a preflight at plan time: read each real target without acting
  on it, bind every item it contains to a plan entry, check every value and required
  decision, and report all mismatches for the batch before a person is involved. The
  late check stays as the last guard.

### 4. Make every classifier total, with a learning loop on "unknown"

A classifier built from patterns has a hole wherever no pattern matches, and code
around it fills the hole with a default that looks like a decision ("optional",
"other", "skip"). Make "no rule matched" an explicit outcome. Route it to a
proposer (a model, where no rule decides), have a person confirm or correct the
proposal, and store the confirmed answer as a new rule. Then each unknown input
stops the pipeline at most once, and the rule set grows exactly where real inputs
needed it.

- Real incident: a free-text field matched a kind that was seeded to hold a
  stored value, but its text is written fresh for each target, so no value ever
  existed; it fell through to "optional" and was left empty. The rule set had the right kind
  and the wrong mode, and nothing made the gap visible.
- The stored rule must stay readable: a pattern, a kind, a mode. A learning loop
  that writes opaque state has traded inspectability for coverage.

### 5. Measure generalization on unseen inputs

Count what the fixes are supposed to reduce, on inputs not used to make them:
stops per batch on targets never seen before, and items per target left for a
person. Both should fall as rules accumulate. If they fall only on the inputs the
fixes came from, the system is memorizing. Report the number with the change.

- Real incident: the pipeline already had a per-target count of items left for
  the operator; it became the coverage measure, alongside stops per batch on new
  sources.

### 6. Keep operating separate from building

Diagnosing and fixing inside an operating session makes the operating session
expensive (every later call re-reads the diagnosis) and tempts point fixes under
time pressure. An operating run records stops and finishes or holds the item; a
building session takes the fixtures and generalizes. The operating instructions
say so explicitly.

- Real incident: one batch of four items, run after a context reset, still grew
  from 54K to 181K tokens of context, partly from diagnosing two defects in the
  same session; its cost per item matched the worst earlier batch.

## When not to use

A one-off script that will not see new inputs gains nothing from a learning loop;
fix it directly. The loop pays where the input distribution is open (new sources,
new document layouts, new sites) and the system is expected to run for long.
