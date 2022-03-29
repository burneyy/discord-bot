import discord
import logging
import os.path


PROJDIR = os.path.dirname(__file__)

logger = logging.getLogger('discord')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename=f'{PROJDIR}/discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

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

    msg += "\n\n**Members without a team**: "+", ".join([f"{m.mention}" for m in not_in_team])
    msg += "\nPlease contact one of the teams with free spaces in order to join them"

    return msg




@client.event
async def on_ready():
    print('We have logged in as {0.user}'.format(client))

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.content.startswith("!teams"):
        await message.channel.send(print_teams(message.guild))


client.run(token)
