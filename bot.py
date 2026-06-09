import os
import discord
from discord.ext import commands
import asyncio
import config
from aiohttp import web
import yt_dlp
import asyncio
import re

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=config.PREFIX, intents=intents, help_command=None)

ydl_opts = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "extract_flat": False,
    "skip_download": True,
    "default_search": "ytsearch",
}

queues = {}

async def healthcheck(request):
    return web.Response(text="ok")

async def run_http():
    app = web.Application()
    app.router.add_get("/", healthcheck)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

def get_queue(guild_id):
    if guild_id not in queues:
        queues[guild_id] = []
    return queues[guild_id]

async def play_next(ctx):
    queue = get_queue(ctx.guild.id)
    if not queue:
        return
    if ctx.voice_client and ctx.voice_client.is_playing():
        return
    info = queue.pop(0)
    source = await discord.FFmpegOpusAudio.from_probe(info["url"], **{"before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"})
    ctx.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop))
    embed = discord.Embed(title="Reproduciendo", description=f"[{info['title']}]({info['webpage_url']})", color=discord.Color.green())
    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f"✅ {bot.user} conectado a Discord ({len(bot.guilds)} servidores)")

@bot.command()
async def join(ctx):
    if not ctx.author.voice:
        await ctx.send("Necesitás estar en un canal de voz.")
        return
    await ctx.author.voice.channel.connect()
    await ctx.send(f"🔊 Conectado a {ctx.author.voice.channel.mention}")

@bot.command()
async def leave(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        queues.pop(ctx.guild.id, None)
        await ctx.send("👋 Desconectado.")
    else:
        await ctx.send("No estoy en un canal de voz.")

@bot.command()
async def play(ctx, *, query: str):
    if not ctx.author.voice:
        await ctx.send("Necesitás estar en un canal de voz.")
        return
    if not ctx.voice_client:
        await ctx.author.voice.channel.connect()

    await ctx.send(f"🔍 Buscando `{query}`...")

    loop = asyncio.get_event_loop()
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        data = await loop.run_in_executor(None, lambda: ydl.extract_info(query, download=False))

    if "entries" in data:
        data = data["entries"][0]

    info = {
        "title": data["title"],
        "url": data["url"],
        "webpage_url": data.get("webpage_url", data.get("original_url", f"https://youtube.com/watch?v={data['id']}")),
        "duration": data.get("duration", 0),
        "channel": data.get("channel", "Desconocido"),
        "thumbnail": data.get("thumbnail", ""),
    }

    queue = get_queue(ctx.guild.id)
    queue.append(info)
    embed = discord.Embed(
        title="Agregado a la cola",
        description=f"[{info['title']}]({info['webpage_url']})",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)

    if not ctx.voice_client.is_playing():
        await play_next(ctx)

@bot.command()
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("⏭ Saltando...")
    else:
        await ctx.send("No hay nada reproduciendo.")

@bot.command()
async def stop(ctx):
    queue = get_queue(ctx.guild.id)
    queue.clear()
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
    await ctx.send("⏹ Música detenida y cola limpiada.")

@bot.command()
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸ Pausado.")
    else:
        await ctx.send("No hay nada reproduciendo.")

@bot.command()
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("▶ Reanudado.")
    else:
        await ctx.send("No hay nada pausado.")

@bot.command()
async def queue(ctx):
    q = get_queue(ctx.guild.id)
    if not q:
        await ctx.send("La cola está vacía.")
        return
    msg = "**Cola de reproducción:**\n"
    for i, s in enumerate(q, 1):
        dur = f"{s['duration']//60}:{s['duration']%60:02d}" if s.get("duration") else "?:??"
        msg += f"`{i}.` [{s['title']}]({s['webpage_url']}) ({dur})\n"
    await ctx.send(msg)

@bot.command()
async def nowplaying(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        await ctx.send("🎵 Reproduciendo ahora mismo.")
    else:
        await ctx.send("No hay nada reproduciendo.")

@bot.command()
async def volume(ctx, vol: int):
    if ctx.voice_client and ctx.voice_client.source:
        ctx.voice_client.source.volume = max(0, min(200, vol / 100))
        await ctx.send(f"🔊 Volumen ajustado a {vol}%")
    else:
        await ctx.send("No hay nada reproduciendo.")

@bot.command()
async def help(ctx):
    embed = discord.Embed(title="🎵 MusicBot - Comandos", color=discord.Color.blue())
    embed.add_field(name="Reproducción", value="""
`!join` — entrar al canal de voz
`!play <canción/URL>` — buscar y reproducir
`!skip` — saltar canción
`!stop` — detener y limpiar cola
`!pause` / `!resume`
`!volume <0-200>`
    """, inline=False)
    embed.add_field(name="Cola", value="""
`!queue` — ver cola
`!nowplaying` — canción actual
    """, inline=False)
    embed.add_field(name="Otros", value="""
`!leave` — salir del canal
    """, inline=False)
    await ctx.send(embed=embed)

async def main():
    await run_http()
    async with bot:
        await bot.start(config.TOKEN)

asyncio.run(main())
