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
            photo.write(data)  # Actually write the photo data to the file_path

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
            supported_image_formats = ['bmp', 'dng', 'jpeg', 'jpg', 'mpo', 'png', 'tif', 'tiff', 'webp']
            s3_photo_key = f'images/{photo_caption}' if photo_caption is not None else f'images/{photo_path.split("/")[1]}'
            logger.info(f'S3 photo_key : {s3_photo_key}')
            # Check the photo's file extension. Blit .jpg if none - existent
            s3_photo_key_file_extension = s3_photo_key.split(".")[-1]
            s3_photo_key = s3_photo_key if s3_photo_key_file_extension in supported_image_formats else s3_photo_key + '.jpg'
            logger.info(f'S3 photo_key_new : {s3_photo_key}')
            self.s3_client.upload_file(Filename=photo_path, Bucket=self.images_bucket, Key=s3_photo_key)
            logger.info(f'Successfully uploaded {photo_path} to "{self.images_bucket}" with the caption "{s3_photo_key}"')

            # Send an HTTP request to the `yolo5` service for prediction
            logger.info(f'Attempting to curl to : http://yolo5:8081/predict?imgName={s3_photo_key}')
            response = requests.post(f'http://yolo5:8081/predict?imgName={s3_photo_key}')
            try:
                response_dict = response.json()  # This line is blocking, which is good, sanity - wise
                logger.info(f'Image prediction successful, results are as follows - response.json(): {response_dict}')

                # Download the predicted image from s3 and send it to the user
                # NOTE : This code is redundant due to yolo5 behavior - it already saves the image contents within its own file system
                # NOTE : This code allows predictions directory "mirroring" between yolo5 and polybot
                s3_predicted_photo_key = f'predictions/{s3_photo_key.split("/")[1]}'  # predicted photo key within aws will be 'predictions/<file_name>'
                if not os.path.exists(s3_predicted_photo_key.split("/")[0]):
                    # If predictions folder doesn't exist within this container, create it.
                    os.makedirs(s3_predicted_photo_key.split("/")[0])
                self.s3_client.download_file(Bucket=self.images_bucket, Key=s3_predicted_photo_key,Filename=s3_predicted_photo_key)
                logger.info(f'Downloaded the predicted photo : {s3_predicted_photo_key}. Sending the image to the user.')
                self.send_photo(msg['chat']['id'], s3_predicted_photo_key)

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
                logger.info(f'Sending prediction labels to the user')
                self.send_text(msg['chat']['id'], detected_objects)

            except requests.exceptions.JSONDecodeError as e:
                # Exeption raised when response contains no content? Meaning if prediction was unsuccessful.
                logger.info(f'What?! No predictions could be made for {s3_photo_key}.\nYolo5 response contents are : {response.text}')
                self.send_text(msg['chat']['id'], f'Oops... No predictions could be made for the image. Try again !')
