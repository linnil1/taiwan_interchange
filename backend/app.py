from flask import Flask, Response, jsonify
from flask_cors import CORS

from persistence import load_interchanges

app = Flask(__name__)
CORS(app)


@app.route("/api/interchanges", methods=["GET"])
def get_interchanges() -> Response:
    """Get interchanges data"""
    interchanges = load_interchanges()
    return jsonify([i.model_dump() for i in interchanges])


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True, port=5000)
