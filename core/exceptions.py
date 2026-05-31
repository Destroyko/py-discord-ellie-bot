"""Domain-specific exceptions."""


class BotError(Exception):
    """Base exception for bot errors."""


class ConfigError(BotError):
    """Invalid or missing configuration."""


class ValidationError(BotError):
    """User input validation failed."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class PermissionDeniedError(BotError):
    """Moderator or bot lacks required permissions."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class TargetNotAllowedError(BotError):
    """Mute target is not allowed by policy."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class DiscordActionError(BotError):
    """Discord API action failed."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)
