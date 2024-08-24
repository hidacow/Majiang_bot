import json
import re
import time
import logging


import common.mj_helper as mj_helper
from common.mj_helper import MjaiType, GameInfo, MJAI_WINDS

LOGGER = logging.getLogger("majiang")
from common.utils import GameMode
from bot import Bot


class KyokuState:
    """data class for kyoku info, will be reset every newround"""

    def __init__(self) -> None:
        self.bakaze: str = None  # Bakaze (場風)
        self.jikaze: str = None  # jikaze jifu (自风)
        self.kyoku: int = None  # Kyoku (局)
        self.honba: int = None  # Honba (本場)
        self.my_tehai: list = None  # list of tehai in mjai format
        self.my_tsumohai: str = None  # tsumohai in mjai format, or None
        self.doras_ms: list[str] = []  # list of doras in ms tile format

        ### flags
        self.pending_reach_acc: dict = None  # Pending MJAI reach accepted message
        self.first_round: bool = (
            True  # flag marking if it is the first move in new round
        )
        self.self_in_reach: bool = False  # if self is in reach state
        self.player_reach: list = [False] * 4  # list of player reach states


class GameState:
    """Stores Majsoul game state and processes inputs outputs to/from Bot"""

    def __init__(self, bot: Bot) -> None:
        """
        params:
            bot (Bot): Bot implemetation"""

        self.mjai_bot: Bot = bot  # mjai bot for generating reactions
        if self.mjai_bot is None:
            raise ValueError("Bot is None")
        self.mjai_pending_input_msgs = []  # input msgs to be fed into bot
        self.game_mode: GameMode = None  # Game mode

        ### Game info
        self.account_id = 0  # Majsoul account id
        self.mode_id: int = -1  # game mode
        self.seat = 0  # seat index
        # seat 0 is chiicha (起家; first dealer; first East)
        # 1-2-3 then goes counter-clockwise
        self.player_scores: list = None  # player scores
        self.kyoku_state: KyokuState = (
            KyokuState()
        )  # kyoku info - cleared every newround

        ### about last reaction
        self.last_reaction: dict = None  # last bot output reaction
        self.last_reaction_pending: bool = (
            True  # reaction pending until there is new maa msg indicating the reaction is done/expired
        )
        self.last_reaction_time: float = None  # last bot reaction calculation time
        self.last_operation: dict = None
        self.last_op_step: int = None  # maa msg 'seq' element

        ### Internal Status flags
        self.is_bot_calculating: bool = False  # if bot is calculating reaction
        self.is_ms_syncing: bool = (
            False  # if mjai_bot is running syncing from MS (after disconnection)
        )
        self.is_round_started: bool = False
        """ if any new round has started (so game info is available)"""
        self.is_game_ended: bool = False  # if game has ended

    def get_game_info(self) -> GameInfo:
        """Return game info. Return None if N/A"""
        if self.is_round_started:
            gi = GameInfo(
                bakaze=self.kyoku_state.bakaze,
                jikaze=self.kyoku_state.jikaze,
                kyoku=self.kyoku_state.kyoku,
                honba=self.kyoku_state.honba,
                my_tehai=self.kyoku_state.my_tehai,
                my_tsumohai=self.kyoku_state.my_tsumohai,
                self_reached=self.kyoku_state.self_in_reach,
                self_seat=self.seat,
                player_reached=self.kyoku_state.player_reach.copy(),
                is_first_round=self.kyoku_state.first_round,
            )
            return gi
        else:  # if game not started: None
            return None

    # def _update_info_from_bot(self):
    #     if self.is_round_started:
    #         self.my_tehai, self.my_tsumohai = self.mjai_bot.get_hand_info()

    def get_pending_reaction(self) -> dict:
        """Return the last pending reaction (not acted on)
        returns:
            dict | None: mjai action, or None if no pending reaction"""
        if self.is_ms_syncing:
            return None
        if self.last_reaction_pending:
            return self.last_reaction
        else:
            return None

    def input(self, majiang_msg: dict) -> dict | None:
        """Input majiang msg for processing and return result MJAI msg if any.

        params:
            majiang_msg(dict): parsed majiang message in majiang dict format
        returns:
            dict: Mjai message in dict format (i.e. AI's reaction) if any. May be None.
        """
        self.is_bot_calculating = True
        start_time = time.time()
        reaction = self._input_inner(majiang_msg)
        time_used = time.time() - start_time
        if reaction is not None:
            # Update last_reaction (not none) and set it to pending
            self.last_reaction = reaction
            self.last_reaction_pending = True
            self.last_reaction_time = time_used
        self.is_bot_calculating = False
        return reaction

    def trans_mjai_react(self, reaction: dict) -> dict:
        """Translate mjai reaction to majiang dict format

        params:
            reaction(dict): mjai reaction in dict format
        returns:
            dict: Translated mjai reaction in majiang dict format
        """
        if reaction is None:
            return {"seq": self.last_op_step}
        re_type = reaction["type"]
        if re_type == MjaiType.NONE:
            return {"seq": self.last_op_step}
        elif re_type == MjaiType.DAHAI:
            pai = mj_helper.cvt_mjai2maa(reaction["pai"])
            if reaction["tsumogiri"]:
                pai += "_"
            return {"dapai": pai, "seq": self.last_op_step}
        elif re_type in [MjaiType.CHI, MjaiType.PON, MjaiType.DAIMINKAN]:
            actor = reaction["actor"]
            target = reaction["target"]
            pai = mj_helper.cvt_mjai2maa(reaction["pai"])
            consumed = sorted(
                [mj_helper.cvt_mjai2maa(x)[-1] for x in reaction["consumed"]]
            )
            # 0(red 5) should be placed after 5
            if consumed[0] == "0":
                consumed = consumed[1:] + ["0"]
            mark = ""
            if (actor + 1) % 4 == target:
                mark = "+"  # shimo
            elif (actor + 2) % 4 == target:
                mark = "="  # toimen
            elif (actor + 3) % 4 == target:
                mark = "-"  # kami
            if re_type == MjaiType.CHI:
                consumed.append(pai[1])
                consumed.sort()
                res = f"{pai[0]}{''.join(consumed)}"
                i_pai = res.find(pai[1]) + 1
                res = f"{res[:i_pai]}{mark}{res[i_pai:]}"
            else:
                res = f"{pai[0]}{''.join(consumed)}{pai[1]}{mark}"
            return {"fulou": res, "seq": self.last_op_step}
        elif re_type == MjaiType.ANKAN:
            pai = mj_helper.cvt_mjai2maa(reaction["consumed"][0])
            p_num = pai[-1]
            if p_num == "0" or p_num == "5":
                p = f"{pai[0]}5550"
            else:
                p = f"{pai[0]}{p_num*4}"
            return {"gang": p, "seq": self.last_op_step}
        elif re_type == MjaiType.KAKAN:
            # - is the current mark for any cases
            pai = mj_helper.cvt_mjai2maa(reaction["pai"])
            consumed = sorted(
                [mj_helper.cvt_mjai2maa(x)[-1] for x in reaction["consumed"]]
            )
            # 0(red 5) should be placed after 5
            if consumed[0] == "0":
                consumed = consumed[1:] + ["0"]
            res = f"{pai[0]}{''.join(consumed)}-{pai[1]}"
        elif re_type == MjaiType.REACH:
            reach_dahai_reaction = reaction["reach_dahai"]
            assert reach_dahai_reaction["type"] == MjaiType.DAHAI
            pai = mj_helper.cvt_mjai2maa(reach_dahai_reaction["pai"])
            if reach_dahai_reaction["tsumogiri"]:
                pai += "_"
            return {"dapai": pai + "*", "seq": self.last_op_step}
        elif re_type == MjaiType.HORA:
            return {"hule": "-", "seq": self.last_op_step}
        elif re_type == MjaiType.RYUKYOKU:
            return {"daopai": "-", "seq": self.last_op_step}
        else:
            LOGGER.warning("Unexpected reaction type: %s", re_type)
            return None

    def _input_inner(self, majiang_msg: dict) -> dict | None:
        print("[GameState]: ", majiang_msg)
        avail_types = {
            "kaiju",
            "qipai",
            "zimo",
            "dapai",
            "fulou",
            "gang",
            "gangzimo",
            "kaigang",
            "hule",
            "pingju",
            "jieju",
        }
        majiang_type = list(majiang_msg.keys())[0]
        # assert majiang_type in avail_types
        if majiang_type not in avail_types:
            print("[GameState]: Unexpected message: ")
            return None
        seq = majiang_msg["seq"]
        self.last_op_step = seq
        # Game Start
        if majiang_type == "kaiju":
            self.account_id = majiang_msg["kaiju"]["id"]
            return self.ms_auth_game(majiang_msg["kaiju"])

        elif majiang_type == "jieju":
            self.is_game_ended = True
            return None
        # Actions
        else:
            self.last_reaction_pending = False
            if majiang_type == "qipai":
                self.kyoku_state.first_round = True
                return self.ms_new_round(majiang_msg["qipai"])
            else:
                self.kyoku_state.first_round = False
                return self.ms_action_prototype(majiang_type, majiang_msg[majiang_type])

    def ms_action_prototype(self, majiang_type: str, majiang_data: dict) -> dict:
        # when there is new action, accept reach, unless it is agari
        if not majiang_type == "hule":
            if self.kyoku_state.pending_reach_acc is not None:
                self.mjai_pending_input_msgs.append(self.kyoku_state.pending_reach_acc)
                self.kyoku_state.pending_reach_acc = None

        # Process dora events
        # According to mjai.app, in the case of an ankan, the dora event comes first, followed by the tsumo event.
        if majiang_type == "kaigang":
            self.mjai_pending_input_msgs.append(
                {
                    "type": MjaiType.DORA,
                    "dora_marker": mj_helper.cvt_majiang2mjai(majiang_data["doras"]),
                }
            )
            self.kyoku_state.doras_ms = majiang_data["doras"]  # never mind the format
            return self._react_all(majiang_data)

        if majiang_type == "zimo" or majiang_type == "gangzimo":
            actor = (majiang_data["l"] + self.kyoku_state.kyoku - 1) % 4
            if majiang_data["p"] == "":  # other player's tsumo
                tile_mjai = "?"
            else:  # my tsumo
                tile_mjai = mj_helper.cvt_majiang2mjai(majiang_data["p"])
                self.kyoku_state.my_tsumohai = tile_mjai
            self.mjai_pending_input_msgs.append(
                {"type": MjaiType.TSUMO, "actor": actor, "pai": tile_mjai}
            )
            return self._react_all(majiang_data)

        # https://github.com/kobalab/majiang-core/wiki/%E7%89%8C
        # dapai -> MJAI DAHAI/REACH
        if majiang_type == "dapai":
            actor = (majiang_data["l"] + self.kyoku_state.kyoku - 1) % 4
            tile_majiang = majiang_data["p"][:2]
            tile_mjai = mj_helper.cvt_majiang2mjai(tile_majiang)

            tsumogiri = "_" in majiang_data["p"]
            if actor == self.seat:
                if self.kyoku_state.my_tsumohai:
                    self.kyoku_state.my_tehai.append(self.kyoku_state.my_tsumohai)
                    self.kyoku_state.my_tsumohai = None
                self.kyoku_state.my_tehai.remove(tile_mjai)
                self.kyoku_state.my_tehai = mj_helper.sort_mjai_tiles(
                    self.kyoku_state.my_tehai
                )

            if "*" in majiang_data["p"]:  # Player declares reach
                if actor == self.seat:  # self reach
                    self.kyoku_state.self_in_reach = True

                self.kyoku_state.player_reach[actor] = True
                self.mjai_pending_input_msgs.append(
                    {"type": MjaiType.REACH, "actor": actor}
                )
                # VERIFY: pending reach accept msg for mjai. this msg will be sent when next action msg is received
                self.kyoku_state.pending_reach_acc = {
                    "type": MjaiType.REACH_ACCEPTED,
                    "actor": actor,
                }

            self.mjai_pending_input_msgs.append(
                {
                    "type": MjaiType.DAHAI,
                    "actor": actor,
                    "pai": tile_mjai,
                    "tsumogiri": tsumogiri,
                }
            )

            return self._react_all(majiang_data)

        # https://github.com/kobalab/majiang-core/wiki/%E9%9D%A2%E5%AD%90
        # fulou -> MJAI CHI/PON/DAIMINKAN
        if majiang_type == "fulou":
            actor = (majiang_data["l"] + self.kyoku_state.kyoku - 1) % 4
            target = actor
            consumed_mjai = []
            tile_mjai = ""
            if "+" in majiang_data["m"]:  # shimo
                target = (actor + 1) % 4
            elif "=" in majiang_data["m"]:  # toimen
                target = (actor + 2) % 4
            elif "-" in majiang_data["m"]:  # kami
                target = (actor + 3) % 4
            # m1-23: 萬子一二三を一でチー
            # s505=: 五索を赤ありで対面からポン
            # s5550+: 赤五索で下家から大明槓
            for ch in majiang_data["m"][1:]:
                if ch in ["+", "=", "-"]:
                    tile_mjai = consumed_mjai.pop()
                    continue
                consumed_mjai.append(
                    mj_helper.cvt_majiang2mjai(majiang_data["m"][0] + ch)
                )
            if actor == self.seat:
                for c in consumed_mjai:
                    self.kyoku_state.my_tehai.remove(c)
                self.kyoku_state.my_tehai = mj_helper.sort_mjai_tiles(
                    self.kyoku_state.my_tehai
                )

            action_type = -1
            if len(consumed_mjai) == 3:
                action_type = MjaiType.DAIMINKAN
            elif len(consumed_mjai) == 2:
                if consumed_mjai[0] == consumed_mjai[1]:
                    action_type = MjaiType.PON
                else:
                    action_type = MjaiType.CHI
            else:
                raise RuntimeError(f"Unexpected fulou tiles: {majiang_data['m']}")
            self.mjai_pending_input_msgs.append(
                {
                    "type": action_type,
                    "actor": actor,
                    "target": target,
                    "pai": tile_mjai,
                    "consumed": consumed_mjai,
                }
            )
            return self._react_all(majiang_data)

        # gang -> MJAI ANKAN / KAKAN
        if majiang_type == "gang":
            action_type = -1
            actor = (majiang_data["l"] + self.kyoku_state.kyoku - 1) % 4
            consumed_mjai = []
            if len(majiang_data["m"]) == 5:  # e.g. p5550: 五筒を暗槓
                action_type = MjaiType.ANKAN
                for ch in majiang_data["m"][1:]:
                    consumed_mjai.append(
                        mj_helper.cvt_majiang2mjai(majiang_data["m"][0] + ch)
                    )
                self.mjai_pending_input_msgs.append(
                    {"type": action_type, "actor": actor, "consumed": consumed_mjai}
                )
            elif len(majiang_data["m"]) == 6:  # e.g. z666-6: 發を加槓
                action_type = MjaiType.KAKAN
                for ch in majiang_data["m"][1:]:
                    consumed_mjai.append(
                        mj_helper.cvt_majiang2mjai(majiang_data["m"][0] + ch)
                    )
                pai = consumed_mjai.pop()
                self.mjai_pending_input_msgs.append(
                    {
                        "type": action_type,
                        "actor": actor,
                        "pai": pai,
                        "consumed": consumed_mjai,
                    }
                )
            else:
                raise RuntimeError(f"Unexpected gang tiles: {majiang_data['m']}")

            if actor == self.seat:
                self.kyoku_state.my_tehai.append(self.kyoku_state.my_tsumohai)
                self.kyoku_state.my_tsumohai = None
                if action_type == MjaiType.ANKAN:
                    for c in consumed_mjai:
                        self.kyoku_state.my_tehai.remove(c)
                else:
                    self.kyoku_state.my_tehai.remove(pai)
                self.kyoku_state.my_tehai = mj_helper.sort_mjai_tiles(
                    self.kyoku_state.my_tehai
                )

            return self._react_all(majiang_data)

        # hule -> MJAI END_KYOKU
        if majiang_type == "hule":
            return self.ms_end_kyoku()

        # pingju -> MJAI END_KYOKU
        if majiang_type == "pingju":
            return self.ms_end_kyoku()

        LOGGER.warning("Unexpected majiang_type: %s", majiang_type)
        return None

    def ms_new_round(self, majiang_data: dict) -> dict:
        """Start kyoku"""
        self.kyoku_state = KyokuState()
        self.mjai_pending_input_msgs = []

        self.kyoku_state.bakaze = MJAI_WINDS[majiang_data["zhuangfeng"]]
        dora_marker = mj_helper.cvt_majiang2mjai(majiang_data["baopai"])
        self.kyoku_state.doras_ms = [dora_marker]
        self.kyoku_state.honba = majiang_data["changbang"]
        oya = majiang_data["jushu"]  # oya is also the seat id of East
        self.kyoku_state.kyoku = oya + 1
        self.kyoku_state.jikaze = MJAI_WINDS[(self.seat - oya)]
        kyotaku = majiang_data["lizhibang"]
        self.player_scores = majiang_data["defen"]
        if self.game_mode in [GameMode.MJ3P]:
            self.player_scores = self.player_scores + [0]
        tehais_mjai = [["?"] * 13] * 4

        my_tehai_majiang_str = majiang_data["shoupai"][(self.seat - oya)]
        assert my_tehai_majiang_str != ""
        my_tehai_majiang = mj_helper.cvt_majiang_tehai_lst(my_tehai_majiang_str)
        self.kyoku_state.my_tehai = [
            mj_helper.cvt_majiang2mjai(tile) for tile in my_tehai_majiang
        ]
        self.kyoku_state.my_tehai = mj_helper.sort_mjai_tiles(self.kyoku_state.my_tehai)

        tehais_mjai[self.seat] = self.kyoku_state.my_tehai
        # mjai accepts 13 tiles + following tsumohai event
        # Majiang is the same as mjai, different from majsoul
        assert len(self.kyoku_state.my_tehai) == 13

        # append messages and react
        start_kyoku_msg = {
            "type": MjaiType.START_KYOKU,
            "bakaze": self.kyoku_state.bakaze,
            "dora_marker": dora_marker,
            "honba": self.kyoku_state.honba,
            "kyoku": self.kyoku_state.kyoku,
            "kyotaku": kyotaku,
            "oya": oya,
            "scores": self.player_scores,
            "tehais": tehais_mjai,
        }
        self.mjai_pending_input_msgs.append(start_kyoku_msg)

        self.is_round_started = True
        return self._react_all(majiang_data)

    def ms_auth_game(self, majiang_data: dict) -> dict:
        self.mode_id = -1
        seatList: list = majiang_data["player"]
        if not seatList:
            LOGGER.debug("No seatList in majiang_data, game has likely ended")
            self.is_game_ended = True
            return None
        if len(seatList) == 4:
            self.game_mode = GameMode.MJ4P
        elif len(seatList) == 3:
            self.game_mode = GameMode.MJ3P
        else:
            raise RuntimeError(f"Unexpected seat len:{len(seatList)}")
        LOGGER.info("Game Mode: %s", self.game_mode.name)
        self.seat = (majiang_data["id"] - majiang_data["qijia"] + 4) % 4
        self.mjai_bot.init_bot(self.seat, self.game_mode)
        # Start_game has no effect for mjai bot, omit here
        self.mjai_pending_input_msgs.append(
            {"type": MjaiType.START_GAME, "id": self.seat}
        )
        self._react_all()
        return None  # no reaction for start_game

    def ms_end_kyoku(self) -> dict | None:
        """End kyoku and get None as reaction"""
        self.mjai_pending_input_msgs = []
        # self.mjai_pending_input_msgs.append(
        #     {
        #         'type': MJAI_TYPE.END_KYOKU
        #     }
        # )
        # self._react_all()
        return None  # no reaction for end_kyoku

    def ms_game_end_results(self, majiang_data: dict) -> dict:
        """End game in normal way (getting results)"""
        if "result" in majiang_data:
            # process end result
            pass

        # self.mjai_pending_input_msgs.append(
        #     {
        #         'type': MJAI_TYPE.END_GAME
        #     }
        # )
        # self._react_all()
        self.is_game_ended = True
        return None  # no reaction for end_game

    def _react_all(self, data=None) -> dict | None:
        """Feed all pending messages to AI bot and get bot reaction
        ref: https://mjai.app/docs/mjai-protocol
        returns:
            dict: the last reaction(output) from bot, or None
        """
        try:
            if len(self.mjai_pending_input_msgs) == 1:
                print("[Bot in]:", self.mjai_pending_input_msgs[0])
                LOGGER.info("Bot in: %s", self.mjai_pending_input_msgs[0])
                output_reaction = self.mjai_bot.react(self.mjai_pending_input_msgs[0])
            else:
                print(
                    "[Bot in]:", "\n".join(str(m) for m in self.mjai_pending_input_msgs)
                )
                LOGGER.info(
                    "Bot in (batch):\n%s",
                    "\n".join(str(m) for m in self.mjai_pending_input_msgs),
                )
                output_reaction = self.mjai_bot.react_batch(
                    self.mjai_pending_input_msgs
                )
        except Exception as e:
            LOGGER.error("Bot react error: %s", e, exc_info=True)
            output_reaction = None
        self.mjai_pending_input_msgs = []  # clear intput queue

        if output_reaction is None:
            return None
        else:
            LOGGER.info("Bot out: %s", output_reaction)
            if self.game_mode == GameMode.MJ3P:
                is_3p = True
            else:
                is_3p = False

            # reaction_convert_meta(output_reaction,is_3p)
            return output_reaction
