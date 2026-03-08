import os
import logging
import json
import asyncio
import pytz
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
import gemini_service
import social_publisher

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# State for ConversationHandler
WAITING_APPROVAL = 1

# Pending content path
PENDING_CONTENT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pending_content.json")

def is_sleep_time() -> bool:
    """Returns True if current time is between 12:00 AM and 9:00 AM IST."""
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    return 0 <= now.hour < 9

def load_pending_content() -> dict:
    """Loads pending content from file if it exists."""
    if os.path.exists(PENDING_CONTENT_FILE):
        try:
            with open(PENDING_CONTENT_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading pending content: {e}")
    return {}

def save_pending_content(data: dict):
    """Saves pending content to file."""
    try:
        with open(PENDING_CONTENT_FILE, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        logger.error(f"Error saving pending content: {e}")

def clear_pending_content():
    """Removes the pending content file."""
    if os.path.exists(PENDING_CONTENT_FILE):
        os.remove(PENDING_CONTENT_FILE)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the automation process by generating a new post idea."""
    if context.user_data.get('is_generating', False):
        await update.message.reply_text("A generation cycle is already in progress. Please wait.")
        return ConversationHandler.END
        
    context.user_data['is_generating'] = True
    result = ConversationHandler.END
    try:
        await update.message.reply_text("Starting the content automation engine... 🚀\nChecking for pending content...")
        result = await process_content_generation(update.message.chat_id, context, update.message.reply_text, update.message.reply_photo)
    finally:
        context.user_data['is_generating'] = False
    return result

async def auto_generate(context: ContextTypes.DEFAULT_TYPE):
    """Scheduled task for hourly automation."""
    chat_id = context.job.data['chat_id']
    
    if is_sleep_time():
        logger.info("Sleep time active (12 AM - 9 AM). Skipping this hourly cycle.")
        return
        
    logger.info(f"Triggering scheduled generation for chat {chat_id}...")
    
    async def reply_text(text, **kwargs):
        return await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
        
    async def reply_photo(photo, **kwargs):
        return await context.bot.send_photo(chat_id=chat_id, photo=photo, **kwargs)
        
    # The scheduled job operates outside the normal ConversationHandler flow.
    # We set a flag in chat_data so handle_approval can pick up spontaneous replies.
    
    if context.chat_data is None:
        # Depending on PTB versions, chat_data might be None if not initialized
        # We can safely use application.chat_data to initialize it 
        # or simply skip setting it if that's safer depending on context object state.
        pass
    else:
        context.chat_data['awaiting_auto_approval'] = True
        
    await process_content_generation(chat_id, context, reply_text, reply_photo, is_auto=True)

async def process_content_generation(chat_id: int, context: ContextTypes.DEFAULT_TYPE, reply_text, reply_photo, is_auto=False) -> int:
    """Core logic to generate topic, content, and image, then send to user."""
    # Check for pending content first
    pending = load_pending_content()
    if pending:
        await reply_text("Found pending content from a previous cycle. Retrying approval...", parse_mode='Markdown')
        caption = pending.get('caption')
        image_prompt = pending.get('image_prompt')
        image_path = pending.get('image_path')
        topic = pending.get('topic', 'Saved Topic')
    else:
        # 1. Generate Topic
        topic = gemini_service.generate_topic_prompt()
        await reply_text(f"Topic gathered: *{topic}*\nNow drafting the content...", parse_mode='Markdown')
        
        # 2. Generate Content
        content_data = gemini_service.generate_content(topic)
        caption = content_data['caption']
        image_prompt = content_data['image_prompt']
        
        await reply_text(f"Content drafted.\nImage Prompt: *{image_prompt}*\n\nGenerating actual imagery...", parse_mode='Markdown')
        
        # 3. Generate Image
        logger.info(f'Image prompt: {image_prompt}')
        image_path = gemini_service.generate_image(image_prompt)
        
        if not image_path:
            await reply_text("Image generation failed, retrying next cycle...")
            return ConversationHandler.END
            
    if context.user_data is not None:
        context.user_data['current_caption'] = caption
        context.user_data['current_image_prompt'] = image_prompt
        context.user_data['current_topic'] = topic
        context.user_data['current_image_path'] = image_path
        context.user_data['is_auto'] = is_auto
    
    # 4. Send to User for verification
    text_to_send = f"Here is your drafted post:\n\n{caption}\n\nDo you approve? Reply *yes* to publish or *no* to regenerate."
    
    if image_path and os.path.exists(image_path):
        with open(image_path, 'rb') as photo:
            await reply_photo(photo=photo, caption=text_to_send, parse_mode='Markdown')
    else:
        await reply_text("Image generation failed, retrying next cycle...")
        return ConversationHandler.END
        
    # Set the 10-minute timeout
    timeout_job = context.job_queue.run_once(approval_timeout, 600, data={'chat_id': chat_id, 'is_auto': is_auto})
    context.user_data['timeout_job'] = timeout_job
        
    return WAITING_APPROVAL

async def approval_timeout(context: ContextTypes.DEFAULT_TYPE):
    """Handles the 10-minute timeout if the user doesn't respond."""
    job = context.job
    chat_id = job.data['chat_id']
    is_auto = job.data.get('is_auto', False)
    
    # If the job is still active, it hasn't been cancelled by user input
    user_data = context.application.user_data.get(chat_id, {})
    
    if is_auto and not context.chat_data.get('awaiting_auto_approval'):
        return # Already handled manually inside ConversationHandler or auto flow
        
    if not is_auto and 'timeout_job' not in user_data:
         return # Already handled via conversation handler

    # It timed out. Save to pending and notify.
    logger.info(f"Chat {chat_id} timed out waiting for approval. Saving to pending.")
    
    pending_data = {
        'caption': user_data.get('current_caption'),
        'image_prompt': user_data.get('current_image_prompt'),
        'image_path': user_data.get('current_image_path'),
        'topic': user_data.get('current_topic')
    }
    save_pending_content(pending_data)
    
    # Clean up state
    if is_auto:
        context.chat_data['awaiting_auto_approval'] = False
    if 'timeout_job' in user_data:
        del user_data['timeout_job']
        
    await context.bot.send_message(
        chat_id=chat_id, 
        text="⏰ Approval timed out (10 minutes). The content has been saved for the next cycle.\nRespond with /start when you are ready again."
    )

async def cancel_timeout_job(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Cancels the pending timeout job if the user responds."""
    user_data = context.application.user_data.get(chat_id, {})
    if 'timeout_job' in user_data:
        job = user_data['timeout_job']
        job.schedule_removal()
        del user_data['timeout_job']
        
    if context.chat_data.get('awaiting_auto_approval'):
         context.chat_data['awaiting_auto_approval'] = False

async def handle_approval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the yes/no responses."""
    # Check if this is part of the auto-flow that was caught outside ConversationHandler 
    # (fallback handler) or part of the ConversationHandler.
    chat_id = update.message.chat_id
    
    is_auto_reply = context.chat_data.get('awaiting_auto_approval', False)
    
    user_response = update.message.text.lower().strip()
    
    if user_response in ['yes', 'no']:
         await cancel_timeout_job(context, chat_id)
         
         if user_response == 'yes':
             await update.message.reply_text("Publishing to Instagram and Pinterest now... ⏳")
             caption = context.user_data.get('current_caption', '')
             image_path = context.user_data.get('current_image_path', '')
             
             # Attempt to publish
             insta_success = social_publisher.publish_to_instagram(caption, image_path)
             pin_success = social_publisher.publish_to_pinterest(caption, image_path)
             
             if insta_success or pin_success:
                 # Clear pending since we successfully handled it
                 clear_pending_content()
             
             results = f"Instagram Publish: {'✅' if insta_success else '❌'}\nPinterest Publish: {'✅' if pin_success else '❌'}"
             await update.message.reply_text(f"Publishing complete:\n{results}\n\nNext automated cycle in 1 hour.")
             
             return ConversationHandler.END
             
         elif user_response == 'no':
             await update.message.reply_text("Okay, discarding that one. Regenerating a completely new idea... ♻️")
             clear_pending_content() # Discard saved pending if 'no' is selected
             return await process_content_generation(chat_id, context, update.message.reply_text, update.message.reply_photo)
             
    else:
        await update.message.reply_text("Please reply with simply *yes* or *no*.", parse_mode='Markdown')
        if is_auto_reply:
             context.chat_data['awaiting_auto_approval'] = True
        return WAITING_APPROVAL

    # Fallback to ensure all paths return an int
    return WAITING_APPROVAL

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    await cancel_timeout_job(context, update.message.chat_id)
    await update.message.reply_text("Automation cancelled. Type /start to begin again or wait for the hourly schedule.")
    return ConversationHandler.END

async def auto_approval_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Catches yes/no replies if they happen outside the active ConversationHandler flow."""
    if context.chat_data.get('awaiting_auto_approval'):
        return await handle_approval(update, context)
    return ConversationHandler.END

async def setniche_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /setniche command to change the content generation niche."""
    if not context.args:
        await update.message.reply_text("Please provide a niche. Example: /setniche fitness")
        return
        
    niche_word = " ".join(context.args)
    await update.message.reply_text(f"Expanding and setting niche to '{niche_word}'... ⏳")
    
    # Run in executor to not block the async event loop with sync requests
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, gemini_service.set_niche, niche_word)
    
    await update.message.reply_text(f"✅ Niche successfully updated!\n\n*Current Niche Focus:*\n{gemini_service.CURRENT_NICHE}", parse_mode='Markdown')

async def currentniche_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Replies with the currently active niche."""
    await update.message.reply_text(f"*Current Niche Focus:*\n{gemini_service.CURRENT_NICHE}", parse_mode='Markdown')

def main() -> None:
    """Run the bot."""
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id_str = os.environ.get("TELEGRAM_CHAT_ID", "5593682924") # Fallback to the one mentioned manually
    
    if not token or token == "your_telegram_bot_token_here":
         logger.error("Please configure the TELEGRAM_BOT_TOKEN in .env file.")
         print("Missing TELEGRAM_BOT_TOKEN inside .env")
         return
         
    try:
        chat_id = int(chat_id_str)
    except ValueError:
        logger.error("TELEGRAM_CHAT_ID must be an integer.")
        return
         
    # Create application
    application = Application.builder().token(token).build()
    
    # Setup conversation handler for manual /start triggers
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_APPROVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_approval)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    
    import re
    application.add_handler(MessageHandler(filters.Regex(re.compile(r'^(yes|no)$', re.IGNORECASE)), auto_approval_fallback))
    
    # Setup Job Queue for the hourly automation
    # interval=3600 (1 hour). Run first one 10 seconds after boot.
    application.job_queue.run_repeating(auto_generate, interval=3600, first=10, data={'chat_id': chat_id})
    
    # Add standalone commands for niche management
    application.add_handler(CommandHandler("setniche", setniche_command))
    application.add_handler(CommandHandler("currentniche", currentniche_command))
    
    # Start the Bot
    logger.info("Content Automation Bot is starting and polling for messages. Hourly scheduler activated.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
