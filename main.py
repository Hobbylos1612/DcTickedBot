import os
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from typing import Optional
import discord.ui
from dotenv import load_dotenv
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

TICKET_CATEGORY_NAME = "Tickets-TicketBot"
TICKET_ARCHIVE_CATEGORY_NAME = "Ticket-Archive"
SUPPORT_ROLE_NAME = "Staff"

# Global ticket counter
ticket_counter = 0

intents = discord.Intents.default()
intents.message_content = True # Required for accessing message content
intents.members = True # Required for member-related operations

class ConfirmButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300) # 5 minutes timeout

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Disable the button after it's clicked
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

        guild = interaction.guild
        channel = interaction.channel
        ticket_creator_id = None
        if channel.topic and "ID:" in channel.topic:
            try:
                # Extract the ID from the topic string
                ticket_creator_id = int(channel.topic.split("ID:")[1].strip().split(")")[0])
                ticket_creator = guild.get_member(ticket_creator_id)
                if not ticket_creator:
                    ticket_creator = await guild.fetch_member(ticket_creator_id)
            except (ValueError, IndexError, discord.NotFound):
                print(f"Could not parse or find ticket creator from channel topic: {channel.topic}")
        
        # Find or create archive category
        archive_category = discord.utils.get(guild.categories, name=TICKET_ARCHIVE_CATEGORY_NAME)
        if not archive_category:
            archive_category = await guild.create_category(TICKET_ARCHIVE_CATEGORY_NAME)
            
        # Get support role
        support_role = discord.utils.get(guild.roles, name=SUPPORT_ROLE_NAME)
        
        # Define overwrites for the archived channel:
        # - Default role: No access
        # - Support role: Read-only access
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
        }
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(read_messages=True, send_messages=False)
        if ticket_creator:
            overwrites[ticket_creator] = discord.PermissionOverwrite(read_messages=False)
        
        # Move channel, rename it, and update permissions
        new_name = f"closed-{channel.name}"
        if len(new_name) > 100:
            new_name = new_name[:100]
            
        await channel.edit(
            category=archive_category, 
            overwrites=overwrites, 
            name=new_name,
            reason="Ticket closed and archived"
        )
        
        await channel.send(f"This ticket is Archived.")

    async def on_timeout(self):
        # Disable all buttons when the view times out
        for child in self.children:
            child.disabled = True
        # You might want to edit the original message to indicate timeout
        # await self.message.edit(content="Ticket closure timed out.", view=self)
        print("Confirm button view timed out.")

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        print(f"Error in ConfirmButtonView: {error}")
        await interaction.followup.send("An error occurred while processing your request.", ephemeral=True)

class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # Persistent view

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket_button")
    async def close_ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _close_ticket_logic(interaction)

    @discord.ui.button(label="Transcribe", style=discord.ButtonStyle.secondary, custom_id="transcribe_button")
    async def transcribe_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if discord.utils.get(interaction.user.roles, name=SUPPORT_ROLE_NAME):
            await _transcribe_ticket_logic(interaction)
        else:
            await interaction.response.send_message("You do not have permission to use this button.", ephemeral=True)



bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'Bot connected as {bot.user}')
    await bot.tree.sync()
    print("Slash commands synced.")

@bot.tree.command(name="hello", description="Says hello to the user.")
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message('Hello!')

@bot.tree.command(name="newticket", description="Creates a new support ticket.")
@app_commands.describe(topic="The topic of your support ticket (optional).")
async def newticket(interaction: discord.Interaction, topic: Optional[str] = None):
    global ticket_counter
    ticket_counter += 1

    guild = interaction.guild
    member = interaction.user

    if not guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    # Find or create a "Tickets" category
    ticket_category = discord.utils.get(guild.categories, name=TICKET_CATEGORY_NAME)
    if not ticket_category:
        ticket_category = await guild.create_category(TICKET_CATEGORY_NAME)

    # Define overwrites for the new channel
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        discord.utils.get(guild.roles, name=SUPPORT_ROLE_NAME): discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }

    # Sanitize member name for channel name
    sanitized_member_name = member.name.lower().replace(' ', '-')
    ticket_num_str = str(ticket_counter)

    # Max length for Discord channel names is 100. Let's aim for 90 to be safe.
    max_len = 90

    if topic:
        sanitized_topic = topic.lower().replace(' ', '-')
        # Base format: topic-username-ticketnum
        # Calculate fixed parts length: hyphens, member name, ticket num
        fixed_parts_len = len(f"-{sanitized_member_name}-{ticket_num_str}")
        available_topic_len = max_len - fixed_parts_len

        if available_topic_len > 0:
            final_topic = sanitized_topic[:available_topic_len].rstrip('-')
            channel_name = f"{final_topic}-{sanitized_member_name}-{ticket_num_str}"
        else:
            # Fallback if topic cannot fit, prioritize member name and ticket num
            channel_name = f"{sanitized_member_name}-{ticket_num_str}"
            if len(channel_name) > max_len:
                channel_name = channel_name[:max_len].rstrip('-')
    else:
        # No topic provided, format: username-ticketnum
        channel_name = f"{sanitized_member_name}-{ticket_num_str}"
        if len(channel_name) > max_len:
            channel_name = channel_name[:max_len].rstrip('-')

    # Final check for empty channel name (unlikely)
    if not channel_name:
        channel_name = f"ticket-{ticket_num_str}" # Fallback to a generic ticket name

    ticket_channel = await guild.create_text_channel(
        channel_name, 
        category=ticket_category, 
        overwrites=overwrites,
        topic=f"Ticket created by {member.name} (ID: {member.id})"
    )

    initial_message = f"Welcome {member.mention}! Your ticket"
    if topic:
        initial_message += f" for '{topic}'"
    initial_message += f" (Ticket #{ticket_counter}) has been created. A staff member will be with you shortly."

    await ticket_channel.send(initial_message, view=TicketControlView())
    await interaction.response.send_message(f"Your ticket (Ticket #{ticket_counter}) has been created in {ticket_channel.mention}", ephemeral=True)

async def _close_ticket_logic(interaction: discord.Interaction):
    if interaction.channel.category and interaction.channel.category.name == TICKET_CATEGORY_NAME:
        view = ConfirmButtonView()
        await interaction.response.send_message("Are you sure you want to close this ticket?", view=view, ephemeral=True)
    else:
        await interaction.response.send_message("This command can only be used in a ticket channel.", ephemeral=True)

@bot.tree.command(name="close", description="Closes the current ticket channel.")
@app_commands.checks.has_role(SUPPORT_ROLE_NAME) # Only users with 'Support' role can use this command
async def close(interaction: discord.Interaction):
    await _close_ticket_logic(interaction)

async def _add_user_to_ticket_logic(interaction: discord.Interaction, member: discord.Member):
    if member == bot.user:
        await interaction.response.send_message("I cannot add myself to a ticket channel.", ephemeral=True)
        return

    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    if interaction.channel.category and interaction.channel.category.name == TICKET_CATEGORY_NAME:
        await interaction.channel.set_permissions(member, read_messages=True, send_messages=True)
        await interaction.response.send_message(f"{member.mention} has been added to this ticket.", ephemeral=True)
    else:
        await interaction.response.send_message("This command can only be used in a ticket channel.", ephemeral=True)

@bot.tree.command(name="add", description="Adds a user to the current ticket channel.")
@app_commands.describe(member="The user to add to the ticket.")
async def add(interaction: discord.Interaction, member: discord.Member):
    await _add_user_to_ticket_logic(interaction, member)

async def _remove_user_from_ticket_logic(interaction: discord.Interaction, member: discord.Member):
    if member == bot.user:
        await interaction.response.send_message("I cannot remove myself from a ticket channel.", ephemeral=True)
        return

    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    if interaction.channel.category and interaction.channel.category.name == TICKET_CATEGORY_NAME:
        await interaction.channel.set_permissions(member, overwrite=None)
        await interaction.response.send_message(f"{member.mention} has been removed from this ticket.", ephemeral=True)
    else:
        await interaction.response.send_message("This command can only be used in a ticket channel.", ephemeral=True)

@bot.tree.command(name="remove", description="Removes a user from the current ticket channel.")
@app_commands.describe(member="The user to remove from the ticket.")
async def remove(interaction: discord.Interaction, member: discord.Member):
    await _remove_user_from_ticket_logic(interaction, member)



async def _transcribe_ticket_logic(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    if interaction.channel.category and interaction.channel.category.name == TICKET_CATEGORY_NAME:
        messages = [msg async for msg in interaction.channel.history(limit=None, oldest_first=True)]
        with open(f"{interaction.channel.name}.txt", "w", encoding="utf-8") as f:
            for msg in messages:
                f.write(f"{msg.author.name} ({msg.created_at}): {msg.content}\n")
        await interaction.response.send_message(file=discord.File(f"{interaction.channel.name}.txt"))
    else:
        await interaction.response.send_message("This command can only be used in a ticket channel.", ephemeral=True)

@bot.tree.command(name="transcribe", description="Generates a text file of the ticket conversation history.")
@app_commands.checks.has_role(SUPPORT_ROLE_NAME)
async def transcribe(interaction: discord.Interaction):
    await _transcribe_ticket_logic(interaction)

bot.run(TOKEN)
