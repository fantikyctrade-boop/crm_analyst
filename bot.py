"""Telegram bot entry point."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import Config
from handlers import router
from handlers.middleware import WhitelistMiddleware
from services import LeadPipeline


async def main() -> None:
    config = Config.from_env()
    pipeline = LeadPipeline()
    pipeline.cleanup_all()

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher(storage=MemoryStorage())
    router.message.outer_middleware(
        WhitelistMiddleware(config.allowed_user_ids)
    )
    router.callback_query.outer_middleware(
        WhitelistMiddleware(config.allowed_user_ids)
    )
    dispatcher.include_router(router)

    try:
        await dispatcher.start_polling(bot, pipeline=pipeline)
    finally:
        pipeline.cleanup_all()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(main())
