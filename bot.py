import os
import discord
from discord.ext import commands
import aiohttp
import asyncio
import datetime
import xml.etree.ElementTree as ET
import yfinance as yf

# Configuration - securely pulls token from GitHub Secrets
TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = 1570231995139887186
USER_PING_ID = 539685617966120990

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# SEC EDGAR Header Requirement (Configured with your bot name & email)
SEC_HEADERS = {
    'User-Agent': 'MicroCapScanner iluuraject@gmail.com',
    'Accept-Encoding': 'gzip, deflate'
}

# High-impact SEC filing forms to monitor
TARGET_FORMS = {'8-K', '424B5', 'S-1', 'S-3', 'SC 13D', 'SC 13G'}


async def get_cik_to_ticker_map(session):
    """Downloads the SEC's official CIK -> Ticker mapping JSON."""
    url = "https://www.sec.gov/files/company_tickers.json"
    async with session.get(url, headers=SEC_HEADERS) as resp:
        if resp.status != 200:
            print(f"Error fetching SEC tickers: HTTP {resp.status}")
            return {}
        data = await resp.json()
        # Pad CIKs to 10 digits with leading zeros to match EDGAR Atom feeds
        return {
            str(entry['cik_str']).zfill(10): {
                'ticker': entry['ticker'],
                'title': entry['title']
            }
            for entry in data.values()
        }


def check_market_filters(ticker_symbol):
    """
    Runs synchronous yfinance lookup to check your exact criteria:
    - Price < $1.00
    - Market Cap < $20,000,000
    - Float < 5,000,000 shares
    """
    try:
        stock = yf.Ticker(ticker_symbol)
        info = stock.info

        price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
        market_cap = info.get('marketCap')
        float_shares = info.get('floatShares')

        if not price or not market_cap:
            return None

        # Apply your strict micro-cap filters
        if price >= 1.00:
            return None
        if market_cap >= 20_000_000:
            return None
        if float_shares and float_shares >= 5_000_000:
            return None

        return {
            'price': float(price),
            'market_cap': market_cap,
            'float_str': f"{float_shares:,.0f}" if float_shares else "Unknown (<5M cap)",
            'volume': info.get('volume', 0)
        }
    except Exception:
        return None


async def fetch_market_catalysts():
    """
    Queries live SEC EDGAR latest filings feed, maps CIKs to tickers,
    and filters for sub-dollar, sub-$20M market cap, <5M float stocks.
    """
    findings = []
    seen_tickers = set()

    async with aiohttp.ClientSession() as session:
        cik_map = await get_cik_to_ticker_map(session)
        if not cik_map:
            return findings

        # Fetch the 100 most recent SEC filings across all public companies
        rss_url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&CIK=&type=&company=&dateb=&owner=include&start=0&count=100&output=atom"
        async with session.get(rss_url, headers=SEC_HEADERS) as resp:
            if resp.status != 200:
                print(f"SEC RSS fetch failed with status: {resp.status}")
                return findings
            xml_text = await resp.text()

        # Parse Atom XML feed
        root = ET.fromstring(xml_text)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        for entry in root.findall('atom:entry', ns):
            category = entry.find('atom:category', ns)
            form_type = category.attrib.get('term', '') if category is not None else ''

            if form_type not in TARGET_FORMS:
                continue

            title_text = entry.find('atom:title', ns).text or ''
            link_el = entry.find('atom:link', ns)
            filing_url = link_el.attrib.get('href', '') if link_el is not None else ''
            summary_text = entry.find('atom:summary', ns).text or ''

            # Extract 10-digit CIK from title formatted like: "8-K - Company Name (0001234567) (Filer)"
            cik = None
            for part in title_text.split('('):
                digits = part.split(')')[0].strip()
                if digits.isdigit() and len(digits) == 10:
                    cik = digits
                    break

            if not cik or cik not in cik_map:
                continue

            ticker = cik_map[cik]['ticker']
            company_name = cik_map[cik]['title']

            if ticker in seen_tickers:
                continue
            seen_tickers.add(ticker)

            # Run Yahoo Finance filter check in a non-blocking thread
            metrics = await asyncio.to_thread(check_market_filters, ticker)
            if not metrics:
                continue

            # Categorize filing type for quick visual scanning
            if form_type in {'424B5', 'S-1', 'S-3'}:
                catalyst_label = f"⚠️ Dilution / Offering Filing ({form_type})"
            elif "Item 3.01" in summary_text:
                catalyst_label = f"🚨 Nasdaq Delisting / Deficiency Notice ({form_type})"
            elif "Item 5.03" in summary_text or "Item 8.01" in summary_text:
                catalyst_label = f"⚡ Material Event / Potential Split ({form_type})"
            else:
                catalyst_label = f"📄 SEC Catalyst Filing ({form_type})"

            findings.append({
                'ticker': ticker,
                'company': company_name,
                'type': catalyst_label,
                'price': metrics['price'],
                'float': metrics['float_str'],
                'details': f"Market Cap: ${metrics['market_cap']:,.0f} | Vol: {metrics['volume']:,}\n[View SEC Filing]({filing_url})"
            })

            # Stay well within SEC EDGAR's 10 requests/second rate limit
            await asyncio.sleep(0.2)

    return findings


def build_alert_embed(alert):
    """Builds a clean Discord embed card for a detected micro-cap catalyst."""
    is_warning = "Delisting" in alert['type'] or "Dilution" in alert['type']
    embed = discord.Embed(
        title=f"🚨 Catalyst Alert: ${alert['ticker']} ({alert['company']})",
        description=f"**Catalyst Type:** {alert['type']}",
        color=discord.Color.red() if is_warning else discord.Color.gold()
    )
    embed.add_field(name="Current Price", value=f"${alert['price']:.4f}", inline=True)
    embed.add_field(name="Estimated Float", value=alert['float'], inline=True)
    embed.add_field(name="Details / Filing Summary", value=alert['details'], inline=False)
    embed.set_footer(text="Micro-Cap Momentum Scanner • Educational Only")
    return embed


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    channel = bot.get_channel(CHANNEL_ID)
    
    if channel:
        print(f"[{datetime.datetime.now()}] Running scheduled scan...")
        detected_alerts = await fetch_market_catalysts()

        if detected_alerts:
            for alert in detected_alerts:
                embed = build_alert_embed(alert)
                ping_message = f"<@{USER_PING_ID}> New micro-cap catalyst detected!"
                await channel.send(content=ping_message, embed=embed)
        else:
            # Matches your current heartbeat message format when no setups pass filters
            await channel.send(f"<@{USER_PING_ID}> 🔍 Scheduled background scan ran successfully! No new anomalies found.")
            
    # Close the bot connection so GitHub Actions finishes the job cleanly and shuts down
    await bot.close()


@bot.command(name='scan')
async def manual_scan(ctx):
    """Manually trigger a scan command from Discord chat."""
    await ctx.send("🔍 Manual scan initiated. Checking live SEC EDGAR filings & sub-dollar low-float trackers...")
    detected_alerts = await fetch_market_catalysts()

    if not detected_alerts:
        await ctx.send("Scan complete. No active filings meeting your strict `< $1.00` / `< $20M cap` / `< 5M float` criteria right now.")
        return

    for alert in detected_alerts:
        embed = build_alert_embed(alert)
        await ctx.send(content=f"<@{USER_PING_ID}>", embed=embed)


# Run the bot
if TOKEN:
    bot.run(TOKEN)
else:
    print("Error: DISCORD_TOKEN environment variable not found.")
