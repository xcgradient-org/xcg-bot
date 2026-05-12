from bot.commands import blocker_command as _blocker_command

globals().update({name: getattr(_blocker_command, name) for name in dir(_blocker_command) if not name.startswith("__")})
