FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Install the SDK as an editable local package so `import ollie_sdk` works
# exactly the same way it would if this were published to a package index.
COPY sdk/ /app/sdk/
RUN pip install --no-cache-dir -e /app/sdk

COPY backend/app ./app

EXPOSE 4000

# Schema is applied to Supabase directly (SQL editor or `supabase db push`),
# not on container start — see backend/supabase/schema.sql and README setup.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "4000"]
