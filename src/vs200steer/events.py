from enum import Enum


class Tap(Enum):
    """A steering tap after the VS200 packet is decoded (before any swap mapping)."""

    LEFT = "left"
    RIGHT = "right"
