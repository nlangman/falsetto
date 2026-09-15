from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Message:
    thread_key: str | None
    body: str


@dataclass(frozen=True)
class Route:
    thread_key: str | None
    queue: str


def pick_route(msg: Message) -> Route:
    queue = "ops" if msg.body.startswith("ops:") else "general"
    return Route(thread_key=msg.thread_key, queue=queue)
