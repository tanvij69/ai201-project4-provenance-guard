# Provenance Guard

A backend API that classifies submitted text as AI-generated or human-written, returns a confidence score and transparency label, logs every decision, and allows creators to appeal misclassifications.

---

## Architecture Overview

A submitted piece of text takes the following path through the system:

1. `POST /submit` receives the text and `creator_id`
2. Flask-Limiter checks the rate limit — rejects with 429 if exceeded
3. **Signal 1 (Groq LLM)** sends the text to `llama-3.3-70b-versatile` and returns a probability score (0 = human, 1 = AI)
4. **Signal 2 (Stylometric heuristics)** computes sentence length variance, type-token ratio, and punctuation density in pure Python and returns a structural score (0 = human, 1 = AI)
5. **Confidence scorer** combines both scores using a 60/40 weighted average
6. **Label generator** maps the combined score to one of three transparency label texts
7. The full result is written to the **SQLite audit log**
8. The API returns `content_id`, `attribution`, `confidence`, `label`, and both signal scores

If a creator disagrees with their classification, `POST /appeal` logs their reasoning, updates the submission status to `under_review`, and returns a confirmation. No automatic re-classification occurs.

---

## Detection Signals

### Signal 1: Groq LLM Classification

**What it measures:** Whether the overall writing style and semantic content read as AI-generated or human-written, based on a holistic judgment by `llama-3.3-70b-versatile`.

**Why I chose it:** LLMs recognize patterns in tone, phrasing, and semantic consistency that statistical tools cannot capture. A single sentence asking the model to return a probability is cheap, fast, and captures things like unnaturally even hedging language or suspiciously generic phrasing.

**What it misses:** It is a black box — there is no explanation for why it assigned a particular score. It can be fooled by heavily edited AI text and may flag polished human writing as AI-generated. Short texts give it little signal to work with.

**Output:** Float between 0 and 1. Returned from `get_llm_score(text)` in `detection.py`.

---

### Signal 2: Stylometric Heuristics

**What it measures:** Three structural properties of the text computed in pure Python:
- **Sentence length variance:** AI text tends to have more uniform sentence lengths. Low standard deviation = AI-like.
- **Type-token ratio (TTR):** Ratio of unique words to total words. AI text reuses vocabulary more, producing a lower TTR.
- **Punctuation density:** Ratio of punctuation characters (commas, dashes, colons, parentheses) to total words. Human writing tends to use more varied punctuation.

**Why I chose it:** These metrics are genuinely independent of the LLM signal — one is semantic, the other is structural. Combining them is more informative than either alone. Stylometric features are also fully explainable, unlike the LLM score.

**What it misses:** Constrained human writing styles (minimalist poets, non-native speakers, genre fiction with repetitive structure) can score as AI-like even though they are human. Very short texts (under ~30 words) produce unreliable scores because there is not enough data to compute meaningful variance.

**Output:** Float between 0 and 1. Returned from `get_stylometric_score(text)` in `detection.py`.

---

## Confidence Scoring

Both signals are combined using a weighted average:

```
combined_score = (0.6 × llm_score) + (0.4 × stylometric_score)
```

The LLM signal is weighted higher (60%) because it captures semantic and stylistic meaning that pure statistics cannot. The stylometric signal (40%) provides an independent structural check.

**Threshold mapping:**

| Combined Score | Verdict | Label Shown |
|---|---|---|
| 0.85 – 1.00 | likely_ai | High Confidence AI |
| 0.60 – 0.84 | likely_ai | Moderate AI indicators |
| 0.40 – 0.59 | uncertain | Uncertain |
| 0.16 – 0.39 | likely_human | Moderate human indicators |
| 0.00 – 0.15 | likely_human | High Confidence Human |

**How I validated it produces meaningful variation:**

I tested four deliberately chosen inputs spanning the range. Scores varied from 0.293 to 0.638 — not clustering near a constant value:

| Input | LLM Score | Stylometric Score | Combined | Verdict |
|---|---|---|---|---|
| Clearly AI (formal AI paragraph) | 0.80 | 0.394 | **0.638** | likely_ai |
| Borderline formal human (monetary policy) | 0.72 | 0.438 | **0.607** | likely_ai |
| Borderline edited AI (remote work) | 0.40 | 0.329 | **0.372** | likely_human |
| Clearly human (casual ramen review) | 0.23 | 0.387 | **0.293** | likely_human |

The clearly AI input scored 0.638 and the clearly human input scored 0.293 — a meaningful gap. The two borderline cases landed between them as expected.

---

## Transparency Label

The exact text displayed to users for each confidence band:

**High Confidence AI** (combined score ≥ 0.85):
> "This content shows strong indicators of AI generation. Our system is highly confident this was not written entirely by a human."

**Moderate AI indicators** (combined score 0.60 – 0.84):
> "This content shows several indicators of AI generation, though our confidence is moderate. Consider this result alongside other context."

**Uncertain** (combined score 0.40 – 0.59):
> "We could not confidently determine whether this content was AI-generated or human-written. The available evidence is mixed, so this result should be interpreted cautiously."

**Moderate human indicators** (combined score 0.16 – 0.39):
> "This content shows several indicators of human authorship, though our confidence is moderate. Consider this result alongside other context."

**High Confidence Human** (combined score < 0.16):
> "This content shows strong indicators of human authorship. Our system found little evidence of AI generation."

The three required variants (high-confidence AI, high-confidence human, uncertain) all produce distinct label texts. A score of 0.638 and a score of 0.95 produce visibly different labels — the system does not make a binary flip at 0.5.

---

## Rate Limiting

**Configuration:** 5 requests per minute per IP address on `POST /submit`. Applied using Flask-Limiter with `storage_uri="memory://"`.

**Reasoning:** A legitimate creator submitting their own work would rarely send more than 1–2 requests per minute. Setting the limit at 5 per minute gives real users comfortable headroom while blocking automated scripts that might flood the endpoint. 100 requests per day would be a reasonable secondary limit for a production deployment.

**Confirmed working** — sending 12 rapid requests produced:

```
200
200
200
200
200
429
429
429
429
429
429
429
```

The first 5 returned 200 (OK). Requests 6–12 returned 429 (Too Many Requests).

---

## Audit Log

Every `POST /submit` and `POST /appeal` call writes a structured entry to a SQLite database (`audit_log.db`). Entries are readable via `GET /log`.

Sample entries:

```json
{
  "id": 2,
  "content_id": "a8903948-1bd0-416b-b15d-d1d1348ae192",
  "creator_id": "test-user-1",
  "timestamp": "2026-06-30T19:20:19.339451+00:00",
  "text_snippet": "Artificial intelligence represents a transformative paradigm shift...",
  "attribution": "likely_ai",
  "confidence": 0.638,
  "llm_score": 0.8,
  "stylometric_score": 0.394,
  "status": "classified",
  "appeal_reason": null
}
```

```json
{
  "id": 3,
  "content_id": "75cc5e9b-2943-4e6d-a8d2-070b20c3df7b",
  "creator_id": "test-user-1",
  "timestamp": "2026-06-30T19:20:32.126764+00:00",
  "text_snippet": "ok so i finally tried that new ramen place downtown and honestly?...",
  "attribution": "likely_human",
  "confidence": 0.293,
  "llm_score": 0.23,
  "stylometric_score": 0.387,
  "status": "under_review",
  "appeal_reason": "I wrote this myself from personal experience. My writing style may appear formal but it is my own."
}
```

```json
{
  "id": 4,
  "content_id": "79e71bc7-c570-428d-b9a0-18c95c2b5e0d",
  "creator_id": "test-user-1",
  "timestamp": "2026-06-30T19:21:49.246136+00:00",
  "text_snippet": "The relationship between monetary policy and asset price inflation...",
  "attribution": "likely_ai",
  "confidence": 0.607,
  "llm_score": 0.72,
  "stylometric_score": 0.438,
  "status": "classified",
  "appeal_reason": null
}
```

---

## Appeal Handling

Creators can contest a classification by calling `POST /appeal` with their `content_id` and a `creator_reasoning` string.

When an appeal is received:
1. The system looks up the original submission by `content_id`
2. The appeal reasoning is stored alongside the original decision in the audit log
3. The submission status updates from `classified` to `under_review`
4. A confirmation is returned to the creator

No automatic re-classification occurs. A human reviewer can query `GET /log` to see the original scores, the label, and the creator's reasoning side by side.

**Example appeal request:**
```json
POST /appeal
{
  "content_id": "75cc5e9b-2943-4e6d-a8d2-070b20c3df7b",
  "creator_reasoning": "I wrote this myself from personal experience. My writing style may appear formal but it is my own."
}
```

**Example response:**
```json
{
  "appeal_logged": true,
  "content_id": "75cc5e9b-2943-4e6d-a8d2-070b20c3df7b",
  "message": "Your appeal was received and is under review.",
  "status": "under_review"
}
```

---

## Known Limitations

**Very short submissions produce unreliable stylometric scores.** The stylometric signal needs enough text to compute meaningful sentence-length variance and vocabulary diversity. A submission under roughly 30 words may produce an extreme score in either direction simply because there is not enough data to measure — not because the writing is actually uniform or varied. This is a property of statistical signals generally: they require a minimum sample size to be trustworthy, and this system does not currently reject or flag short inputs before running them through the pipeline.

**Constrained human writing styles score as AI-like.** Minimalist poetry, children's writing, and song lyrics with refrains all use intentional repetition and simple vocabulary — which lowers type-token ratio and sentence-length variance, both of which the stylometric signal interprets as "AI-like." This is a fundamental limitation of the signal design, not a calibration problem. The system partially compensates by weighting the LLM signal higher (60%), but a skilled minimalist writer who also uses formal, consistent phrasing may still land in the uncertain or likely_ai band even though their work is entirely human.

---

## Spec Reflection

**One way the spec helped:** Writing the planning.md confidence scoring section before any code forced me to decide what a score of 0.5 actually means to a user before I had any implementation to lean on. This meant the threshold design (5 bands instead of a binary flip at 0.5) was a deliberate design decision rather than something I backed into after seeing scores cluster in the middle. The spec section became a direct implementation checklist for `compute_confidence()`.

**One way implementation diverged from the spec:** The planning.md described three label variants (high-confidence AI, high-confidence human, uncertain). In implementation, I ended up with five label variants — adding "moderate AI indicators" and "moderate human indicators" bands — because the 0.60–0.84 and 0.16–0.39 ranges felt meaningfully different from both the extreme and the center, and collapsing them all into "uncertain" would have made a 0.62 look the same as a 0.50. The spec said a 0.51 and a 0.95 should produce different labels; achieving that cleanly required the extra bands.

---

## AI Usage

**Instance 1: Generating the Flask skeleton and Groq signal function**

I provided the Detection Signals section and Architecture diagram from planning.md and asked Claude to generate a Flask app skeleton with a `POST /submit` route stub and a `get_llm_score()` function that calls the Groq API and returns a float between 0 and 1. The generated function returned a correctly structured JSON response but used `temperature=0` which made the model occasionally refuse to answer — I revised this to `temperature=0.2` after seeing refusals in testing. I also added the markdown code fence stripping logic (`if raw_output.startswith("```")`) because the model occasionally wrapped its JSON output in backticks despite being told not to.

**Instance 2: Generating the stylometric signal and confidence scoring logic**

I provided the Detection Signals section, Uncertainty Representation section, and architecture diagram and asked Claude to generate `get_stylometric_score()` and `compute_confidence()`. The generated scoring function used a simple 50/50 average rather than the 60/40 weighting specified in planning.md — I corrected this before wiring it in. The normalization ranges for sentence-length variance also required manual tuning after testing: the original ranges produced scores that clustered near 0.5 for most inputs, so I adjusted the upper bound of the standard deviation normalization from 5.0 to 8.0 to spread scores more meaningfully across the range.

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/submit` | Submit text for classification |
| POST | `/appeal` | Appeal a classification |
| GET | `/log` | View audit log entries |

---

## Tech Stack

- Python 3
- Flask
- Flask-Limiter
- Groq API (llama-3.3-70b-versatile)
- SQLite (built-in)
- python-dotenv