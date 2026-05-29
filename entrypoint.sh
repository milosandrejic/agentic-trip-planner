#!/usr/bin/env bash
set -e

echo "Waiting for postgres at ${POSTGRES_HOST:-db}:${POSTGRES_PORT:-5432}..."
until python -c "
import asyncio, asyncpg, os, sys
async def ping():
    try:
        c = await asyncpg.connect(
            user=os.environ['POSTGRES_USER'],
            password=os.environ['POSTGRES_PASSWORD'],
            database=os.environ['POSTGRES_DB'],
            host=os.environ.get('POSTGRES_HOST', 'db'),
            port=int(os.environ.get('POSTGRES_PORT', '5432')),
        )
        await c.close()
    except Exception as e:
        sys.exit(1)
asyncio.run(ping())
" 2>/dev/null; do
    sleep 0.5
done
echo "Postgres is up."

echo "Running Alembic migrations..."
alembic upgrade head

exec "$@"
