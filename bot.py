import discord
from discord.ext import tasks
import aiohttp
import asyncio
import logging
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
client = discord.Client(intents=intents)

token = None
with open(f"{PROJDIR}/bot_token.txt", "r") as f:
    token = f.read().strip()


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
    for t in range(1,11,1):
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




@client.event
async def on_ready():
    logger.info('We have logged in as {0.user}'.format(client))

@client.event
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

        msg = "\n".join([f"{i+1}. {user.mention}: "+" ".join([f"{reaction}" for reaction in reactions]) for i, (user, reactions) in enumerate(users.items())])
        await message.channel.send(msg)




@tasks.loop(minutes=5)
async def update_teams():
    logger.info("Updating team constellations...")
    channel = client.get_channel(945591403382181888) #ID of the pinboard channel
    if channel is None:
        logger.warning("No channel found to update teams")
    else:
        message = await channel.fetch_message(958342147042598932) #ID of the team constellations message
        old_msg = message.content
        new_msg = print_teams(message.guild)

        if new_msg != old_msg:
            logger.info("Team constellations have changed. Updating message...")
            await message.edit(content=new_msg)

async def club_log(json):
    logger.info("Updating club log...")
    channel = client.get_channel(945616010986266634) #ID of the log channel
    #channel = client.get_channel(958972040654778418) #ID of the test channel
    if channel is None:
        logger.warning("No channel found to update club log")
        return

    last_timestamp = None
    with open(f"{PROJDIR}/clublog_timestamp.txt", "r") as f:
        old_timestamp = int(f.readline().strip())
        newest_timestamp = old_timestamp

    member_change = False
    for entry in reversed(json["history"]):
        timestamp = entry["timestamp"]
        if timestamp > old_timestamp:
            #New entry
            d = entry["data"]
            t = entry["type"]
            player = d["player"] if "player" in d else None
            if t == "members":
                #Join or leave messages
                if d["joined"]:
                    action = "joined"
                    sign = ":dizzy:"
                else:
                    action = "left"
                    sign = ":no_entry_sign:"
                member_change = True
                await channel.send(f"{sign}  **{player['name']}** (`#{player['tag']}`) {action} the club.")
            elif t == "roles":
                #Promotions
                if d["promote"]:
                    action = "promoted"
                    sign = ":arrow_upper_right:"
                else:
                    action = "demoted"
                    sign = ":arrow_lower_right:"
                await channel.send(f"{sign}  **{player['name']}** (`#{player['tag']}`) was {action} from {d['old']} to {d['new']}.")
            elif t == "settings" and d["type"] == "requirement":
                #Trophy requirement changed
                await channel.send(f":trophy:  Trophy requirement changed from {d['old']} to {d['new']}.")
            elif t == "settings" and d["type"] == "status":
                #Club status (open, invite-only etc.)
                await channel.send(f":tools:  Club status changed from {d['old']} to {d['new']}.")
        if timestamp > newest_timestamp:
            newest_timestamp = timestamp

    if member_change:
        n_members = json["club"]["memberCount"]
        await channel.send(f":people_holding_hands:  Current member count: {n_members}/30.")

    with open(f"{PROJDIR}/clublog_timestamp.txt", "w") as f:
        f.write(str(newest_timestamp))


async def club_stats(json):
    logger.info("Updating club stats...")
    channel = client.get_channel(945301557614903349) #ID of the welcome channel
    message = await channel.fetch_message(959085993070313474)
    if channel is None or message is None:
        logger.warning("No channel/message found to update club stats")
        return

    c = json["club"]

    trophies = c['trophies']
    members = c['memberCount']
    trophies_avg = trophies//members
    trophies_req = c['requiredTrophies']
    tag = c['tag']
    url = f"https://brawlify.com/stats/club/{tag}"

    msg = "**========= Club Stats =========**"
    msg += f"\n:scroll:  {c['description']}" 
    msg += f"\n:people_holding_hands:  {members}/30 members"
    msg += f"\n:trophy:  {trophies} total trophies ({trophies_avg} per member)"
    msg += f"\n:no_entry:  {trophies_req} trophies required to join"
    msg += f"\n:link:  {url}"

    await message.edit(content=msg)


async def update_club():
    async with aiohttp.ClientSession() as http_client:
        while True:
            await asyncio.sleep(300) #Every 5 minutes

            async with http_client.get("https://api.brawlapi.com/v1/clublog/2R288L2YV") as resp:
                json = await resp.json()
                await club_log(json)
                await club_stats(json)



loop = asyncio.get_event_loop()
task = loop.create_task(update_club())

update_teams.start()
client.run(token)

