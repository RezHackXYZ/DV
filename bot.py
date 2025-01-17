from pydoc import text
from time import thread_time
import slack
import os
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, cli
from slackeventsapi import SlackEventAdapter

env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

app = Flask(__name__)
slack_event_adapter = SlackEventAdapter(os.environ['SLACK_SIGNING_SECRET'], "/slack/events", app)

client = slack.WebClient(token=os.environ['SLACK_TOKERN'])

BOT_ID = client.api_call("auth.test")['user_id']

def getChatGptResponse (text):
    return text

@slack_event_adapter.on('message')
def message(payload):
    event = payload.get('event', {})
    channel_id = event.get('channel')
    user_id = event.get('user')
    text = event.get('text')
    ts = event.get('ts')

    if channel_id == '#high-seas-help-test':
        if BOT_ID != user_id:
            client.chat_postMessage(channel=channel_id, text=getChatGptResponse(text), thread_ts=ts)

if __name__ == '__main__':
    app.run(debug=True)