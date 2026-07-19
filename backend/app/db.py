import os
from supabase import create_client, Client

# Service-role client: this is a trusted backend process, so it connects
# with the service_role key and bypasses Row Level Security by design
# (RLS is still enabled on every table in supabase/schema.sql — it just
# doesn't apply to this key). Never ship the service_role key to the
# frontend; the frontend only ever talks to our own FastAPI, never to
# Supabase directly.
#
# Note (tradeoff): supabase-py's client here is synchronous — each .execute()
# call blocks the running event loop briefly. Fine for a demo's request
# volume; a production version would move these calls behind
# asyncio.to_thread(...) or use supabase-py's async client (`acreate_client`)
# so a slow query can't stall other in-flight requests. See README.
supabase: Client = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_ROLE_KEY"],
)
