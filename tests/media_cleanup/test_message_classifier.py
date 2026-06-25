"""Tests for media vs text message classification."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import discord
import pytest

from modules.media_cleanup.service import is_media_message, is_text_message


def _message(
    *,
    attachments: list[object] | None = None,
    embed_types: list[str | None] | None = None,
) -> MagicMock:
    message = MagicMock(spec=discord.Message)
    message.attachments = attachments or []
    embeds = []
    for embed_type in embed_types or []:
        embed = MagicMock(spec=discord.Embed)
        embed.type = embed_type
        embeds.append(embed)
    message.embeds = embeds
    return message


class TestMessageClassifier:
    def test_attachment_is_media(self) -> None:
        message = _message(attachments=[SimpleNamespace()])
        assert is_media_message(message) is True
        assert is_text_message(message) is False

    def test_image_embed_is_media(self) -> None:
        message = _message(embed_types=["image"])
        assert is_media_message(message) is True

    def test_video_embed_is_media(self) -> None:
        message = _message(embed_types=["video"])
        assert is_media_message(message) is True

    def test_gifv_embed_is_media(self) -> None:
        message = _message(embed_types=["gifv"])
        assert is_media_message(message) is True

    def test_rich_embed_is_text(self) -> None:
        message = _message(embed_types=["rich"])
        assert is_media_message(message) is False
        assert is_text_message(message) is True

    def test_empty_message_is_text(self) -> None:
        message = _message()
        assert is_text_message(message) is True

    def test_attachment_wins_over_text_embed(self) -> None:
        message = _message(
            attachments=[SimpleNamespace()],
            embed_types=["rich"],
        )
        assert is_media_message(message) is True

    @pytest.mark.parametrize("embed_type", ["link", "article", None])
    def test_non_media_embed_types_are_text(self, embed_type: str | None) -> None:
        message = _message(embed_types=[embed_type])
        assert is_media_message(message) is False
