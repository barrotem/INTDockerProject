import telebot
from loguru import logger
import os
import time
from telebot.types import InputFile
import boto3  # For AWS interaction
import requests  # For inter-container communication


class Bot:

    def __init__(self, token, telegram_chat_url):
        # create a new instance of the TeleBot class.
        # all communication with Telegram servers are done using self.telegram_bot_client
        self.telegram_bot_client = telebot.TeleBot(token)

        # remove any existing webhooks configured in Telegram servers
        self.telegram_bot_client.remove_webhook()
        time.sleep(0.5)

        # set the webhook URL
        self.telegram_bot_client.set_webhook(url=f'{telegram_chat_url}/{token}/', timeout=60)

        logger.info(f'Telegram Bot information\n\n{self.telegram_bot_client.get_me()}')

    def send_text(self, chat_id, text):
        self.telegram_bot_client.send_message(chat_id, text)

    def send_text_with_quote(self, chat_id, text, quoted_msg_id):
        self.telegram_bot_client.send_message(chat_id, text, reply_to_message_id=quoted_msg_id)

    def is_current_msg_photo(self, msg):
        return 'photo' in msg

    def download_user_photo(self, msg):
        """
        Downloads the photos that sent to the Bot to `photos` directory (should be existed)
        :return:
        """
        # if not self.is_current_msg_photo(msg):
        #     raise RuntimeError(f'Message content of type \'photo\' expected')

        logger.info(f'Received a new photo !')
        file_info = self.telegram_bot_client.get_file(msg['photo'][-1]['file_id'])
        photo_caption = msg['caption'] if 'caption' in msg else None
        data = self.telegram_bot_client.download_file(file_info.file_path)
        folder_name = file_info.file_path.split('/')[0]
        # Add informative logs regarding files' metadata
        logger.info(f'Downloaded received photo to the following path : {file_info.file_path}')

        if not os.path.exists(folder_name):
            os.makedirs(folder_name)

        with open(file_info.file_path, 'wb') as photo:
            photo.write(data)

        return file_info.file_path, photo_caption

    def send_photo(self, chat_id, img_path):
        if not os.path.exists(img_path):
            raise RuntimeError("Image path doesn't exist")

        self.telegram_bot_client.send_photo(
            chat_id,
            InputFile(img_path)
        )

    def handle_message(self, msg):
        """Bot Main message handler"""
        logger.info(f'Incoming message: {msg}')
        self.send_text(msg['chat']['id'], f'Your original message: {msg["text"]}')


class ObjectDetectionBot(Bot):
    def __init__(self, token, telegram_chat_url, images_bucket):
        super().__init__(token, telegram_chat_url)
        # Add specific implementation code :
        # Initialize s3 realted variables
        self.s3_client = boto3.client('s3')
        self.images_bucket = images_bucket

    def handle_message(self, msg):
        logger.info(f'Incoming message: {msg}')

        if self.is_current_msg_photo(msg):
            photo_path, photo_caption = self.download_user_photo(msg)
            # Upload the photo to S3
            s3_photo_key = f'images/{photo_caption}' if photo_caption is not None else f'images/{photo_path.split("/")[1]}'
            self.s3_client.upload_file(Filename=photo_path, Bucket=self.images_bucket, Key=s3_photo_key)
            logger.info(f'Successfully uploaded {photo_path} to "{self.images_bucket}" with the caption "{s3_photo_key}"')

            # Send an HTTP request to the `yolo5` service for prediction
            logger.info(f'Attempting to curl to : http://yolo5:8081/predict?imgName={s3_photo_key}')
            response = requests.post(f'http://yolo5:8081/predict?imgName={s3_photo_key}')
            response_dict = response.json()
            logger.info(f'response.json(): {response_dict}')

            # Send the returned results to the Telegram end-user
            # Count number of prediction objects withing the image
            prediction_label_counts = {}
            for prediction in response_dict['labels']:
                # prediction is a json array (dict) representing all metadata of a specific prediction
                label = prediction['class']
                if label in prediction_label_counts:
                    prediction_label_counts[label] += 1
                else:
                    prediction_label_counts[label] = 1
            # Prepare a formatted string to send to the user
            detected_objects = f'Detected the following objects within the image :\n'
            for label in prediction_label_counts:
                detected_objects += f'{label} : {prediction_label_counts[label]}\n'
            self.send_text(msg['chat']['id'],detected_objects)
