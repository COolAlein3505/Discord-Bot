import discord
from discord.ext import commands
import aiosqlite
import math
import json
import asyncio
from datetime import datetime, timedelta
import requests
import time
import csv
import os

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# === ROLE CONFIGURATION ===
ROLE_TIERS = [
    {"name": "Newbie", "color": discord.Color.light_grey(), "threshold": 0},
    {"name": "Pupil", "color": discord.Color.green(), "threshold": 2},
    {"name": "Specialist", "color": discord.Color.blue(), "threshold": 5},
    {"name": "Expert", "color": discord.Color.dark_blue(), "threshold": 20},
    {"name": "Candidate Master", "color": discord.Color.purple(), "threshold": 50},
    {"name": "Master", "color": discord.Color.gold(), "threshold": 100},
    {"name": "International Master", "color": discord.Color.orange(), "threshold": 150},
    {"name": "Grandmaster", "color": discord.Color.red(), "threshold": 200}
]
    
def has_ad_role(ctx):
    return any(role.name == "AD" for role in ctx.author.roles)

# Database initialization
async def init_db():
    async with aiosqlite.connect('market.db') as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance REAL DEFAULT 20.0,
                shares TEXT,
                correct_predictions INTEGER DEFAULT 0
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS questions (
                question_id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER,
                question_text TEXT,
                option1 TEXT,
                option2 TEXT,
                option1_price REAL DEFAULT 5.0,
                option2_price REAL DEFAULT 5.0,
                end_time DATETIME,
                correct_option INTEGER,
                resolved BOOLEAN DEFAULT FALSE
            )
        ''')
        await db.commit()
        
# === RANK CHECK COMMAND ===
# Update this in your checkrank command
async def checkrank(ctx):
    async with aiosqlite.connect('market.db') as db:
        # CALCULATE correct count the same way balance does
        # by checking resolved questions against user holdings
        cursor = await db.execute(
            "SELECT question_id, correct_option FROM questions WHERE resolved = TRUE"
        )
        resolved_questions = await cursor.fetchall()
        
        user = await (await db.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (ctx.author.id,)
        )).fetchone()
        
        # Use the SAME calculation as in balance
        correct_count = 0
        if user and user[2]:  # if user exists and has shares
            shares = json.loads(user[2])
            for qid, correct_option in resolved_questions:
                qid_str = str(qid)
                if qid_str in shares:
                    user_options = shares[qid_str]
                    for opt in user_options:
                        if int(opt) == correct_option:
                            correct_count += 1

# === IMPROVED ROLE UPDATE FUNCTION ===
async def update_user_role(guild, user_id):
    """Update a user's role based on their prediction success"""
    try:
        # Refresh role data
        await guild.fetch_roles()
        
        # Get user data
        async with aiosqlite.connect('market.db') as db:
            cursor = await db.execute(
                "SELECT COALESCE(correct_predictions, 0) FROM users WHERE user_id = ?", 
                (user_id,)
            )
            result = await cursor.fetchone()
            correct_count = result[0] if result else 0

        # Find appropriate tier
        current_tier = next((t for t in reversed(ROLE_TIERS) if correct_count >= t["threshold"]), None)
        if not current_tier:
            return

        member = guild.get_member(user_id)
        if not member:
            return

        # Get or create role with proper hierarchy
        role = discord.utils.get(guild.roles, name=current_tier["name"])
        if not role:
            try:
                bot_top_role = guild.me.top_role
                role = await guild.create_role(
                    name=current_tier["name"],
                    color=current_tier["color"],
                    reason="Auto-created prediction tier role",
                    position=bot_top_role.position - 1
                )
            except discord.Forbidden:
                print(f"Missing permissions to create role: {current_tier['name']}")
                return

        # Check role position
        if role.position >= guild.me.top_role.position:
            print(f"Bot cannot assign higher role: {role.name}")
            return

        # Remove old tier roles
        current_roles = [r for r in member.roles if r.name in [t["name"] for t in ROLE_TIERS]]
        if current_roles:
            await member.remove_roles(*current_roles, reason="Rank update")
            
        # Add new role
        await member.add_roles(role, reason="Rank update")
        
    except Exception as e:
        print(f"Error updating roles: {str(e)}")
        
        
@bot.command()
@commands.check(has_ad_role)  # Only users with 'AD' role can use this
async def test_role(ctx, member: discord.Member):
    """Test role assignment (Admin only)"""
    try:
        role = discord.utils.get(ctx.guild.roles, name="Newbie")
        if not role:
            await ctx.send("Role 'Newbie' does not exist!")
            return
        await member.add_roles(role)
        await ctx.send(f"✅ Assigned {role.name} to {member.mention}")
    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)}")

@bot.command()
async def check_perms(ctx):
    """Check bot's permissions"""
    perms = ctx.guild.me.guild_permissions
    embed = discord.Embed(title="Bot Permissions", color=0x00ff00)
    embed.add_field(name="Manage Roles", value=str(perms.manage_roles))
    embed.add_field(name="Administrator", value=str(perms.administrator))
    embed.add_field(name="Top Role", value=ctx.guild.me.top_role.name)
    await ctx.send(embed=embed)


# Background task
async def check_active_questions():
    await bot.wait_until_ready()
    while not bot.is_closed():
        async with aiosqlite.connect('market.db') as db:
            now = datetime.now().isoformat()
            async with db.execute(
                "SELECT question_id, channel_id, question_text FROM questions WHERE end_time < ? AND resolved = FALSE",
                (now,)
            ) as cursor:
                expired = await cursor.fetchall()
            for qid, channel_id, question_text in expired:
                await db.execute(
                    "UPDATE questions SET resolved = TRUE WHERE question_id = ?",
                    (qid,)
                )
                channel = bot.get_channel(channel_id)
                if channel:
                    await channel.send(
                        f"⏰ **Prediction Closed!**\n> {question_text}\nNo more bets are accepted."
                    )
            await db.commit()
        await asyncio.sleep(60)
        
@bot.command(name="check_rank")
async def check_rank(ctx):
    """Show your prediction rank and update your role if needed."""

    async with aiosqlite.connect('market.db') as db:
        # Get all resolved questions
        cursor = await db.execute(
            "SELECT question_id, correct_option FROM questions WHERE resolved = TRUE AND correct_option IS NOT NULL"
        )
        resolved_questions = await cursor.fetchall()

        # Get user data
        user = await (await db.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (ctx.author.id,)
        )).fetchone()

    # Calculate correct predictions (1 per correct question, not per share)
    correct_count = 0
    if user and user[2]:
        shares = json.loads(user[2])
        for qid, correct_option in resolved_questions:
            qid_str = str(qid)
            if qid_str in shares:
                user_options = shares[qid_str]
                if str(correct_option) in user_options and user_options[str(correct_option)] > 0:
                    correct_count += 1

    # Determine rank/tier
    current_tier = None
    for tier in reversed(ROLE_TIERS):
        if correct_count >= tier["threshold"]:
            current_tier = tier
            break
    role_name = current_tier["name"] if current_tier else "Newbie"

    # --- Role update logic ---
    member = await ctx.guild.fetch_member(ctx.author.id)  # Always fetch fresh member data

    if member and current_tier:
        # Get or create the role
        role = discord.utils.get(ctx.guild.roles, name=current_tier["name"])
        if not role:
            # Create the role just below the bot's top role
            bot_top_role = ctx.guild.me.top_role
            role = await ctx.guild.create_role(
                name=current_tier["name"],
                color=current_tier["color"],
                reason="Auto-created prediction tier role",
            )
            # Move the role just below the bot's top role
            await role.edit(position=bot_top_role.position - 1)

        # Remove all other prediction roles
        tier_names = [t["name"] for t in ROLE_TIERS]
        roles_to_remove = [r for r in member.roles if r.name in tier_names and r != role]
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason="Prediction rank update")

        # Add the correct role if not already present
        if role not in member.roles:
            await member.add_roles(role, reason="Prediction rank update")

    # --- Send result embed ---
    embed = discord.Embed(
        title="Your Prediction Rank",
        color=current_tier["color"] if current_tier and "color" in current_tier else 0x7289da
    )
    embed.add_field(name="Correct Predictions", value=str(correct_count))
    embed.add_field(name="Current Rank", value=role_name)
    await ctx.send(embed=embed)


@bot.command()
async def buy(ctx, question_id: int, option: int, shares: float):
    """Buy shares in a prediction market"""
    if option not in [1, 2]:
        await ctx.send("Invalid option! Use 1 or 2")
        return

    async with aiosqlite.connect('market.db') as db:
        async with db.execute("BEGIN TRANSACTION"):
            # Get question and user data
            question = await (await db.execute(
                "SELECT * FROM questions WHERE question_id = ? AND resolved = FALSE",
                (question_id,)
            )).fetchone()
            
            user = await (await db.execute(
                "SELECT * FROM users WHERE user_id = ?",
                (ctx.author.id,)
            )).fetchone()

            if not question:
                await ctx.send("Invalid or expired question ID!")
                return

            # Calculate cost
            price = question[5 if option == 1 else 6]
            total_cost = shares * price

            # Check balance
            current_balance = user[1] if user else 20.0
            if current_balance < total_cost:
                await ctx.send("Insufficient funds!")
                return

            # Update price
            new_price = update_price(price, shares)
            await db.execute(f'''
                UPDATE questions 
                SET option{option}_price = ?
                WHERE question_id = ?
            ''', (new_price, question_id))

            # Update user balance and shares
            new_balance = current_balance - total_cost
            shares_data = json.loads(user[2]) if user and user[2] else {}
            shares_data.setdefault(str(question_id), {})[str(option)] = shares_data.get(str(question_id), {}).get(str(option), 0) + shares
            
            await db.execute('''
                INSERT OR REPLACE INTO users 
                (user_id, balance, shares)
                VALUES (?,?,?)
            ''', (ctx.author.id, new_balance, json.dumps(shares_data)))
            
            await db.commit()

    await ctx.send(f"✅ Bought {shares} shares of Option {option} at {price:.2f} each!")

@bot.command()
async def market(ctx, question_id: int):
    """View current market status"""
    async with aiosqlite.connect('market.db') as db:
        question = await (await db.execute(
            "SELECT * FROM questions WHERE question_id = ?",
            (question_id,)
        )).fetchone()

    if not question:
        await ctx.send("❌ Invalid question ID!")
        return

    # Extract info for clarity
    qid = question[0]
    qtext = question[2]
    option1 = question[3]
    option2 = question[4]
    price1 = question[5]
    price2 = question[6]
    end_time = datetime.fromisoformat(question[7])
    resolved = question[9]
    correct_option = question[8]

    status = "🟢 **Active**" if not resolved else "🔒 **Closed**"
    result = ""
    if resolved and correct_option:
        result = f"\n\n🏆 **Result:** Option {correct_option} was correct!"

    embed = discord.Embed(
        title=f"📊 Prediction Market #{qid}",
        description=f"**{qtext}**\n\nMarket Status: {status}{result}",
        color=0x00ff00 if not resolved else 0xff5555
    )
    embed.add_field(
        name=f"🟩 Option 1: {option1}",
        value=f"💸 **Price:** {price1:.2f} coins",
        inline=True
    )
    embed.add_field(
        name=f"🟥 Option 2: {option2}",
        value=f"💸 **Price:** {price2:.2f} coins",
        inline=True
    )
    embed.add_field(
        name="⏰ Closes At",
        value=end_time.strftime("%Y-%m-%d %H:%M"),
        inline=False
    )
    embed.set_footer(text="Use !buy <question_id> <option_number> <shares> to participate!")

    await ctx.send(embed=embed)

    await ctx.send(embed=embed)

# Add this command handler
@bot.command()
async def sell(ctx, question_id: int, option: int, shares: float):
    """Sell shares in a prediction market"""
    if option not in [1, 2]:
        await ctx.send("Invalid option! Use 1 or 2")
        return

    async with aiosqlite.connect('market.db') as db:
        async with db.execute("BEGIN TRANSACTION"):
            # Get question and user data
            question = await (await db.execute(
                "SELECT * FROM questions WHERE question_id = ? AND resolved = FALSE",
                (question_id,)
            )).fetchone()
            
            user = await (await db.execute(
                "SELECT * FROM users WHERE user_id = ?",
                (ctx.author.id,)
            )).fetchone()

            if not question:
                await ctx.send("Invalid or expired question ID!")
                return

            if not user or not user[2]:
                await ctx.send("You don't own any shares in this question!")
                return

            shares_data = json.loads(user[2])
            holdings = shares_data.get(str(question_id), {}).get(str(option), 0)
            
            if shares > holdings:
                await ctx.send(f"You only have {holdings} shares to sell!")
                return

            # Calculate proceeds
            price = question[5 if option == 1 else 6]
            total_proceeds = shares * price

            # Update price
            new_price = update_price(price, -shares)  # Negative quantity for selling
            await db.execute(f'''
                UPDATE questions 
                SET option{option}_price = ?
                WHERE question_id = ?
            ''', (new_price, question_id))

            # Update user balance and shares
            new_balance = user[1] + total_proceeds
            shares_data[str(question_id)][str(option)] -= shares
            
            # Cleanup empty holdings
            if shares_data[str(question_id)][str(option)] <= 0:
                del shares_data[str(question_id)][str(option)]
            if not shares_data[str(question_id)]:
                del shares_data[str(question_id)]
            
            await db.execute('''
                UPDATE users 
                SET balance = ?, shares = ?
                WHERE user_id = ?
            ''', (new_balance, json.dumps(shares_data), ctx.author.id))
            
            await db.commit()

    await ctx.send(f"✅ Sold {shares} shares of Option {option} at {price:.2f} each!")

# Update the balance command
@bot.command()
async def balance(ctx):
    """Check your balance, holdings, and prediction stats with role display"""
    async with aiosqlite.connect('market.db') as db:
        # Get user data
        user_data = await (await db.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (ctx.author.id,)
        )).fetchone()
        
        # Get all resolved questions
        cursor = await db.execute(
            "SELECT question_id, correct_option FROM questions WHERE resolved = TRUE AND correct_option IS NOT NULL"
        )
        resolved_questions = await cursor.fetchall()

    # Set defaults if user doesn't exist
    if not user_data:
        balance = 20.0
        shares = {}
        correct = 0
        wrong = 0
        total_attempted = 0
    else:
        balance = user_data[1]
        shares = json.loads(user_data[2]) if user_data[2] else {}
        
        # Calculate stats
        correct = 0
        wrong = 0
        total_attempted = 0
        
        if shares and resolved_questions:
            for q_id, correct_option in resolved_questions:
                q_str = str(q_id)
                if q_str in shares:
                    user_options = shares[q_str]
                    for opt in user_options:
                        total_attempted += 1
                        if int(opt) == correct_option:
                            correct += 1
                        else:
                            wrong += 1

    # Determine user's role and next threshold
    current_tier = None
    next_threshold = None
    for tier in reversed(ROLE_TIERS):
        if correct >= tier["threshold"]:
            current_tier = tier
            break
    if current_tier:
        idx = ROLE_TIERS.index(current_tier)
        if idx + 1 < len(ROLE_TIERS):
            next_threshold = ROLE_TIERS[idx + 1]["threshold"]
    role_name = current_tier["name"] if current_tier else "Newbie"
    role_color = current_tier["color"] if current_tier and "color" in current_tier else 0x7289da

    # Create the embed
    embed = discord.Embed(
        title=f"💼 {ctx.author.display_name}'s Prediction Portfolio",
        color=role_color
    )
    embed.add_field(
        name="💰 **Balance**",
        value=f"**{balance:.2f} coins**",
        inline=False
    )

    # Holdings section
    if shares:
        portfolio_lines = []
        for qid, opts in shares.items():
            opt_str = " | ".join(f"Option {opt}: **{amt}**" for opt, amt in opts.items())
            portfolio_lines.append(f"• **Market {qid}**: {opt_str}")
        embed.add_field(
            name="📈 **Your Holdings**",
            value="\n".join(portfolio_lines),
            inline=False
        )
    else:
        embed.add_field(
            name="📈 **Your Holdings**",
            value="You don't own any shares yet. Use `!buy` to start predicting!",
            inline=False
        )

    # Stats section
    stats = (
        f"✅ **Correct:** {correct}\n"
        f"❌ **Wrong:** {wrong}\n"
        f"📊 **Total Attempted:** {total_attempted}"
    )
    embed.add_field(
        name="📊 **Prediction Stats**",
        value=stats,
        inline=False
    )

    # Rank section
    rank_info = f"🏅 **Current Rank:** `{role_name}`"
    if next_threshold:
        rank_info += f"\n🔜 *Next rank at* **{next_threshold}** *correct predictions*"
    else:
        rank_info += "\n🏆 *You are at the highest rank!*"
    embed.add_field(
        name="🏆 **Rank Progression**",
        value=rank_info,
        inline=False
    )

    embed.set_footer(text="Keep predicting to climb the ranks! Use !check_rank to update your role.")
    await ctx.send(embed=embed)
    
bot.remove_command('help')
    
@bot.command()
async def help(ctx):
    """Show available commands, ranking system, and examples"""
    embed = discord.Embed(
        title="✨ Prediction Market Bot Help ✨",
        description="Welcome to the Prediction Market! Place bets, climb the ranks, and become a Grandmaster! 🏆",
        color=0x00ffcc
    )

    # Admin commands
    admin_cmds = (
        "🔹 `!create_question \"Question?\" \"Option1\" \"Option2\" <minutes>`\n"
        "  Create a new prediction market (Admin only)\n"
        "🔹 `!resolve <question_id> <correct_option>`\n"
        "  Resolve a market and distribute winnings (Admin only)"
    )
    embed.add_field(name="👑 Admin Commands", value=admin_cmds, inline=False)

    # User commands (all available)
    user_cmds = (
        "🔹 `!list_questions` — **See all open prediction questions**\n"
        "🔹 `!market <question_id>` — View details of a specific question\n"
        "🔹 `!buy <question_id> <option_number> <shares>` — Buy shares in a question\n"
        "🔹 `!sell <question_id> <option_number> <shares>` — Sell your shares in a question\n"
        "🔹 `!balance` — Show your coin balance, holdings, and stats\n"
        "🔹 `!check_rank` — See your current rank and force a role update"
    )
    embed.add_field(name="🧑‍💼 User Commands", value=user_cmds, inline=False)

    # Ranking system
    ranking = (
        "🏅 **Ranking System:**\n"
        "• 🕹️ **Newbie** *(0+ correct)* — Grey\n"
        "• 🟩 **Pupil** *(2+ correct)* — Green\n"
        "• 🟦 **Specialist** *(5+ correct)* — Light Blue\n"
        "• 🔵 **Expert** *(20+ correct)* — Dark Blue\n"
        "• 🟣 **Candidate Master** *(50+ correct)* — Purple\n"
        "• 🟡 **Master** *(100+ correct)* — Gold/Yellow\n"
        "• 🟧 **International Master** *(150+ correct)* — Orange/Yellow\n"
        "• 🟥 **Grandmaster** *(200+ correct)* — Red\n\n"
        "⭐ Your rank upgrades automatically as you get more predictions correct!\n"
        "⭐ Use `!check_rank` anytime to see your rank or force an update."
    )
    embed.add_field(name="🏆 Ranking System", value=ranking, inline=False)

    # Examples
    examples = (
        "**Quick Examples:**\n"
        "• `!create_question \"Will CSK win today?\" \"Yes\" \"No\" 60`\n"
        "• `!list_questions` (See all open questions)\n"
        "• `!buy 1 1 5` (Buy 5 shares of option 1 for question 1)\n"
        "• `!sell 1 2 3` (Sell 3 shares of option 2 for question 1)\n"
        "• `!resolve 1 2` (Declare option 2 as correct for question 1)\n"
        "• `!check_rank` (See or update your rank)"
    )
    embed.add_field(name="📝 Examples", value=examples, inline=False)

    embed.set_footer(text="Good luck! May the odds be ever in your favor. 🎲")
    await ctx.send(embed=embed)

    
@bot.command()
async def create_question(ctx, question: str, option1: str, option2: str, minutes: int):
    # Only allow users with the 'AD' role
    if not has_ad_role(ctx):
        await ctx.send("⛔ You don't have permission to use this command. Only users with the 'AD' role can use it.")
        return
    try:
        end_time = datetime.now() + timedelta(minutes=minutes)
        async with aiosqlite.connect('market.db') as db:
            cursor = await db.execute('''
                INSERT INTO questions 
                (channel_id, question_text, option1, option2, end_time)
                VALUES (?,?,?,?,?)
            ''', (ctx.channel.id, question, option1, option2, end_time.isoformat()))
            await db.commit()
            # Get the question_id of the last inserted row
            question_id = cursor.lastrowid

        embed = discord.Embed(
            title=f"📊 New Prediction Market (ID: {question_id})",
            description=f"**{question}**\n\n"
                        f"1️⃣ {option1}\n2️⃣ {option2}\n"
                        f"⏳ Closes in {minutes} minutes",
            color=0x00ff00
        )
        embed.set_footer(text=f"Question ID: {question_id} • Use this ID to buy shares.")
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"Error creating question: {str(e)}")

@bot.command()
@commands.check(has_ad_role)
async def resolve(ctx, question_id: int, correct_option: int):
    """Resolve a prediction market and update user roles"""
    try:
        async with aiosqlite.connect('market.db') as db:
            # Get the question
            question = await (await db.execute(
                "SELECT * FROM questions WHERE question_id = ?", (question_id,)
            )).fetchone()
            
            if not question:
                await ctx.send("❌ Invalid question ID.")
                return
                
            if question[8] is not None:
                await ctx.send("❌ This question has already been resolved with a correct option.")
                return
                
            if correct_option not in [1, 2]:
                await ctx.send("❌ Correct option must be 1 or 2.")
                return
                
            final_price = question[5] if correct_option == 1 else question[6]

            # Get all users that need updating
            cursor = await db.execute("SELECT * FROM users")
            users_data = await cursor.fetchall()
            
            # Track users who got this correct (for role updates)
            correct_users = []
            
            # Process payouts
            for user_data in users_data:
                user_id = user_data[0]
                shares = json.loads(user_data[2]) if user_data[2] and len(user_data) > 2 else {}
                holdings = shares.get(str(question_id), {})
                
                if str(correct_option) in holdings:
                    # User predicted correctly
                    payout = holdings[str(correct_option)] * final_price
                    new_balance = user_data[1] + payout
                    
                    # First, make sure the column exists
                    try:
                        await db.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS correct_predictions INTEGER DEFAULT 0")
                    except:
                        pass  # Column already exists
                    
                    # Then update both balance and correct_predictions in a single query
                    await db.execute(
                        "UPDATE users SET balance = ?, correct_predictions = COALESCE(correct_predictions, 0) + 1 WHERE user_id = ?",
                        (new_balance, user_id)
                    )
                    
                    # Add to list for role updates
                    correct_users.append(user_id)
                    
                    print(f"✅ User {user_id} predicted correctly, incremented correct_predictions")

            # Mark question as resolved
            await db.execute(
                "UPDATE questions SET correct_option = ?, resolved = TRUE WHERE question_id = ?",
                (correct_option, question_id)
            )
            
            await db.commit()
        
        # Update roles for users who got it right
        for user_id in correct_users:
            try:
                member = ctx.guild.get_member(user_id)
                if member:
                    # Update user's role based on their CURRENT correct predictions count
                    async with aiosqlite.connect('market.db') as db:
                        cursor = await db.execute(
                            "SELECT correct_predictions FROM users WHERE user_id = ?", 
                            (user_id,)
                        )
                        result = await cursor.fetchone()
                        if result:
                            print(f"User {user_id} now has {result[0]} correct predictions")
                    
                    await update_user_role(ctx.guild, user_id)
            except Exception as role_error:
                print(f"Error updating role for user {user_id}: {str(role_error)}")
            
        await ctx.send(f"✅ Market resolved! Option {correct_option} is correct. Winnings have been distributed.")

    except Exception as e:
        import traceback
        print(f"Resolve error: {str(e)}")
        print(traceback.format_exc())
        await ctx.send(f"❌ Error resolving question: {str(e)}")

        
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        # For admin-only commands
        await ctx.send("⛔ You don't have permission to use this command. Admin privileges required.")
    elif isinstance(error, commands.CommandNotFound):
        # For invalid commands
        await ctx.send("❓ Unknown command. Use `!help` to see available commands.")
    elif isinstance(error, commands.MissingRequiredArgument):
        # For commands with missing arguments
        await ctx.send("⚠️ Missing required argument. Please check command syntax.")
    else:
        # For other errors
        await ctx.send(f"❌ An error occurred: {str(error)}")
        
@bot.command()
async def give_coins(ctx, member: discord.Member, amount: float):
    # Check if the invoker has the 'AD' role
    if not any(role.name == "AD" for role in ctx.author.roles):
        await ctx.send("⛔ You don't have permission to use this command. Only users with the 'AD' role can use it.")
        return
    if amount <= 0:
        await ctx.send("❌ Please specify a positive amount of coins to give.")
        return
    async with aiosqlite.connect('market.db') as db:
        # Get the user's current balance
        user = await (await db.execute(
            "SELECT * FROM users WHERE user_id = ?", (member.id,)
        )).fetchone()
        if not user:
            balance = 20.0 + amount  # If user doesn't exist, start with 20 + amount
        else:
            balance = user[1] + amount
        await db.execute(
            "INSERT OR REPLACE INTO users (user_id, balance, shares) VALUES (?, ?, ?)",
            (member.id, balance, user[2] if user else json.dumps({}))
        )
        await db.commit()
    await ctx.send(f"✅ Gave {amount:.2f} coins to {member.mention}. New balance: {balance:.2f} coins.")
    
@bot.command()
async def list_questions(ctx):
    """List all active prediction markets (Available to everyone)"""
    async with aiosqlite.connect('market.db') as db:
        now = datetime.now().isoformat()
        cursor = await db.execute(
            "SELECT question_id, question_text, option1, option2, end_time FROM questions WHERE resolved = FALSE AND end_time > ?",
            (now,)
        )
        rows = await cursor.fetchall()
    
    if not rows:
        await ctx.send("🟡 There are no active prediction questions right now. Use `!create_question` to start one!")
        return

    embed = discord.Embed(
        title="🟢 **Active Prediction Markets**",
        description="Place your bets! Use `!market <question_id>` to see prices and details.",
        color=0x00ff99
    )
    for qid, qtext, opt1, opt2, end_time in rows:
        dt_end = datetime.fromisoformat(end_time)
        remaining = dt_end - datetime.now()
        total_seconds = int(remaining.total_seconds())
        if total_seconds > 0:
            hours, remainder = divmod(total_seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            time_left = f"⏰ `{hours}h {minutes}m` remaining"
        else:
            time_left = "⏰ Closing soon"
        
        embed.add_field(
            name=f"❓ **Q{qid}: {qtext}**",
            value=f"1️⃣ **{opt1}**  |  2️⃣ **{opt2}**\n{time_left}",
            inline=False
        )
    embed.set_footer(text="Use !buy <question_id> <option_number> <shares> to participate!")
    await ctx.send(embed=embed)


# Price calculation function
def update_price(old_price, quantity):
    return old_price * math.exp(0.001 * quantity)

# Bot events
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    # Start the background task here after the bot is ready
    bot.bg_task = asyncio.create_task(check_active_questions())

# Run the bot
async def main():
    await init_db()
    await bot.start('MTM2Mjc3ODIxMjUyNTkzMjY5NA.GNMAYE.tHpMM0QdchSD2mdFVISmTW5Uxvu9wZGJEnbVH8')  # Replace with your actual token

if __name__ == "__main__":
    asyncio.run(main())
    