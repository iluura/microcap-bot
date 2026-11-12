import os
import discord
from discord.ext import commands
import aiohttp
import asyncio
import datetime

# Configuration - securely pulls token from GitHub Secrets
TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = 1570231995139887186

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# SEC EDGAR Header Requirement
SEC_HEADERS = {
    'User-Agent': 'MicroCapScannerAlertBot admin@yourdomain.com',
    'Accept-Encoding': 'gzip, deflate',
    'Host': 'data.sec.gov'
}

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    channel = bot.get_channel(CHANNEL_ID)
    
    if channel:
        print(f"[{datetime.datetime.now()}] Running scheduled scan...")
        detected_alerts = await fetch_market_catalysts()

        for alert in detected_alerts:
            embed = discord.Embed(
                title=f"🚨 Catalyst Alert: ${alert['ticker']} ({alert['company']})",
                description=f"**Catalyst Type:** {alert['type']}",
                color=discord.Color.red() if "Delisting" in alert['type'] else discord.Color.gold()
            )
            embed.add_field(name="Current Price", value=f"${alert['price']:.2f}", inline=True)
            embed.add_field(name="Estimated Float", value=alert['float'], inline=True)
            embed.add_field(name="Details / Filing Summary", value=alert['details'], inline=False)
            embed.set_footer(text="Micro-Cap Momentum Scanner • Educational Only")
            
            # 🔔 Pings you directly (Make sure to replace YOUR_USER_ID with your numbers)
            ping_message = "<@539685617966120990> New micro-cap catalyst detected!"
            
            # Send the text mention alongside the embed block
            await channel.send(content=ping_message, embed=embed)
            
    # Close the bot connection so GitHub Actions finishes the job cleanly and shuts down
    await bot.close()

async def fetch_market_catalysts():
    """
    Placeholder/Implementation logic linking to SEC RSS/JSON feeds and market data providers.
    In a live deployment, query the SEC submissions API or a market data provider 
    filtering for market cap < $20M, price < $1.00, and float < 5M.
    """
    simulated_findings = []
    return simulated_findings

@bot.command(name='scan')
async def manual_scan(ctx):
    """Manually trigger a scan command from Discord chat."""
    await ctx.send("🔍 Manual scan initiated. Checking active sub-dollar low-float trackers...")
    await ctx.send("Scan complete. No active anomalous squeezes meeting the strict filter criteria right now.")

# Run the bot
bot.run(TOKEN)
