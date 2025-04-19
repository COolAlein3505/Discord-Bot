import discord
from discord.ext import commands
import aiosqlite
import math
import json
import asyncio
from datetime import datetime, timedelta

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

def has_ad_role(ctx):
    return any(role.name == "AD" for role in ctx.author.roles)

# Database initialization
async def init_db():
    async with aiosqlite.connect('market.db') as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance REAL DEFAULT 20.0,
                shares TEXT
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
        await ctx.send("Invalid question ID!")
        return

    embed = discord.Embed(
        title=question[2],
        description=f"Market ID: {question[0]}",
        color=0x00ff00
    )
    embed.add_field(name=f"🟢 {question[3]}", value=f"Price: {question[5]:.2f}")
    embed.add_field(name=f"🔴 {question[4]}", value=f"Price: {question[6]:.2f}")
    embed.set_footer(text=f"Closes at {datetime.fromisoformat(question[7]).strftime('%H:%M')}")
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
    """Check your balance, holdings, and prediction stats"""
    async with aiosqlite.connect('market.db') as db:
        user = await (await db.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (ctx.author.id,)
        )).fetchone()

        # Get all resolved questions
        resolved_questions = await (await db.execute(
            "SELECT question_id, correct_option FROM questions WHERE resolved = TRUE"
        )).fetchall()

    if not user:
        balance = 20.0
        shares = {}
    else:
        balance = user[1]
        shares = json.loads(user[2]) if user[2] else {}

    # Calculate prediction stats
    correct = 0
    wrong = 0
    total_attempted = 0
    
    for qid, correct_option in resolved_questions:
        qid_str = str(qid)
        if qid_str in shares:
            user_options = shares[qid_str]
            for opt in user_options:
                total_attempted += 1
                if int(opt) == correct_option:
                    correct += 1
                else:
                    wrong += 1

    embed = discord.Embed(
        title=f"{ctx.author.display_name}'s Portfolio",
        color=0x7289da
    )
    embed.add_field(name="💰 Balance", value=f"{balance:.2f} coins", inline=False)
    
    if shares:
        portfolio = "\n".join(
            f"Market {qid}: {', '.join(f'{opt}×{amt}' for opt, amt in opts.items())}"
            for qid, opts in shares.items()
        )
        embed.add_field(name="📈 Holdings", value=portfolio, inline=False)
    
    stats = [
        f"✅ Correct Predictions: {correct}",
        f"❌ Wrong Predictions: {wrong}",
        f"📊 Total Attempted: {total_attempted}"
    ]
    embed.add_field(name="📊 Prediction Stats", value="\n".join(stats), inline=False)
    
    await ctx.send(embed=embed)
    
bot.remove_command('help')
    
@bot.command()
async def help(ctx):
    """Show available commands"""
    embed = discord.Embed(
        title="Prediction Market Bot Commands",
        description="List of available commands:",
        color=0x7289da
    )
    
    # Admin commands
    admin_cmds = (
        "`!create_question \"Question?\" \"Option1\" \"Option2\" <minutes>` - Create a new prediction market\n"
        "`!resolve <question_id> <correct_option>` - Resolve a market"
    )
    embed.add_field(name="👑 Admin Commands", value=admin_cmds, inline=False)
    
    # User commands
    user_cmds = (
        "`!list_questions` - List all active questions\n"
        "`!market <question_id>` - View details of a question\n"
        "`!buy <question_id> <option_number> <shares>` - Buy shares in a question\n"
        "`!balance` - Show your coin balance and holdings"
    )
    embed.add_field(name="👤 User Commands", value=user_cmds, inline=False)
    
    # Examples
    examples = (
        "**Examples:**\n"
        "- `!create_question \"Will CSK win today?\" \"Yes\" \"No\" 60`\n"
        "- `!buy 1 1 5` (Buy 5 shares of option 1 for question 1)\n"
        "- `!resolve 1 2` (Declare option 2 as correct for question 1)"
    )
    embed.add_field(name="📝 Examples", value=examples, inline=False)
    
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
            await db.execute('''
                INSERT INTO questions 
                (channel_id, question_text, option1, option2, end_time)
                VALUES (?,?,?,?,?)
            ''', (ctx.channel.id, question, option1, option2, end_time.isoformat()))
            await db.commit()
        embed = discord.Embed(
            title="📊 New Prediction Market",
            description=f"**{question}**\n\n"
                        f"1️⃣ {option1}\n2️⃣ {option2}\n"
                        f"⏳ Closes in {minutes} minutes",
            color=0x00ff00
        )
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"Error creating question: {str(e)}")

@bot.command()
@commands.has_role("AD")
async def resolve(ctx, question_id: int, correct_option: int):
    """Resolve a prediction market (Admin only)"""
    try:
        async with aiosqlite.connect('market.db') as db:
            # Get the question
            question = await (await db.execute(
                "SELECT * FROM questions WHERE question_id = ?", (question_id,)
            )).fetchone()
            if not question:
                await ctx.send("❌ Invalid question ID.")
                return
            # question[8] is correct_option, question[9] is resolved
            if question[8] is not None:
                await ctx.send("❌ This question has already been resolved with a correct option.")
                return
            if correct_option not in [1, 2]:
                await ctx.send("❌ Correct option must be 1 or 2.")
                return

            final_price = question[5] if correct_option == 1 else question[6]

            # Update all users
            users = await (await db.execute("SELECT * FROM users")).fetchall()
            for user in users:
                shares = json.loads(user[2]) if user[2] else {}
                holdings = shares.get(str(question_id), {})
                if str(correct_option) in holdings:
                    payout = holdings[str(correct_option)] * final_price
                    new_balance = user[1] + payout
                    await db.execute(
                        "UPDATE users SET balance = ? WHERE user_id = ?",
                        (new_balance, user[0])
                    )

            # Mark question as resolved and set correct option
            await db.execute(
                "UPDATE questions SET correct_option = ?, resolved = TRUE WHERE question_id = ?",
                (correct_option, question_id)
            )
            await db.commit()

        await ctx.send(f"✅ Market resolved! Option {correct_option} is correct. Winnings have been distributed.")
    except Exception as e:
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
        await ctx.send("There are no active questions right now.")
        return

    embed = discord.Embed(
        title="🟢 Active Prediction Markets",
        color=0x00ff00
    )
    for qid, qtext, opt1, opt2, end_time in rows:
        remaining = datetime.fromisoformat(end_time) - datetime.now()
        hours, remainder = divmod(remaining.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        time_left = f"{hours}h {minutes}m remaining" if remaining.total_seconds() > 0 else "Closing soon"
        
        embed.add_field(
            name=f"ID: {qid} | {time_left}",
            value=f"**{qtext}**\n1️⃣ {opt1} | 2️⃣ {opt2}",
            inline=False
        )
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
    await bot.start('MTM2Mjc3ODIxMjUyNTkzMjY5NA.GHOJ_2.J1b9itnnEL5JfS-y9f9B-VF4RYnycAgrWYPkeo')  # Replace with your actual token

if __name__ == "__main__":
    asyncio.run(main())
