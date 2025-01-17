from datetime import datetime
import slack
import os
import json
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask
from slackeventsapi import SlackEventAdapter
import requests
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
    "LLM_API_KEY": os.environ.get("LLM_API_KEY"),
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


class QADatabase:
    def __init__(self, filename="qa.json"):
        self.filename = filename
        self.qa_data = self.load_data()

    def load_data(self):
        try:
            with open(self.filename, "r", encoding="utf-8") as file:
                data = json.load(file)
                logger.info(f"Successfully loaded {len(data)} Q&A pairs")
                # Log first entry as sample (if exists)
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
        """Simple direct matching for demonstration"""
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

    # If no direct answer, try LLM API
    try:
        logger.info(f"Processing question via LLM API: {text}")

        request_body = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a helpful assistant. Answer questions based on the provided database or respond with 'No relevant answer found.'",
                },
                {
                    "role": "user",
                    "content": f"Database: {json.dumps(qa_database.qa_data)}\n\nUser Question: {text}",
                },
            ],
        }

        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {required_env_vars['LLM_API_KEY']}",
            },
            json=request_body,
            timeout=30,
        )

        logger.info(f"API Response Status: {response.status_code}")

        if response.status_code == 200:
            result = response.json()
            logger.debug(f"API Response: {result}")

            if result and "choices" in result and result["choices"]:
                answer = (
                    result["choices"][0].get("message", {}).get("content", "").strip()
                )
                logger.info(f"LLM answer: {answer}")
                return answer
        else:
            logger.error(f"API Error: {response.status_code} - {response.text}")

    except requests.exceptions.Timeout:
        logger.error("API request timed out")
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
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

    # Check if the message is in the specified channel and not in a thread
    if (channel_id == "C088ZPE8WTF" or channel_id == "C07PZNMBPBN") and (not thread_ts or thread_ts == ts):
        try:
            # Ignore bot's own messages
            if user_id == BOT_ID:
                return

            logger.info(f"Processing message from user {user_id}: {text}")

            if not text:
                logger.warning("Received empty message")
                return

            answer = get_llm_answer(text)

            if answer != "No relevant answer found.":
                logger.info(f"Sending answer: {answer}")
                client.chat_postMessage(
                    channel=channel_id,
                    text=f"``` {answer} ```\n This Anwer is from LLM, it may be incorrect or misleading or wrong. contact @A_TechyBoy for more info or to give any suggestions.\n\n for more info check https://github.com/A-TechyBoy/DV",
                    thread_ts=ts,
                )
            else:
                logger.info("No relevant answer found")

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

    # Send startup message
    send_startup_message()

    # Run Flask app on all interfaces
    app.run(debug=True, host="0.0.0.0", port=5000)
