import os
import time
import base64
import uuid
import threading
import requests

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, FileResponse
from google import genai

# =========================================================
# CONFIG
# =========================================================

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


# =========================================================
# GEMINI MODELS
# =========================================================

# Text model
TEXT_MODEL = "gemini-3.5-flash-lite"

# Image editing model
IMAGE_MODEL = "gemini-3.1-flash-image"


# =========================================================
# SETTINGS
# =========================================================

GEMINI_MAX_RETRIES = 3

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")


OUTPUT_FOLDER = "generated_images"

IMAGE_DELETE_AFTER_SECONDS = 600


# =========================================================
# ENVIRONMENT CHECK
# =========================================================

if not VERIFY_TOKEN:
    print("WARNING: VERIFY_TOKEN is missing")

if not FACEBOOK_PAGE_ACCESS_TOKEN:
    print("WARNING: FACEBOOK_PAGE_ACCESS_TOKEN is missing")

if not GEMINI_API_KEY:
    print("WARNING: GEMINI_API_KEY is missing")

if not PUBLIC_BASE_URL:
    print("WARNING: PUBLIC_BASE_URL is missing")
    print("Example: https://your-app.onrender.com")


# =========================================================
# CREATE OUTPUT FOLDER
# =========================================================

os.makedirs(OUTPUT_FOLDER, exist_ok=True)


# =========================================================
# FASTAPI APP
# =========================================================

app = FastAPI()


# =========================================================
# GEMINI CLIENT
# =========================================================

gemini_client = genai.Client(api_key=GEMINI_API_KEY)


# =========================================================
# DUPLICATE MESSAGE PROTECTION
# =========================================================

# Fine for testing.
#
# For production:
# use Redis or a database.

PROCESSED_MESSAGES = set()


# =========================================================
# CHECK GEMINI COMMAND
# =========================================================


def is_gemini_command(text: str) -> bool:

    if not text:
        return False

    return text.lower().startswith("gemini")


# =========================================================
# EXTRACT GEMINI PROMPT
# =========================================================


def extract_gemini_prompt(text: str) -> str:

    if not text:
        return ""

    # Remove "gemini"
    prompt = text[6:].strip()

    # Remove optional quotation marks
    if len(prompt) >= 2 and prompt[0] == '"' and prompt[-1] == '"':
        prompt = prompt[1:-1].strip()

    return prompt


# =========================================================
# DELETE IMAGE LATER
# =========================================================


def delete_image_later(file_path: str):

    def delete_file():

        try:

            if os.path.exists(file_path):

                os.remove(file_path)

                print("Deleted old generated image:", file_path)

        except Exception as e:

            print("Image cleanup error:", repr(e))

    timer = threading.Timer(IMAGE_DELETE_AFTER_SECONDS, delete_file)

    timer.daemon = True

    timer.start()


# =========================================================
# GEMINI TEXT CHAT
# =========================================================


def chat_with_gemini(message: str) -> str:

    for attempt in range(1, GEMINI_MAX_RETRIES + 1):

        try:

            print(
                f"Gemini text request " f"(attempt {attempt}/" f"{GEMINI_MAX_RETRIES})"
            )

            response = gemini_client.models.generate_content(
                model=TEXT_MODEL, contents=message
            )

            if response.text:

                return response.text.strip()

            return "Sorry, I couldn't " "generate a response."

        except Exception as e:

            print("Gemini text error:", repr(e))

            if attempt < GEMINI_MAX_RETRIES:

                wait_time = attempt * 2

                print(f"Retrying Gemini in " f"{wait_time} seconds...")

                time.sleep(wait_time)

            else:

                return "Sorry, I'm having " "trouble answering " "right now."

    return "Sorry, I couldn't " "generate a response."


# =========================================================
# DOWNLOAD IMAGE FROM FACEBOOK
# =========================================================


def download_facebook_image(image_url: str):

    try:

        print("Downloading Facebook image...")

        response = requests.get(
            image_url, params={"access_token": FACEBOOK_PAGE_ACCESS_TOKEN}, timeout=30
        )

        print("Facebook image download status:", response.status_code)

        response.raise_for_status()

        image_bytes = response.content

        mime_type = response.headers.get("Content-Type", "image/jpeg")

        # Remove charset
        #
        # image/jpeg; charset=utf-8
        #
        # becomes:
        #
        # image/jpeg

        mime_type = mime_type.split(";")[0].strip()

        if not mime_type.startswith("image/"):

            print("Invalid image MIME type:", mime_type)

            mime_type = "image/jpeg"

        print("Downloaded image bytes:", len(image_bytes))

        print("Image MIME type:", mime_type)

        return image_bytes, mime_type

    except Exception as e:

        print("Facebook image download error:", repr(e))

        return None, None


# =========================================================
# GEMINI IMAGE EDITING
# =========================================================


def edit_image_with_gemini(image_bytes: bytes, mime_type: str, prompt: str):

    for attempt in range(1, GEMINI_MAX_RETRIES + 1):

        try:

            print("===================================")

            print("GEMINI IMAGE EDITING")

            print("===================================")

            print(f"Attempt {attempt}/" f"{GEMINI_MAX_RETRIES}")

            print("User instruction:", prompt)

            # Convert image to Base64
            image_base64 = base64.b64encode(image_bytes).decode("utf-8")

            # Send image + instruction
            # to Gemini

            interaction = gemini_client.interactions.create(
                model=IMAGE_MODEL,
                input=[
                    {"type": "text", "text": prompt},
                    {"type": "image", "data": image_base64, "mime_type": mime_type},
                ],
                response_format={"type": "image", "mime_type": "image/jpeg"},
            )

            # Get generated image
            generated_image = interaction.output_image

            if generated_image:

                print("Gemini generated " "edited image!")

                generated_bytes = base64.b64decode(generated_image.data)

                # Unique filename
                filename = f"{uuid.uuid4().hex}.png"

                file_path = os.path.join(OUTPUT_FOLDER, filename)

                # Save image
                with open(file_path, "wb") as file:

                    file.write(generated_bytes)

                print("Edited image saved:", file_path)

                # Delete later
                delete_image_later(file_path)

                # Public URL
                if not PUBLIC_BASE_URL:

                    print("PUBLIC_BASE_URL " "is missing")

                    return None

                public_url = f"{PUBLIC_BASE_URL}" f"/generated-image/" f"{filename}"

                print("Public edited image URL:", public_url)

                return public_url

            print("Gemini did not " "return an image.")

            return None

        except Exception as e:

            print("Gemini image editing error:", repr(e))

            if attempt < GEMINI_MAX_RETRIES:

                wait_time = attempt * 2

                print(f"Retrying in " f"{wait_time} seconds...")

                time.sleep(wait_time)

            else:

                return None

    return None


# =========================================================
# SERVE GENERATED IMAGE
# =========================================================


@app.get("/generated-image/{filename}")
async def get_generated_image(filename: str):

    # Security:
    # Prevent paths such as:
    #
    # ../../something

    safe_filename = os.path.basename(filename)

    file_path = os.path.join(OUTPUT_FOLDER, safe_filename)

    if not os.path.exists(file_path):

        return PlainTextResponse("Image not found", status_code=404)

    return FileResponse(file_path, media_type="image/png")


# =========================================================
# FACEBOOK SEND TEXT MESSAGE
# =========================================================


def send_facebook_message(sender_id: str, message: str):

    url = "https://graph.facebook.com/" "v26.0/me/messages"

    params = {"access_token": FACEBOOK_PAGE_ACCESS_TOKEN}

    data = {"recipient": {"id": sender_id}, "message": {"text": message}}

    try:

        response = requests.post(url, params=params, json=data, timeout=30)

        print("Facebook text send status:", response.status_code)

        print("Facebook response:", response.text)

        return response.ok

    except Exception as e:

        print("Facebook text send error:", repr(e))

        return False


# =========================================================
# FACEBOOK SEND IMAGE
# =========================================================


def send_facebook_image(sender_id: str, image_url: str):

    url = "https://graph.facebook.com/" "v26.0/me/messages"

    params = {"access_token": FACEBOOK_PAGE_ACCESS_TOKEN}

    data = {
        "recipient": {"id": sender_id},
        "message": {
            "attachment": {
                "type": "image",
                "payload": {"url": image_url, "is_reusable": False},
            }
        },
    }

    try:

        print("Sending edited image " "to Facebook...")

        print("Image URL:", image_url)

        response = requests.post(url, params=params, json=data, timeout=30)

        print("Facebook image send status:", response.status_code)

        print("Facebook response:", response.text)

        return response.ok

    except Exception as e:

        print("Facebook image send error:", repr(e))

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

        # Only Facebook Page events
        if data.get("object") != "page":

            return {"status": "ignored"}

        # =====================================================
        # LOOP THROUGH ENTRIES
        # =====================================================

        for entry in data.get("entry", []):

            # Loop through messages
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

                # Ignore Page echo
                if message.get("is_echo"):

                    print("Echo message ignored")

                    continue

                # =================================================
                # MESSAGE ID
                # =================================================

                message_id = message.get("mid")

                if not message_id:

                    print("Message has no ID")

                    continue

                # =================================================
                # DUPLICATE PROTECTION
                # =================================================

                if message_id in (PROCESSED_MESSAGES):

                    print("Duplicate message ignored:", message_id)

                    continue

                PROCESSED_MESSAGES.add(message_id)

                print("Message ID:", message_id)

                # =================================================
                # TEXT
                # =================================================

                text = message.get("text")

                print("Text:", text)

                # =================================================
                # ATTACHMENTS
                # =================================================

                attachments = message.get("attachments", [])

                print("Attachments:", attachments)

                # =================================================
                # CHECK GEMINI COMMAND
                # =================================================

                gemini_command = is_gemini_command(text)

                # =================================================
                # IMAGE MESSAGE
                # =================================================

                image_found = False

                for attachment in attachments:

                    attachment_type = attachment.get("type")

                    # Only process images
                    if attachment_type != "image":

                        continue

                    image_found = True

                    payload = attachment.get("payload", {})

                    image_url = payload.get("url")

                    # ---------------------------------------------
                    # IMAGE URL MISSING
                    # ---------------------------------------------

                    if not image_url:

                        send_facebook_message(
                            sender_id,
                            ("I received the image, " "but I couldn't access it."),
                        )

                        continue

                    # ---------------------------------------------
                    # CHECK GEMINI COMMAND
                    # ---------------------------------------------

                    if not gemini_command:

                        # Image received without
                        # the "gemini" command.

                        send_facebook_message(
                            sender_id,
                            (
                                "I received your image.\n\n"
                                "To use AI with this image, "
                                "send a message like:\n\n"
                                'gemini "describe this image"\n\n'
                                "or\n\n"
                                'gemini "remove the background"'
                            ),
                        )

                        continue

                    # ---------------------------------------------
                    # GET USER INSTRUCTION
                    # ---------------------------------------------

                    prompt = extract_gemini_prompt(text)

                    # ---------------------------------------------
                    # EMPTY GEMINI COMMAND
                    # ---------------------------------------------

                    if not prompt:

                        send_facebook_message(
                            sender_id,
                            (
                                "Please provide an "
                                "instruction after "
                                '"gemini".\n\n'
                                "Example:\n"
                                'gemini "describe this image"'
                            ),
                        )

                        continue

                    print("Image Gemini instruction:", prompt)

                    # ---------------------------------------------
                    # DOWNLOAD IMAGE
                    # ---------------------------------------------

                    image_bytes, mime_type = download_facebook_image(image_url)

                    if not image_bytes:

                        send_facebook_message(
                            sender_id, ("Sorry, I couldn't " "download your image.")
                        )

                        continue

                    # ---------------------------------------------
                    # TELL USER
                    # ---------------------------------------------

                    send_facebook_message(
                        sender_id, ("🖼️ Processing your image. " "Please wait...")
                    )

                    # ---------------------------------------------
                    # EDIT IMAGE
                    # ---------------------------------------------

                    edited_image_url = edit_image_with_gemini(
                        image_bytes, mime_type, prompt
                    )

                    # ---------------------------------------------
                    # SEND RESULT
                    # ---------------------------------------------

                    if edited_image_url:

                        success = send_facebook_image(sender_id, edited_image_url)

                        if success:

                            print("Edited image " "sent successfully!")

                        else:

                            send_facebook_message(
                                sender_id,
                                (
                                    "I edited the image, "
                                    "but I had trouble "
                                    "sending it back."
                                ),
                            )

                    else:

                        send_facebook_message(
                            sender_id,
                            ("Sorry, I couldn't " "process that image " "right now."),
                        )

                # =================================================
                # TEXT-ONLY MESSAGE
                # =================================================

                if text and not image_found:

                    print("User text:", text)

                    # =================================================
                    # GEMINI COMMAND
                    # =================================================

                    if gemini_command:

                        ai_prompt = extract_gemini_prompt(text)

                        # -----------------------------------------
                        # EMPTY COMMAND
                        # -----------------------------------------

                        if not ai_prompt:

                            send_facebook_message(
                                sender_id,
                                (
                                    "Please provide a "
                                    "message after "
                                    '"gemini".\n\n'
                                    "Example:\n"
                                    'gemini "Hello AI."'
                                ),
                            )

                        else:

                            print("Gemini command detected")

                            print("Gemini prompt:", ai_prompt)

                            # -------------------------------------
                            # SEND TO GEMINI
                            # -------------------------------------

                            reply = chat_with_gemini(ai_prompt)

                            print("Gemini reply:", reply)

                            # -------------------------------------
                            # SEND GEMINI RESPONSE
                            # -------------------------------------

                            send_facebook_message(sender_id, reply)

                    # =================================================
                    # NORMAL CONVERSATION
                    # =================================================

                    else:

                        print("Normal conversation " "message")

                        # IMPORTANT:
                        #
                        # This message is NOT sent to Gemini.
                        #
                        # Put your own normal chatbot
                        # behavior here.

                        send_facebook_message(sender_id, ("You said: " f"{text}"))

                # =================================================
                # UNSUPPORTED ATTACHMENT
                # =================================================

                if attachments and not image_found and not text:

                    send_facebook_message(
                        sender_id, ("I currently support " "text and image messages.")
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

    return {
        "status": "online",
        "message": (
            "Facebook Gemini AI chatbot "
            "with command-based AI "
            "and image editing is running!"
        ),
    }
