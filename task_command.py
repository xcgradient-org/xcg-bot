from bot.commands import task_command as _task_command

globals().update({name: getattr(_task_command, name) for name in dir(_task_command) if not name.startswith("__")})
