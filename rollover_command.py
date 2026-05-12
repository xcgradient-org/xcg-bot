from bot.commands import rollover_command as _rollover_command

globals().update({name: getattr(_rollover_command, name) for name in dir(_rollover_command) if not name.startswith("__")})
