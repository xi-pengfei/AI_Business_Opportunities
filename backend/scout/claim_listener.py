"""Outbound Stream connection: no public webhook or chat-history access required."""

import asyncio
import logging

import dingtalk_stream

from scout.claims import accept_claim
from scout.config import settings
from scout.dingtalk import configured


class ClaimHandler(dingtalk_stream.CallbackHandler):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.logger.disabled = True

    async def process(self, message):
        try:
            await asyncio.to_thread(accept_claim, message.data, self.config)
            return dingtalk_stream.AckMessage.STATUS_OK, "OK"
        except Exception as exc:
            logging.warning("claim callback failed (%s)", type(exc).__name__)
            return 500, "retry"


async def main():
    config = settings()
    while not config.dingtalk_enabled or not configured(config):
        await asyncio.sleep(5)
    logger = logging.getLogger("scout.dingtalk.stream")
    logger.disabled = True  # SDK connection diagnostics may include credential-bearing URLs.
    client = dingtalk_stream.DingTalkStreamClient(
        dingtalk_stream.Credential(config.dingtalk_app_key, config.dingtalk_app_secret),
        logger=logger,
    )
    client.register_callback_handler("/v1.0/im/bot/messages/get", ClaimHandler(config))
    await client.start()


if __name__ == "__main__":
    asyncio.run(main())
