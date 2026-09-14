import os
import time
import requests

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from google import genai
from google.genai import types

# =========================================================
# CONFIG
# =========================================================

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Use a Gemini model available to your API key
GEMINI_MODEL = "gemini-3.5-flash-lite"

# Number of times Gemini will be retried after temporary errors
GEMINI_MAX_RETRIES = 3


# =========================================================
# ENVIRONMENT CHECK
# =========================================================

if not VERIFY_TOKEN:
    print("WARNING: VERIFY_TOKEN is missing")

if not FACEBOOK_PAGE_ACCESS_TOKEN:
    print("WARNING: FACEBOOK_PAGE_ACCESS_TOKEN is missing")

if not GEMINI_API_KEY:
    print("WARNING: GEMINI_API_KEY is missing")


# =========================================================
# APP
# =========================================================

app = FastAPI()


# =========================================================
# GEMINI CLIENT
# =========================================================

gemini_client = genai.Client(api_key=GEMINI_API_KEY)


# =========================================================
# DUPLICATE MESSAGE PROTECTION
# =========================================================

# Stores Facebook message IDs that have already been processed.
#
# This is fine for testing.
# For production, use Redis or a database.
PROCESSED_MESSAGES = set()


# =========================================================
# GEMINI TEXT CHAT
# =========================================================


def chat_with_gemini(message: str) -> str:

    for attempt in range(1, GEMINI_MAX_RETRIES + 1):

        try:

            print(f"Gemini text request " f"(attempt {attempt}/{GEMINI_MAX_RETRIES})")

            response = gemini_client.models.generate_content(
                model=GEMINI_MODEL, contents=message
            )

            if response.text:
                return response.text.strip()

            return "Sorry, I couldn't generate a response."

        except Exception as e:

            print("Gemini text error:", repr(e))

            # Retry if this is not the final attempt
            if attempt < GEMINI_MAX_RETRIES:

                wait_time = attempt * 2

                print(f"Retrying Gemini in {wait_time} seconds...")

                time.sleep(wait_time)

            else:

                return "Sorry, I'm having trouble " "answering right now."

    return "Sorry, I couldn't generate a response."


# =========================================================
# GEMINI IMAGE ANALYSIS
# =========================================================


def analyze_image(image_url: str, prompt: str) -> str:

    try:

        print("===================================")
        print("IMAGE ANALYSIS")
        print("===================================")

        print("Downloading image...")
        print("Image URL:", image_url)

        # -------------------------------------------------
        # Download image from Facebook
        # -------------------------------------------------

        image_response = requests.get(
            image_url, params={"access_token": FACEBOOK_PAGE_ACCESS_TOKEN}, timeout=20
        )

        print("Facebook image status:", image_response.status_code)

        image_response.raise_for_status()

        image_bytes = image_response.content

        print("Image downloaded:", len(image_bytes), "bytes")

        # -------------------------------------------------
        # Detect MIME type
        # -------------------------------------------------

        mime_type = image_response.headers.get("Content-Type", "image/jpeg")

        # Remove anything after semicolon
        #
        # Example:
        # image/jpeg; charset=utf-8
        #
        # becomes:
        # image/jpeg

        mime_type = mime_type.split(";")[0].strip()

        # Make sure it is actually an image
        if not mime_type.startswith("image/"):

            print("Invalid MIME type:", mime_type)

            mime_type = "image/jpeg"

        print("MIME type:", mime_type)

        # -------------------------------------------------
        # Create Gemini image part
        # -------------------------------------------------

        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

        # -------------------------------------------------
        # Send image + prompt to Gemini
        # -------------------------------------------------

        for attempt in range(1, GEMINI_MAX_RETRIES + 1):

            try:

                print(
                    f"Gemini image request "
                    f"(attempt {attempt}/"
                    f"{GEMINI_MAX_RETRIES})"
                )

                response = gemini_client.models.generate_content(
                    model=GEMINI_MODEL, contents=[image_part, prompt]
                )

                if response.text:

                    return response.text.strip()

                return "I couldn't understand " "the image."

            except Exception as e:

                print("Gemini image error:", repr(e))

                # Retry temporary errors
                if attempt < GEMINI_MAX_RETRIES:

                    wait_time = attempt * 2

                    print(f"Retrying Gemini in " f"{wait_time} seconds...")

                    time.sleep(wait_time)

                else:

                    return "Sorry, I'm having trouble " "analyzing the image right now."

    except requests.exceptions.RequestException as e:

        print("Facebook image download error:", repr(e))

        return "Sorry, I couldn't access " "the image."

    except Exception as e:

        print("Image processing error:", repr(e))

        return "Sorry, I'm having trouble " "analyzing the image right now."


# =========================================================
# FACEBOOK SEND MESSAGE
# =========================================================


def send_facebook_message(sender_id: str, message: str):

    url = "https://graph.facebook.com/" "v26.0/me/messages"

    params = {"access_token": FACEBOOK_PAGE_ACCESS_TOKEN}

    data = {"recipient": {"id": sender_id}, "message": {"text": message}}

    try:

        response = requests.post(url, params=params, json=data, timeout=20)

        print("Facebook send status:", response.status_code)

        print("Facebook response:", response.text)

        return response.ok

    except Exception as e:

        print("Facebook send error:", repr(e))

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

        print("===================================")
        print("FACEBOOK WEBHOOK")
        print(data)
        print("===================================")

        # -------------------------------------------------
        # Check Facebook Page event
        # -------------------------------------------------

        if data.get("object") != "page":

            return {"status": "ignored"}

        # -------------------------------------------------
        # Loop through entries
        # -------------------------------------------------

        for entry in data.get("entry", []):

            # -------------------------------------------------
            # Loop through messaging events
            # -------------------------------------------------

            for event in entry.get("messaging", []):

                # =================================================
                # SENDER
                # =================================================

                sender = event.get("sender", {})

                sender_id = sender.get("id")

                if not sender_id:

                    continue

                # =================================================
                # MESSAGE
                # =================================================

                message = event.get("message", {})

                # -------------------------------------------------
                # Ignore echo messages
                # -------------------------------------------------

                if message.get("is_echo"):

                    print("Echo message ignored")

                    continue

                # -------------------------------------------------
                # MESSAGE ID
                # -------------------------------------------------

                message_id = message.get("mid")

                if not message_id:

                    print("Message has no ID")

                    continue

                # -------------------------------------------------
                # Prevent duplicate messages
                # -------------------------------------------------

                if message_id in PROCESSED_MESSAGES:

                    print("Duplicate message ignored:", message_id)

                    continue

                PROCESSED_MESSAGES.add(message_id)

                # =================================================
                # TEXT
                # =================================================

                text = message.get("text")

                # =================================================
                # ATTACHMENTS
                # =================================================

                attachments = message.get("attachments", [])

                print("Message ID:", message_id)

                print("Text:", text)

                print("Attachments:", attachments)

                # =================================================
                # IMAGE MESSAGE
                # =================================================

                image_found = False

                for attachment in attachments:

                    attachment_type = attachment.get("type")

                    # -------------------------------------------------
                    # Only process images
                    # -------------------------------------------------

                    if attachment_type != "image":

                        continue

                    image_found = True

                    payload = attachment.get("payload", {})

                    image_url = payload.get("url")

                    # -------------------------------------------------
                    # Image URL missing
                    # -------------------------------------------------

                    if not image_url:

                        send_facebook_message(
                            sender_id,
                            "I received the image, " "but I couldn't access it.",
                        )

                        continue

                    # -------------------------------------------------
                    # User's instruction
                    # -------------------------------------------------

                    if text:

                        prompt = text

                    else:

                        prompt = (
                            "Analyze this image and "
                            "describe what you see "
                            "in detail."
                        )

                    print("Image prompt:", prompt)

                    # -------------------------------------------------
                    # Ask Gemini
                    # -------------------------------------------------

                    reply = analyze_image(image_url, prompt)

                    print("Gemini image reply:", reply)

                    # -------------------------------------------------
                    # Send response
                    # -------------------------------------------------

                    send_facebook_message(sender_id, reply)

                # =================================================
                # TEXT-ONLY MESSAGE
                # =================================================

                if text and not image_found:

                    print("User text:", text)

                    reply = chat_with_gemini(text)

                    print("Gemini reply:", reply)

                    send_facebook_message(sender_id, reply)

                # =================================================
                # UNSUPPORTED ATTACHMENT
                # =================================================

                if attachments and not image_found and not text:

                    send_facebook_message(
                        sender_id, "I currently support " "text and image messages."
                    )

        return {"status": "ok"}

    except Exception as e:

        print("===================================")
        print("WEBHOOK ERROR")
        print(repr(e))
        print("===================================")

        return {"status": "error", "message": str(e)}


# =========================================================
# HOME
# =========================================================


@app.get("/")
async def home():

    return {"status": "online", "message": "Facebook Gemini chatbot is running!"}
