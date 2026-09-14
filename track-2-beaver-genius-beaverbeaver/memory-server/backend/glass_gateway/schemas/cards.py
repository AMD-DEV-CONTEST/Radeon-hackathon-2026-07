from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field


class WakeCardProps(BaseModel):
    title: str = "海狸"
    body: str = "我在听"


class ThinkingCardProps(BaseModel):
    title: str = "海狸"
    body: str = "思考中"


class AnswerCardProps(BaseModel):
    title: str = "海狸"
    body: str = Field(max_length=240)


class ErrorCardProps(BaseModel):
    title: str = "出错"
    body: str = Field(max_length=180)


class StatusCardProps(BaseModel):
    title: str = "状态"
    body: str = Field(max_length=180)


class WakeCard(BaseModel):
    id: str = "wake"
    kind: Literal["WakeCard"] = "WakeCard"
    ttl_ms: int = 8000
    props: WakeCardProps = WakeCardProps()


class ThinkingCard(BaseModel):
    id: str = "thinking"
    kind: Literal["ThinkingCard"] = "ThinkingCard"
    ttl_ms: int = 15000
    props: ThinkingCardProps = ThinkingCardProps()


class AnswerCard(BaseModel):
    id: str = "answer"
    kind: Literal["AnswerCard"] = "AnswerCard"
    ttl_ms: int = 30000
    props: AnswerCardProps


class ErrorCard(BaseModel):
    id: str = "error"
    kind: Literal["ErrorCard"] = "ErrorCard"
    ttl_ms: int = 6000
    props: ErrorCardProps


class StatusCard(BaseModel):
    id: str = "status"
    kind: Literal["StatusCard"] = "StatusCard"
    ttl_ms: int = 10000
    props: StatusCardProps


Card = Annotated[
    Union[WakeCard, ThinkingCard, AnswerCard, ErrorCard, StatusCard],
    Field(discriminator="kind"),
]


class UiPatch(BaseModel):
    type: Literal["ui.patch"] = "ui.patch"
    seq: int
    screen: str = "main"
    mode: Literal["replace"] = "replace"
    cards: list[Card]
