import asyncio

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes.chat import router as chat_router
from .routes.ingest import router as ingest_router, process_ingestion_event
from .queue.rabbitmq import start_ingestion_consumer

app = FastAPI(title="Ollive Inference Logging API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix="/api")
app.include_router(ingest_router, prefix="/api/ingest")


@app.get("/health")
async def health():
    return {"status": "ok"}


async def _connect_consumer_with_retry(retry_seconds: float = 3.0):
    """
    Starts the async ingestion consumer. If RabbitMQ isn't reachable yet
    (e.g. container still starting under Docker Compose), retry with
    backoff instead of crashing the whole API.
    """
    try:
        await start_ingestion_consumer(process_ingestion_event)
    except Exception as err:
        print(f"[queue] consumer connect failed ({err}), retrying in {retry_seconds}s")
        await asyncio.sleep(retry_seconds)
        asyncio.create_task(_connect_consumer_with_retry(min(retry_seconds * 1.5, 15.0)))


@app.on_event("startup")
async def on_startup():
    asyncio.create_task(_connect_consumer_with_retry())
