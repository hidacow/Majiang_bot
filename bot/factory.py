""" Bot factory"""
from common.utils import Folder, sub_file
from .bot import Bot, GameMode
from .local.bot_local import BotMortalLocal

MODEL_TYPE_STRINGS = ["Local"]

def get_bot(model_path:str) -> Bot:
    """create the Bot instance based on settings"""

    model_files: dict = {
        GameMode.MJ4P: sub_file("", model_path)
    }
    bot = BotMortalLocal(model_files)

    return bot
