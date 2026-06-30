# Provenance Guard - Planning

## Project Overview

Provenance Guard is a backend API that analyzes submitted text to determine the likelihood of it being produced by either a human or an AI. Instead of making a simple yes/no decision, the backend API uses multiple detection signals to generate a confidence score using a custom-built confidence scoring engine. The system offers a transparent label to users, maintains an audit log of all decisions made, and allows content creators to appeal a judgment they believe has been assigned in error.

---

# Architecture Narrative

When a creator submits a piece of text, the text is sent to the `POST /submit`  endpoint for processing. The text submission first goes through a rate limit check (via Flask-Limiter), and if successful, it will be accepted. If the creator has exceeded their limit for requests, the request will be rejected.

If the request passes the rate limit, then it will be passed into the two independent detection signals for determination of whether it is AI-generated or human-generated content. The first signal uses the Groq Llama model to classify the content based upon overall writing style, coherence and semantic patterns. The second detection signal uses stylometric metrics such as sentence length variation, vocabulary diversity (type-token ratio) and punctuation marks to assess the variance of how naturally the content is produced.

Upon completion of both detection signals, the final outputs will be combined into a single confidence score by the confidence scoring engine. Using the confidence score, the system then generates one of the three transparency labels:

- High Confidence AI
- High Confidence Human
- Uncertain

Before the API sends back the response to the user, it saves the individual signal scores, confidence score, label for transparency and timestamp in the audit log.

If the user disagrees with their decision through this process, they can appeal against it using `POST /appeal/<submission_id>` endpoint. This will add an explanation for the appeal in the audit log along with the original decision and the new status will be marked as **Under Review** until it has been reviewed by a human being.

---

# Detection Signals

## Signal 1: LLM-Based Classification (Groq)

### What it measures
Uses a large language model to assess the overall written style of both AI and human-created content via a measure of semantic and stylistic coherence.

### Why it works
Large language models are able to measure the variety of grammar, organization, tone, and semantic consistency as a relative measure to distinguish between AI and human generated written content, as well as the prior exposure to both kinds of text.

### Blind spots
- Can incorrectly classify polished or unusual human writing as AI.
- May struggle with heavily edited AI content.
- Depends on the quality of the prompt and model output.
- Acts as a black box — there is no clear explanation for why it assigned a particular score.

---

## Signal 2: Stylometric Heuristics

### What it measures
- Sentence length variation
- Vocabulary diversity (Type-Token Ratio)
- Punctuation density
- Average sentence complexity

### Why it works
When composing written material, human-created content tends to exhibit greater variation and inconsistency, whereas AI-generated written content typically demonstrates greater consistency in sentence structure and vocabulary. All of this can be computed using pure Python without needing any third-party libraries.

### Blind spots
- Skilled or constrained writers (e.g., minimalist poets, non-native speakers) may naturally write consistently and score as "AI-like" despite being human.
- AI text can be edited afterward to appear more naturally varied.
- Short pieces of text provide fewer useful statistics to measure.

These two signals are genuinely independent: one is semantic (LLM judgment), the other is structural (statistical measurement). Combining them is more informative than either alone.

---

# Confidence Scoring

Each detection signal produces its own score. The final confidence score is a weighted combination of the LLM score (60%) and the stylometric score (40%). The LLM receives a slightly higher weight because it captures broader semantic and stylistic patterns, while the stylometric features provide an independent structural check.

combined_score = (0.6 × llm_score) + (0.4 × stylometric_score)

Example ranges:

| Confidence | Result |
|------------|--------|
| 0.90 - 1.00 | High Confidence AI |
| 0.60 - 0.89 | Likely AI |
| 0.40 - 0.59 | Uncertain |
| 0.10 - 0.39 | Likely Human |
| 0.00 - 0.09 | High Confidence Human |

The system intentionally favors uncertainty over making incorrect accusations, since a false positive (labeling a human's work as AI-generated) is worse than a false negative on a creative writing platform. Borderline scores should produce the "Uncertain" label instead of confidently labeling human work as AI-generated.

---

# False Positive Scenario

A human poet submits a tightly controlled, minimalist poem. Their natural style has low sentence-length variance, which scores "AI-like" on the stylometric signal, while the Groq signal is uncertain on its own. The combined confidence comes out around 0.55, which falls into the "Uncertain" band rather than "High Confidence AI."

Because of this, the transparency label tells the reader that the system could not confidently determine the source, rather than issuing a damning AI accusation. The poet can then call `POST /appeal/<submission_id>`, explain that this is their natural style, and the submission's status flips to "Under Review" for a human to look at. This scenario is why the confidence band matters more than a binary yes/no: a 0.55 should visibly read differently than a 0.95.

---

# Anticipated Edge Cases

## Very Short Submissions

Submissions under roughly 30 words don't give the stylometric signal enough data to compute meaningful sentence-length variance or vocabulary diversity. A two-sentence submission can produce an extreme stylometric score simply because there isn't enough text to measure, not because the writing is actually uniform or varied. This could push a legitimate short piece toward an inaccurate "AI-like" or "human-like" score.

## Heavily Repetitive or Simple-Vocabulary Creative Writing

Genres like children's poetry or song lyrics with refrains intentionally repeat words and phrases. This lowers vocabulary diversity and reduces sentence-length variance, both of which the stylometric signal interprets as "AI-like," even though the repetition is a deliberate human artistic choice rather than evidence of AI generation.

---

# API Endpoints

## POST /submit

### Input
```json
{
  "text": "Submitted writing...",
  "creator_id": "creator_123"
}
```

### Returns
```json
{
  "submission_id": 1,
  "classification": "AI",
  "confidence": 0.91,
  "label": "High Confidence AI",
  "signals": {
    "llm_score": 0.93,
    "stylometric_score": 0.89
  }
}
```

---

## POST /appeal/<submission_id>

### Input
```json
{
  "reason": "I wrote this myself."
}
```

### Returns
```json
{
  "submission_id": 1,
  "status": "Under Review",
  "appeal_logged": true
}
```

---

## GET /status/<submission_id>

### Returns
```json
{
  "submission_id": 1,
  "classification": "AI",
  "confidence": 0.91,
  "status": "Under Review"
}
```

---

## GET /log

Returns all audit log entries including:

- submission ID
- timestamp
- individual signal scores
- combined confidence score
- final classification
- transparency label
- appeal status

---

# Architecture Diagram

Submission Flow

```
      POST /submit (raw text)
            |
            v
       Rate Limiter ----(reject if exceeded)----> 429 response
            |
            v
+--------------------------+
|  Signal 1 (Groq LLM)     |  ---> score_llm
+--------------------------+
            |
            v
+--------------------------+
| Signal 2 (Stylometric)   |  ---> score_style
+--------------------------+
            |
            v (score_llm, score_style)
  Confidence Score Engine  ---> combined_score, verdict
            |
            v (combined_score, verdict)
  Transparency Label       ---> label_text
            |
            v (everything above)
      Audit Log (SQLite write)
            |
            v
    Return API Response: {verdict, confidence, label_text}
```

Appeal Flow

```
      POST /appeal/<id> (reasoning text)
            |
            v
  Lookup Original Submission
            |
            v (reasoning + original record)
    Append Audit Log
            |
            v
Update Status: Under Review
            |
            v
    Return Confirmation: {status: "Under Review"}
```

---

# Planned Technologies

- Flask
- Flask-Limiter
- Groq API (Llama 3.3 70B)
- SQLite
- Python
- python-dotenv

---

# Future Stretch Goal (Optional)

If time permits, implement an ensemble detection system using three signals instead of two by adding readability metrics as a third signal. The three signals will vote or use weighted averaging to improve overall classification reliability.

---

# Transparency Label Design

These are the exact messages displayed to users based on the confidence score.

## High Confidence AI

"This content shows strong indicators of AI generation. Our system is highly confident this was not written entirely by a human."

## High Confidence Human

"This content shows strong indicators of human authorship. Our system found little evidence of AI generation."

## Uncertain

"We could not confidently determine whether this content was AI-generated or human-written. The available evidence is mixed, so this result should be interpreted cautiously."

The purpose of the uncertain label is to avoid making unfair accusations when the evidence is not strong enough. A score near the middle should communicate uncertainty rather than forcing a binary decision.

---

# Appeals Workflow

## Who Can Submit an Appeal?

Only the original creator can submit an appeal for their content. The system verifies the creator using the `creator_id` connected to the original submission.

## Information Provided by Creator

The creator submits:

```json
{
  "creator_id": "creator_123",
  "reason": "I wrote this myself."
}
```

## What Happens When an Appeal Is Submitted?

When the system receives an appeal:

1. The original submission is located using the submission ID.
2. The creator identity is verified using the stored creator ID.
3. The creator's explanation is stored with the original submission.
4. A new audit log entry is created containing the appeal information.
5. The submission status changes from `"Completed"` to `"Under Review"`.

The system does not automatically re-classify the content after an appeal. A human reviewer is expected to examine the original decision and the creator's explanation.

## Human Reviewer View

When a human reviewer opens an appeal, they will see:

- Submission ID
- Original submitted text
- LLM detection score
- Stylometric score
- Combined confidence score
- Original transparency label
- Creator's appeal explanation
- Timestamp
- Current submission status

This information allows the reviewer to understand how the original classification was made and why the creator disagreed with the result.

---

# AI Tool Plan

## Milestone 3: Submission Endpoint + First Signal

### Sections Provided to AI Tool

- Detection Signals
- Architecture Diagram

### AI Request

Generate a Flask application with a `POST /submit` endpoint and implement the first detection signal using the Groq Llama model.

The endpoint should accept submitted text and return an AI confidence score between 0 and 1.

### Verification

- Test clearly human-written text samples.
- Test AI-generated text samples.
- Confirm the LLM signal produces different scores before adding additional components.

---

## Milestone 4: Second Signal + Confidence Scoring

### Sections Provided to AI Tool

- Detection Signals
- Confidence Scoring
- Architecture Diagram

### AI Request

Generate the stylometric analysis function and confidence scoring logic.

The implementation should:
- Calculate stylometric features.
- Combine the LLM and stylometric scores using the defined 60/40 weighting.
- Apply the confidence thresholds defined in this planning document.

### Verification

- Compare AI-generated and human-written examples.
- Confirm confidence scores vary meaningfully between different writing samples.
- Verify uncertain examples fall into the middle confidence range.

---

## Milestone 5: Production Layer

### Sections Provided to AI Tool

- Transparency Label Design
- Appeals Workflow
- Architecture Diagram

### AI Request

Generate the transparency label logic, `POST /appeal/<submission_id>` endpoint, audit logging, and submission status updates.

### Verification

- Confirm all three transparency labels can be produced.
- Submit an appeal and verify the submission status changes to `"Under Review"`.
- Verify the appeal information appears in the audit log.

---