""" Common/utility methods
no logging in this file because logging might not have been initialized yet
"""

from enum import Enum, auto
import pathlib
import sys
import ctypes
import time
import subprocess
import threading
import random
import string
import requests


class Folder:
    """Folder name consts"""

    MODEL = "models"
    BROWSER_DATA = "browser_data"
    RES = "resources"
    LOG = "log"
    MITM_CONF = "mitm_config"
    PROXINJECT = "proxinject"
    UPDATE = "update"
    TEMP = "temp"
    CHROME_EXT = "chrome_ext"


class GameClientType(Enum):
    """Game client type"""

    PLAYWRIGHT = auto()  # playwright browser
    PROXY = auto()  # other client through mitm proxy


class GameMode(Enum):
    """Game Modes for bots/models"""

    MJ4P = "4P"
    MJ3P = "3P"


# for automation
GAME_MODES = ["4E", "4S", "3E", "3S"]


class UiState(Enum):
    """UI State for the game"""

    NOT_RUNNING = 0
    MAIN_MENU = 1
    IN_GAME = 10
    GAME_ENDING = 20


# === Exceptions ===
class LocalModelException(Exception):
    """Exception for model file error"""


class BotNotSupportingMode(Exception):
    """Bot not supporting current mode"""

    def __init__(self, mode: GameMode):
        super().__init__(mode)


def error_to_str(error: Exception, lan="") -> str:
    """Convert error to language specific string"""
    if isinstance(error, LocalModelException):
        return lan.LOCAL_MODEL_ERROR
    elif isinstance(error, BotNotSupportingMode):
        return lan.MODEL_NOT_SUPPORT_MODE_ERROR + f" {error.args[0].value}"
    elif isinstance(error, requests.exceptions.ConnectionError):
        return lan.CONNECTION_ERROR + f": {error}"
    elif isinstance(error, requests.exceptions.ReadTimeout):
        return lan.CONNECTION_ERROR + f": {error}"
    else:
        return str(error)


def sub_folder(folder_name: str) -> pathlib.Path:
    """return the subfolder Path, create it if not exists"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = pathlib.Path(sys._MEIPASS).parent  # pylint: disable=W0212,E1101
    except Exception:  # pylint: disable=broad-except
        base_path = pathlib.Path(".")

    subfolder = base_path / folder_name
    if not subfolder.exists():
        subfolder.mkdir(exist_ok=True)
    return subfolder.resolve()


def sub_file(folder: str, file: str) -> str:
    """return the file absolute path string, given folder and filename, create the folder if not exists"""
    subfolder = sub_folder(folder)
    file_str = str((subfolder / file).resolve())
    return file_str


def wait_for_file(file: str, timeout: int = 5) -> bool:
    """Wait for file creation (blocking until the file exists) for {timeout} seconds
    returns:
        bool: True if file exists within timeout, False otherwise
    """
    # keep checking if the file exists until timeout
    start_time = time.time()
    while not pathlib.Path(file).exists():
        if time.time() - start_time > timeout:
            return False
        time.sleep(0.5)
    return True


def sub_run_args() -> dict:
    """return **args for subprocess.run"""
    startup_info = subprocess.STARTUPINFO()
    startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup_info.wShowWindow = subprocess.SW_HIDE
    args = {
        "capture_output": True,
        "text": True,
        "check": False,
        "shell": True,
        "startupinfo": startup_info,
    }
    return args


def list_children(
    folder: str, full_path: bool = False, incl_file: bool = True, incl_dir: bool = False
) -> list[pathlib.Path]:
    """return the list of children in the folder
    params:
        folder(str): name of the folder
        full_path(bool): True to return the full path, while False to return only the file name
        incl_file(bool): True to include files in the list
        incl_dir(bool): True to include directories in the list"""
    try:

        def to_include(f: pathlib.Path) -> bool:
            return (incl_file and f.is_file()) or (incl_dir and f.is_dir())

        files = [f for f in pathlib.Path(folder).iterdir() if to_include(f)]
        if full_path:
            return [str(f.resolve()) for f in files]
        else:
            return [f.name for f in files]
    except:  # pylint:disable=bare-except
        return []


def random_str(length: int) -> str:
    """Generate random string with specified length"""
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def set_dpi_awareness():
    """Set DPI Awareness"""
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # for Windows 8.1 and later
        except AttributeError:
            ctypes.windll.user32.SetProcessDPIAware()  # for Windows Vista and later
        except:  # pylint:disable=bare-except
            pass


ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


def prevent_sleep():
    """prevent system going into sleep/screen saver"""
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
        )


class FPSCounter:
    """Class for counting frames and calculating fps."""

    def __init__(self):
        self.lock = threading.Lock()
        self.timestamps = []  # List to hold timestamps of frame calls
        self.last_calc_time = time.time()  # Last time fps was calculated
        self.last_fps = 0  # Last calculated fps value

    def frame(self):
        """Indicates that a frame has been rendered or processed. Adds the current time to timestamps."""
        with self.lock:
            self.timestamps.append(time.time())

    def reset(self):
        """Resets the counter by clearing all recorded timestamps."""
        with self.lock:
            self.timestamps.clear()

    @property
    def fps(self):
        """Returns the current frames per second, calculated as the number of frames in the past second."""
        if time.time() - self.last_calc_time < 0.5:
            return self.last_fps
        with self.lock:
            # Filter out timestamps that are older than 1 second from the current time
            cur_time = time.time()
            self.timestamps = [t for t in self.timestamps if cur_time - t < 1]
            self.last_fps = len(self.timestamps)
            self.last_calc_time = cur_time
            return self.last_fps
