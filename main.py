"""Entry point: config, bot instance, wiring. All logic lives in the modules."""
import discord
from discord.ext import commands as discord_commands

import config
import commands
import db
import handlers


class DailyScoreBot(discord_commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        db.init_db()
        await self.tree.sync()
        print("Database initialized & Slash commands synced.")


bot = DailyScoreBot()
handlers.register(bot)
commands.register(bot)

if __name__ == "__main__":
    bot.run(config.BOT_TOKEN)
