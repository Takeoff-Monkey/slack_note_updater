import os
import re
import io
import ssl
import certifi
import urllib.request
import base64
import requests
import json
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build, build as gdoc_build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.service_account import Credentials

# Added for Slack OAuth URL generation (if needed in future)
from slack_sdk.oauth import AuthorizeUrlGenerator



ssl_context = ssl.create_default_context(cafile=certifi.where())
urllib.request.urlopen("https://slack.com", context=ssl_context)

load_dotenv()

creds_json = os.getenv("GOOGLE_CREDS_JSON")
if not creds_json:
    raise Exception("GOOGLE_CREDS_JSON not found in environment variables!")
creds_dict = json.loads(creds_json)
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",  # <-- This is the main one for gspread
    "https://www.googleapis.com/auth/drive"          # <-- Optional: if you need file access
]
google_creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)

GAS_WEBHOOK_URL = os.getenv("GAS_WEBHOOK_URL")

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
drive_service = build("drive", "v3", credentials=google_creds)

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_WORKSHEET_NAME = os.getenv("GOOGLE_WORKSHEET_NAME")

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
client = gspread.authorize(google_creds)
sheet = client.open_by_key(GOOGLE_SHEET_ID).worksheet(GOOGLE_WORKSHEET_NAME)

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]

slack_client = WebClient(token=SLACK_BOT_TOKEN)

app = App(token=SLACK_BOT_TOKEN)
active_threads = {}

JOB_PATTERN = re.compile(r"#(\d{5})!")


def post_image_to_gas(doc_id, image_url):
    try:
        payload = {
            "docId": doc_id,
            "imageUrl": image_url
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}"
        }
        response = requests.post(
            GAS_WEBHOOK_URL,
            json=payload,
            headers=headers)
        print(f"📤 Posting image to GAS: {image_url} — status {response.status_code}")
        return response.status_code == 200
    except Exception as e:
        print(f"Failed to post image to GAS: {e}")
        return False


def find_doc_by_job_number(job_number: str):
    query = f"name contains '{job_number} |' and mimeType='application/vnd.google-apps.document'"
    results = drive_service.files().list(
        q=query,
        spaces='drive',
        fields='files(id, name)',
        pageSize=1
    ).execute()
    files = results.get("files", [])
    return files[0] if files else None


def fetch_thread(channel, thread_ts):
    try:
        response = slack_client.conversations_replies(channel=channel, ts=thread_ts)
        return response["messages"]
    except SlackApiError as e:
        print(f"error fetching thread: {e}!")
        return []


def format_thread_messages(messages):
    formatted = []
    for i, msg in enumerate(messages):
        if msg.get("subtype") == "bot_message" or msg.get("bot_id"):
            continue

        user_id = msg.get("user", "Unknown")
        try:
            user_info = slack_client.users_info(user=user_id)
            user = user_info["user"]["profile"]["display_name"] or user_info["user"]["real_name"]
        except SlackApiError:
            user = user_id

        ts = float(msg.get("ts", 0))
        text = msg.get("text", "").strip()
        time = datetime.fromtimestamp(ts).strftime("%H:%M")
        date = datetime.fromtimestamp(ts).strftime("%m-%d-%y")

        if i == 0:
            formatted.append(f"{user} @ {time} {date}: {text}")
        else:
            formatted.append(f"     {user} @ {time}: {text}")
    return "\n".join(formatted)


# Helper functions for image upload
def get_image_as_base64(url, headers):
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return base64.b64encode(response.content).decode("utf-8")
    return None

def insert_image_inline(docs_service, doc_id, base64_image):
    doc = docs_service.documents().get(documentId=doc_id).execute()
    end_index = doc.get("body").get("content")[-1]["endIndex"] - 1
    requests_ = [
        {
            "insertInlineImage": {
                "location": {"index": end_index},
                "uri": f"data:image/png;base64,{base64_image}",
                "objectSize": {
                    "height": {"magnitude": 200, "unit": "PT"},
                    "width": {"magnitude": 200, "unit": "PT"}
                }
            }
        }
    ]
    docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": requests_}).execute()


def append_to_google_doc(docs_service, doc_id, content):
    # requests = [
    #     {
    #         "insertText": {
    #             "location": {"index": 1},
    #             "text": content + "\n\n"
    #         }
    #     }
    # ]
    # docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
    doc = docs_service.documents().get(documentId=doc_id).execute()
    end_index = doc.get("body").get("content")[-1]["endIndex"] - 1
    requests = [
        {
            "insertText": {
                "location": {"index": end_index},
                "text": content + "\n\n"
            }
        }
    ]
    docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()



@app.event("message")
def handle_message(event, say, logger):
    text = event.get("text", "")
    ts = event.get("ts")
    channel = event.get("channel")
    thread_ts = event.get("thread_ts", ts)

    if "bot_id" in event:
        return

    match = JOB_PATTERN.search(text)

    if match:
        job_number = match.group(1)
        logger.info(f"Detected job number: {job_number}")

        try:
            job_list = sheet.col_values(1)
            if job_number in job_list:
                doc = find_doc_by_job_number(job_number)
                if doc:
                    doc_id = doc["id"]
                    say(text=f":white_check_mark: Got it! Logging to job #{job_number}.", thread_ts=ts)

                    # Register this thread
                    active_threads[thread_ts] = {
                        "job_number": job_number,
                        "doc_id": doc_id,
                    }

                    thread_messages = fetch_thread(channel, thread_ts)
                    formatted_text = format_thread_messages(thread_messages)
                    docs_service = gdoc_build("docs", "v1", credentials=google_creds)
                    append_to_google_doc(docs_service, doc_id, formatted_text)

                    files = event.get("files", [])
                    for file in files:
                        mimetype = file.get("mimetype", "")
                        if mimetype.startswith("image/") and "url_private" in file:
                            image_url = file["url_private"]
                            try:
                                success = post_image_to_gas(doc_id, image_url)
                                if success:
                                    logger.info(f"✅ Image posted to GAS: {image_url}")
                                else:
                                    logger.error(f"❌ GAS script failed for image: {image_url}")
                            except Exception as e:
                                logger.error(f"❌ Exception sending image to GAS: {e}")
                                say(text=":warning: sorry, I can't process that image. Please try sending as a link, or adding directly to the google doc",
                                    thread_ts=ts)
                        elif "permalink" in file:
                            try:
                                file_link = file["permalink"]
                                file_name = file.get("name", "Attachment")
                                link_text = f"\n📎 Attachment: [{file_name}]({file_link})\n"
                                append_to_google_doc(docs_service, doc_id, link_text)
                                logger.info(f"📎 File link appended to Google Doc: {file_link}")
                            except Exception as e:
                                logger.error(f"❌ Failed to append file link to doc: {e}")

                else:
                    say(text=f":warning: No Google Doc found for job #{job_number}!", thread_ts=ts)
            else:
                say(text=f":warning: Job #{job_number} not found in records.", thread_ts=ts)
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            say(text=f":x: Could not validate job number #{job_number}.", thread_ts=ts)

    # 🔁 Case 2: It’s a reply to an existing thread we’ve seen before
    elif thread_ts in active_threads:
        logger.info(f"Logging reply in tracked thread {thread_ts}")
        doc_id = active_threads[thread_ts]["doc_id"]

        try:
            user_id = event.get("user", "Unknown")
            try:
                user_info = slack_client.users_info(user=user_id)
                user = user_info["user"]["profile"]["display_name"] or user_info["user"]["real_name"]
            except SlackApiError:
                user = user_id

            ts_float = float(ts)
            time = datetime.fromtimestamp(ts_float).strftime("%H:%M")
            text_clean = text.strip()
            formatted_text = f"     {user} @ {time}: {text_clean}"

            docs_service = gdoc_build("docs", "v1", credentials=google_creds)
            append_to_google_doc(docs_service, doc_id, formatted_text)

            # debugging:
            print("files debug>>>", event.get("files"))

            # Enhanced file upload handling in replies (Google Apps Script approach)
            files = event.get("files", [])
            if not files:
                logger.info("No files found in reply event.")
            else:
                for file in files:
                    logger.info(f"Fallback file handler: file = {file}")
                    mimetype = file.get("mimetype", "")
                    if mimetype.startswith("image/") and "url_private" in file:
                        file_url = file["url_private"]
                        try:
                            success = post_image_to_gas(doc_id, file_url)
                            if success:
                                logger.info(f"✅ Fallback: Image posted to GAS: {file_url}")
                            else:
                                logger.error(f"❌ Fallback: GAS script failed for image: {file_url}")
                        except Exception as e:
                            logger.error(f"❌ Fallback: Exception sending image to GAS: {e}")
                            say(text=":warning: sorry, I can't process that image. Please try sending as a link, or adding directly to the google doc",
                                thread_ts=ts)
                    elif "permalink" in file:
                        try:
                            file_link = file["permalink"]
                            file_name = file.get("name", "Attachment")
                            link_text = f"\n📎 Attachment: [{file_name}]({file_link})\n"
                            append_to_google_doc(docs_service, doc_id, link_text)
                            logger.info(f"📎 Fallback file link appended to Google Doc: {file_link}")
                        except Exception as e:
                            logger.error(f"❌ Fallback: Failed to append file link to doc: {e}")

        except Exception as e:
            logger.error(f"Failed to log reply in thread {thread_ts}: {e}")


# Handle image uploads via file_shared events
@app.event("file_shared")
def handle_file_shared(event, logger):
    file_id = event["file_id"]
    logger.info(f"file_shared event received with file_id: {file_id}")
    print(f"file_shared event received with file_id: {file_id}")

    try:
        # Get file info from Slack
        response = slack_client.files_info(file=file_id)
        print("File info fetched:", response)
        file_info = response["file"]

        # Check if it's an image and linked to a thread we care about
        if file_info["mimetype"].startswith("image/") and "url_private" in file_info:
            image_url = file_info["url_private"]

            # Try to find the thread the file was shared in
            channels = file_info.get("channels", []) + file_info.get("groups", []) + file_info.get("ims", [])
            for channel_id in channels:
                # Try to find recent messages with this file ID in threads we’re watching
                history = slack_client.conversations_history(channel=channel_id, limit=50)
                for msg in history["messages"]:
                    if msg.get("thread_ts") in active_threads and "files" in msg:
                        for f in msg["files"]:
                            if f["id"] == file_id:
                                doc_id = active_threads[msg["thread_ts"]]["doc_id"]
                                logger.info(f"Matched image to tracked thread {msg['thread_ts']}. Posting to doc.")
                                post_image_to_gas(doc_id, image_url)
                                return
    except Exception as e:
        logger.error(f"Error handling file_shared event: {e}")


if __name__ == "__main__":
    SocketModeHandler(app, SLACK_APP_TOKEN).start()
