#!/bin/bash
# Simple bash script to initiate a replica-set "mongo_rs" of 3 mongo-db containers named : "mongo1-3"
# This script will be used by docker-compose.
echo "Sleeping in order to ensure mongo containers are up ..."
sleep 5
echo "Attempting to initiate replica-set ..."
mongo_state=$(mongosh --host mongo1 --eval "rs.initiate({
 _id: \"mongo_rs\",
 members: [
   {_id: 0, host: \"mongo1\"},
   {_id: 1, host: \"mongo2\"},
   {_id: 2, host: \"mongo3\"}
 ]
})")

echo "Mongo state is : $mongo_state"
if [[ $mongo_state = *"ok"* ]];
then
  echo "Replica-set initiation finished successfully. Shutting down"
else
  if [[ -z $mongo_state ]];
  then
    echo "Replica-set initiation finished unsuccessfully, replica-set might already be initialized. Shutting down"
  else
    echo "Replica-set initiation finished unsuccessfully due to a general error. Shutting down"
  fi
fi
