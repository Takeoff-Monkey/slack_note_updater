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
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build, build as gdoc_build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.service_account import Credentials
from slack_sdk.oauth import AuthorizeUrlGenerator
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from doctor_client import Doctor
import pytz


ssl_context = ssl.create_default_context(cafile=certifi.where())
urllib.request.urlopen("https://slack.com", context=ssl_context)

load_dotenv()

creds_json = os.getenv("GOOGLE_CREDS_JSON")
if not creds_json:
    raise Exception("GOOGLE_CREDS_JSON not found in environment variables!")
creds_dict = json.loads(creds_json)
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
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
sheet_delivered = client.open_by_key(GOOGLE_SHEET_ID).worksheet("Delivered")

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]

FEEDBACK_RELAY_CHANNEL = "C08HUKW7NDU"           # ewing_internal
EWING_DRFS_FOLDER_ID = "1UBEbGB2o9Fl_HpRnxx-JJqSDCeq3GWBC"
FEEDBACK_SUMMARY_CHANNELS = ["C08HUKW7NDU", "C09A297JGQ0"]

slack_client = WebClient(token=SLACK_BOT_TOKEN)

app = App(token=SLACK_BOT_TOKEN)
active_threads = {}
feedback_threads = {}  # thread_ts -> {job_number, doc_id, original_channel}

JOB_PATTERN = re.compile(r"#(\d{5,})!")
FEEDBACK_PATTERN = re.compile(r"#feedback!", re.IGNORECASE)


# ─────────────────────────────────────────────
# Google Drive / Docs helpers
# ─────────────────────────────────────────────

def post_image_to_gas(doc_id, image_url):
    try:
        payload = {"docId": doc_id, "imageUrl": image_url}
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}"
        }
        response = requests.post(GAS_WEBHOOK_URL, json=payload, headers=headers)
        print(f"📤 Posting image to GAS: {image_url} — status {response.status_code}")
        return response.status_code == 200
    except Exception as e:
        print(f"Failed to post image to GAS: {e}")
        return False


def find_doc_by_job_number(job_number: str):
    query = f"name contains '{job_number} |' and mimeType='application/vnd.google-apps.document'"
    results = drive_service.files().list(
        q=query, spaces='drive', fields='files(id, name)', pageSize=1
    ).execute(num_retries=5)
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
            profile = user_info.get("user", {}).get("profile", {})
            user = profile.get("display_name") or profile.get("real_name") or user_id
        except Exception:
            user = f"Unknown User ({user_id})"
        ts = float(msg.get("ts", 0))
        text = msg.get("text", "").strip()
        time = datetime.fromtimestamp(ts).strftime("%H:%M")
        date = datetime.fromtimestamp(ts).strftime("%m-%d-%y")
        if i == 0:
            formatted.append(f"{user} @ {time} {date}: {text}")
        else:
            formatted.append(f"     {user} @ {time}: {text}")
    return "\n".join(formatted)


def get_user_display_name(user_id):
    try:
        user_info = slack_client.users_info(user=user_id)
        profile = user_info.get("user", {}).get("profile", {})
        return profile.get("display_name") or profile.get("real_name") or user_id
    except Exception:
        return user_id


def get_image_as_base64(url, headers):
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return base64.b64encode(response.content).decode("utf-8")
    return None


def insert_image_inline(docs_service, doc_id, base64_image):
    doc = docs_service.documents().get(documentId=doc_id).execute(num_retries=5)
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
    docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": requests_}).execute(num_retries=5)


def append_to_google_doc(docs_service, doc_id, content):
    doc = docs_service.documents().get(documentId=doc_id).execute(num_retries=5)
    end_index = doc.get("body").get("content")[-1]["endIndex"] - 1
    requests = [
        {
            "insertText": {
                "location": {"index": end_index},
                "text": content + "\n\n"
            }
        }
    ]
    docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute(num_retries=5)


def append_feedback_to_google_doc(docs_service, doc_id, content):
    """Append text to a Google Doc in red font."""
    doc = docs_service.documents().get(documentId=doc_id).execute(num_retries=5)
    end_index = doc.get("body").get("content")[-1]["endIndex"] - 1
    text_to_insert = content + "\n\n"
    insert_start = end_index

    batch_requests = [
        {
            "insertText": {
                "location": {"index": insert_start},
                "text": text_to_insert
            }
        },
        {
            "updateTextStyle": {
                "range": {
                    "startIndex": insert_start,
                    "endIndex": insert_start + len(text_to_insert)
                },
                "textStyle": {
                    "foregroundColor": {
                        "color": {
                            "rgbColor": {"red": 1.0, "green": 0.0, "blue": 0.0}
                        }
                    }
                },
                "fields": "foregroundColor"
            }
        }
    ]
    docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": batch_requests}).execute(num_retries=5)


# ─────────────────────────────────────────────
# Weekly feedback doc helpers
# ─────────────────────────────────────────────

def get_week_date_range():
    """Return (monday, sunday) as date objects for the current Mon–Sun week (ET)."""
    today = datetime.now(pytz.timezone("America/New_York")).date()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def get_weekly_doc_title():
    monday, sunday = get_week_date_range()
    if monday.month == sunday.month:
        return f"Ewing Feedback {monday.strftime('%B')} {monday.day} - {sunday.day}"
    else:
        return f"Ewing Feedback {monday.strftime('%B')} {monday.day} - {sunday.strftime('%B')} {sunday.day}"


_weekly_feedback_doc_cache = {}  # title -> {id, name, webViewLink}


def get_or_create_weekly_feedback_doc():
    """Find this week's feedback doc in Ewing DRFs folder, or create it.

    Cached per title (the week doesn't change mid-week) so a burst of
    feedback messages/replies doesn't re-search Drive on every single one.
    """
    title = get_weekly_doc_title()
    if title in _weekly_feedback_doc_cache:
        return _weekly_feedback_doc_cache[title]

    query = (
        f"name = '{title}' "
        f"and mimeType = 'application/vnd.google-apps.document' "
        f"and '{EWING_DRFS_FOLDER_ID}' in parents "
        f"and trashed = false"
    )
    results = drive_service.files().list(
        q=query, spaces="drive",
        fields="files(id, name, webViewLink)", pageSize=1
    ).execute(num_retries=5)
    files = results.get("files", [])
    if files:
        _weekly_feedback_doc_cache[title] = files[0]
        return files[0]

    # Created via the Apps Script (runs as konur@): the service account has a
    # 0-byte Drive quota, so files().create fails with storageQuotaExceeded.
    response = requests.post(
        GAS_WEBHOOK_URL, json={"action": "create_weekly_doc", "title": title}, timeout=60
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise Exception(f"Apps Script could not create weekly doc: {result.get('error')}")
    new_file = {k: result[k] for k in ("id", "name", "webViewLink")}
    print(f"📄 Created weekly feedback doc: {title} ({new_file['id']})")
    _weekly_feedback_doc_cache[title] = new_file
    return new_file


def get_previous_week_doc():
    """Find last week's feedback doc to link in the Monday summary."""
    today = datetime.now(pytz.timezone("America/New_York")).date()
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_sunday = last_monday + timedelta(days=6)

    if last_monday.month == last_sunday.month:
        title = f"Ewing Feedback {last_monday.strftime('%B')} {last_monday.day} - {last_sunday.day}"
    else:
        title = f"Ewing Feedback {last_monday.strftime('%B')} {last_monday.day} - {last_sunday.strftime('%B')} {last_sunday.day}"

    query = (
        f"name = '{title}' "
        f"and mimeType = 'application/vnd.google-apps.document' "
        f"and '{EWING_DRFS_FOLDER_ID}' in parents "
        f"and trashed = false"
    )
    results = drive_service.files().list(
        q=query, spaces="drive",
        fields="files(id, name, webViewLink)", pageSize=1
    ).execute(num_retries=5)
    files = results.get("files", [])
    return files[0] if files else None


def send_weekly_feedback_summary():
    """Scheduled job: every Monday at midnight ET, post last week's doc link."""
    print("📬 Running weekly feedback summary job...")
    doc = get_previous_week_doc()
    if not doc:
        print("No feedback doc found for last week — skipping summary.")
        return

    url = doc.get("webViewLink", "")
    message = f"Here's all the feedback we received from our customers last week: {url}"
    for ch in FEEDBACK_SUMMARY_CHANNELS:
        try:
            slack_client.chat_postMessage(channel=ch, text=message)
            print(f"✅ Weekly summary sent to {ch}")
        except SlackApiError as e:
            print(f"❌ Failed to send weekly summary to {ch}: {e}")


# ─────────────────────────────────────────────
# Slack relay helpers
# ─────────────────────────────────────────────

def relay_feedback_to_internal(job_number, user_name, formatted_text, original_channel, thread_ts):
    """Post the feedback message to the internal channel."""
    try:
        channel_mention = f"<#{original_channel}>"
        header = f":mega: *Customer Feedback — Job #{job_number}*\nPosted in {channel_mention} by *{user_name}*\n\n"
        full_message = header + formatted_text
        slack_client.chat_postMessage(channel=FEEDBACK_RELAY_CHANNEL, text=full_message)
    except SlackApiError as e:
        print(f"❌ Failed to relay feedback to internal channel: {e}")


def relay_feedback_reply_to_internal(job_number, user_name, formatted_line, original_channel):
    """Post a single feedback thread reply to the internal channel."""
    try:
        channel_mention = f"<#{original_channel}>"
        message = f":speech_balloon: *Feedback reply — Job #{job_number}* (from {channel_mention})\n{formatted_line}"
        slack_client.chat_postMessage(channel=FEEDBACK_RELAY_CHANNEL, text=message)
    except SlackApiError as e:
        print(f"❌ Failed to relay feedback reply to internal channel: {e}")


# ─────────────────────────────────────────────
# Event handlers
# ─────────────────────────────────────────────

@app.event("message")
def handle_message(event, say, logger):
    text = event.get("text", "")
    ts = event.get("ts")
    channel = event.get("channel")
    thread_ts = event.get("thread_ts", ts)

    if "bot_id" in event:
        return

    if "#revise!" in text.lower():
        logger.info("skipping this as it is answered by another bot")
        return

    is_feedback = bool(FEEDBACK_PATTERN.search(text))
    job_match = JOB_PATTERN.search(text)

    # ─────────────────────────────────────────────
    # CASE 0: Feedback trigger — #feedback! #12345!
    # ─────────────────────────────────────────────
    if is_feedback and job_match:
        job_number = job_match.group(1)
        logger.info(f"Feedback detected for job #{job_number}")

        try:
            job_list = sheet.col_values(1) + sheet_delivered.col_values(1)
            if job_number not in job_list:
                say(text=f":warning: Job #{job_number} not found in records.", thread_ts=ts)
                return

            doc = find_doc_by_job_number(job_number)
            if not doc:
                say(text=f":warning: No Google Doc found for job #{job_number}!", thread_ts=ts)
                return

            doc_id = doc["id"]
            user_id = event.get("user", "Unknown")
            user_name = get_user_display_name(user_id)
            ts_float = float(ts)
            time_str = datetime.fromtimestamp(ts_float).strftime("%H:%M")
            date_str = datetime.fromtimestamp(ts_float).strftime("%m-%d-%y")

            clean_text = re.sub(r"#feedback!", "", text, flags=re.IGNORECASE).strip()
            clean_text = re.sub(r"#\d{5,}!", "", clean_text).strip()

            formatted_text = f"[CUSTOMER FEEDBACK] {user_name} @ {time_str} {date_str}: {clean_text}"

            feedback_threads[thread_ts] = {
                "job_number": job_number,
                "doc_id": doc_id,
                "original_channel": channel
            }

            docs_service = gdoc_build("docs", "v1", credentials=google_creds)

            # Write to job doc in red
            append_feedback_to_google_doc(docs_service, doc_id, formatted_text)

            # Write to weekly feedback doc in red — non-fatal, so a Drive
            # problem here doesn't block the relay after the job doc is written
            try:
                weekly_doc = get_or_create_weekly_feedback_doc()
                job_header = f"Job #{job_number}"
                append_feedback_to_google_doc(docs_service, weekly_doc["id"], f"{job_header}\n{formatted_text}")
            except Exception as e:
                logger.error(f"Weekly feedback doc write failed for job #{job_number}: {e}")

            # Relay to internal channel
            relay_feedback_to_internal(job_number, user_name, formatted_text, channel, thread_ts)

            say(text=f":red_circle: Feedback received for job #{job_number} — logged and forwarded to the team. Thank you!", thread_ts=ts)
            logger.info(f"✅ Feedback logged and relayed for job #{job_number}")

        except Exception as e:
            logger.error(f"Feedback handling failed: {e}")
            say(text=f":x: Could not process feedback for job #{job_number}.", thread_ts=ts)
        return

    # ─────────────────────────────────────────────
    # CASE 0b: Reply in an existing feedback thread
    # ─────────────────────────────────────────────
    if thread_ts in feedback_threads and thread_ts != ts:
        logger.info(f"Reply in feedback thread {thread_ts}")
        fb = feedback_threads[thread_ts]
        doc_id = fb["doc_id"]
        job_number = fb["job_number"]
        original_channel = fb["original_channel"]

        try:
            user_id = event.get("user", "Unknown")
            user_name = get_user_display_name(user_id)
            ts_float = float(ts)
            time_str = datetime.fromtimestamp(ts_float).strftime("%H:%M")
            formatted_line = f"     [FEEDBACK REPLY] {user_name} @ {time_str}: {text.strip()}"

            docs_service = gdoc_build("docs", "v1", credentials=google_creds)

            # Write to job doc in red
            append_feedback_to_google_doc(docs_service, doc_id, formatted_line)

            # Write to weekly feedback doc in red (non-fatal)
            try:
                weekly_doc = get_or_create_weekly_feedback_doc()
                append_feedback_to_google_doc(docs_service, weekly_doc["id"], formatted_line)
            except Exception as e:
                logger.error(f"Weekly feedback doc write failed for job #{job_number}: {e}")

            relay_feedback_reply_to_internal(job_number, user_name, formatted_line, original_channel)

        except Exception as e:
            logger.error(f"Failed to log feedback reply: {e}")
        return

    # ─────────────────────────────────────────────
    # CASE 1: Normal job logging — #12345!
    # ─────────────────────────────────────────────
    match = JOB_PATTERN.search(text)

    if match:
        job_number = match.group(1)
        logger.info(f"Detected job number: {job_number}")

        try:
            job_list = sheet.col_values(1) + sheet_delivered.col_values(1)
            if job_number in job_list:
                doc = find_doc_by_job_number(job_number)
                if doc:
                    doc_id = doc["id"]
                    say(text=f":white_check_mark: Got it! Logging to job #{job_number}.", thread_ts=ts)
                    doctor.run(user_id=event.get("user"), action="#job-note")  # usage telemetry

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

    # ─────────────────────────────────────────────
    # CASE 2: Reply to an existing normal thread
    # ─────────────────────────────────────────────
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

            print("files debug>>>", event.get("files"))

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


@app.event("file_shared")
def handle_file_shared(event, logger):
    file_id = event["file_id"]
    logger.info(f"file_shared event received with file_id: {file_id}")
    print(f"file_shared event received with file_id: {file_id}")

    try:
        response = slack_client.files_info(file=file_id)
        print("File info fetched:", response)
        file_info = response["file"]

        if file_info["mimetype"].startswith("image/") and "url_private" in file_info:
            image_url = file_info["url_private"]
            channels = file_info.get("channels", []) + file_info.get("groups", []) + file_info.get("ims", [])
            for channel_id in channels:
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


# ─────────────────────────────────────────────
# Scheduler
# ─────────────────────────────────────────────

scheduler = BackgroundScheduler(timezone=pytz.timezone("America/New_York"))
scheduler.add_job(
    send_weekly_feedback_summary,
    CronTrigger(day_of_week="mon", hour=0, minute=0)
)
# Doctor health reporting — 60s liveness beat on the existing scheduler.
doctor = Doctor()
scheduler.add_job(doctor.heartbeat, IntervalTrigger(seconds=60), id="doctor_heartbeat")
scheduler.start()

if __name__ == "__main__":
    SocketModeHandler(app, SLACK_APP_TOKEN).start()