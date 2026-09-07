import os
import requests

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from google import genai

# =========================================================
# CONFIG
# =========================================================

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Change this if you want to use another Gemini model
GEMINI_MODEL = "gemini-3.7-flash"


# =========================================================
# APP
# =========================================================

app = FastAPI()


# =========================================================
# GEMINI
# =========================================================

gemini_client = genai.Client(api_key=GEMINI_API_KEY)


def chat_with_gemini(message: str) -> str:

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL, contents=message
        )

        reply = response.text

        if not reply:
            return "Sorry, I couldn't generate a response."

        return reply.strip()

    except Exception as e:
        print("Gemini error:", e)

        return "Sorry, I'm having trouble answering right now."


# =========================================================
# FACEBOOK SEND MESSAGE
# =========================================================


def send_facebook_message(sender_id: str, message: str):

    url = "https://graph.facebook.com/v26.0/me/messages"

    params = {"access_token": FACEBOOK_PAGE_ACCESS_TOKEN}

    data = {"recipient": {"id": sender_id}, "message": {"text": message}}

    try:

        response = requests.post(url, params=params, json=data, timeout=20)

        print("Facebook response:", response.status_code)
        print(response.text)

        return response.ok

    except Exception as e:

        print("Facebook send error:", e)

        return False


# =========================================================
# WEBHOOK VERIFICATION
# =========================================================


@app.get("/webhook")
async def verify_webhook(request: Request):

    params = request.query_params

    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    print("Webhook verification request")

    if mode == "subscribe" and token == VERIFY_TOKEN:

        print("Webhook verified!")

        return PlainTextResponse(challenge)

    print("Webhook verification failed")

    return PlainTextResponse("Verification failed", status_code=403)


# =========================================================
# FACEBOOK WEBHOOK
# =========================================================


@app.post("/webhook")
async def facebook_webhook(request: Request):

    try:

        data = await request.json()

        print("Facebook webhook received:")
        print(data)

        # Check that this is a Facebook Page event
        if data.get("object") != "page":
            return {"status": "ignored"}

        # Process entries
        for entry in data.get("entry", []):

            for event in entry.get("messaging", []):

                # -------------------------------------------------
                # Get sender
                # -------------------------------------------------

                sender = event.get("sender", {})
                sender_id = sender.get("id")

                if not sender_id:
                    continue

                # -------------------------------------------------
                # Get message
                # -------------------------------------------------

                message = event.get("message", {})

                text = message.get("text")

                # Ignore messages without text
                if not text:
                    continue

                print("User:", text)

                # -------------------------------------------------
                # Ask Gemini
                # -------------------------------------------------

                reply = chat_with_gemini(text)

                print("Gemini:", reply)

                # -------------------------------------------------
                # Send reply to Facebook
                # -------------------------------------------------

                send_facebook_message(sender_id, reply)

        return {"status": "ok"}

    except Exception as e:

        print("Webhook error:", e)

        return {"status": "error", "message": str(e)}


# =========================================================
# HOME
# =========================================================


@app.get("/")
async def home():

    return {"status": "online", "message": "Facebook Gemini chatbot is running!"}
