from fastapi import FastAPI, File, UploadFile, HTTPException, Form
import tempfile
import os
import time
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
    try:
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
    except Exception as e:
        print(e)
        raise

    # 3. FINALIZE
    try:
        requests.post(
            "https://upload.twitter.com/1.1/media/upload.json",
            params={"command": "FINALIZE", "media_id": media_id},
            auth=oauth
        ).raise_for_status()
    except Exception as e:
        print(e)
        raise

    #4.0 CHECK STATUS
    print('\nchecking status...\n')
    try:
        url = "https://upload.twitter.com/1.1/media/upload.json"
        params = {
            "command": "STATUS",
            "media_id": media_id
        }
        cnt = 1
        while True:
            print("\nattempt #{cnt}\n")
            resp = requests.get(url, params=params, auth=oauth)
            resp.raise_for_status()
            data = resp.json()
            if data.get("processing_info"):
                state = data["processing_info"].get("state")
                if state == "succeeded":
                    break
                elif state == "failed":
                    raise Exception(f"Media processing failed: {data}")
                else:
                    # ждём
                    check_after = data["processing_info"].get("check_after_secs", 1)
                    time.sleep(check_after)
                    cnt += 1
            else:
                break  # нет processing_info — значит, готово
    except Exception as e:
        print('Error in getting status: {e}\n')

    # 4. POST TWEET
    # tweet_resp = requests.post(
    #     "https://api.twitter.com/2/tweets",
    #     json={"text": tweet_text, "media": {"media_ids": [media_id]}},
    #     auth=oauth
    # )
    # tweet_resp.raise_for_status()
    
    print('\nposting tweet...\n')
    try:
        url = "https://api.twitter.com/2/tweets"
        payload = {
            "text": tweet_text,
            "media": {"media_ids": [media_id]}
        }
        headers = {"Content-Type": "application/json"}
        print(f'\npayload - {payload}\n')
        resp = requests.post(url, json=payload, headers=headers, auth=oauth)
        resp.raise_for_status()
    except Exception as e:
        print(e)
        raise

    return resp.json()


@app.post("/upload-video/")
async def upload_video(
    tweet_text: str = Form("Posted via API"), 
    video: UploadFile = File(...)
):
    print((f"Received video: filename={video.filename}, size={video.size}, content_type={video.content_type}"))
    print('\nrecieved tweet text: {tweet_text}')

    if video.content_type != "video/mp4":
        raise HTTPException(status_code=400, detail="Only MP4 allowed")
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
        content = await video.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = upload_video_to_twitter(tmp_path, tweet_text)
        print('\ntweet has been posted!\n')
        return {"status": "success", "tweet": result}
    finally:
        os.unlink(tmp_path)

@app.post("/tweet/")
async def post_text_tweet(tweet_text: str = Form(...)):
    """
    Публикует текстовый твит без медиа.
    """
    if not tweet_text.strip():
        raise HTTPException(status_code=400, detail="Tweet text cannot be empty")

    try:
        url = "https://api.twitter.com/2/tweets"
        payload = {"text": tweet_text}
        headers = {"Content-Type": "application/json"}
        resp = requests.post(url, json=payload, headers=headers, auth=oauth)
        resp.raise_for_status()
        return {"status": "success", "tweet": resp.json()}
    except requests.exceptions.HTTPError as e:
        error_detail = resp.json() if resp.content else str(e)
        raise HTTPException(status_code=resp.status_code, detail=error_detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to post tweet: {str(e)}")

@app.get("/health/live")
async def liveness_check():
    return {"status": "alive"}
