import os
from uuid import UUID

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from postgrest import APIError
from supabase import Client, create_client

load_dotenv()

app = Flask(__name__)

supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_PUBLISHABLE_KEY")
supabase: Client | None = (
    create_client(supabase_url, supabase_key) if supabase_url and supabase_key else None
)


@app.after_request
def enable_cors(response):
    """Allow browser clients from any origin to call this API."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


@app.route("/", methods=["GET"])
def index():
    return jsonify({"message": "Events API", "endpoints": [
        "/api/events",
        "/api/events/<id>",
        "/api/registrations",
        "/api/me/registrations?user_id=<uuid>",
        "/api/events/<id>/registrations",
    ]})


def database():
    if supabase is None:
        return None, (jsonify({"error": "Supabase is not configured"}), 500)
    return supabase, None


def valid_uuid(value):
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


def api_error(error):
    return jsonify({"error": getattr(error, "message", str(error))}), 500


@app.route("/api/events", methods=["GET"])
def list_events():
    client, error = database()
    if error:
        return error
    try:
        result = client.table("events").select("id, organizer_id, title, capacity, status").execute()
        return jsonify(result.data)
    except APIError as exc:
        return api_error(exc)


@app.route("/api/events/<event_id>", methods=["GET"])
def get_event(event_id):
    event_id = valid_uuid(event_id)
    if not event_id:
        return jsonify({"error": "event id must be a UUID"}), 400
    client, error = database()
    if error:
        return error
    try:
        result = client.table("events").select(
            "id, organizer_id, title, capacity, status"
        ).eq("id", event_id).maybe_single().execute()
        if result.data is None:
            return jsonify({"error": "Event not found"}), 404
        return jsonify(result.data)
    except APIError as exc:
        return api_error(exc)


@app.route("/api/registrations", methods=["POST"])
def create_registration():
    payload = request.get_json(silent=True) or {}
    user_id = valid_uuid(payload.get("user_id"))
    event_id = valid_uuid(payload.get("event_id"))
    if not user_id or not event_id:
        return jsonify({"error": "user_id and event_id must be valid UUIDs"}), 400

    client, error = database()
    if error:
        return error
    try:
        event_result = client.table("events").select(
            "id, capacity, status"
        ).eq("id", event_id).maybe_single().execute()
        event = event_result.data
        if event is None:
            return jsonify({"error": "Event not found"}), 404

        duplicate = client.table("registrations").select("id").eq(
            "user_id", user_id
        ).eq("event_id", event_id).limit(1).execute()
        if duplicate.data:
            return jsonify({"error": "User is already registered for this event"}), 409

        registrations = client.table("registrations").select(
            "id", count="exact", head=True
        ).eq("event_id", event_id).execute()
        capacity = event.get("capacity")
        if capacity is not None and (registrations.count or 0) >= capacity:
            return jsonify({"error": "Event is at capacity"}), 409

        created = client.table("registrations").insert({
            "user_id": user_id,
            "event_id": event_id,
        }).execute()
        return jsonify(created.data[0]), 201
    except APIError as exc:
        # A unique constraint can catch duplicate requests arriving together.
        if getattr(exc, "code", None) == "23505":
            return jsonify({"error": "User is already registered for this event"}), 409
        return api_error(exc)


@app.route("/api/me/registrations", methods=["GET"])
def my_registrations():
    user_id = valid_uuid(request.args.get("user_id"))
    if not user_id:
        return jsonify({"error": "user_id query parameter must be a UUID"}), 400
    client, error = database()
    if error:
        return error
    try:
        result = client.table("registrations").select(
            "id, user_id, event_id, created_at, events(id, title, capacity, status)"
        ).eq("user_id", user_id).execute()
        return jsonify(result.data)
    except APIError as exc:
        return api_error(exc)


@app.route("/api/events/<event_id>/registrations", methods=["GET"])
def event_registrations(event_id):
    event_id = valid_uuid(event_id)
    if not event_id:
        return jsonify({"error": "event id must be a UUID"}), 400
    client, error = database()
    if error:
        return error
    try:
        event_result = client.table("events").select("id").eq(
            "id", event_id
        ).maybe_single().execute()
        if event_result.data is None:
            return jsonify({"error": "Event not found"}), 404
        result = client.table("registrations").select(
            "id, user_id, event_id, created_at, users(id, email, role)"
        ).eq("event_id", event_id).execute()
        return jsonify(result.data)
    except APIError as exc:
        return api_error(exc)


if __name__ == "__main__":
    app.run(debug=True)
