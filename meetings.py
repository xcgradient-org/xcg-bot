from bot.commands import meetings as _meetings

globals().update({name: getattr(_meetings, name) for name in dir(_meetings) if not name.startswith("__")})
