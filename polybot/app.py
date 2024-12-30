import flask
from flask import request
import os
from bot import ObjectDetectionBot

app = flask.Flask(__name__)

# Acquire telegram secret files path from environment varibles
TELEGRAM_TOKEN_PATH = os.environ['TELEGRAM_TOKEN_PATH']
TELEGRAM_APP_URL_PATH = os.environ['TELEGRAM_APP_URL_PATH']
# Read and turn secret file contents to the appropriate static variables
with open(TELEGRAM_TOKEN_PATH) as telegram_token_file:
    TELEGRAM_TOKEN = telegram_token_file.read()
with open(TELEGRAM_APP_URL_PATH) as telegram_app_url_file:
    TELEGRAM_APP_URL = telegram_app_url_file.read()

# Define AWS interaction required varibales
IMAGES_BUCKET = os.environ['BUCKET_NAME']

@app.route('/', methods=['GET'])
def index():
    return 'Ok'


@app.route(f'/{TELEGRAM_TOKEN}/', methods=['POST'])
def webhook():
    req = request.get_json()
    bot.handle_message(req['message'])
    return 'Ok'


if __name__ == "__main__":
    bot = ObjectDetectionBot(TELEGRAM_TOKEN, TELEGRAM_APP_URL, IMAGES_BUCKET)

    app.run(host='0.0.0.0', port=8443)
