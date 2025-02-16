from datetime import datetime
import slack
import os
import json
import requests
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask
from slackeventsapi import SlackEventAdapter
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# Load environment variables
env_path = Path(".") / ".env"
load_dotenv(dotenv_path=env_path)

# Initialize Flask app
app = Flask(__name__)

# Verify environment variables are present
required_env_vars = {
    "SLACK_SIGNING_SECRET": os.environ.get("SLACK_SIGNING_SECRET"),
    "SLACK_TOKEN": os.environ.get("SLACK_TOKEN"),
}

missing_vars = [k for k, v in required_env_vars.items() if not v]
if missing_vars:
    logger.error(f"Missing environment variables: {', '.join(missing_vars)}")
    raise ValueError(
        f"Missing required environment variables: {', '.join(missing_vars)}"
    )

# Initialize Slack event adapter
try:
    event_adapter = SlackEventAdapter(
        required_env_vars["SLACK_SIGNING_SECRET"], "/slack/events", app
    )
except Exception as e:
    logger.error(f"Failed to initialize Slack event adapter: {e}")
    raise

# Initialize Slack client
try:
    client = slack.WebClient(token=required_env_vars["SLACK_TOKEN"])
    BOT_ID = client.api_call("auth.test")["user_id"]
    logger.info(f"Bot initialized with ID: {BOT_ID}")
except Exception as e:
    logger.error(f"Failed to initialize Slack client: {e}")
    raise

# Track processed messages using message IDs
processed_messages = set()

class QADatabase:
    def __init__(self, filename="qa.json"):
        self.filename = filename
        self.qa_data = self.load_data()

    def load_data(self):
        try:
            with open(self.filename, "r", encoding="utf-8") as file:
                data = json.load(file)
                logger.info(f"Successfully loaded {len(data)} Q&A pairs")
                if data:
                    logger.info(f"Sample Q&A entry: {json.dumps(data[0], indent=2)}")
                return data
        except FileNotFoundError:
            logger.error(f"Q&A database file {self.filename} not found")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {self.filename}: {e}")
            return []
        except Exception as e:
            logger.error(f"Error loading Q&A database: {e}")
            return []

    def find_answer(self, question):
        question = question.lower().strip()
        for qa in self.qa_data:
            if qa.get("question", "").lower().strip() == question:
                return qa.get("answer")
        return None

# Initialize Q&A database
qa_database = QADatabase()

def get_llm_answer(text):
    if not text:
        logger.warning("Empty question received")
        return None

    # First try direct Q&A database
    direct_answer = qa_database.find_answer(text)
    if direct_answer:
        logger.info(f"Found direct answer for: {text}")
        return direct_answer

    # If no direct answer, use Hack Club AI API
    try:
        logger.info(f"Processing question via Hack Club AI API: {text}")

        messages = [
            {"role": "system", "content": "You are a helpful assistant that answers questions based on a provided Q&A database. If you cannot find a relevant answer, respond with just \"Not sure.\" Keep answers concise and on-point."},
            {"role": "user", "content": f"Database: {json.dumps(qa_database.qa_data)}\n\nUser Question: {text}"}
        ]

        response = requests.post(
            "https://ai.hackclub.com/chat/completions",
            headers={"Content-Type": "application/json"},
            json={"messages": messages}
        )

        if response.status_code == 200:
            response_data = response.json()
            answer = response_data.get('choices', [{}])[0].get('message', {}).get('content', '')
            logger.info(f"Hack Club AI API response: {answer}")
            return answer.strip()
        else:
            logger.error(f"Error from Hack Club AI API: {response.status_code} - {response.text}")
            return None

    except Exception as e:
        logger.error(f"Error in get_llm_answer: {e}")
        return None

@event_adapter.on("message")
def message(payload):
    event = payload.get("event", {})
    channel_id = event.get("channel")
    user_id = event.get("user")
    text = event.get("text")
    ts = event.get("ts")
    thread_ts = event.get("thread_ts")
    
    # Create a unique identifier for this message
    message_id = f"{channel_id}:{ts}"
    
    # Skip if we've already processed this message
    if message_id in processed_messages:
        logger.info(f"Skipping already processed message {message_id}")
        return
    
    # Add to processed messages
    processed_messages.add(message_id)

    if (channel_id == "C088ZPE8WTF") and (not thread_ts or thread_ts == ts):
        try:
            if user_id == BOT_ID:
                return

            logger.info(f"Processing message from user {user_id}: {text}")

            if not text:
                logger.warning("Received empty message")
                return

            answer = get_llm_answer(text)

            if answer and answer != "Not sure.":
                logger.info(f"Sending answer: {answer}")
                client.chat_postMessage(
                    channel=channel_id,
                    text=f"{answer}\n\n_Note: Answer provided by AI - may need verification. Issues/suggestions: contact @A_TechyBoy_",
                    thread_ts=ts,
                )
            else:
                logger.info(f"No relevant answer found for question: {text}")
                client.chat_postMessage(
                    channel=channel_id,
                    text="No relevant answer found. Try checking our Q&A database: github.com/A-TechyBoy/DV/blob/main/qa.json",
                    thread_ts=ts,
                )

        except Exception as e:
            logger.error(f"Error processing message event: {e}")
            try:
                client.chat_postMessage(
                    channel=channel_id,
                    text="Sorry, I encountered an error while processing your request.",
                    thread_ts=ts,
                )
            except:
                logger.error("Failed to send error message to Slack")

def send_startup_message():
    try:
        logger.info("Sent startup message successfully")
    except Exception as e:
        logger.error(f"Failed to send startup message: {e}")

if __name__ == "__main__":
    logger.info("Starting the bot...")
    logger.info(f"Loaded {len(qa_database.qa_data)} Q&A pairs from database")
    send_startup_message()
    app.run(debug=True, host="0.0.0.0", port=5000)
