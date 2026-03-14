import asyncio
import logging
import json
import os
from typing import Dict, List, Set, Any
from concurrent.futures import ThreadPoolExecutor
from instagrapi import Client
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import time
from collections import deque

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Config
OWNER_ID = 7131424891
AUTHORIZED_USERS: Set[int] = {OWNER_ID}
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8251249054:AAF8hTREHAyiKORWpZqSZQtwGnTr-Iyf6n8")

# ⚡ SPEED PRESETS - NOW WITH ZERO DELAYS & 50 WORKERS
SPEED_OPTIONS = {
    'ultra': {'delay': 0, 'workers': 50, 'batch': 10, 'name': '⚡⚡⚡ ULTRA (3000 msg/min)', 'emoji': '🔴'},
    'turbo': {'delay': 0.1, 'workers': 40, 'batch': 8, 'name': '🚀 TURBO (1200 msg/min)', 'emoji': '🟠'},
    'fast': {'delay': 0.3, 'workers': 30, 'batch': 5, 'name': '⚡ FAST (600 msg/min)', 'emoji': '🟡'},
    'normal': {'delay': 0.5, 'workers': 20, 'batch': 3, 'name': '⚖️ NORMAL (240 msg/min)', 'emoji': '🟢'},
}

# Multi-Client Pool for parallel sending
class ClientPool:
    def __init__(self, pool_size: int = 10):
        self.clients: List[Client] = [Client() for _ in range(pool_size)]
        self.client_index = 0
        self.lock = asyncio.Lock()
    
    async def get_client(self) -> Client:
        async with self.lock:
            client = self.clients[self.client_index]
            self.client_index = (self.client_index + 1) % len(self.clients)
            return client

# Global state
client_pool = ClientPool(pool_size=10)
active_tasks: Dict[int, asyncio.Task] = {}
task_status: Dict[int, Dict] = {}

class ParallelSender:
    def __init__(self, workers: int = 50):
        self.workers = workers
        self.executor = ThreadPoolExecutor(max_workers=workers)
        self.semaphore = asyncio.Semaphore(workers)
    
    async def send_to_target(self, client: Client, target_id: str, message: str, target_type: str = 'user'):
        """Send message with minimal overhead"""
        async with self.semaphore:
            loop = asyncio.get_event_loop()
            try:
                if target_type == 'thread':
                    await loop.run_in_executor(
                        self.executor,
                        lambda: client.direct_send(message, thread_ids=[target_id])
                    )
                else:
                    await loop.run_in_executor(
                        self.executor,
                        lambda: client.direct_send(message, user_ids=[int(target_id)])
                    )
                return True, "✅"
            except Exception as e:
                return False, str(e)
    
    async def send_batch_parallel(self, target_id: str, message: str, count: int, 
                                 config: Dict, target_type: str = 'user'):
        """Send multiple messages in parallel batches"""
        tasks = []
        batch_size = config.get('batch', 5)
        delay = config.get('delay', 0)
        
        for i in range(count):
            client = await client_pool.get_client()
            
            task = asyncio.create_task(
                self.send_to_target(client, target_id, message, target_type)
            )
            tasks.append(task)
            
            if (i + 1) % batch_size == 0:
                if delay > 0:
                    await asyncio.sleep(delay)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        success = sum(1 for r in results if isinstance(r, tuple) and r[0])
        failed = len(results) - success
        
        return success, failed

sender = ParallelSender(workers=50)

def load_all_data():
    global AUTHORIZED_USERS
    if os.path.exists("authorized.json"):
        with open("authorized.json", 'r') as f:
            AUTHORIZED_USERS = set(json.load(f))

def save_all_data():
    with open("authorized.json", 'w') as f:
        json.dump(list(AUTHORIZED_USERS), f)

user_sessions: Dict[int, Dict[str, Any]] = {}
user_speeds: Dict[int, str] = {}

async def check_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if user_id == OWNER_ID or user_id in AUTHORIZED_USERS:
        return True
    
    keyboard = [[InlineKeyboardButton("🔐 Request Access", callback_data="request_access")]]
    await update.message.reply_text(
        "🔒 *Private Bot* - Request access from owner!", 
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return False

async def mass_sender(user_id: int, chat_id: str, message: str, speed: str, count: int, update_msg_id: int, app, target_type: str = 'user'):
    """Main sending function with parallel batches"""
    try:
        config = SPEED_OPTIONS[speed]
        task_status[user_id] = {'status': 'running', 'progress': 0}
        
        start_time = time.time()
        success, failed = await sender.send_batch_parallel(chat_id, message, count, config, target_type)
        
        total_time = time.time() - start_time
        rate = (success + failed) / max(total_time, 0.1)
        
        final_msg = (
            f"✅ **COMPLETE!** 🎉\n\n"
            f"📊 **Stats:**\n"
            f"✅ Success: {success}\n❌ Failed: {failed}\n"
            f"⏱️ Time: {total_time:.2f}s\n"
            f"📈 Rate: **{rate:.0f} msg/sec** ({rate*60:.0f} msg/min)\n"
            f"⚡ Speed: **{config['name']}**"
        )
        
        await app.bot.send_message(OWNER_ID, final_msg, parse_mode='Markdown')
        
    except asyncio.CancelledError:
        await app.bot.send_message(OWNER_ID, "🛑 *Task cancelled!*", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in mass_sender: {e}")
        await app.bot.send_message(OWNER_ID, f"❌ Error: {str(e)}", parse_mode='Markdown')
    finally:
        active_tasks.pop(user_id, None)
        task_status.pop(user_id, None)
        save_all_data()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_access(update, context):
        return
    
    speed = user_speeds.get(str(user_id), 'normal')
    speed_name = SPEED_OPTIONS[speed]['name']
    
    keyboard = [
        [InlineKeyboardButton("⚡ Set Speed", callback_data="set_speed")],
        [InlineKeyboardButton("🍪 Session ID Login", callback_data="login_sessionid")],
        [InlineKeyboardButton("🔐 Session JSON Login", callback_data="login_session")],
        [InlineKeyboardButton("📱 Send Messages", callback_data="select_target")]
    ]
    
    if user_id == OWNER_ID:
        keyboard.extend([
            [InlineKeyboardButton("👥 Manage Users", callback_data="manage_users")],
            [InlineKeyboardButton("📊 Active Tasks", callback_data="show_tasks")]
        ])
    
    await update.message.reply_text(
        f"🤖 *Instagram Speed Bot v3.0* ⚡\n\n"
        f"🚀 Speed: **{speed_name}**\n"
        f"👥 Workers: **50 parallel**\n"
        f"📤 Batches: **Zero delay**\n\n"
        f"Choose action:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if not (user_id == OWNER_ID or user_id in AUTHORIZED_USERS):
        await query.edit_message_text("❌ Access denied!")
        return
    
    if query.data == "set_speed":
        keyboard = [[InlineKeyboardButton(config['name'], callback_data=f"speed_{k}")] 
                   for k, config in SPEED_OPTIONS.items()]
        keyboard.append([InlineKeyboardButton("❌ Back", callback_data="back_main")])
        
        await query.edit_message_text(
            "⚡ *Select Speed* (Risk ↑ Speed ↑):\n\n"
            "**ULTRA** = 50 workers, 0 delay\n"
            "**TURBO** = 40 workers, 0.1s delay\n"
            "**FAST** = 30 workers, 0.3s delay\n"
            "**NORMAL** = 20 workers, 0.5s delay",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    if query.data.startswith("speed_"):
        speed = query.data.split("_")[1]
        user_speeds[str(user_id)] = speed
        save_all_data()
        config = SPEED_OPTIONS[speed]
        await query.edit_message_text(
            f"✅ **{config['name']}**\n"
            f"🔄 Workers: **{config['workers']}**\n"
            f"📦 Batch: **{config['batch']}**\n\n"
            f"⚡ Ready! Use /start",
            parse_mode='Markdown'
        )
        return
    
    if query.data == "login_sessionid":
        context.user_data['awaiting'] = 'sessionid_cookie'
        await query.edit_message_text(
            "🍪 *Instagram Session ID*\n\n"
            "Copy from Browser:\n"
            "1. instagram.com → F12\n"
            "2. Application → Cookies\n"
            "3. Find `sessionid` → Copy\n"
            "4. Paste here ↓",
            parse_mode='Markdown'
        )
        return
    
    if query.data == "select_target":
        context.user_data['awaiting'] = 'target_chat'
        await query.edit_message_text(
            "📱 *Enter Target:*\n\n"
            "• Username: `username`\n"
            "• @mention: `@username`\n"
            "• User ID: `123456789`\n"
            "• Link: `instagram.com/username`",
            parse_mode='Markdown'
        )
        return
    
    if query.data == "manage_users":
        if user_id != OWNER_ID:
            return
        msg = "👥 *Authorized Users:*\n"
        for uid in AUTHORIZED_USERS:
            msg += f"• `{uid}`\n"
        keyboard = [
            [InlineKeyboardButton("➕ Add", callback_data="add_user")],
            [InlineKeyboardButton("➖ Remove", callback_data="remove_user")],
            [InlineKeyboardButton("❌ Back", callback_data="back_main")]
        ]
        await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    if query.data == "add_user":
        context.user_data['awaiting'] = 'add_user_id'
        await query.edit_message_text("Enter user ID to add:")
        return
    
    if query.data == "remove_user":
        context.user_data['awaiting'] = 'remove_user_id'
        await query.edit_message_text("Enter user ID to remove:")
        return
    
    if query.data == "show_tasks":
        if user_id != OWNER_ID:
            return
        if not active_tasks:
            await query.edit_message_text("✅ No active tasks")
            return
        msg = "📊 **ACTIVE TASKS:**\n\n"
        for uid in active_tasks.keys():
            msg += f"👤 User {uid} - Sending...\n"
        await query.edit_message_text(msg, parse_mode='Markdown')
        return
    
    if query.data == "confirm_send":
        data = user_sessions.get(user_id, {})
        speed = user_speeds.get(str(user_id), 'normal')
        config = SPEED_OPTIONS[speed]
        
        keyboard = [
            [InlineKeyboardButton("🚀 START", callback_data="send_now")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
        ]
        
        await query.edit_message_text(
            f"🚀 *Ready to Send*\n\n"
            f"📱 Target: *{data.get('target_display', '?')}*\n"
            f"📝 Message: `{str(data.get('message',''))[:50]}`\n"
            f"🔢 Count: *{data.get('count', 10)}*\n"
            f"⚡ **{config['name']}**\n"
            f"🔄 **50 Parallel Workers**\n\n"
            f"Confirm?",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    if query.data == "send_now":
        data = user_sessions.get(user_id, {})
        speed = user_speeds.get(str(user_id), 'normal')
        
        msg = await context.bot.send_message(
            OWNER_ID,
            f"🚀 **STARTING PARALLEL SEND**\n⚡ {SPEED_OPTIONS[speed]['name']}\n🔄 50 Workers Active",
            parse_mode='Markdown'
        )
        
        task = asyncio.create_task(
            mass_sender(user_id, data['target_chat'], data['message'], speed, 
                       data.get('count', 10), msg.message_id, context.application, 
                       data.get('target_type', 'user'))
        )
        active_tasks[user_id] = task
        return
    
    if query.data == "back_main":
        await start(update, context)
        return

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not (user_id == OWNER_ID or user_id in AUTHORIZED_USERS):
        return
    
    text = update.message.text
    awaiting = context.user_data.get('awaiting')
    
    if not awaiting:
        return
    
    if awaiting == 'sessionid_cookie':
        sessionid = text.strip()
        try:
            loop = asyncio.get_event_loop()
            client = await client_pool.get_client()
            await loop.run_in_executor(None, lambda: client.login_by_sessionid(sessionid))
            user_sessions[user_id] = {'logged_in': True}
            context.user_data['awaiting'] = None
            await update.message.reply_text("✅ *Logged in!*\n\n/start to send messages", parse_mode='Markdown')
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")
        return
    
    if awaiting == 'target_chat':
        raw = text.strip().rstrip('/')
        username = raw.lstrip('@').split('/')[-1] if 'instagram.com/' in raw else raw.lstrip('@')
        
        if username.isdigit():
            ig_user_id = username
        else:
            try:
                loop = asyncio.get_event_loop()
                client = await client_pool.get_client()
                ig_user_id = str(await loop.run_in_executor(None, lambda: client.user_id_from_username(username)))
            except:
                await update.message.reply_text(f"❌ Username not found: {username}")
                return
        
        user_sessions[user_id] = {'target_chat': ig_user_id, 'target_type': 'user', 'target_display': f"@{username}"}
        context.user_data['awaiting'] = 'message'
        await update.message.reply_text(f"✅ Target: **{username}**\n\n📝 Type your message:", parse_mode='Markdown')
        return
    
    if awaiting == 'message':
        user_sessions[user_id]['message'] = text
        context.user_data['awaiting'] = 'count'
        await update.message.reply_text("🔢 *How many messages?* (number, e.g., 50)", parse_mode='Markdown')
        return
    
    if awaiting == 'count':
        if not text.strip().isdigit():
            await update.message.reply_text("❌ Enter a number only!")
            return
        user_sessions[user_id]['count'] = int(text.strip())
        context.user_data['awaiting'] = None
        
        keyboard = [
            [InlineKeyboardButton("🚀 START", callback_data="send_now")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
        ]
        await update.message.reply_text(
            "🚀 *Ready to send?*",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    if awaiting == 'add_user_id':
        try:
            new_uid = int(text)
            AUTHORIZED_USERS.add(new_uid)
            save_all_data()
            context.user_data['awaiting'] = None
            await update.message.reply_text(f"✅ User `{new_uid}` added!", parse_mode='Markdown')
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID")
        return
    
    if awaiting == 'remove_user_id':
        try:
