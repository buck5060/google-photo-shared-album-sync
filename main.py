import requests
import time
import logging
import os
import json
import threading
import signal

from flask import Flask
from flask import request
from waitress import create_server

from webdav3.client import Client as WdClient

from rich.progress import track

WD_CONFIG_PATH = "webdav_config.json"
GOOGLE_OAUTH_CONFIG_PATH = "googla_oauth_config.json"

DRY_RUN = False

FORMAT = '[%(asctime)s][%(levelname)s]: %(message)s'
logging.basicConfig(level=logging.INFO, format=FORMAT)
token_path = "token.json"


def save_oauth_code(oauth_code):
    if os.path.isfile(token_path) is True:
        f = open(token_path)
        data = json.load(f)
        f.close()
    else:
        data = {}

    data['oauth_code'] = oauth_code

    with open(token_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def load_oauth_code():
    if os.path.isfile(token_path) is False:
        return ""

    f = open(token_path)
    data = json.load(f)
    f.close()

    if 'oauth_code' in data.keys():
        return data['oauth_code']
    else:
        return ""


def save_refresh_token(refresh_token):
    if os.path.isfile(token_path) is True:
        f = open(token_path)
        data = json.load(f)
        f.close()
    else:
        data = {}

    data['refresh_token'] = refresh_token

    with open(token_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def load_refresh_token():
    if os.path.isfile(token_path) is False:
        return ""

    f = open(token_path)
    data = json.load(f)
    f.close()

    if 'refresh_token' in data.keys():
        return data['refresh_token']
    else:
        return ""


class GoogleOauth2:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.code = ""
        self.refresh_token = load_refresh_token()
        self.redirect_uri = "http://localhost:9527/auth/google/callback"
        self.expiry_time = time.time()

    def get_code(self):
        scope = "https://www.googleapis.com/auth/photoslibrary.readonly"
        # scope += "+https://www.googleapis.com/auth/photoslibrary.appendonly"
        # scope += "+https://www.googleapis.com/auth/photoslibrary.readonly.appcreateddata"
        # scope += "+https://www.googleapis.com/auth/photoslibrary.edit.appcreateddata"
        # scope += "+https://www.googleapis.com/auth/photoslibrary.sharing"

        url = "https://accounts.google.com/o/oauth2/v2/auth?response_type=code&"
        url += "scope="+scope+"&"
        url += "client_id="+self.client_id+"&"
        url += "redirect_uri="+self.redirect_uri+"&"
        url += "access_type=offline&prompt=consent"

        logging.info("Oauth2 URL: "+url)

        server = create_server(app, port=9527)

        def server_run():
            server.run()
        t = threading.Thread(target=server_run)

        save_oauth_code("")
        t.start()

        while load_oauth_code() == "":
            time.sleep(1)

        # server.close()
        logging.debug("oauth_code: "+load_oauth_code())

        return load_oauth_code()

    def get_access_token(self):
        if self.refresh_token != "":
            logging.debug("Using Refresh Token")
            p = {"refresh_token": self.refresh_token,
                 "client_id": self.client_id,
                 "client_secret": self.client_secret,
                 "grant_type": "refresh_token"}
        else:
            logging.info("New Authentication")
            p = {"code": self.get_code(),
                 "client_id": self.client_id,
                 "client_secret": self.client_secret,
                 "redirect_uri": self.redirect_uri,
                 "grant_type": "authorization_code",
                 "prompt": "consent"}

        x = requests.post(
            "https://www.googleapis.com/oauth2/v3/token", params=p)

        logging.debug(x.text)

        if self.refresh_token == "":
            self.refresh_token = x.json()['refresh_token']
            self.expiry_time = time.time() + x.json()['expires_in']
            save_refresh_token(self.refresh_token)

        return x.json()['access_token']


class PhotoApi:
    def __init__(self, access_token, expiry_time):
        self.access_token = access_token
        self.expiry_time = expiry_time
        self.endpoint = "https://photoslibrary.googleapis.com/"

    def listAlbum(self, pageToken=""):
        p = {"access_token": self.access_token}
        if pageToken != "":
            p['pageToken'] = pageToken
        x = requests.get(self.endpoint+"v1/albums", params=p)

        return x

    def listSharedAlbums(self, pageToken=""):
        p = {"access_token": self.access_token}
        if pageToken != "":
            p['pageToken'] = pageToken
        x = requests.get(self.endpoint+"v1/sharedAlbums", params=p)

        return x

    def listAlbumMedia(self, pageToken="", album_id=""):
        p = {"access_token": self.access_token}
        if pageToken != "":
            p['pageToken'] = pageToken
        data = {"pageSize": "100",
                "albumId": album_id}
        x = requests.post(
            self.endpoint+"v1/mediaItems:search", params=p, json=data)

        return x

    def downMedia(self, media, downPath):
        p = {"access_token": self.access_token}
        downUrl = media['baseUrl']+'=d'
        r = requests.get(downUrl, allow_redirects=True, params=p)
        open(downPath+'/'+media['filename'], 'wb').write(r.content)


app = Flask(__name__)


@app.route('/auth/google/callback')
def auth_google_callback():
    oauth_code = request.args.get('code')
    scope = request.args.get('scope')
    save_oauth_code(oauth_code)
    return "Auth. OK"


logging.info(">>> Google OAuth")
f = open(GOOGLE_OAUTH_CONFIG_PATH)
config = json.load(f)
f.close()
o2 = GoogleOauth2(config['client_id'], config['client_secret'])
access_token = o2.get_access_token()

api = PhotoApi(access_token, o2.expiry_time)

logging.info(">>> Listing Shared Albums")
nextPageToken = ""
albumList = []
while True:
    res = api.listSharedAlbums(nextPageToken)
    # print(res.text)
    for album in res.json()['sharedAlbums']:
        if 'title' in album.keys():
            albumList.append(album)
    if "nextPageToken" in res.json().keys():
        logging.debug("next page!")
        print(".", end="", flush=True)
        nextPageToken = res.json()['nextPageToken']
    else:
        break
if nextPageToken != "":
    print("")

if (len(albumList) == 0):
    logging.info("No Shared Album !")
    os.kill(os.getpid(), signal.SIGKILL)

for i in range(0, len(albumList)):
    logging.info("  "+str(i+1)+". "+albumList[i]['title'])

while True:
    idx = int(input("\nChoose which shared album to sync: "))
    if idx > 0 and idx <= len(albumList):
        albumSelected = albumList[idx-1]
        break
    else:
        logging.error("Invalid Index! Try Again.")

album_id = albumSelected['id']

logging.info(">>> Listing Media in the Album")
photoList = []
nextPageToken = ""
while True:
    res = api.listAlbumMedia(nextPageToken, album_id)
    for media in res.json()['mediaItems']:
        if 'filename' in media.keys():
            photoList.append(media)
    if "nextPageToken" in res.json().keys():
        logging.debug("next page!")
        print(".", end="", flush=True)
        nextPageToken = res.json()['nextPageToken']
    else:
        break
if nextPageToken != "":
    print("")

logging.info(">>> Listing Media in the WebDav")
f = open(WD_CONFIG_PATH)
wdConfig = json.load(f)
f.close()
wdOptions = {
    'webdav_hostname': wdConfig['webdav_hostname'],
    'webdav_login':    wdConfig['webdav_login'],
    'webdav_password': wdConfig['webdav_password'],
}
client = WdClient(wdOptions)
wdPhotoList = client.list(wdConfig['webdav_path'])

photoDownload = {}
for i in track(range(0, len(photoList)), description="Syncing..."):
    media = photoList[i]
    if media['filename'] not in wdPhotoList:
        os.system('mkdir -p downloads/')
        print("Sync the Media File: "+media['filename'])
        if DRY_RUN is True:
            continue
        api.downMedia(media, "downloads/")
        client.upload_sync(remote_path=wdConfig['webdav_path']+media['filename'],
                           local_path="downloads/"+media['filename'])
        os.system('rm '+"downloads/"+media['filename'])


# The web server is still open. kill the program itself as workaround.
os.kill(os.getpid(), signal.SIGKILL)
