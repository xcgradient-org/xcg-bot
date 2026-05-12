from bot.commands import log_command as _log_command

globals().update({name: getattr(_log_command, name) for name in dir(_log_command) if not name.startswith("__")})
