import os
import secrets
from datetime import datetime, timezone, timedelta

import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
BOT_USERNAME = os.environ["BOT_USERNAME"].lstrip("@")
OWNER_CHAT_ID = os.environ["OWNER_CHAT_ID"]

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}


def telegram(method, data):
    response = requests.post(
        f"{TELEGRAM_API}/{method}",
        json=data,
        timeout=15
    )
    return response.json()


def send_message(chat_id, text):
    return telegram(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True
        }
    )


def create_request(channel_id, message_id):
    token = secrets.token_urlsafe(18)

    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=2)

    data = {
        "token": token,
        "channel_id": str(channel_id),
        "message_id": message_id,
        "created_at": now.isoformat(),
        "expires_at": expires.isoformat()
    }

    response = requests.post(
        f"{SUPABASE_URL}/rest/v1/requests",
        headers={
            **HEADERS,
            "Prefer": "return=minimal"
        },
        json=data,
        timeout=15
    )

    response.raise_for_status()

    return token


def get_request(token):
    response = requests.get(
        f"{SUPABASE_URL}/rest/v1/requests",
        headers=HEADERS,
        params={
            "token": f"eq.{token}",
            "select": "*",
            "limit": "1"
        },
        timeout=15
    )

    response.raise_for_status()

    rows = response.json()

    if not rows:
        return None

    return rows[0]


def delete_request(token):
    requests.delete(
        f"{SUPABASE_URL}/rest/v1/requests",
        headers=HEADERS,
        params={
            "token": f"eq.{token}"
        },
        timeout=15
    )


def cleanup_expired():
    try:
        now = datetime.now(timezone.utc).isoformat()

        requests.delete(
            f"{SUPABASE_URL}/rest/v1/requests",
            headers=HEADERS,
            params={
                "expires_at": f"lt.{now}"
            },
            timeout=10
        )
    except Exception:
        pass


@app.route("/", methods=["GET"])
def home():
    return "Telegram Link Bot is running."


@app.route("/api/webhook", methods=["POST"])
def webhook():

    cleanup_expired()

    update = request.get_json(silent=True)

    if not update:
        return jsonify({"ok": True})

    # ==========================================
    # 1. MAIN CHANNEL POST
    # ==========================================

    channel_post = update.get("channel_post")

    if channel_post:

        channel_id = channel_post["chat"]["id"]
        message_id = channel_post["message_id"]

        try:
            token = create_request(
                channel_id,
                message_id
            )

            link = f"https://t.me/{BOT_USERNAME}?start={token}"

            send_message(
                OWNER_CHAT_ID,
                "🔗 New Request Link\n\n"
                f"{link}\n\n"
                "⏳ Expires in 2 minutes."
            )

        except Exception as e:
            print("Channel error:", e)

        return jsonify({"ok": True})

    # ==========================================
    # 2. USER STARTS BOT WITH TOKEN
    # ==========================================

    message = update.get("message")

    if not message:
        return jsonify({"ok": True})

    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    if text.startswith("/start"):

        parts = text.split(maxsplit=1)

        if len(parts) == 1:
            send_message(
                chat_id,
                "👋 Send me a valid request link."
            )
            return jsonify({"ok": True})

        token = parts[1].strip()

        record = get_request(token)

        if not record:
            send_message(
                chat_id,
                "❌ This link is invalid or has expired."
            )
            return jsonify({"ok": True})

        # Check expiration
        expires_at = datetime.fromisoformat(
            record["expires_at"].replace("Z", "+00:00")
        )

        now = datetime.now(timezone.utc)

        if now >= expires_at:

            delete_request(token)

            send_message(
                chat_id,
                "⏳ This link has expired.\n\n"
                "Please request a new link."
            )

            return jsonify({"ok": True})

        # ==========================================
        # SEND ORIGINAL CHANNEL POST
        # ==========================================

        result = telegram(
            "copyMessage",
            {
                "chat_id": chat_id,
                "from_chat_id": int(record["channel_id"]),
                "message_id": int(record["message_id"])
            }
        )

        if not result.get("ok"):

            send_message(
                chat_id,
                "❌ I couldn't retrieve this post."
            )

            return jsonify({"ok": True})

        # Delete the token immediately.
        # This makes the request link one-time-use.
        delete_request(token)

        return jsonify({"ok": True})

    return jsonify({"ok": True})


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok"
    })
