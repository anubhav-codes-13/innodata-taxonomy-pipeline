# The Self-Healing System — Explained Simply

## 1. What problem are we solving?

Our system reads legal documents and automatically pulls out **keywords** — the
important words and phrases that describe what each document is about.

The problem: **not every keyword it pulls out is useful.** Some are genuinely
helpful, but some are plain **junk** — words that don't help anyone find or
classify a document. For example, the system sometimes pulls out:

- **Filler phrases** — `"the said matter"`, `"various factors"`, `"recent developments"`
- **Mistakes** — a page number, a date, or an author's name accidentally grabbed as a keyword
- **Meaningless fragments** — `"Article 1(3)"` with no law attached, so you can't tell what it refers to
- **Odd leftovers** — `"Technological Due Process"` appearing 137 times in a collection about
  arbitration, where it clearly doesn't belong

These add clutter and make search worse. So we need a second system whose only job
is to **look at each keyword and decide: is this useful, or is it junk we should
throw away?** Think of it as a **quality inspector** standing at the end of a
factory line.

> **One important clarification — what this is NOT about.**
>
> This system only decides **keep vs. throw away** (is a keyword useful?). It is
> **not** about tidying up words that mean *similar* things — for example
> `"Mediation Law"` and `"Mediation Procedure"`. Those look alike, but they are
> often **deliberately kept separate** because each is a useful filter option in
> the final product (the "grid"). Deciding whether to keep such words apart or
> combine them is a **different job, handled by a different part of the system.**
>
> Don't confuse the two. Here, we are **only hunting for irrelevant junk to
> discard** — not merging look-alikes.

---

## 2. The obvious solution (and why it doesn't work)

The obvious idea:

> "Let an AI check each keyword, then have a human double-check the AI."

That sounds fine for a few documents. But we're going to process **15,000
documents.** Those documents contain **millions of keywords.**

If a human had to look at millions of keywords one by one, it would take **years.**
A person checking one keyword every 5 seconds, 8 hours a day, would need decades.

**So the challenge isn't "how do we check keywords" — it's "how do we check them
without drowning a human in work."**

This is what the self-healing system is designed to solve.

---

## 3. The big idea in one sentence

> **Instead of asking a human to check everything, we filter the keywords through a
> series of cheap automatic checks, so that a human only ever sees the tiny handful
> that are genuinely confusing — and once they decide, the system remembers forever.**

Let's unpack that with three simple ideas.

---

### Idea 1 — Check each *word*, not each *appearance*

Imagine the word **"State Immunity"** shows up in **6,000 places** across all our
documents.

A human does **not** need to approve it 6,000 times. They approve the **word once**,
and that one decision covers all 6,000 appearances.

> **Analogy:** A teacher grading essays doesn't re-learn what the word "the" means
> in every essay. They know it once, and apply that knowledge everywhere.

This one idea shrinks the job from **millions of checks** down to roughly
**10,000–30,000 unique words** to ever consider. That's already a hundred times
smaller.

---

### Idea 2 — A human should only see the *confusing* ones

Most keywords are easy to judge automatically:

- `"State Immunity"` — obviously a real, useful legal term. **Keep it.** (No human needed.)
- `"the said matter"` — obviously meaningless filler. **Throw it away.** (No human needed.)

The only ones worth a human's time are the **genuinely unclear** ones in the middle
— where even the AI isn't sure.

> **Analogy:** Airport security. Most bags go straight through the scanner with no
> problem. Only the **suspicious** ones get pulled aside for a human to inspect.
> Nobody hand-searches every single bag.

---

### Idea 3 — Every human decision is remembered forever

When a human finally does make a decision, the system **writes it down permanently.**

So if a human says *"throw away 'Technological Due Process' — it's nonsense,"* the
system records that. From then on, **it never asks about that word again.** Not
tomorrow, not for document number 14,000, not ever.

> **Analogy:** Teaching a child that a stove is hot. You explain it **once.** After
> that, they just know. You don't re-explain it every single day.

This is why it's called **"self-healing"** — every time a human fixes something, the
system gets a little smarter and needs a little less help. The work gets **easier
over time, not harder.**

---

## 4. How it actually works — the funnel

Picture a **funnel** (wide at the top, narrow at the bottom). All the keywords pour
in at the top. At each level, some get sorted out automatically, so fewer and fewer
fall through to the next level. By the bottom, only a trickle reaches the human.

Each level is called a **"gate."** Let's walk a few example keywords through it.

Our example keywords entering the funnel:
1. `"State Immunity"` — a genuine, important legal term
2. `"xy z"` — garbage text
3. `"various factors"` — a vague filler phrase that means nothing useful
4. `"Technological Due Process"` — we discussed and rejected this before
5. `"Algorithmic Award Drafting"` — a brand-new term nobody has seen yet

---

### Gate 1 — The simple rules check  *(instant, free)*

The first gate uses dead-simple rules to catch obvious garbage:
- Too short? Just numbers? Just filler words like "the said"? → **Thrown away.**

> `"xy z"` is caught here and **deleted.** It never bothers anyone again.

The rest move on.

---

### Gate 2 — The memory check  *(instant, free)*

The second gate asks: **"Have we seen this exact word before and already decided?"**

It checks two lists the system keeps:
- A **KEEP list** (words humans already approved)
- A **DISCARD list** (words humans already rejected)

> `"Technological Due Process"` is on the DISCARD list from a past decision.
> The system **throws it away automatically** — no human, no AI, no second-guessing.

This is the memory from Idea 3 doing its job. The more decisions that pile up here,
the more keywords get resolved instantly.

The rest move on.

---

### Gate 3 — The AI inspector  *(cheap)*

Now the AI looks at the keywords that are genuinely new. But it doesn't just guess —
it weighs several clues at once, like a detective:

- **How often does it appear?** A word in just 1 spot out of 300,000 is probably
  noise. A word in thousands of spots is probably real.
- **Does it look like words we already approved?** If yes, probably useful.
- **Does it look like words we already rejected?** If yes, probably junk.

Based on these clues, the AI sorts each keyword into one of three buckets:

| AI's verdict | What happens |
|--------------|--------------|
| **Clearly useful** | Kept automatically — no human needed |
| **Clearly junk** | Thrown away automatically — no human needed |
| **Not sure** ("gray zone") | Sent to the next gate |

> `"State Immunity"` — appears thousands of times, looks like other approved terms →
> **Clearly useful. Kept automatically.**
>
> `"various factors"` — vague filler, looks like other rejected words →
> **Clearly junk. Thrown away automatically.**
>
> `"Algorithmic Award Drafting"` — brand new, appears only a few times, the AI genuinely
> can't tell if it's an important emerging topic or just noise → **gray zone. Moves on.**

After this gate, only a small "not sure" pile remains.

---

### Gate 4 — The second opinion  *(medium cost)*

For the "not sure" pile, we ask **three AI judges** the same question independently —
like getting a second and third doctor's opinion.

- If **all three agree** → we trust it and decide automatically.
- If **they disagree** → this is genuinely tricky, so it finally goes to a human.

This catches a lot more, so the pile that reaches a human gets even smaller.

---

### The Human  *(expensive — used sparingly)*

Finally, a person looks at what's left — only the **truly confusing** keywords.

And we make their job as easy as possible:
- They see the keyword **plus the AI's explanation** of why it's unsure.
- They see **real examples** of where it appeared.
- The list is **sorted by importance** — the keyword appearing in 500 documents is
  shown before the one appearing in 1, so their time goes where it matters most.
- Similar keywords are **grouped together** so one decision can cover several at
  once (e.g. *"here are 8 vague procedural fragments — reject them all?"*) instead
  of judging each one in isolation.

> `"Algorithmic Award Drafting"` reaches the human. They recognize it as a real
> emerging topic (AI being used to write legal awards), and click **Keep.**

And here's the magic: **that decision is instantly written to the KEEP list.** The
next time this word appears — in any future document — it sails through Gate 2
automatically. The human is never asked again.

---

## 5. The whole journey at a glance

```
        ALL KEYWORDS FROM THE SYSTEM
        (millions of appearances → ~10–30K unique words)
                       │
                       ▼
   ┌─────────────────────────────────────────────┐
   │ GATE 1: Simple rules        → trash obvious junk
   ├─────────────────────────────────────────────┤
   │ GATE 2: Memory check        → apply past decisions
   ├─────────────────────────────────────────────┤
   │ GATE 3: AI inspector        → keep / trash the clear ones
   ├─────────────────────────────────────────────┤
   │ GATE 4: Three AI judges     → decide if they all agree
   └─────────────────────────────────────────────┘
                       │
                       ▼
               👤  HUMAN  (sees only the few truly confusing ones)
                       │
                       ▼ (decision saved to memory — forever)
               ✅  CLEAN, APPROVED KEYWORDS
```

Notice the shape: **a wide flood at the top, a thin trickle at the bottom.** That
trickle is all a human ever has to deal with.

---

## 6. Why it keeps getting easier (the "self-healing" part)

Here's the most important payoff. Two things happen as we process more documents:

**1. The memory keeps growing.**
Every human decision is saved. So Gate 2 catches more and more keywords
automatically over time. The pile reaching the human shrinks with every batch.

**2. The vocabulary runs out of new words.**
Law has a limited set of terms. After the first few thousand documents, we've
basically seen them all. Document number 14,000 almost never contains a word we
haven't already decided on.

> **Analogy:** Learning a language. At first, every sentence has new words and you
> reach for the dictionary constantly. After a while, you know almost all the words,
> and you barely need it anymore.

**The result:** the human works hardest at the very beginning, then less and less,
until checking a brand-new document needs **almost no human effort at all.**

---

## 7. What if the automatic part makes a mistake?

Fair question — we're trusting computers to throw away keywords without a human
looking. What if they get it wrong?

We have a **safety net** called **spot-checking** (the same idea a factory uses for
quality control):

> Every so often, we grab a **random handful** of the keywords the system decided on
> its own, and have a human check them.
>
> - If the system was right almost every time (say, 98%+) → we trust it and carry on.
> - If too many were wrong → we make the AI **more cautious**, so it sends more
>   keywords to humans instead of deciding alone.

This gives us a **dial we can turn**: more speed (trust the AI more) or more
caution (involve humans more), based on real measured accuracy — not guesswork.

---

## 8. The one-paragraph summary

We have a system that pulls keywords out of legal documents, but some keywords are
junk. Checking them all by hand is impossible at scale. So we built a **funnel of
automatic filters**: simple rules catch obvious garbage, a memory catches anything
already decided, and an AI (double-checked by three AI judges) handles the clear
cases. Only the genuinely confusing keywords — a tiny fraction — ever reach a
human. And because **every human decision is remembered forever** and **law has a
limited vocabulary**, the human's workload shrinks steadily until new documents need
almost no attention at all. A random spot-check keeps the whole thing honest. The
human stops being a **worker who processes everything** and becomes a **teacher who
occasionally corrects the system** — and the system heals itself from there.
