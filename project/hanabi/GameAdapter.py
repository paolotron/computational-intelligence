import socket
import time
from abc import ABC, abstractmethod
from collections import UserDict
from typing import Union, List
from constants import *

import GameData
from enum import Enum

from knowledge import KnowledgeMap, Color


class HintType(Enum):
    NUMBER = 0
    COLOR = 1


# noinspection PyTypeChecker
class GameAdapter:
    """
    Class to play hanabi with a server.
    Use it in a for loop to iterate through the game
    """

    def __init__(self, name: str, *, ip: str = '127.0.0.1', port: int = 1026, datasize: int = 10240):
        """
        Initialize Game Manager creating a connection with the server
        @param name: Player Name
        @param ip: Host IP
        @param port: Process Port
        @param datasize: Size of the socket packets
        """
        self.name = name
        self.ip = ip
        self.port = port
        self.datasize = datasize
        self.move_history = []
        self.action = None
        self.game_end = False
        self.board_state = None
        self.board_state: GameData.ServerGameStateData
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        while True:
            try:
                self.socket.connect((ip, port))
                break
            except ConnectionRefusedError:
                time.sleep(0.001)
        self.socket.send(GameData.ClientPlayerAddData(name).serialize())
        assert type(GameData.GameData.deserialize(self.socket.recv(datasize))) is GameData.ServerPlayerConnectionOk
        print("Connection accepted by the server. Welcome " + name)
        print("[" + name + " - " + "Lobby" + "]: ", end="")
        self.socket.send(GameData.ClientPlayerStartRequest(name).serialize())
        data = GameData.GameData.deserialize(self.socket.recv(datasize))
        assert type(data) is GameData.ServerPlayerStartRequestAccepted
        # print("Ready: " + str(data.acceptedStartRequests) + "/" + str(data.connectedPlayers) + " players")
        data = GameData.GameData.deserialize(self.socket.recv(datasize))
        assert type(data) is GameData.ServerStartGameData
        self.socket.send(GameData.ClientPlayerReadyData(name).serialize())
        self.players = tuple(data.players)
        self.knowledgeMap = KnowledgeMap(list(self.players), self.name)
        time.sleep(0.01)

    def _request_state(self) -> GameData.ServerGameStateData:
        """
        Request Board State
        """
        data = GameData.ClientGetGameStateRequest(self.name)
        print(f"{self.name} DEBUG: {type(data)} PLAYER: {data.sender}")
        self.socket.send(data.serialize())
        while True:
            print(f"{self.name} STUCK IN REQUEST")
            request = GameData.GameData.deserialize(self.socket.recv(self.datasize))
            t = self._register_action(request)
            if t is GameData.ServerGameStateData:
                break
        print(f"{self.name} UNSTUCK, USED STORM TOKENS {self.board_state.usedStormTokens}")

    def __iter__(self):
        """
        create iterator for proceeding through the game
        @return: self
        """
        self.current = 0
        return self

    def __next__(self) -> KnowledgeMap:
        """
        next step in the iteration
        returns the current state of the board and the list of all moves
        @rtype: board_state, move_list
        """
        if self.game_end:
            raise StopIteration

        try:
            self._request_state()
        except ConnectionResetError:
            raise StopIteration
        while self.board_state.currentPlayer != self.name:
            try:
                response = GameData.GameData.deserialize(self.socket.recv(self.datasize))
                self._register_action(response)
                self._request_state()
            except ConnectionResetError:
                raise StopIteration

        self.knowledgeMap.updateHands(self.move_history, self.board_state)
        return self.knowledgeMap

    def _send_action(self, action: GameData.ClientToServerData):
        """
        send action to the socket
        @param action: GameData
        @return: GameData
        """
        self.socket.send(action.serialize())
        try:
            response = GameData.GameData.deserialize(self.socket.recv(self.datasize))
        except ConnectionResetError:
            raise StopIteration
        self._register_action(response)
        return response

    def _register_action(self, response: GameData.ServerToClientData):

        if type(response) is GameData.ServerGameStateData:
            response: GameData.ServerGameStateData
            self.board_state = response
            print(f"BOARDSTATE {self.name}: ", end='')
            print(f"{self.board_state.currentPlayer}")
        elif type(response) is GameData.ServerHintData:
            response: GameData.ServerHintData
            self.move_history.append(response)
        elif type(response) is GameData.ServerPlayerMoveOk or type(response) is GameData.ServerPlayerThunderStrike:
            response: GameData.ServerPlayerMoveOk
            self.move_history.append(response)
        elif type(response) is GameData.ServerActionValid:
            response: GameData.ServerActionValid
            self.move_history.append(response)
        elif type(response) is GameData.ServerGameOver:
            self.game_end = True
            raise StopIteration
        elif type(response) is GameData.ServerStartGameData:
            self.socket.send(GameData.ClientGetGameStateRequest(self.name).serialize())

        return type(response)

    def reset(self):
        self.move_history = []
        self.action = None
        self.game_end = False
        self.board_state = None
        self.knowledgeMap = KnowledgeMap(list(self.players), self.name)

    def get_all_players(self):
        """
        Get all players
        @return: tuple(str)
        """
        return list(self.players)

    def get_other_players(self):
        """
        Get all players but the playing one
        @return: tuple(str)
        """
        p = list(self.players)
        p.remove(self.name)
        return tuple(p)

    def send_hint(self, player: Union[str, int], type_h: HintType, val: Union[str, int]) -> bool:
        """
        Send a hint to a specific player
        @param player: player receiving the hint
        @param type_h: type of the hint to be sent
        @param val: value or colour
        @return: True if the hint was sent successfully
        """
        type_h = {HintType.NUMBER: 'value', HintType.COLOR: 'colour'}[type_h]
        try:
            result = self._send_action(GameData.ClientHintData(self.name, player, type_h, val))
        except StopIteration:
            return False

        if type(result) in [GameData.ServerActionInvalid, GameData.ServerInvalidDataReceived]:
            return False
        if type(result) is GameData.ServerHintData:
            return True
        raise ValueError

    def send_play_card(self, card_number: int) -> bool:
        """
        Play a card from hand
        @param card_number: index of the card
        @return: True if the card was correct False otherwise
        """
        try:
            result = self._send_action(GameData.ClientPlayerPlayCardRequest(self.name, card_number))
        except StopIteration:
            return False
        if type(result) is GameData.ServerPlayerMoveOk:
            return True
        if type(result) is GameData.ServerPlayerThunderStrike:
            return False
        raise ValueError

    def send_discard_card(self, card_number: int) -> bool:
        """
        Discard a card
        @param card_number: card index
        @return: if the card was successfully discarded
        """
        try:
            result = self._send_action(GameData.ClientPlayerDiscardCardRequest(self.name, card_number))
        except StopIteration:
            return False

        if type(result) is GameData.ServerActionValid:
            return True
        if type(result) is GameData.ServerActionInvalid:
            return False
        raise ValueError

    def end_game_data(self):
        points = sum([max(map(lambda x: x.value, cards), default=0) for cards in self.board_state.tableCards.values()])
        return {
            "n_turns": len(self.move_history),
            "points": points,
            "loss": self.board_state.usedStormTokens == 3
        }


class Player(ABC):

    def __init__(self, name: str, conn_params=None):
        self.name = name
        if conn_params is None:
            self.start_dict = {
                'name': name,
                'ip': HOST,
                'port': PORT,
                'datasize': DATASIZE,
            }
        else:
            self.start_dict = conn_params
        self.io = None

    @abstractmethod
    def make_action(self, state):
        pass

    def setup(self, *args, **kwargs):
        pass

    def cleanup(self):
        pass

    def end_game_data(self):
        return self.io.end_game_data()

    def start(self, *args, **kwargs):

        if self.io is None:
            self.io = GameAdapter(**self.start_dict)
        else:
            self.io.reset()

        self.setup(*args, **kwargs)
        for state in self.io:
            self.make_action(state)

        self.cleanup()
