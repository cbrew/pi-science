# Experience report: verifying OEIS A001002 against (2,3)-rooted trees

A short retrospective on the first worked example run through this harness
(`examples/a001002-demo/`, recorded in `.pi/science/`). Goal: demonstrate that
the OEIS comment "a(n+1) is number of (2,3)-rooted trees on n nodes" is correct,
as a simple scientific exercise in the harness's research-question-first workflow.

## What went well

- **Question → operationalization → verification → report in one sitting.** The
  harness structure made the shape of the work obvious: pin down the claim, define
  the object precisely, compute, compare, record evidence with provenance, write
  the conclusion. The "finish with an answer, don't invent new work" rule from the
  operating contract was genuinely useful — it kept the experiment from sprawling.
- **Independent methods caught a real data error.** Three methods were built from
  scratch (leaf-count DP, the OEIS dissection recurrence, brute-force generation).
  When an early run showed a mismatch at L ≥ 27, methods 1 and 2 agreed with each
  other but not with the reference array — which isolated the bug to the reference
  data, not the computation. The terms 26–30 I had hand-transcribed were indeed
  wrong (hallucinated extrapolation); the b-file confirmed the computation. Without
  triangulation this would have looked like a failed verification.
- **Triage policy earned its keep.** "Validity-critical → do now, engineering-only
  → defer" was applied: verify computationally (do now), read the b-file directly
  instead of hand-transcribing (do now), stop chasing the original literature once
  the definition was settled (defer).
- **Evidence recording surfaced the caveats.** Requiring `source` + `limitation`
  on every observation made the limits explicit (41 terms, not a proof; recurrence
  not independent of OEIS's own formulas), and the resolved issues section keeps a
  record of the transcription-error incident rather than burying it.

## What didn't

- **Definition ambiguity cost the most time.** "(2,3)-rooted trees on n nodes" is
  terse; my first (plausible!) reading — plane trees sized by total nodes — is
  *wrong* (gives 1, 0, 1, 3, 10 …, not 1, 3, 10, 38 …). The size parameter is the
  number of leaves. This was only settled after an initial enumeration, a manual
  arithmetic slip (I "verified" the wrong sequence by hand before trusting the
  program), user clarification, and the data itself. A terse OEIS comment should be
  treated as a hypothesis to be pinned down by data, not as a definition.
- **Over-archaeology.** I spent several rounds trying to find the original source:
  the cited book is lending-restricted, web search was blocked, an OCR text was a
  stub. The user had to pull me back ("why are you making such a fuss"). The
  literature lookup was never load-bearing: the computation resolved the question.
  Lesson: for a claim like this, go computational immediately and use literature
  only to *explain* the result, not to settle it.
- **Reference data integrity.** Hand-transcribing terms from an API response into
  an array is exactly the kind of silent corruption the harness warns about.
  The final script reads the b-file from disk with index validation, but the
  intermediate error was real and briefly misleading.
- **The extension tools weren't exercised in-session.** `science_record` etc.
  weren't registered in this Pi session, so the ledger was driven by calling
  `src/core.js` directly (`run.mjs`). The result is faithful (same functions, same
  state file) but it's not the same as a live `/science` session exercising the
  real tool path — worth testing in a real session next.

## Takeaways

1. When a claim's vocabulary is ambiguous, enumerate candidate definitions and let
   the data decide — cheap and decisive.
2. Never hand-transcribe reference data; read from source, validate shape, and
   treat discrepancies as evidence, not failure.
3. Budget the archaeology: external sources fail in unhelpful ways; cap the attempt
   and default to direct computation.
4. Independent verification isn't just for correctness — here it was what made a
   botched reference array discoverable at all.
