"""Seed default example memories for a new user.

Usage:
    # From within the hub container or with DB access:
    python -m scripts.seed_memories --user-id <uuid>

    # Or via the Hub API (admin only):
    POST /api/v1/admin/seed?user_id=<uuid>

The seed memories are loaded from hub/seed_memories.json.
If the user already has memories, this script does nothing (safe to re-run).
"""

import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import async_session_factory  # noqa: E402
from app.models.memory import Memory  # noqa: E402
from app.services.token_counter import count_tokens  # noqa: E402

SEED_FILE = Path(__file__).parent.parent / "seed_memories.json"


async def seed_memories_for_user(user_id: str, force: bool = False) -> int:
    """Load seed memories for a user. Returns number of memories created.

    If force=False (default), skips if user already has any memories.
    """
    async with async_session_factory() as session:
        # Check if user already has memories
        if not force:
            count_result = await session.execute(
                select(func.count()).select_from(
                    select(Memory).where(Memory.user_id == user_id).subquery()
                )
            )
            existing_count = count_result.scalar_one()
            if existing_count > 0:
                print(f"User {user_id} already has {existing_count} memories. Skipping seed.")
                return 0

        # Load seed data
        if not SEED_FILE.exists():
            print(f"Seed file not found: {SEED_FILE}")
            return 0

        seed_data = json.loads(SEED_FILE.read_text())
        created = 0

        for item in seed_data:
            memory = Memory(
                user_id=user_id,
                title=item["title"],
                content=item["content"],
                type=item["type"],
                layer=item["layer"],
                priority=item["priority"],
                tags=item["tags"],
                status=item["status"],
                scope_global=item["scope"]["global"],
                scope_projects=item["scope"].get("projects", []),
                scope_exclude=item["scope"].get("exclude_projects", []),
                source=item["source"],
                visibility=item.get("visibility", "private"),
                token_count=count_tokens(item["content"]),
            )
            session.add(memory)
            created += 1

        await session.commit()
        print(f"Created {created} seed memories for user {user_id}")
        return created


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Seed example memories for a user")
    parser.add_argument("--user-id", required=True, help="UUID of the user")
    parser.add_argument("--force", action="store_true", help="Seed even if user has memories")
    args = parser.parse_args()

    await seed_memories_for_user(args.user_id, force=args.force)


if __name__ == "__main__":
    asyncio.run(main())
