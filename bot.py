import discord
from discord.ext import tasks, commands
from datetime import datetime, timezone
from thefuzz import fuzz
import aiohttp
import asyncio
import logging
import os.path
import json

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
DC_CH_CLUB_MEMBERS = 1008354101207257098
DC_MSG_CLUB_MEMBERS_1 = 1172931277410795602
DC_MSG_CLUB_MEMBERS_2 = 1172931280489422879
DC_MSG_CLUB_MEMBERS_3 = 1172931281688993882

DC_MEMBER_ROLES = ["Member", "Senior", "Vice-President", "President"]
DC_EXCLUSIVE_ROLES = DC_MEMBER_ROLES + ["Friends"]


def utc_time_now():
    return datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M:%S UTC")


def print_teams(guild):
    msg = "**Club League Team Constellations**\n**========================**\n"

    roles = guild.roles
    team_roles = {}
    member_roles = {}
    for role in roles:
        if role.name.startswith("Team"):
            team_roles[role.name] = role.id

        if role.name in ["Member", "Senior", "Vice-President", "President"]:
            member_roles[role.name] = role.id

    # Print teams
    ids_in_teams = []
    for t in range(1, 11, 1):
        team_name = f"Team {t}"
        msg += f"\n{t}. "
        team_id = team_roles[team_name]
        role = guild.get_role(team_id)
        team_members = role.members
        ids_in_teams.extend([m.id for m in team_members])

        msg += ", ".join([f"{m.mention}" for m in team_members])
        if len(team_members) != 3:
            msg += f" ({len(team_members)}/3)"

    # Find members not in a team
    not_in_team = []
    for role_name, role_id in member_roles.items():
        role_members = guild.get_role(role_id).members
        for member in role_members:
            if member.id not in ids_in_teams:
                not_in_team.append(member)

    msg += "\n\n**Members without a team**: "
    if len(not_in_team) > 0:
        msg += ", ".join([f"{m.mention}" for m in not_in_team])
    else:
        msg += "<None>"
    msg += "\nPlease contact one of the teams with free spaces in order to join them"

    return msg


async def fetch_bs_club_members():
    async with aiohttp.ClientSession(headers=BS_HEADERS) as http_client:
        async with http_client.get("https://api.brawlstars.com/v1/clubs/%232R288L2YV/members") as resp:
            json_body = await resp.json()
            return json_body["items"] if "items" in json_body else []


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
    message = await channel.fetch_message(959085993070313474)
    if channel is None or message is None:
        logger.warning("No channel/message found to update club stats")
        return

    trophies = json_dict['trophies']
    members = json_dict['members']
    memberCount = len(members)
    trophies_avg = trophies // memberCount
    trophies_req = json_dict['requiredTrophies']
    tag = json_dict['tag'].replace("#", "")
    url = f"https://brawlify.com/stats/club/{tag}"

    msg = "**========= Club Stats =========**"
    msg += f"\n:scroll:  {json_dict['description']}"
    msg += f"\n:people_holding_hands:  {memberCount}/30 members"
    msg += f"\n:trophy:  {trophies} total trophies ({trophies_avg} per member)"
    msg += f"\n:no_entry:  {trophies_req} trophies required to join"
    msg += f"\n:link:  {url}"
    msg += f"\n\nLast updated: {utc_time_now()}"

    await message.edit(content=msg)


class MainCog(commands.Cog):
    def __init__(self, bot):
        print("run init")
        self.index = 0
        self.bot = bot
        self.update_members.start()
        self.update_club.start()

    def cog_unload(self):
        self.update_members.cancel()
        self.update_club.cancel()

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
            content += f"\n{pos+1}. {bs_name}"
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

    @tasks.loop(minutes=5)
    async def update_club(self):
        channel = self.bot.get_channel(945301557614903349)  # ID of the welcome channel
        headers = {"Authorization": f"Bearer {bs_token}"}
        async with aiohttp.ClientSession(headers=headers) as http_client:
            async with http_client.get("https://api.brawlstars.com/v1/clubs/%232R288L2YV") as resp:
                json_dict = await resp.json()
                # await club_log(json)
                await club_stats(json_dict, channel)

    @update_members.before_loop
    async def before_update_members(self):
        await self.bot.wait_until_ready()

    @update_club.before_loop
    async def before_update_club(self):
        await self.bot.wait_until_ready()


# @client.event
async def on_message(message):
    if message.author == client.user:
        return

    text = message.content
    if text.startswith("!eval_poll"):
        parts = text.split(" ")

        if len(parts) != 3:
            await message.channel.send("Command has to be in the form: !eval_poll <channel_id> <message_id>")
            return

        poll = await client.get_channel(int(parts[1])).fetch_message(int(parts[2]))
        users = dict()
        for reaction in poll.reactions:
            async for user in reaction.users():
                if user in users:
                    users[user].append(reaction)
                else:
                    users[user] = [reaction]

        msg = "\n".join(
            [f"{i + 1}. {user.mention}: " + " ".join([f"{reaction}" for reaction in reactions]) for i, (user, reactions)
             in enumerate(users.items())])
        await message.channel.send(msg)


@bot.command()
async def profile(ctx, *args):
    if len(args) > 1:
        await ctx.send("Command has to be used as: !profile [user_id]")
        return

    user_id = ctx.author.id
    with open(f"{PROJDIR}/database.json", "w+") as db:
        user_id = ctx.author.id
        try:
            json_dict = json.load(db)
        except json.JSONDecodeError:
            json_dict = {"users": {}}

        if len(args) == 0:
            if user_id not in json_dict["users"]:
                await ctx.send(f"No entry for user id {user_id}")
                return

            await ctx.send(users[user_id])


        elif len(args) == 1:
            bs_tag = args[0].lstrip("#")
            if len(bs_tag) != 8:
                await ctx.send(f"Invalid brawl stars tag {bs_tag}")
                return

            bs_info = {}
            headers = {"Authorization": f"Bearer {bs_token}"}
            async with aiohttp.ClientSession(headers=headers) as http_client:
                async with http_client.get(f"https://api.brawlstars.com/v1/players/%23{bs_tag}") as resp:
                    if resp.status != 200:
                        await ctx.send(f"Brawl stars tag #{bs_tag} not found")
                        return
                    bs_info = await resp.json()

            json_dict["users"][user_id] = bs_tag
            json.dump(json_dict, db, indent=4)
            await ctx.send(f"Saved BrawlStars profile #{bs_tag} ({bs_info['name']}, {bs_info['trophies']} trophies)")


@bot.event
async def on_ready():
    logger.info('We have logged in as {0.user}'.format(bot))


async def main():
    await bot.add_cog(MainCog(bot))
    await bot.start(discord_token)


asyncio.run(main())
