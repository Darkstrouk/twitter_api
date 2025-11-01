from fastapi import FastAPI, File, UploadFile, HTTPException
import tempfile
import os
import requests
from requests_oauthlib import OAuth1

app = FastAPI()

API_KEY = os.getenv("TWITTER_API_KEY")
API_SECRET = os.getenv("TWITTER_API_SECRET")
ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")

oauth = OAuth1(
    client_key=API_KEY,
    client_secret=API_SECRET,
    resource_owner_key=ACCESS_TOKEN,
    resource_owner_secret=ACCESS_TOKEN_SECRET
)

CHUNK_SIZE = 2 * 1024 * 1024  # 2 MB

def upload_video_to_twitter(file_path: str, tweet_text: str = "Test tweet"):

    # 1. INIT
    try:
        file_size = os.path.getsize(file_path)
        init_resp = requests.post(
            "https://upload.twitter.com/1.1/media/upload.json",
            params={
                "command": "INIT",
                "media_type": "video/mp4",
                "total_bytes": file_size,
                "media_category": "tweet_video"
            },
            auth=oauth
        )
        init_resp.raise_for_status()
        media_id = init_resp.json()["media_id_string"]
    except Exception as e:
        print(e)
        raise

    # 2. APPEND
    with open(file_path, "rb") as f:
        segment_index = 0
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            append_resp = requests.post(
                "https://upload.twitter.com/1.1/media/upload.json",
                params={
                    "command": "APPEND",
                    "media_id": media_id,
                    "segment_index": segment_index
                },
                files={"media": ("media", chunk, "application/octet-stream")},
                auth=oauth
            )
            append_resp.raise_for_status()
            segment_index += 1

    # 3. FINALIZE
    requests.post(
        "https://upload.twitter.com/1.1/media/upload.json",
        params={"command": "FINALIZE", "media_id": media_id},
        auth=oauth
    ).raise_for_status()

    # 4. POST TWEET
    # tweet_resp = requests.post(
    #     "https://api.twitter.com/2/tweets",
    #     json={"text": tweet_text, "media": {"media_ids": [media_id]}},
    #     auth=oauth
    # )
    # tweet_resp.raise_for_status()
    
    url = "https://api.twitter.com/2/tweets"
    payload = {
        "text": tweet_text,
        "media": {"media_ids": [media_id]}
    }
    headers = {"Content-Type": "application/json"}
    print(f'\npayload - {payload}\n')
    resp = requests.post(url, json=payload, headers=headers, auth=oauth)
    resp.raise_for_status()

    return resp.json()


@app.post("/upload-video/")
async def upload_video(tweet_text: str = "Posted via API", video: UploadFile = File(...)):
    if video.content_type != "video/mp4":
        raise HTTPException(status_code=400, detail="Only MP4 allowed")
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
        content = await video.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = upload_video_to_twitter(tmp_path, tweet_text)
        return {"status": "success", "tweet": result}
    finally:
        os.unlink(tmp_path)