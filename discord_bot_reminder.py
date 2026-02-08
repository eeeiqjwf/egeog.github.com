import discord
from discord.ext import commands, tasks
import os
import logging
import asyncio
from datetime import datetime, timedelta, timezone
import re
import json

from keep_alive import keep_alive

keep_alive()

logging.basicConfig(level=logging.INFO)

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.members = True

bot = commands.Bot(command_prefix='.', intents=intents)

REMINDER_CHANNEL_ID = 1468407822860423273
VIDEO_TRACK_CHANNEL_ID = 1469432714896740474

MANAGED_ROLES = [
    1417986455296278538, 
    1417959557719654550, 
    1417968485031608443, 
    1427466045324787742, 
    1418029602735128586, 
    1417970206990532730
]

USER_MAPPING = {
    1086571236160708709: "FunwithBg",
    1157663612115107981: "Snipzy-AZ",
    1444845857701630094: "Jay",
    1458104862834167824: "Raccoon",
    1210942252264857673: "RINGTA EMPIRE"
}

SPECIAL_QUOTA = {
    1086571236160708709: {"count": 1, "days": 3}
}

DEMOTED_USERS_FILE = "demoted_users.json"
CONFIG_FILE = "config.json"

def load_json(filename, fallback):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            try:
                return json.load(f)
            except:
                return fallback
    return fallback

def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f)

demoted_users = load_json(DEMOTED_USERS_FILE, {})
config = load_json(CONFIG_FILE, {"reminder_interval": 60, "last_demotion_date": "", "last_reminder_date": ""})

def is_owner(ctx):
    return ctx.author.id == 608461552034643992

def get_deadline_for_day(dt):
    est_offset = timezone(timedelta(hours=-5))
    dt_est = dt.astimezone(est_offset).replace(hour=18, minute=0, second=0, microsecond=0)
    if dt_est > dt.astimezone(est_offset):
        dt_est -= timedelta(days=1)
    return dt_est.replace(tzinfo=est_offset).astimezone(timezone.utc)

@bot.command(name='set_interval')
@commands.check(is_owner)
async def set_interval(ctx, minutes: int):
    if minutes < 1:
        await ctx.send("Interval must be at least 1 minute.")
        return
    config["reminder_interval"] = minutes
    save_json(CONFIG_FILE, config)
    reminder_loop.change_interval(minutes=minutes)
    await ctx.send(f"✅ Reminder interval set to {minutes} minutes.")

async def check_user_restoration(uid_str):
    global demoted_users
    if uid_str not in demoted_users:
        return
    uid = int(uid_str)
    name = USER_MAPPING.get(uid)
    if not name:
        return
    track_channel = bot.get_channel(VIDEO_TRACK_CHANNEL_ID)
    if not track_channel:
        try:
            track_channel = await bot.fetch_channel(VIDEO_TRACK_CHANNEL_ID)
        except:
            return
    deadline_utc = get_deadline_for_day(datetime.now(timezone.utc))
    last_period = deadline_utc - timedelta(days=1)
    count = 0
    async for msg in track_channel.history(limit=1000, after=last_period, before=deadline_utc):
        content = msg.content if msg.content else ""
        if msg.embeds:
            for embed in msg.embeds:
                if embed.description: content += f" {embed.description}"
                if embed.author and embed.author.name: content += f" {embed.author.name}"
                if embed.title: content += f" {embed.title}"
        pattern = rf"{re.escape(name)}\s+just\s+posted\s+a\s+new\s+video!"
        if re.search(pattern, content, re.IGNORECASE):
            count += 1
        elif msg.author.bot and name.lower() in content.lower():
            if any(term in content.lower() for term in ["posted", "new video", "youtu.be", "youtube.com"]):
                if not re.search(pattern, content, re.IGNORECASE):
                    count += 1
    missing = demoted_users[uid_str]["missing"]
    if count >= missing:
        guild = track_channel.guild
        member = guild.get_member(uid)
        if not member:
            try:
                member = await guild.fetch_member(uid)
            except:
                return
        restore_roles = [guild.get_role(rid) for rid in demoted_users[uid_str]["roles"] if guild.get_role(rid)]
        if restore_roles:
            await member.add_roles(*restore_roles)
        log_channel = bot.get_channel(REMINDER_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"✅ <@{uid}> uploaded their missing videos and roles are restored.")
        del demoted_users[uid_str]
        save_json(DEMOTED_USERS_FILE, demoted_users)

@bot.event
async def on_message(message):
    if message.channel.id == VIDEO_TRACK_CHANNEL_ID:
        for uid_str in list(demoted_users.keys()):
            name = USER_MAPPING.get(int(uid_str))
            if name:
                pattern = rf"{re.escape(name)}\s+just\s+posted\s+a\s+new\s+video!"
                content = message.content or ""
                if message.embeds:
                    for embed in message.embeds:
                        if embed.description: content += f" {embed.description}"
                if re.search(pattern, content, re.IGNORECASE):
                    await check_user_restoration(uid_str)
    await bot.process_commands(message)

async def run_yesterday_demotion():
    global demoted_users
    now = datetime.now(timezone.utc)
    deadline = get_deadline_for_day(now)
    last_deadline = deadline - timedelta(days=1)
    track_channel = bot.get_channel(VIDEO_TRACK_CHANNEL_ID)
    if not track_channel:
        try:
            track_channel = await bot.fetch_channel(VIDEO_TRACK_CHANNEL_ID)
        except:
            return
    user_counts = {uid: 0 for uid in USER_MAPPING}
    async for msg in track_channel.history(limit=500, after=last_deadline, before=deadline):
        content = msg.content if msg.content else ""
        if msg.embeds:
            for embed in msg.embeds:
                if embed.description: content += f" {embed.description}"
                if embed.author and embed.author.name: content += f" {embed.author.name}"
                if embed.title: content += f" {embed.title}"
        for uid, name in USER_MAPPING.items():
            pattern = rf"{re.escape(name)}\s+just\s+posted\s+a\s+new\s+video!"
            if re.search(pattern, content, re.IGNORECASE):
                user_counts[uid] += 1
            elif msg.author.bot and name.lower() in content.lower():
                if any(term in content.lower() for term in ["posted", "new video", "youtu.be", "youtube.com"]):
                    if not re.search(pattern, content, re.IGNORECASE):
                        user_counts[uid] += 1
    guild = track_channel.guild
    demoted_now = []
    for uid, name in USER_MAPPING.items():
        if str(uid) in demoted_users:
            continue
        quota_data = SPECIAL_QUOTA.get(uid, {"count": 3})
        required = quota_data["count"]
        if user_counts[uid] < required:
            member = guild.get_member(uid)
            if not member:
                try:
                    member = await guild.fetch_member(uid)
                except:
                    continue
            to_remove = [r.id for r in member.roles if r.id in MANAGED_ROLES]
            if to_remove:
                role_objs = [guild.get_role(rid) for rid in to_remove if guild.get_role(rid)]
                if role_objs:
                    await member.remove_roles(*role_objs)
                    demoted_users[str(uid)] = {
                        "roles": to_remove,
                        "missing": required - user_counts[uid]
                    }
                    save_json(DEMOTED_USERS_FILE, demoted_users)
                    demoted_now.append(f"<@{uid}> ({user_counts[uid]}/{required})")
    log_channel = bot.get_channel(REMINDER_CHANNEL_ID)
    if log_channel:
        embed = discord.Embed(
            title="📊 Yesterday's Video Check",
            color=discord.Color.red() if demoted_now else discord.Color.green(),
            description=f"From <t:{int(last_deadline.timestamp())}:f> to <t:{int(deadline.timestamp())}:f>"
        )
        lines = []
        for uid, name in USER_MAPPING.items():
            quota_data = SPECIAL_QUOTA.get(uid, {"count": 3})
            required = quota_data["count"]
            lines.append(f"<@{uid}>: {user_counts[uid]}/{required}")
        embed.add_field(name="Video Counts", value="\n".join(lines), inline=False)
        if demoted_now:
            embed.add_field(name="🚨 Demoted", value="\n".join(demoted_now), inline=False)
            embed.set_footer(text="Demoted users must upload missing videos to get roles restored.")
        else:
            embed.set_footer(text="All members met the quota yesterday ✅")
        await log_channel.send(embed=embed)

@tasks.loop(minutes=5)
async def check_restores():
    global demoted_users
    if not demoted_users:
        return
    for uid_str in list(demoted_users.keys()):
        await check_user_restoration(uid_str)

@tasks.loop(minutes=60)
async def reminder_loop():
    est_offset = timezone(timedelta(hours=-5))
    now_est = datetime.now(est_offset)
    today_str = now_est.strftime("%Y-%m-%d")
    if config.get("last_reminder_date") != today_str and now_est.hour == 18:
        config["last_reminder_date"] = today_str
        save_json(CONFIG_FILE, config)
        await run_yesterday_demotion()

@bot.event
async def on_ready():
    if not check_restores.is_running():
        check_restores.start()
    if not reminder_loop.is_running():
        reminder_loop.start()

if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if token:
        bot.run(token)
