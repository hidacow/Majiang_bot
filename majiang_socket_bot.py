from dataclasses import dataclass
import threading
import socketio
import requests
import random
import string
import time
from bot import Bot, get_bot
from game_state import GameState
import argparse


def generate_random_name(length=5):
    letters = string.ascii_letters
    return "Mortal_" + "".join([random.choice(letters) for _ in range(length)])


@dataclass
class MajiangBotSetting:
    server: str = "https://kobalab.net/"
    apppath: str = "majiang/"
    modelpath: str = "model.pth"


class MajiangBot:
    sio: socketio.Client = None
    server: str = ""
    authpath: str = ""
    socketpath: str = ""
    bot: Bot = None
    game: GameState = None
    myuid = ""
    myname = ""
    is_in_room = False
    is_in_game = False
    room = ""
    session: requests.Session = None

    def __init__(self, setting: MajiangBotSetting, room=""):
        self.server = setting.server
        self.authpath = setting.apppath + "server/auth/"
        self.socketpath = setting.apppath + "server/socket.io/"
        self.bot = get_bot(setting.modelpath)
        self.game = GameState(self.bot)
        self.room = room

    def loop(self):
        self.sio.wait()

    def start(self):
        # self.session.verify = False
        self.myname = generate_random_name(4)
        print("Starting bot:", self.myname)
        self.session = requests.Session()
        r = self.session.post(
            self.server + self.authpath, data={"name": self.myname, "passwd": "*"}
        )
        if not r.status_code in [200, 302]:
            print(r.status_code, r.text)
            raise Exception(
                "Failed to auth on the server: " + self.server + self.authpath
            )
        time.sleep(1)
        self.sio = socketio.Client(http_session=self.session)
        self.callbacks()
        self.sio.connect(self.server, socketio_path=self.socketpath)
        self.loop()
        return 0

    def callbacks(self):
        @self.sio.event
        def connect():
            print(self.myname, "Connected to server:", self.server)
            if self.room:
                self.sio.emit("ROOM", self.room)
            else:
                self.sio.emit("ROOM")

        @self.sio.event
        def connect_error(data):
            print(self.myname, ": connection failed!", data)

        @self.sio.event
        def disconnect():
            print(self.myname, "is disconnected!")

        @self.sio.on("HELLO")
        def on_hello(data):
            print(self.myname, ": HELLO received:", data)
            self.is_in_room = False
            if not data:
                print(self.myname, "Login failed!")
                self.sio.disconnect()
            else:
                if self.myuid and "offline" in data.keys():
                    print(self.myname, "get kicked out")
                    self.sio.disconnect()
                else:
                    self.myuid = data["uid"]
                # print(self.myname,"User ID:", self.myuid)

        @self.sio.on("ROOM")
        def on_room(data):
            print(self.myname, "ROOM received:", data)
            self.is_in_room = True

        @self.sio.on("START")
        def on_start():
            self.is_in_game = True
            print(self.myname, "START received")

        @self.sio.on("END")
        def on_end(data):
            print(self.myname, "END received:", data)
            self.is_in_game = False
            self.is_in_room = False
            self.sio.disconnect()

        @self.sio.on("ERROR")
        def on_error(data):
            print(self.myname, "ERROR received:", data)
            self.sio.disconnect()

        @self.sio.on("GAME")
        def on_game(data):
            if "players" in data.keys():
                print(self.myname, "GAME received:", data)
                return
            # msg = json.loads(data)
            # print(game.input(msg))
            mjai_react = self.game.input(data)
            reaction = self.game.trans_mjai_react(mjai_react)
            print(mjai_react, reaction)
            self.sio.emit("GAME", reaction)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--number", help="number of bots", type=int, default=3)
    parser.add_argument(
        "-p",
        "--modelpath",
        help="path to the local Mortal model",
        type=str,
        default="model.pth",
    )
    parser.add_argument("-r", "--room", help="room name", type=str)
    parser.add_argument(
        "-s",
        "--server",
        help="server address",
        type=str,
        default="https://kobalab.net/",
    )
    parser.add_argument(
        "-a", "--apppath", help="app path on the server", type=str, default="majiang/"
    )
    args = parser.parse_args()
    print(args)
    if args.number not in [1, 2, 3]:
        raise Exception("Number of bots should be 1 ~ 3")
    setting = MajiangBotSetting(
        server=args.server, apppath=args.apppath, modelpath=args.modelpath
    )
    bots = [MajiangBot(setting, args.room) for _ in range(args.number)]
    threads = [threading.Thread(target=b.start) for b in bots]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
