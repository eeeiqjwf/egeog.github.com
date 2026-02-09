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

def load_demoted_data():
    if os.path.exists(DEMOTED_USERS_FILE):
        with open(DEMOTED_USERS_FILE, "r") as f:
            try:
                return json.load(f)
            except:
                return {}
    return {}

def save_demoted_data(data):
    with open(DEMOTED_USERS_FILE, "w") as f:
        json.dump(data, f)

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            try:
                return json.load(f)
            except:
                return {"reminder_interval": 60, "last_demotion_date": "", "last_reminder_date": ""}
    return {"reminder_interval": 60, "last_demotion_date": "", "last_reminder_date": ""}

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f)

demoted_users = load_demoted_data()
config = load_config()

def is_owner(ctx):
    return ctx.author.id == 608461552034643992

def get_next_deadline():
    est_offset = timezone(timedelta(hours=-5))
    now_est = datetime.now(est_offset)
    deadline_est = now_est.replace(hour=18, minute=0, second=0, microsecond=0)
    
    if now_est >= deadline_est:
        deadline_est += timedelta(days=1)
        
    return deadline_est.astimezone(timezone.utc)

async def check_user_restoration(uid_str):
    global demoted_users
    if uid_str not in demoted_users:
        return

    uid = int(uid_str)
    name = USER_MAPPING.get(uid)
    if not name: return

    track_channel = bot.get_channel(VIDEO_TRACK_CHANNEL_ID)
    if not track_channel:
        try: track_channel = await bot.fetch_channel(VIDEO_TRACK_CHANNEL_ID)
        except: return

    deadline_utc = get_next_deadline()
    last_reset = deadline_utc - timedelta(days=1)
    
    guild = track_channel.guild
    data = demoted_users[uid_str]
    
    new_count = 0
    async for msg in track_channel.history(limit=1000, after=last_reset):
        content = ""
        if msg.content: content += msg.content
        if msg.embeds:
            for embed in msg.embeds:
                if embed.description: content += f" {embed.description}"
                if embed.author and embed.author.name: content += f" {embed.author.name}"
                if embed.title: content += f" {embed.title}"

        pattern = rf"{re.escape(name)}\s+just\s+posted\s+a\s+new\s+video!"
        if re.search(pattern, content, re.IGNORECASE):
            new_count += 1
        elif msg.author.bot and name.lower() in content.lower():
            if any(term in content.lower() for term in ["posted", "new video", "youtu.be", "youtube.com"]):
                if not re.search(pattern, content, re.IGNORECASE):
                    new_count += 1
    
    if new_count >= data["missing"]:
        member = guild.get_member(uid)
        if not member:
            try: member = await guild.fetch_member(uid)
            except: return
        
        roles_to_add = [guild.get_role(rid) for rid in data["roles"] if guild.get_role(rid)]
        if roles_to_add:
            await member.add_roles(*roles_to_add)
            
        log_channel = bot.get_channel(REMINDER_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"✅ <@{uid}> uploaded their missing videos! Roles restored. Note: You still need to upload 3 more for today!")
        
        del demoted_users[uid_str]
        save_demoted_data(demoted_users)

@bot.command(name='set_interval')
@commands.check(is_owner)
async def set_interval(ctx, minutes: int):
    if minutes < 1:
        await ctx.send("Interval must be at least 1 minute.")
        return
    
    config["reminder_interval"] = minutes
    save_config(config)
    
    reminder_loop.change_interval(minutes=minutes)
    await ctx.send(f"✅ Reminder interval set to {minutes} minutes.")

@set_interval.error
async def set_interval_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("❌ Only the owner can use this command.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Please provide a time in minutes. Example: `.set_interval 20`")

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

async def run_demotion_check(is_first_of_day=False):
    global demoted_users
    now_utc = datetime.now(timezone.utc)
    est_offset = timezone(timedelta(hours=-5))
    now_est = now_utc.astimezone(est_offset)
    
    period_end_est = now_est.replace(hour=18, minute=0, second=0, microsecond=0)
    if now_est < period_end_est:
        period_end_est -= timedelta(days=1)
    
    period_end = period_end_est.astimezone(timezone.utc)
    # If first message of the day, check 48 hours (2 days)
    # Otherwise check 24 hours (1 day)
    check_days = 2 if is_first_of_day else 1
    period_start = period_end - timedelta(days=check_days)

    logging.info(f"DEMOTION CHECK: first_of_day={is_first_of_day}, window={check_days}d, from={period_start} to={period_end}")
    
    track_channel = bot.get_channel(VIDEO_TRACK_CHANNEL_ID)
    if not track_channel:
        try: track_channel = await bot.fetch_channel(VIDEO_TRACK_CHANNEL_ID)
        except: 
            logging.error(f"FAILED TO FIND TRACK CHANNEL: {VIDEO_TRACK_CHANNEL_ID}")
            return
        
    current_counts = {uid: 0 for uid in USER_MAPPING}
    async for msg in track_channel.history(limit=5000, after=period_start, before=period_end):
        content = ""
        if msg.content: content += msg.content
        if msg.embeds:
            for embed in msg.embeds:
                if embed.description: content += f" {embed.description}"
                if embed.author and embed.author.name: content += f" {embed.author.name}"
                if embed.title: content += f" {embed.title}"

        for uid, name in USER_MAPPING.items():
            pattern = rf"{re.escape(name)}\s+just\s+posted\s+a\s+new\s+video!"
            if re.search(pattern, content, re.IGNORECASE):
                current_counts[uid] += 1
            elif msg.author.bot and name.lower() in content.lower():
                if any(term in content.lower() for term in ["posted", "new video", "youtu.be", "youtube.com"]):
                    if not re.search(pattern, content, re.IGNORECASE):
                        current_counts[uid] += 1
    
    for uid, quota in SPECIAL_QUOTA.items():
        if quota["days"] > 1:
            window_start = period_end - timedelta(days=quota["days"])
            name = USER_MAPPING.get(uid)
            count = 0
            async for msg in track_channel.history(limit=2000, after=window_start, before=period_end):
                content = ""
                if msg.content: content += msg.content
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
            current_counts[uid] = count

    guild = track_channel.guild
    demotion_details = []
    for uid, count in current_counts.items():
        if str(uid) in demoted_users:
            continue
            
        quota = SPECIAL_QUOTA.get(uid, {"count": 3})
        required = quota["count"]
        
        if count < required:
            member = guild.get_member(uid)
            if not member:
                try: member = await guild.fetch_member(uid)
                except: continue
            
            roles_to_remove = [r.id for r in member.roles if r.id in MANAGED_ROLES]
            if roles_to_remove:
                roles_objects = [guild.get_role(rid) for rid in roles_to_remove if guild.get_role(rid)]
                if roles_objects:
                    try:
                        await member.remove_roles(*roles_objects)
                        demoted_users[str(uid)] = {
                            "roles": roles_to_remove,
                            "missing": required - count
                        }
                        save_demoted_data(demoted_users)
                        demotion_details.append(f"<@{uid}>: {count}/{required} videos")
                    except Exception as e:
                        logging.error(f"Failed to demote user {uid}: {e}")
    
    if demotion_details and is_first_of_day:
        log_channel = bot.get_channel(REMINDER_CHANNEL_ID)
        if log_channel:
            msg = "**Yesterday videos posted (48h check):**\n" + "\n".join(demotion_details)
            msg += "\n\n⚠️ These users have been demoted. Upload your missing videos to get your roles back!"
            await log_channel.send(msg)
    elif demotion_details:
        log_channel = bot.get_channel(REMINDER_CHANNEL_ID)
        if log_channel:
            for detail in demotion_details:
                await log_channel.send(f"⚠️ {detail} has been demoted for missing videos in the previous period.")

@tasks.loop(minutes=1)
async def check_demotion_loop():
    now_utc = datetime.now(timezone.utc)
    est_offset = timezone(timedelta(hours=-5))
    now_est = now_utc.astimezone(est_offset)
    
    if now_est.hour == 18 and now_est.minute == 0:
        today_str = now_est.strftime("%Y-%m-%d")
        if config.get("last_demotion_date") != today_str:
            await run_demotion_check()
            config["last_demotion_date"] = today_str
            save_config(config)

@tasks.loop(minutes=5)
async def track_restoration_loop():
    global demoted_users
    if not demoted_users:
        return
    for uid_str in list(demoted_users.keys()):
        await check_user_restoration(uid_str)

@tasks.loop(minutes=60)
async def reminder_loop():
    channel = bot.get_channel(REMINDER_CHANNEL_ID)
    if not channel:
        try: channel = await bot.fetch_channel(REMINDER_CHANNEL_ID)
        except: return

    est_offset = timezone(timedelta(hours=-5))
    now_est = datetime.now(est_offset)
    today_str = now_est.strftime("%Y-%m-%d")
    
    if config.get("last_reminder_date") != today_str:
        config["last_reminder_date"] = today_str
        save_config(config)
        await run_demotion_check(is_first_of_day=True)

    now_utc = datetime.now(timezone.utc)
    deadline_utc = get_next_deadline()
    diff = deadline_utc - now_utc
    total_seconds = int(diff.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60

    time_str = f"{hours}h {minutes}m"
    period_start = deadline_utc - timedelta(days=1)
    
    track_channel = bot.get_channel(VIDEO_TRACK_CHANNEL_ID)
    if not track_channel:
        try: track_channel = await bot.fetch_channel(VIDEO_TRACK_CHANNEL_ID)
        except: return

    current_counts = {uid: 0 for uid in USER_MAPPING}
    async for msg in track_channel.history(limit=2000, after=period_start, before=now_utc):
        content = ""
        if msg.content: content += msg.content
        if msg.embeds:
            for embed in msg.embeds:
                if embed.description: content += f" {embed.description}"
                if embed.author and embed.author.name: content += f" {embed.author.name}"
                if embed.title: content += f" {embed.title}"

        for uid, name in USER_MAPPING.items():
            pattern = rf"{re.escape(name)}\s+just\s+posted\s+a\s+new\s+video!"
            if re.search(pattern, content, re.IGNORECASE):
                current_counts[uid] += 1
            elif msg.author.bot and name.lower() in content.lower():
                if any(term in content.lower() for term in ["posted", "new video", "youtu.be", "youtube.com"]):
                     if not re.search(pattern, content, re.IGNORECASE):
                         current_counts[uid] += 1

    mentions_list = []
    completed_list = []
    for uid, name in USER_MAPPING.items():
        count = current_counts[uid]
        quota_data = SPECIAL_QUOTA.get(uid, {"count": 3})
        required_count = quota_data["count"]
        
        if count >= required_count:
            completed_list.append(f"<@{uid}> ({count}/{required_count})")
        else:
            mentions_list.append(f"<@{uid}> ({count}/{required_count})")

    embed = discord.Embed(
        title="📹 Video Upload Reminder",
        description=f"Time remaining until next deadline (<t:1769900400:t>): **{time_str}**\n\n"
                    f"**Required:** 3 videos per day (unless specified otherwise).",
        color=discord.Color.orange()
    )
    
    if mentions_list:
        embed.add_field(name="⚠️ Need to Upload", value="\n".join(mentions_list), inline=False)
    if completed_list:
        embed.add_field(name="✅ Completed", value="\n".join(completed_list), inline=False)

    await channel.send(embed=embed)

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user.name}')
    if not check_demotion_loop.is_running():
        check_demotion_loop.start()
    if not track_restoration_loop.is_running():
        track_restoration_loop.start()
    if not reminder_loop.is_running():
        reminder_loop.start()

if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if token:
        bot.run(token)
    else:
        logging.error("No DISCORD_BOT_TOKEN found in environment.")
