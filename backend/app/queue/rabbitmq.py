"""
Event-based ingestion queue, using RabbitMQ via aio-pika.

Single shared connection/channel, lazily created and reused. The HTTP
ingestion endpoint's only job is to validate the payload shape and publish
it here — actual parsing, PII redaction, and persistence happen in the
consumer (see process_ingestion_event in routes/ingest.py). This keeps the
ingestion endpoint's response time independent of DB load, and means a
burst of chatbot traffic doesn't back up chat responses.
"""

import asyncio
import json
import os
from typing import Callable, Awaitable

import aio_pika
from aio_pika.abc import AbstractIncomingMessage

QUEUE_NAME = "inference.logs"
RABBITMQ_URL = os.environ.get("RABBITMQ_URL", "amqp://localhost")

_connection: aio_pika.RobustConnection | None = None
_channel: aio_pika.Channel | None = None
_lock = asyncio.Lock()


async def _get_channel() -> aio_pika.Channel:
    global _connection, _channel
    async with _lock:
        if _channel is None:
            _connection = await aio_pika.connect_robust(RABBITMQ_URL)
            _channel = await _connection.channel()
            await _channel.declare_queue(QUEUE_NAME, durable=True)
    return _channel


async def publish_log_event(event: dict) -> None:
    channel = await _get_channel()
    await channel.default_exchange.publish(
        aio_pika.Message(
            body=json.dumps(event).encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        ),
        routing_key=QUEUE_NAME,
    )


async def start_ingestion_consumer(handler: Callable[[dict], Awaitable[None]]) -> None:
    """
    Starts the consumer that does the actual ingestion work: parse metadata,
    redact PII, write to Postgres (via Supabase). prefetch=1 keeps
    ordering-ish behavior simple for a demo (see README "scaling
    considerations" for how this would change under load). On a handler
    exception, `message.process()` rejects the message without requeueing —
    avoids a poison-message infinite loop; a production version would route
    to a dead-letter queue instead (see README).
    """
    channel = await _get_channel()
    await channel.set_qos(prefetch_count=1)
    queue = await channel.declare_queue(QUEUE_NAME, durable=True)

    async def on_message(message: AbstractIncomingMessage) -> None:
        async with message.process(requeue=False):
            event = json.loads(message.body.decode())
            await handler(event)

    await queue.consume(on_message)
    print(f'[queue] consuming from "{QUEUE_NAME}"')
