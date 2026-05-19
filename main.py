import os
import json
import aiohttp
from dotenv import load_dotenv
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    ReplyKeyboardMarkup, 
    KeyboardButton
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# Load the variables from the .env file
load_dotenv()

# --- CONFIG & SECRETS ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")

# Payment Details
LTC_ADDRESS = "ltc1qczgu6hl7xksc7ga62r222urvad6lek89jtj99l"

# --- ADMIN & WHITELIST SETUP ---
ADMIN_HANDLE = "NOT_SPARSH"
WHITELIST_FILE = "whitelist.json"
USERS_FILE = "users.json"
WHITELIST_ENABLED = True  # Set to False to let anyone use the bot

# --- MENU BUTTON STRINGS ---
MENU_SERIES = "Search TV Series"
MENU_MOVIES = "Search Movies"
MENU_CONTACT = "Contact Us"
MENU_DONATE = "Donate"

# --- SERVERS ---
SERIES_SERVERS = {
    "Server 1": "https://www.mapple.uk/watch/tv/{tmdb_id}/{season}/{episode}",
    "Server 2": "https://vidfast.pro/tv/{tmdb_id}/{season}/{episode}",
    "Server 3": "https://player.videasy.net/tv/{tmdb_id}/{season}/{episode}",
    "Server 4": "https://vidlink.pro/tv/{tmdb_id}/{season}/{episode}",
    "Server 5": "https://vidsrc-embed.ru/embed/tv/{tmdb_id}/{season}/{episode}"
}

MOVIE_SERVERS = {
    "Server 1": "https://www.mapple.uk/watch/movie/{tmdb_id}",
    "Server 2": "https://vidfast.pro/movie/{tmdb_id}",
    "Server 3": "https://player.videasy.net/movie/{tmdb_id}",
    "Server 4": "https://vidlink.pro/movie/{tmdb_id}",
    "Server 5": "https://vidsrc-embed.ru/embed/movie/{tmdb_id}"
}

# --- CONVERSATION STATES ---
TYPING_SERIES_QUERY, TYPING_MOVIE_QUERY = range(2)

# --- UTILS, WHITELIST & USER TRACKING LOGIC ---
def load_json_file(filepath, default_data):
    if not os.path.exists(filepath):
        with open(filepath, "w") as f:
            json.dump(default_data, f)
        return default_data
    with open(filepath, "r") as f:
        return json.load(f)

def save_json_file(filepath, data):
    with open(filepath, "w") as f:
        json.dump(data, f)

def load_whitelist():
    return load_json_file(WHITELIST_FILE, [ADMIN_HANDLE])

def save_whitelist(whitelist_data):
    save_json_file(WHITELIST_FILE, whitelist_data)

def is_authorized(username: str) -> bool:
    if not WHITELIST_ENABLED:
        return True
    clean_username = username.replace("@", "") if username else ""
    return clean_username in load_whitelist()

def track_user(user):
    """Saves the user to users.json with their summon status."""
    users = load_json_file(USERS_FILE, {})
    chat_id_str = str(user.id)
    
    if chat_id_str not in users:
        users[chat_id_str] = {
            "username": user.username or "No_Username",
            "first_name": user.first_name or "Unknown",
            "summon_status": "none"  # "none", "normal", or "force"
        }
    else:
        # Update details but keep their summon status intact
        users[chat_id_str]["username"] = user.username or "No_Username"
        users[chat_id_str]["first_name"] = user.first_name or "Unknown"
        if "summon_status" not in users[chat_id_str]:
            users[chat_id_str]["summon_status"] = "none"
            
    save_json_file(USERS_FILE, users)

def get_admin_id(users_data):
    return next((cid for cid, data in users_data.items() if data.get('username') == ADMIN_HANDLE), None)

def escape_html(text: str) -> str:
    """Helper to escape HTML to prevent Telegram parsing errors"""
    if not text:
        return "N/A"
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def get_main_menu():
    """Returns the persistent bottom keyboard layout"""
    keyboard = [
        [KeyboardButton(MENU_SERIES), KeyboardButton(MENU_MOVIES)],
        [KeyboardButton(MENU_CONTACT), KeyboardButton(MENU_DONATE)]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- TMDB FETCHERS ---
async def fetch_tmdb_search(query: str, search_type="tv"):
    url = f"https://api.themoviedb.org/3/search/{search_type}?api_key={TMDB_API_KEY}&query={query}&language=en-US&page=1"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            return data.get("results", [])[:5] 

async def fetch_tmdb_details(tmdb_id: str, media_type="tv"):
    url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}?api_key={TMDB_API_KEY}&language=en-US"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.json()

# --- ADMIN COMMANDS ---
async def wl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username != ADMIN_HANDLE:
        return

    args = context.args
    if not args or len(args) == 0:
        await update.message.reply_text("Usage:\n/wl list\n/wl add username\n/wl remove username")
        return

    action = args[0].lower()
    whitelist = load_whitelist()

    if action == "list":
        users = "\n".join([f"- @{u}" for u in whitelist])
        await update.message.reply_text(f"Whitelisted Users:\n{users}")
        
    elif action == "add":
        if len(args) < 2: return
        username = args[1].replace("@", "")
        if username not in whitelist:
            whitelist.append(username)
            save_whitelist(whitelist)
            await update.message.reply_text(f"@{username} added to whitelist.")
            
    elif action == "remove":
        if len(args) < 2: return
        username = args[1].replace("@", "")
        if username == ADMIN_HANDLE: return
        if username in whitelist:
            whitelist.remove(username)
            save_whitelist(whitelist)
            await update.message.reply_text(f"@{username} removed from whitelist.")

async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists all tracked users, tagging any with an active summon."""
    if update.effective_user.username != ADMIN_HANDLE: return
    users = load_json_file(USERS_FILE, {})
    if not users:
        await update.message.reply_text("No users tracked yet.")
        return
    text = "Tracked Users:\n"
    for cid, data in users.items():
        status = f"[{data.get('summon_status', 'none').upper()}]" if data.get('summon_status', 'none') != "none" else ""
        text += f"- @{data['username']} {status}\n"
    await update.message.reply_text(text, parse_mode="HTML")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a clean message to ALL tracked users."""
    if update.effective_user.username != ADMIN_HANDLE: return
    msg = " ".join(context.args)
    if not msg: return
    users = load_json_file(USERS_FILE, {})
    sent_count = 0
    for chat_id in users:
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"Announcement:\n\n{msg}", parse_mode="HTML")
            sent_count += 1
        except Exception: continue
    await update.message.reply_text(f"Broadcast sent successfully to {sent_count} users.")

async def dm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a private message to a specific user via the bot, cleaned of emojis."""
    if update.effective_user.username != ADMIN_HANDLE: return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /dm username <your message>")
        return
    target_uname = context.args[0].replace("@", "")
    msg = " ".join(context.args[1:])
    users = load_json_file(USERS_FILE, {})
    target_id = next((cid for cid, data in users.items() if data['username'].lower() == target_uname.lower()), None)
    
    if not target_id:
        await update.message.reply_text(f"User @{target_uname} not found.")
        return
    try:
        await context.bot.send_message(chat_id=target_id, text=f"Message from Admin:\n\n{msg}", parse_mode="HTML")
        await update.message.reply_text(f"Message sent to @{target_uname}!")
    except Exception:
        await update.message.reply_text("Failed to send.")

# --- CHAT & SUMMON SYSTEM ---
async def summon_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pings a user to open a 2-way comms line with /stop option."""
    if update.effective_user.username != ADMIN_HANDLE: return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /summon username")
        return
        
    target_uname = context.args[0].replace("@", "")
    users = load_json_file(USERS_FILE, {})
    target_id = next((cid for cid, data in users.items() if data.get('username', '').lower() == target_uname.lower()), None)

    if not target_id:
        await update.message.reply_text(f"User @{target_uname} not found in database.")
        return

    # Update status in DB
    users[target_id]["summon_status"] = "normal"
    save_json_file(USERS_FILE, users)

    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=f"You have been summoned by the Admin (@{ADMIN_HANDLE}).\n\nYou can now type your messages here to chat directly with them. Use /stop to end this chat.",
            parse_mode="HTML"
        )
        await update.message.reply_text(f"Summon activated for @{target_uname}. They can use /stop to leave.")
    except Exception:
        await update.message.reply_text(f"Failed to summon @{target_uname}.")

async def forcesummon_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pings a user, forces comms line, and denies them /stop."""
    if update.effective_user.username != ADMIN_HANDLE: return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /forcesummon username")
        return
        
    target_uname = context.args[0].replace("@", "")
    users = load_json_file(USERS_FILE, {})
    target_id = next((cid for cid, data in users.items() if data.get('username', '').lower() == target_uname.lower()), None)

    if not target_id:
        await update.message.reply_text(f"User @{target_uname} not found in database.")
        return

    # Update status in DB
    users[target_id]["summon_status"] = "force"
    save_json_file(USERS_FILE, users)

    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=f"The Admin (@{ADMIN_HANDLE}) has forced a chat connection with you.\n\nPlease respond below.",
            parse_mode="HTML"
        )
        await update.message.reply_text(f"Force-summon activated for @{target_uname}. They cannot use /stop.")
    except Exception:
        await update.message.reply_text(f"Failed to force-summon @{target_uname}.")

async def endchat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to manually close any summon session."""
    if update.effective_user.username != ADMIN_HANDLE: return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /endchat username")
        return
        
    target_uname = context.args[0].replace("@", "")
    users = load_json_file(USERS_FILE, {})
    target_id = next((cid for cid, data in users.items() if data.get('username', '').lower() == target_uname.lower()), None)

    if not target_id:
        await update.message.reply_text(f"User @{target_uname} not found in database.")
        return

    # Update status in DB
    users[target_id]["summon_status"] = "none"
    save_json_file(USERS_FILE, users)

    await update.message.reply_text(f"Chat session with @{target_uname} has been closed.")
    try:
        await context.bot.send_message(chat_id=target_id, text="The Admin has ended the chat session.")
    except Exception:
        pass

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User command to stop a normal summon."""
    user_id = str(update.effective_user.id)
    users = load_json_file(USERS_FILE, {})
    
    if user_id not in users:
        return

    status = users[user_id].get("summon_status", "none")

    if status == "none":
        await update.message.reply_text("There is no active chat session to stop.")
    elif status == "force":
        await update.message.reply_text("You cannot end this chat. Only the Admin can close this session.")
    elif status == "normal":
        users[user_id]["summon_status"] = "none"
        save_json_file(USERS_FILE, users)
        await update.message.reply_text("You have disconnected from the chat with the Admin.")
        
        # Alert Admin
        admin_id = get_admin_id(users)
        if admin_id:
            try:
                handle = users[user_id].get('username', 'Unknown')
                await context.bot.send_message(chat_id=admin_id, text=f"@{handle} has left the chat session.")
            except Exception:
                pass

async def forward_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Catches stray messages and forwards to admin, tagging if they are in an active chat."""
    if not update.message or not update.message.text: return
    user = update.effective_user
    
    if user.username == ADMIN_HANDLE: return 

    users = load_json_file(USERS_FILE, {})
    admin_id = get_admin_id(users)
    
    user_data = users.get(str(user.id), {})
    status = user_data.get("summon_status", "none")

    if admin_id:
        text = escape_html(update.message.text)
        handle = user.username or "Unknown"
        
        # Add a tag so you know if this is an active conversation or just a random message
        prefix = "[Active Chat]" if status in ["normal", "force"] else "[Stray Message]"
        
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"<b>{prefix} Incoming from @{handle}:</b>\n\n{text}",
                parse_mode="HTML"
            )
        except Exception:
            pass 

# --- MENU & CONVERSATION HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user.username):
        await update.message.reply_text(f"You are not whitelisted. Contact @{ADMIN_HANDLE} for access.")
        return ConversationHandler.END

    track_user(user) # Saves them to the tracking DB
    text = "Welcome to the EZstream bot!\n\nUse the menu below to navigate:"
    await update.message.reply_text(text, reply_markup=get_main_menu())
    return ConversationHandler.END

async def contact_us(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"For any support, queries, or content requests, please contact @{ADMIN_HANDLE}")
    return ConversationHandler.END

async def donate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    upi_text = "7007640876@fam"
    text = (
        "Support the Bot!\n\n"
        "Donations help keep the streaming servers fast and ad-free.\n\n"
        f"UPI ID: <code>{upi_text}</code>\n"
        f"LTC: <code>{LTC_ADDRESS}</code>\n\n"
        "You can also scan this QR code to donate. Thank you for your support!"
    )
    
    # Send the actual file from your server
    photo_path = 'qr.jpeg'
    if os.path.exists(photo_path):
        try:
            with open(photo_path, 'rb') as photo:
                await context.bot.send_photo(chat_id=update.message.chat_id, photo=photo, caption=text, parse_mode="HTML")
        except Exception as e:
            # Fallback to text if the photo cannot be sent
            print(f"Error sending photo: {e}")
            await update.message.reply_text(text, parse_mode="HTML")
    else:
        # Fallback to text if the file is not there
        await update.message.reply_text(text, parse_mode="HTML")
        
    return ConversationHandler.END

async def prompt_series_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Please type the name of the TV Series you want to watch:")
    return TYPING_SERIES_QUERY

async def prompt_movie_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Please type the name of the Movie you want to watch:")
    return TYPING_MOVIE_QUERY

async def execute_series_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text
    results = await fetch_tmdb_search(query, search_type="tv")
    
    if not results:
        await update.message.reply_text("No series found. Try searching another title.")
        return ConversationHandler.END

    keyboard = []
    for show in results:
        title = show.get('name', 'Unknown')
        date = show.get('first_air_date', '????')[:4]
        cb_data = f"tv_{show['id']}"
        keyboard.append([InlineKeyboardButton(f"{title} ({date})", callback_data=cb_data)])

    reply_markup = InlineKeyboardMarkup(keyboard)
    context.user_data['last_tv_markup'] = reply_markup
    
    await update.message.reply_text("Choose a series:", reply_markup=reply_markup)
    return ConversationHandler.END

async def execute_movie_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text
    results = await fetch_tmdb_search(query, search_type="movie")
    
    if not results:
        await update.message.reply_text("No movies found. Try searching another title.")
        return ConversationHandler.END

    keyboard = []
    for movie in results:
        title = movie.get('title', 'Unknown')
        date = movie.get('release_date', '????')[:4]
        cb_data = f"mov_{movie['id']}"
        keyboard.append([InlineKeyboardButton(f"{title} ({date})", callback_data=cb_data)])

    reply_markup = InlineKeyboardMarkup(keyboard)
    context.user_data['last_mov_markup'] = reply_markup

    await update.message.reply_text("Choose a movie:", reply_markup=reply_markup)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Action cancelled.")
    return ConversationHandler.END

# --- GLOBAL CALLBACK HANDLERS ---
async def handle_series_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "tvres_back":
        markup = context.user_data.get('last_tv_markup')
        if markup:
            await query.edit_message_text("Choose a series:", reply_markup=markup)
        else:
            await query.edit_message_text("Session expired. Please search again.")

    elif data.startswith("tv_"):
        tmdb_id = data.split("_")[1]
        series = await fetch_tmdb_details(tmdb_id, "tv")
        
        title = escape_html(series.get('name'))
        year = escape_html(series.get('first_air_date', '????')[:4])
        rating = series.get('vote_average', 'N/A')
        if isinstance(rating, float): rating = round(rating, 1)
        genres = ", ".join([g['name'] for g in series.get('genres', [])])
        overview = escape_html(series.get('overview', 'No overview available.'))
        if len(overview) > 500: overview = overview[:500] + "..."
        
        poster_path = series.get('poster_path')
        poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else ""

        text = f'<a href="{poster_url}">&#8203;</a>' if poster_url else ""
        text += f"<b>{title}</b> ({year})\n\n"
        text += f"<b>Rating:</b> {rating}/10\n"
        if genres: text += f"<b>Genres:</b> {genres}\n"
        text += f"\n<b>Overview:</b> <i>{overview}</i>"

        keyboard = [
            [InlineKeyboardButton("View Seasons", callback_data=f"tvs_{tmdb_id}")],
            [InlineKeyboardButton("Back to Results", callback_data="tvres_back")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data.startswith("tvs_"):
        tmdb_id = data.split("_")[1]
        series = await fetch_tmdb_details(tmdb_id, "tv")
        
        keyboard = []
        for season in series.get('seasons', []):
            if season['season_number'] == 0: continue
            cb_data = f"ts_{tmdb_id}_{season['season_number']}_{season['episode_count']}"
            keyboard.append([InlineKeyboardButton(f"Season {season['season_number']} ({season['episode_count']} eps)", callback_data=cb_data)])
            
        keyboard.append([InlineKeyboardButton("Back to Info", callback_data=f"tv_{tmdb_id}")])
        await query.edit_message_text(f"Select a season for <b>{escape_html(series['name'])}</b>:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data.startswith("ts_"):
        _, tmdb_id, season_num, ep_count = data.split("_")
        
        keyboard = []
        row = []
        for ep in range(1, int(ep_count) + 1):
            row.append(InlineKeyboardButton(str(ep), callback_data=f"te_{tmdb_id}_{season_num}_{ep}"))
            if len(row) == 5:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
            
        keyboard.append([InlineKeyboardButton("Back to Seasons", callback_data=f"tvs_{tmdb_id}")])
        await query.edit_message_text(f"Season {season_num} - Select Episode:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("te_"):
        _, tmdb_id, season_num, ep_num = data.split("_")
        current_s = int(season_num)
        current_e = int(ep_num)
        
        series = await fetch_tmdb_details(tmdb_id, "tv")
        seasons = {s['season_number']: s['episode_count'] for s in series.get('seasons', []) if s['season_number'] > 0}
        
        # Next / Prev Logic across seasons, text-based
        has_prev, has_next = False, False
        prev_s, prev_e = current_s, current_e
        next_s, next_e = current_s, current_e
        
        if current_e > 1:
            has_prev = True
            prev_e -= 1
        elif (current_s - 1) in seasons:
            has_prev = True
            prev_s -= 1
            prev_e = seasons[prev_s]
            
        if current_e < seasons.get(current_s, 0):
            has_next = True
            next_e += 1
        elif (current_s + 1) in seasons:
            has_next = True
            next_s += 1
            next_e = 1

        keyboard = []
        # Server Buttons
        for name, url_template in SERIES_SERVERS.items():
            link = url_template.format(tmdb_id=tmdb_id, season=season_num, episode=ep_num)
            keyboard.append([InlineKeyboardButton(name, url=link)])
            
        # Navigation Row
        nav_row = []
        if has_prev: nav_row.append(InlineKeyboardButton("<< Prev", callback_data=f"te_{tmdb_id}_{prev_s}_{prev_e}"))
        if has_next: nav_row.append(InlineKeyboardButton("Next >>", callback_data=f"te_{tmdb_id}_{next_s}_{next_e}"))
        if nav_row: keyboard.append(nav_row)
        
        # Back Button
        ep_count = seasons.get(current_s, 0)
        keyboard.append([InlineKeyboardButton("Back to Episodes", callback_data=f"ts_{tmdb_id}_{season_num}_{ep_count}")])
        
        title = series.get('name', 'Unknown')
        text = f"<b>{escape_html(title)}</b>\nS{season_num} E{ep_num} Servers:"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def handle_movie_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "movres_back":
        markup = context.user_data.get('last_mov_markup')
        if markup:
            await query.edit_message_text("Choose a movie:", reply_markup=markup)
        else:
            await query.edit_message_text("Session expired. Please search again.")

    elif data.startswith("mov_"):
        tmdb_id = data.split("_")[1]
        movie = await fetch_tmdb_details(tmdb_id, "movie")
        
        title = escape_html(movie.get('title'))
        year = escape_html(movie.get('release_date', '????')[:4])
        rating = movie.get('vote_average', 'N/A')
        if isinstance(rating, float): rating = round(rating, 1)
        genres = ", ".join([g['name'] for g in movie.get('genres', [])])
        runtime = movie.get('runtime', 0)
        overview = escape_html(movie.get('overview', 'No overview available.'))
        if len(overview) > 500: overview = overview[:500] + "..."
        
        poster_path = movie.get('poster_path')
        poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else ""

        text = f'<a href="{poster_url}">&#8203;</a>' if poster_url else ""
        text += f"<b>{title}</b> ({year})\n\n"
        text += f"<b>Rating:</b> {rating}/10\n"
        text += f"<b>Runtime:</b> {runtime} mins\n"
        if genres: text += f"<b>Genres:</b> {genres}\n"
        text += f"\n<b>Overview:</b> <i>{overview}</i>"

        keyboard = [
            [InlineKeyboardButton("Watch Movie", callback_data=f"movwatch_{tmdb_id}")],
            [InlineKeyboardButton("Back to Results", callback_data="movres_back")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data.startswith("movwatch_"):
        tmdb_id = data.split("_")[1]
        
        keyboard = []
        for name, url_template in MOVIE_SERVERS.items():
            link = url_template.format(tmdb_id=tmdb_id)
            keyboard.append([InlineKeyboardButton(name, url=link)])
            
        keyboard.append([InlineKeyboardButton("Back to Info", callback_data=f"mov_{tmdb_id}")])
        await query.edit_message_text("Select a server to start watching:", reply_markup=InlineKeyboardMarkup(keyboard))

# --- MAIN SETUP ---
def main():
    if not TELEGRAM_TOKEN or not TMDB_API_KEY:
        print("Missing API Keys! Make sure your .env file is set up correctly.")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Create filter that listens for normal text, but ignores the menu buttons
    menu_regex = f"^({MENU_SERIES}|{MENU_MOVIES}|{MENU_CONTACT}|{MENU_DONATE})$"
    search_text_filter = filters.TEXT & ~filters.COMMAND & ~filters.Regex(menu_regex)

    # Standard Commands and Menu
    entry_handlers = [
        CommandHandler("start", start),
        CommandHandler("wl", wl_command),
        CommandHandler("users", users_command),
        CommandHandler("broadcast", broadcast_command),
        CommandHandler("dm", dm_command),
        CommandHandler("summon", summon_command),
        CommandHandler("forcesummon", forcesummon_command),
        CommandHandler("endchat", endchat_command),
        CommandHandler("stop", stop_command),
        MessageHandler(filters.Regex(f"^{MENU_SERIES}$"), prompt_series_search),
        MessageHandler(filters.Regex(f"^{MENU_MOVIES}$"), prompt_movie_search),
        MessageHandler(filters.Regex(f"^{MENU_CONTACT}$"), contact_us),
        MessageHandler(filters.Regex(f"^{MENU_DONATE}$"), donate),
    ]

    main_conv = ConversationHandler(
        entry_points=entry_handlers,
        states={
            TYPING_SERIES_QUERY: [MessageHandler(search_text_filter, execute_series_search)],
            TYPING_MOVIE_QUERY: [MessageHandler(search_text_filter, execute_movie_search)]
        },
        fallbacks=entry_handlers + [CommandHandler("cancel", cancel)]
    )

    app.add_handler(main_conv)
    app.add_handler(CallbackQueryHandler(handle_series_callbacks, pattern="^(tv_|tvs_|ts_|te_|tvres_back$)"))
    app.add_handler(CallbackQueryHandler(handle_movie_callbacks, pattern="^(mov_|movwatch_|movres_back$)"))
    
    # Catch any standard text messages (for forward/chat feature)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, forward_to_admin))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
