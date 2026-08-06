import base64
from dataclasses import dataclass, field


@dataclass
class AudioTurn:
    turn_id: str
    chunks: dict[int, bytes] = field(default_factory=dict)

    def add_chunk(self, index: int, data_b64: str) -> None:
        self.chunks[index] = base64.b64decode(data_b64)

    def pcm_bytes(self) -> bytes:
        return b"".join(self.chunks[index] for index in sorted(self.chunks))


class AudioTurnManager:
    def __init__(self) -> None:
        self._turns: dict[str, AudioTurn] = {}

    def start(self, turn_id: str) -> AudioTurn:
        turn = AudioTurn(turn_id=turn_id)
        self._turns[turn_id] = turn
        return turn

    def get(self, turn_id: str) -> AudioTurn | None:
        return self._turns.get(turn_id)

    def add_chunk(self, turn_id: str, index: int, data_b64: str) -> None:
        turn = self._turns.setdefault(turn_id, AudioTurn(turn_id=turn_id))
        turn.add_chunk(index, data_b64)

    def finish(self, turn_id: str) -> bytes:
        turn = self._turns.pop(turn_id, AudioTurn(turn_id=turn_id))
        return turn.pcm_bytes()
