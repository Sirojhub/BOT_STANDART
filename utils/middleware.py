import time
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, limit: float = 0.7, penalty: float = 10.0):
        self.rate_limit = limit
        self.penalty_duration = penalty
        self.users = {} # {user_id: {'last_time': float, 'count': int, 'blocked_until': float}}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        user_id = user.id
        current_time = time.time()
        
        # Initialize user data
        if user_id not in self.users:
            self.users[user_id] = {'last_time': 0.0, 'count': 0, 'blocked_until': 0.0}
            
        user_stats = self.users[user_id]
        
        # Check if blocked
        if current_time < user_stats['blocked_until']:
            # User is blocked, ignore update (or answer callback to stop spinner)
            if isinstance(event, CallbackQuery):
                await event.answer("⚠️ Juda tez! 10 soniya kuting.", show_alert=True)
            return
            
        # Check rate limit
        elapsed = current_time - user_stats['last_time']
        
        if elapsed < self.rate_limit:
            user_stats['count'] += 1
        else:
            user_stats['count'] = 1 # Reset count if enough time passed
            
        user_stats['last_time'] = current_time
        
        # Trigger Penalty
        if user_stats['count'] > 3:
            user_stats['blocked_until'] = current_time + self.penalty_duration
            user_stats['count'] = 0 # Reset count
            
            # Notify user
            try:
                if isinstance(event, Message):
                    await event.answer(f"⚠️ <b>Juda tez harakat qilyapsiz!</b>\n\nBot serveriga yuklama tushmasligi uchun siz <b>{int(self.penalty_duration)} soniyaga</b> bloklandingiz.", parse_mode="HTML")
                elif isinstance(event, CallbackQuery):
                    await event.answer(f"⚠️ Juda tez! {int(self.penalty_duration)} soniya kuting.", show_alert=True)
            except:
                pass
            return

        return await handler(event, data)
