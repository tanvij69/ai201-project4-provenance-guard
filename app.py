import uuid
from datetime import datetime, timezone

from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

from detection import get_llm_score, get_stylometric_score, compute_confidence
from audit import init_db, log_entry, get_log, get_submission, update_status

load_dotenv()

app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["20 per hour"],
    storage_uri="memory://",
)

init_db()


@app.route("/submit", methods=["POST"])
@limiter.limit("5 per minute")
def submit():
    data = request.get_json(silent=True)
    if not data or "text" not in data or "creator_id" not in data:
        return jsonify({"error": "Request must include 'text' and 'creator_id'"}), 400

    text = data["text"]
    creator_id = data["creator_id"]

    content_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    # Signal 1: Groq LLM
    signal1 = get_llm_score(text)
    llm_score = signal1["llm_score"]

    # Signal 2: Stylometrics
    signal2 = get_stylometric_score(text)
    stylometric_score = signal2["stylometric_score"]

    # Combine into confidence score
    result = compute_confidence(llm_score, stylometric_score)
    confidence = result["combined_score"]
    verdict = result["verdict"]
    label = result["label"]

    log_entry({
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": timestamp,
        "text_snippet": text[:200],
        "attribution": verdict,
        "confidence": confidence,
        "llm_score": llm_score,
        "stylometric_score": stylometric_score,
        "status": "classified",
        "appeal_reason": None,
    })

    return jsonify({
        "content_id": content_id,
        "attribution": verdict,
        "confidence": confidence,
        "label": label,
        "signals": {
            "llm_score": llm_score,
            "stylometric_score": stylometric_score,
        }
    })


@app.route("/appeal", methods=["POST"])
def appeal():
    data = request.get_json(silent=True)
    if not data or "content_id" not in data or "creator_reasoning" not in data:
        return jsonify({"error": "Request must include 'content_id' and 'creator_reasoning'"}), 400

    content_id = data["content_id"]
    creator_reasoning = data["creator_reasoning"]

    existing = get_submission(content_id)
    if not existing:
        return jsonify({"error": "Submission not found"}), 404

    if existing.get("creator_id") and data.get("creator_id"):
        if existing["creator_id"] != data["creator_id"]:
            return jsonify({"error": "creator_id does not match original submission"}), 403

    update_status(content_id, "under_review", appeal_reason=creator_reasoning)

    timestamp = datetime.now(timezone.utc).isoformat()
    log_entry({
        "content_id": content_id,
        "creator_id": existing.get("creator_id"),
        "timestamp": timestamp,
        "text_snippet": existing.get("text_snippet"),
        "attribution": existing.get("attribution"),
        "confidence": existing.get("confidence"),
        "llm_score": existing.get("llm_score"),
        "stylometric_score": existing.get("stylometric_score"),
        "status": "under_review",
        "appeal_reason": creator_reasoning,
    })

    return jsonify({
        "content_id": content_id,
        "status": "under_review",
        "appeal_logged": True,
        "message": "Your appeal was received and is under review."
    })


@app.route("/log", methods=["GET"])
def get_log_route():
    return jsonify({"entries": get_log()})


if __name__ == "__main__":
    app.run(debug=True, port=5000)