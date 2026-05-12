from bot.commands import meeting_command as _meeting_command

globals().update({name: getattr(_meeting_command, name) for name in dir(_meeting_command) if not name.startswith("__")})
