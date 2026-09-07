import os
import requests
from fastapi import FastAPI, Request
from openai import OpenAI

app = FastAPI()

# =========================
# SETTINGS
# =========================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY)


# =========================
# OPENAI
# =========================


def chat_with_gpt(message):
    response = client.responses.create(model="gpt-5-mini", input=message)

    return response.output_text


# =========================
# FACEBOOK
# =========================


def send_facebook_message(sender_id, message):

    url = "https://graph.facebook.com/v23.0/me/messages"

    data = {
        "recipient": {"id": sender_id},
        "message": {"text": message},
        "access_token": FACEBOOK_PAGE_ACCESS_TOKEN,
    }

    requests.post(url, json=data)


# =========================
# WEBHOOK VERIFICATION
# =========================


@app.get("/webhook")
async def verify_webhook(request: Request):

    params = request.query_params

    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return int(challenge)

    return "Verification failed"


# =========================
# RECEIVE FACEBOOK MESSAGE
# =========================


@app.post("/webhook")
async def receive_message(request: Request):

    data = await request.json()

    for entry in data.get("entry", []):

        for messaging in entry.get("messaging", []):

            sender_id = messaging["sender"]["id"]

            message = messaging.get("message", {})
            text = message.get("text")

            if text:

                # Send message to OpenAI
                reply = chat_with_gpt(text)

                # Send AI response back to Messenger
                send_facebook_message(sender_id, reply)

    return {"status": "ok"}
