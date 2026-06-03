from enum import StrEnum


class SpecRole(StrEnum):
    BLUE = "blue"
    RED = "red"
    REFEREE = "referee"
    CREATE_GAME = "create_game"
    DECOMPOSE = "decompose"
    CREATE_GAME_RED = "create_game_red"
    SUMMARIZE = "summarize"
