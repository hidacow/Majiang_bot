from bot import Bot, get_bot
from game_state import GameState

bot = get_bot("D:/tenhoulog/model_v4_20240308_best_min.pth")
gametest = GameState(bot)
print(gametest.trans_mjai_react({"type":"kakan","actor":0,"pai":"6m","consumed":["6m","6m","6m"]}))