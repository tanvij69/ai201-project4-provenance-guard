import uuid
from datetime import datetime, timezone

from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

from detection import get_llm_score
from audit import init_db, log_entry, get_log

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

    # --- Signal 1: Groq LLM classification ---
    signal1_result = get_llm_score(text)
    llm_score = signal1_result["llm_score"]

    # Placeholder confidence/label until Milestone 4 adds signal 2 + real scoring
    confidence = llm_score
    if confidence >= 0.6:
        attribution = "likely_ai"
        label = "Placeholder: leaning AI-generated (signal 2 not yet implemented)"
    elif confidence <= 0.4:
        attribution = "likely_human"
        label = "Placeholder: leaning human-written (signal 2 not yet implemented)"
    else:
        attribution = "uncertain"
        label = "Placeholder: uncertain (signal 2 not yet implemented)"

    log_entry({
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": timestamp,
        "text_snippet": text[:200],
        "attribution": attribution,
        "confidence": confidence,
        "llm_score": llm_score,
        "stylometric_score": None,
        "status": "classified",
        "appeal_reason": None,
    })

    return jsonify({
        "content_id": content_id,
        "attribution": attribution,
        "confidence": confidence,
        "label": label,
        "signals": {
            "llm_score": llm_score
        }
    })


@app.route("/log", methods=["GET"])
def get_log_route():
    return jsonify({"entries": get_log()})


if __name__ == "__main__":
    app.run(debug=True, port=5000)