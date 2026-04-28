import requests
import re
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ==========================================
# 1. 토큰 설정 (본인 키값으로 채우기!)
# ==========================================
TELEGRAM_TOKEN = "여기에_텔레그램_봇_토큰_입력"
GITHUB_PAT = "여기에_깃허브_PAT_토큰_입력"

GITHUB_OWNER = "jinaplus-svg"
GITHUB_REPO = "ai-stock-bot"
WORKFLOW_ID = "auto_poster.yml"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

def trigger_github(category, ref_url):
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/{WORKFLOW_ID}/dispatches"
    headers = {"Authorization": f"token {GITHUB_PAT}", "Accept": "application/vnd.github.v3+json"}
    data = {"ref": "main", "inputs": {"category": category, "topic": "외부 링크 참조 포스팅", "reference_url": ref_url}}
    
    print(f"📡 깃허브 신호 전송 시도... (카테고리: {category})")
    try:
        response = requests.post(url, headers=headers, json=data, timeout=10)
        return response.status_code == 204
    except Exception as e:
        print(f"❌ 깃허브 전송 오류: {e}")
        return False

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if "http" in text:
        url_match = re.search(r'(https?://[^\s]+)', text)
        if url_match:
            context.user_data['url'] = url_match.group(1)
            # ⭐️ 유튜브 대신 '여행/숙박' 버튼으로 변경했습니다!
            btns = [
                [InlineKeyboardButton("IT/기술", callback_data='it'), InlineKeyboardButton("맛집/음식", callback_data='food')],
                [InlineKeyboardButton("뉴스/이슈", callback_data='news'), InlineKeyboardButton("주식/경제", callback_data='stock')],
                [InlineKeyboardButton("여행/숙박", callback_data='travel')] 
            ]
            await update.message.reply_text("🔥 링크 확인! 어떤 블로그에 올릴까요?", reply_markup=InlineKeyboardMarkup(btns))

async def handle_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data
    url = context.user_data.get('url', "")
    
    await query.edit_message_text(f"🚀 [{category.upper()}] 블로그 발행 요청 중...")
    if trigger_github(category, url):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ 깃허브 공장이 가동되었습니다!")
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ 깃허브 호출 실패!")

if __name__ == '__main__':
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    app.add_handler(CallbackQueryHandler(handle_btn))
    print("\n🤖 텔레그램 리모컨 가동 중...")
    app.run_polling()
