# webapp/routes.py

from flask import Blueprint, jsonify

main_bp = Blueprint("main", __name__)

@main_bp.route("/")
def index():
    return jsonify({"status": "ok", "message": "Welcome to your web service!"})
