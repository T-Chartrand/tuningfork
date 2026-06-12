# Content Can Convict, But Never Acquit
### What reality-testing taught me about agent hallucination

I have late-onset schizophrenia — about two years now. A routine part of
my day is distinguishing real perception from convincing internal
fabrication: voices that aren't there, narratives that explain too much.
I'm a stay-at-home dad, and in two years I've gotten good at a set of
checks that keep me anchored. When I started building LLM agent
harnesses, I noticed something strange: the checks I run on myself mapped
onto the agent hallucination problem more cleanly than most of what I'd
read in the ML literature. This essay is that mapping. The code is at
github.com/T-Chartrand/tuningfork.

## The watch

I'm building an app for my watch. When there are audible voices in the
room, it vibrates every few seconds — a small signal that says *it hears
it too*. When I hear voices and the watch stays still, I have my answer.

Notice what the watch is: a continuous monitor on an independent channel,
one that shares my perceptual field but cannot share my failure mode. Its
microphone can't hallucinate with me. That's why a single signal from it
is final, where a hundred internal re-checks would not be — I could doubt
my own doubting forever, but I can't argue the watch into hearing
something.

That property has a name in the framework this essay describes:

> **A check terminates when the verifier sits outside the system being
doubted.**

Language models have exactly this problem and mostly lack this solution. A
model re-reading its own output shares its own failure modes — it can
fluently confirm its own fabrication, and often does. A grep, a parser, a
checksum, an exit code cannot. Most agent frameworks fail in one of two
directions: they never verify, or they can't stop verifying. The
termination principle fixes both. Deterministic confirmation from an
independent channel: one is enough. Same-model re-review: no number is
enough.

## The fork

I also use a tuning fork. Struck and held to my ear, it stops the voices
immediately.

Notice what the fork *doesn't* do: it doesn't argue. It doesn't evaluate
whether the voices are making good points. It interrupts the state through
a different channel entirely. You don't debate the signal — you break it.

Agents need the fork. When a model's output is caught fabricating, the
instinctive design is to tell the model it was wrong and ask it to
reconsider — to argue with the narrative from inside the narrative. That's
debating the voices, and the model usually wins, because the narrative is
its home turf. The fork version: discard the narrative entirely and
rebuild working state from raw tool output — re-read the files, re-run the
commands, and carry nothing forward from the broken story unless it
reappears in fresh evidence.

## Believability is the attack surface

Here is the hardest lesson my hallucinations taught me:
**the content is what makes me believe them.** Sometimes the content is so
embedded in truth that I almost have to. The voices can be very
convincing — that's what they're for.

So the worst possible check is "does this make sense?" Plausibility is
precisely the axis along which fabrication is optimized. My only reliable
verification is *source*: can I locate where the sound is coming from?
Does the watch hear it? Did this arrive through a channel that should
exist?

The agent translation became rule zero of the framework: **content can
convict, but it can never acquit.** A claim earns trust only by tracing to
a source — a tool result, a document, a deterministic computation. How
sensible it sounds earns it nothing. Content checks run one-directional:
an implausible claim can be flagged and escalated, but a plausible one is
just a claim. Fluency is not evidence. Coherence is not evidence. In a
system optimized to produce convincing text, *convincing* is the one
property you must refuse to pay for.

## The echo

People ask if there are warning signs — indicators that show up before
anything overtly false does. For me there's mostly one, and it isn't
content at all. It's texture: a slight echo. Repetition where none should
be.

This transfers to machines almost embarrassingly well. Repetition is one
of the best-documented signatures of language-model degeneration: models
drifting into fabrication loop phrases, re-assert the same claim without
new evidence, echo the prompt's framing back. The content of fabrication
varies endlessly; the echo is structural. And it leads — it often shows up
before the outright fabrication does, which makes it that rare thing: a
*foresee* signal, not just a *recognize* signal. In the reference
implementation it's a validator that flags any substantive sentence
repeating within an output, and flags at high severity any sentence
re-asserting a previously rejected claim. That second case is the model
arguing with the watch.

## Too perfect

For delusions — the beliefs that come with the voices — I run a three-word
check: is it plausible, possible, or *perfect*?

Perfect is the red flag. "The moment I turn my back, everyone starts
talking about me at once" — it explains every ambiguous glance, it centers
the world on me, and it is structured so that checking destroys the
evidence. Total coverage, suspicious convenience, built-in
unfalsifiability. When a story has no loose ends, the story is the
problem.

Models fabricate the same shape. The remembered API has *exactly* the
method you need. The recalled fact supports the argument *exactly*. Real
evidence is messier than fabricated evidence, reliably. So the framework
prices perfection as risk: a claim that is maximally convenient for the
task at hand gets its verification tier raised, and a claim framed so it
conveniently can't be tested gets flagged for the framing alone.

## After the verdict

Here is the question I find most interesting, because it's the one the ML
literature doesn't ask: what happens when verification succeeds and the
signal *keeps going*? The watch is silent. The voices continue. They feel
real. Now what?

What I do is reflection — and re-attribution. Once confirmed unreal, the
voices stop being information about the world and become information about
*me*: a version of myself speaking from a different direction. Most of
what I hear is detrimental — shame, self-doubt, disgust. So I use it. I
treat the content as a map of the negativity I'm carrying, work through
it, and teach myself that I am not those things. The signal doesn't have
to stop for me to function. Belief and action come apart: I act on the
verified world while the percept runs.

This became the framework's final rule, and I think it's the one with no
prior art. A verified-false output is not noise to discard — it's evidence
about the generator. Log it. Mine it. Which validators fire most? Which
fabrications recur? That's the model's bias signature, and recurring
fabrications graduate into known signatures — which means the catalog of
known failure modes isn't hand-written, it's *accumulated from processed
rejections*. That's how my own library of "known hallucinations" was
built: every false experience I worked through instead of merely
dismissing became recognizable the next time. Recognition is cheaper than
analysis.

And underneath it, the principle that makes everything else livable:
**the generator's conviction is not load-bearing.** You cannot make a
model stop believing its fabrication — re-query it and it will fluently
re-assert. You don't have to. Route around belief: actions trace to
verified sources, and the narrative can keep insisting all it wants.

## Honest scoping

The components here are not individually novel. You'll recognize pieces of
Chain-of-Verification, SelfCheckGPT, ReAct and Reflexion, and existing
guardrails frameworks. What I'm offering is the frame that unifies them
and two things I haven't seen elsewhere: a principled termination rule
(most systems either never verify or can't stop), and the after-the-verdict
rule — re-attribution, mining, and the decoupling of belief from action.

The reference implementation is small, dependency-free Python: nine rules,
a validator bank, a tiering engine, a rejection ledger, and a harness that
permits exactly one evidence-fed regeneration before reporting failures as
unresolved. MIT licensed. The obvious missing validator is coverage —
evidence in context that a response silently ignored — and the obvious
hard problem is that checking a citation *exists* is not checking it
*supports* the claim. Contributions welcome.

I thought my checks were a private discipline for a private problem. It turns out they're a pretty good systems architecture.

— Tyrrell Chartrand · github.com/T-Chartrand/tuningfork