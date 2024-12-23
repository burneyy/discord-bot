import discord
from discord.ext import tasks, commands
from datetime import datetime, timezone, timedelta
from thefuzz import fuzz
import aiohttp
import asyncio
import logging
import urllib.parse
import os.path

PROJDIR = os.path.dirname(__file__)

# LOGGING
logger = logging.getLogger('discord')
logger.setLevel(logging.INFO)
fileHandler = logging.FileHandler(filename=f'{PROJDIR}/discord.log', encoding='utf-8', mode='w')
fileHandler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(fileHandler)
consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(consoleHandler)

intents = discord.Intents().default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

with open(f"{PROJDIR}/bot_token.txt", "r") as f:
    discord_token = f.read().strip()

with open(f"{PROJDIR}/bs_token.txt", "r") as f:
    bs_token = f.read().strip()

# Brawl Stars Constants
BS_HEADERS = {"Authorization": f"Bearer {bs_token}"}
BS_ROLE_TO_ID = {"president": 945309687685984276, "vicePresident": 945310000761438218,
                 "senior": 945310228830908436, "member": 945310581827715082}

# Discord constants
DC_CH_CLUB_MEMBERS = 1008354101207257098  # ID of club-members channel
DC_MSG_CLUB_MEMBERS_1 = 1172931277410795602
DC_MSG_CLUB_MEMBERS_2 = 1172931280489422879
DC_MSG_CLUB_MEMBERS_3 = 1172931281688993882

DC_CH_WELCOME = 945301557614903349  # ID of welcome channel
DC_MSG_CLUB_STATS = 959085993070313474

DC_CH_TEST = 958972040654778418  # ID of bot-test channel

DC_CH_ACTIVITY_MONITOR = 1320345572435169290  # ID of the activity-monitor channel
DC_MSG_AVG_MATCHES = 1320725632937627690

DC_MEMBER_ROLES = ["Member", "Senior", "Vice-President", "President"]
DC_EXCLUSIVE_ROLES = DC_MEMBER_ROLES + ["Friends"]


def utc_time_now():
    return datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M:%S UTC")


async def fetch_bs_club_members():
    async with aiohttp.ClientSession(headers=BS_HEADERS) as http_client:
        async with http_client.get("https://api.brawlstars.com/v1/clubs/%232R288L2YV/members") as resp:
            json_body = await resp.json()
            return json_body["items"] if "items" in json_body else []


async def fetch_battle_log(player_tag, player_name):
    response = {"name": player_name, "tag": player_tag, }
    async with aiohttp.ClientSession(headers=BS_HEADERS) as http_client:
        url = f"https://api.brawlstars.com/v1/players/{urllib.parse.quote(player_tag)}/battlelog"
        async with http_client.get(url) as resp:
            json_body = await resp.json()
            response["matches"] = json_body.get("items", [])
    return response


def filter_bots(users):
    return [user for user in users if "Bots" not in [role.name for role in user.roles]]


def filter_club_members(users):
    members = []
    for user in users:
        for role in user.roles:
            if role.name in DC_MEMBER_ROLES:
                members.append(user)
    return members


def fuzzy_search_dc_member(name, members, score_cutoff=0):
    best_score = 0
    best_member = None
    for member in members:
        score = fuzz.WRatio(name, member.display_name)
        if score > best_score:
            best_score = score
            best_member = member

    if best_score > score_cutoff:
        return best_member


async def club_stats(json_dict, channel):
    logger.info("Updating club stats...")
    message = await channel.fetch_message(DC_MSG_CLUB_STATS)
    if channel is None or message is None:
        logger.warning("No channel/message found to update club stats")
        return

    trophies = json_dict['trophies']
    members = json_dict['members']
    member_count = len(members)
    trophies_avg = trophies // member_count
    trophies_req = json_dict['requiredTrophies']
    tag = json_dict['tag'].replace("#", "")
    url = f"https://brawlify.com/stats/club/{tag}"

    msg = "**========= Club Stats =========**"
    msg += f"\n:scroll:  {json_dict['description']}"
    msg += f"\n:people_holding_hands:  {member_count}/30 members"
    msg += f"\n:trophy:  {trophies} total trophies ({trophies_avg} per member)"
    msg += f"\n:no_entry:  {trophies_req} trophies required to join"
    msg += f"\n:link:  {url}"
    msg += f"\n\nLast updated: {utc_time_now()}"

    await message.edit(content=msg)
    logger.info("Updated club stats")


class MainCog(commands.Cog):
    def __init__(self, bot):
        print("run init")
        self.index = 0
        self.bot = bot
        self.update_members.start()
        self.update_club.start()
        self.update_activity.start()

    def cog_unload(self):
        self.update_members.cancel()
        self.update_club.cancel()
        self.update_activity.cancel()

    @tasks.loop(minutes=5)
    async def update_members(self):
        logger.info("Updating club members...")
        channel = self.bot.get_channel(DC_CH_CLUB_MEMBERS)
        if channel is None:
            logger.warning("No channel found to update members")
            return

        dc_users = filter_bots(channel.guild.members)

        message = await channel.fetch_message(DC_MSG_CLUB_MEMBERS_1)
        content = "**========= Brawl Stars Club Members =========**"
        bs_members = await fetch_bs_club_members()
        dc_member_ids_listed = []
        for pos, bs_member in enumerate(bs_members):
            if pos == 15:
                await message.edit(content=content)
                content = ""
                message = await channel.fetch_message(DC_MSG_CLUB_MEMBERS_2)

            # Brawl Stars vs. Discord Name
            bs_name = bs_member["name"]
            content += f"\n{pos + 1}. {bs_name}"
            dc_member = fuzzy_search_dc_member(bs_name, dc_users, score_cutoff=75)
            if dc_member is not None:
                dc_member_ids_listed.append(dc_member.id)
                content += f" / {dc_member.mention}"
            else:
                content += " / " + 3 * ":question:"

            # Brawl Stars vs. Discord Role
            bs_role = bs_member["role"]
            bs_role_mention = f"<@&{BS_ROLE_TO_ID[bs_role]}>"
            content += f" - {bs_role_mention}"
            if dc_member is not None:
                dc_role_mention = "*None*"
                for role in dc_member.roles:
                    if role.name in DC_EXCLUSIVE_ROLES:
                        dc_role_mention = role.mention
                        break
                if dc_role_mention != bs_role_mention:
                    content += f" / {dc_role_mention} " + 3 * ":question:"

            # Trophies
            content += f" - {bs_member['trophies']} :trophy:"

        await message.edit(content=content)

        # Not listed discord members
        message = await channel.fetch_message(DC_MSG_CLUB_MEMBERS_3)
        dc_members = filter_club_members(dc_users)
        content = "**Discord members not found in club:** "
        dc_members_unlisted = [m for m in dc_members if m.id not in dc_member_ids_listed]
        if len(dc_members_unlisted) > 0:
            content += ", ".join([m.mention for m in dc_members_unlisted])
        else:
            content += "*None*"

        # Duplicate listings
        content += "\n**Discord members found multiple times in club:** "
        dc_members_duplicate = [m for m in dc_members if dc_member_ids_listed.count(m.id) > 1]
        if len(dc_members_duplicate) > 0:
            content += ", ".join([m.mention for m in dc_members_duplicate])
        else:
            content += "*None*"

        content += f"\n\nLast updated: {utc_time_now()}"
        await message.edit(content=content)
        logger.info("Updated club members")

    @tasks.loop(minutes=5)
    async def update_club(self):
        channel = self.bot.get_channel(DC_CH_WELCOME)
        async with aiohttp.ClientSession(headers=BS_HEADERS) as http_client:
            async with http_client.get("https://api.brawlstars.com/v1/clubs/%232R288L2YV") as resp:
                json_dict = await resp.json()
                await club_stats(json_dict, channel)

    @tasks.loop(hours=6)
    async def update_activity(self):
        logger.info("Updating activity...")
        channel = self.bot.get_channel(DC_CH_ACTIVITY_MONITOR)
        message = await channel.fetch_message(DC_MSG_AVG_MATCHES)
        if channel is None:
            logger.warning("No channel found to update activity")
            return

        content = "**========= Average matches per day in last 7 days =========**"
        club_members = await fetch_bs_club_members()
        tasks = []
        for member in club_members:
            tag = member["tag"]
            name = member["name"]
            tasks.append(asyncio.create_task(fetch_battle_log(tag, name)))
        player_logs = await asyncio.gather(*tasks)

        activity_list = []
        for player_log in player_logs:
            name = player_log["name"]
            timestamps = [datetime.strptime(match["battleTime"], "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=timezone.utc)
                          for match in player_log["matches"]]
            min_timestamp = min(timestamps)
            now = datetime.now(timezone.utc)
            th_timestamp = now - timedelta(days=7)
            timestamps = [ts for ts in timestamps if ts > th_timestamp]
            if min_timestamp < th_timestamp:
                min_timestamp = th_timestamp
            time_diff_days = (now - min_timestamp).total_seconds() / (24 * 3600)
            n_matches = len(timestamps)
            matches_per_day = n_matches / time_diff_days

            player_activity = {"player": name, "avg_matches": matches_per_day,
                               "n_matches": n_matches, "timespan": time_diff_days}
            activity_list.append(player_activity)

        sorted_activity_list = sorted(activity_list, key=lambda x: x["avg_matches"], reverse=True)

        for idx, player_activity in enumerate(sorted_activity_list):
            name = player_activity["player"]
            avg_matches = player_activity["avg_matches"]
            tot_matches = player_activity["n_matches"]
            timespan = player_activity["timespan"]
            content += f"\n{idx + 1}. {name}: {avg_matches:.1f} ({tot_matches} matches in last {timespan:.1f} days)"

        content += f"\n\nLast updated: {utc_time_now()}"
        await message.edit(content=content)
        logger.info("Updated activity")

    @update_members.before_loop
    @update_club.before_loop
    @update_activity.before_loop
    async def wait_until_ready(self):
        await self.bot.wait_until_ready()


@bot.event
async def on_ready():
    logger.info('We have logged in as {0.user}'.format(bot))


async def main():
    await bot.add_cog(MainCog(bot))
    await bot.start(discord_token)


asyncio.run(main())
