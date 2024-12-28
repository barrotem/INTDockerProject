import time
from pathlib import Path
from flask import Flask, request
from detect import run
import uuid
import yaml
from loguru import logger
import os
import boto3
import pymongo

images_bucket = os.environ['BUCKET_NAME']

with open("data/coco128.yaml", "r") as stream:
    names = yaml.safe_load(stream)['names']

app = Flask(__name__)

@app.route('/predict', methods=['POST'])
def predict():
    # Generates a UUID for this current prediction HTTP request. This id can be used as a reference in logs to identify and track individual prediction requests.
    prediction_id = str(uuid.uuid4())

    logger.info(f'prediction: {prediction_id}. start processing')

    # Receives a URL parameter representing the image to download from S3
    img_name = request.args.get('imgName')
    img_path = Path(img_name)
    # Initialize s3 resource
    s3_resource = boto3.client("s3")

    # Download and store the remote image under predictions/<image_filename>
    original_img_path = Path(f'predictions/{img_path.name}')
    if not os.path.exists(original_img_path.parent):
        # Create predictions directory if it doesn't already exist
        os.makedirs(original_img_path.parent)
    logger.info(f'downloading image based on the following strings (bucket, bucket_image_path, destionation_local_path):,'
                f'{images_bucket},{img_name},{str(original_img_path)}')
    s3_resource.download_file(Bucket=images_bucket, Key=img_name, Filename=str(original_img_path))
    logger.info(f'prediction: {prediction_id}/{original_img_path}. Download img completed')

    # Predicts the objects in the image
    run(
        weights='yolov5s.pt',
        data='data/coco128.yaml',
        source=original_img_path,
        project='static/data',
        name=prediction_id,
        save_txt=True
    )
    logger.info(f'prediction: {prediction_id}/{original_img_path}. done')

    # This is the path for the predicted image with labels
    # The predicted image typically includes bounding boxes drawn around the detected objects, along with class labels and possibly confidence scores.
    predicted_img_path = Path(f'static/data/{prediction_id}/{original_img_path.name}')
    # Uploads the predicted image (predicted_img_path) to S3 - without accidentally overriding the original image.
    s3_resource.upload_file(Filename=str(predicted_img_path), Bucket=images_bucket, Key=str(original_img_path))
    logger.info(f'Uploaded {str(predicted_img_path)} to {images_bucket}/{str(original_img_path)}')

    # Parse prediction labels and create a summary
    pred_summary_path = Path(f'static/data/{prediction_id}/labels/{str(Path(original_img_path.name).with_suffix(".txt"))}')  # Replace file extension for .txt
    logger.info(f'looking for prediction summary in path: {pred_summary_path}...')
    # The file located in pred_summary_path represents the model's prediction results.
    # Parse prediction results into a JSON like object and return the result.
    if pred_summary_path.exists():
        with open(pred_summary_path) as f:
            labels = f.read().splitlines()
            labels = [line.split(' ') for line in labels]
            labels = [{
                'class': names[int(l[0])],
                'cx': float(l[1]),
                'cy': float(l[2]),
                'width': float(l[3]),
                'height': float(l[4]),
            } for l in labels]

        logger.info(f'prediction: {prediction_id}/{original_img_path}. prediction summary:\n\n{labels}\n')

        prediction_summary = {
            'prediction_id': prediction_id,
            'original_img_path': str(original_img_path), #PosixPath(s) have to be turned to strings to be serialized into JSON
            'predicted_img_path': str(predicted_img_path), #PosixPath(s) have to be turned to strings to be serialized into JSON
            'labels': labels,
            'time': time.time()
        }

        # Store the prediction summary in MongoDB
        try:
            # Connect to the MongoDB instance
            uri = "mongodb://mongo1:27017,mongo2:27017,mongo3:27017/test"
            mongodb_client = pymongo.MongoClient(uri)
            # Create a new "predictions" collection if it doesn't already exist and interact with it
            mongodb_database = mongodb_client["test"]
            mongodb_collection = mongodb_database["predictions"]
            # Store prediction summary within MongoDB
            result = mongodb_collection.insert_one(prediction_summary)
            logger.info(f'Succesffuly stored prediction summary within MongoDB :{result.acknowledged}')

        except Exception as e:
            logger.info(e)

        # Return prediction_summary as a response to the request.
        # Problem : prediction_summary might now have the _id key with an ObjectID type assigned as a value.
        # This value isn't JSON serializable, and will be manually cast to a str.
        if "_id" in prediction_summary:
            prediction_summary["_id"] = str(prediction_summary["_id"])
        return prediction_summary
    else:
        logger.info(f'prediction: {prediction_id}/{original_img_path}. prediction result not found')
        return f'prediction: {prediction_id}/{original_img_path}. prediction result not found', 404


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8081)
