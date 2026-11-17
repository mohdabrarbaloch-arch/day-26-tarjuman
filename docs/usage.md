# Usage

## The three views

The app is one page with three tabs. No build step, no router — just three
sections that show and hide.

### Translate

The main view. Source language, target language, a text box, a button.

- **Detect language** is the default source. It reads the script and, for Latin
  text, checks whether the words look like Roman Urdu.
- **Swap** flips source and target and moves the text across.
- **Try a sample** cycles four examples. Two are Roman Urdu, and one of those is
  the transliteration trap — worth running to see the verifier catch it.
- `Ctrl`/`Cmd` + `Enter` translates without reaching for the mouse.

The character counter turns amber past 4,000 and red past 5,000. The server
enforces the same limit, so the counter is a courtesy, not the guard.

### Reading the verdict

The badge is the headline; the axes are the actual answer.

| Badge | Meaning |
|---|---|
| **VERIFIED** | Every applicable check passed. |
| **LIKELY** | Nothing failed, but at least one check was inconclusive. |
| **UNCERTAIN** | A check failed that could also fail on a good translation — usually round-trip on an idiom. Read the translation yourself. |
| **FAILED** | A check failed that cannot fail on a real translation. The provider did not translate. |

Each axis shows a score from 0 to 1 and a sentence explaining itself. The
sentence is generated from the actual numbers, not a template — if it says "44%
overlap", that is the measured overlap.

**Skipped is not passed.** When round-trip is skipped (text over 1,200
characters), the axis says *skipped* and is excluded from the confidence
calculation. It never silently counts as a pass.

### Conversation mode

Requires sign-in. Pick two languages, start a session, and type.

- Each turn shows the original above the translation.
- The speaker flips automatically after each message, so you can hand the phone
  back and forth.
- Every turn carries its own verdict. A failed turn is flagged in the transcript
  rather than passed through as if it worked.
- The transcript is saved, so you can come back to it.

This is the mode that makes the verification useful in practice: in a live
conversation you cannot stop to check a translation, so the app marks the ones
you should not trust.

### History

Requires sign-in. Every saved translation, newest first.

- Filter by verdict, or show only favourites.
- **The verdict stored is the verdict earned at the time.** If the verification
  rules change, old records keep what they were given. History should not
  silently rewrite itself.
- Delete removes the record permanently. There is no undo, and the button asks
  first.

---

## Common tasks

### Translate a paragraph longer than the provider's limit

Just paste it. The chunker splits on paragraph, then sentence, then clause, then
word, and reassembles losslessly. Each chunk is verified separately, and if any
chunk fails the whole document fails — an average would hide one bad paragraph
in ten.

### Translate Roman Urdu

Type it as you normally would and set the target to English. The app detects
Roman Urdu and tells the provider the source is Urdu.

**Expect failures here, and read them.** Many providers transliterate rather than
translate Roman Urdu. When that happens the app says so:

> The output is still Roman Urdu — the same words, respelled. The provider
> normalised the spelling instead of translating.

That is a true statement about the provider, not a bug in the app.

### Use it without an account

Translation works signed out. History and conversation mode need an account,
because they store things.

### Point it at a different provider

Implement two methods on a class in `app/core/provider.py`:

```python
class MyProvider:
    name = "my-provider"
    max_chars = 5000

    async def translate(self, text, source, target) -> str: ...
```

Then swap the instance in `get_provider()`. Nothing else changes — the chunker
reads `max_chars`, and the verifier does not care where the text came from.

---

## What the app will not do

- **Tell you whether a claim is true.** It verifies how a translation was
  produced, not whether the original sentence is correct.
- **Transcribe speech.** There is no microphone button because there is no
  speech pipeline. The brief mentioned speech translation; this build is
  text-only and says so.
- **Guarantee a good translation.** It can prove a translation *did not happen*.
  It cannot prove one is *good* — a fluent, wrong translation passes every check
  except round-trip, and round-trip is the axis most likely to be fooled.
