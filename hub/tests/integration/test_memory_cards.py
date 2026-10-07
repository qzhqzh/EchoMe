"""Card judgments must stay tenant-scoped and quarantine incorrect memories."""

import asyncio

import pytest
from sqlalchemy import func, select

from app.models.memory import Memory, MemoryFeedback
from app.schemas.feedback import CARD_REVIEW_CONTEXT


@pytest.mark.asyncio
async def test_card_queue_feedback_and_wrong_quarantine(api, database, test_user_id):
    async with database() as session:
        useful = Memory(
            user_id=test_user_id,
            title="Useful card",
            content="A useful and current memory.",
            type="method",
            layer="L1",
            priority=9,
            status="active",
            tags=["card:skill", "card:knowledge"],
        )
        incorrect = Memory(
            user_id=test_user_id,
            title="Incorrect card",
            content="An incorrect network address.",
            type="context",
            layer="L1",
            status="ai_review",
            tags=["card:knowledge"],
        )
        foreign = Memory(
            user_id="another-user",
            title="Foreign card",
            content="Another user's memory.",
            type="context",
            layer="L1",
        )
        session.add_all([useful, incorrect, foreign])
        await session.commit()
        useful_id, incorrect_id, foreign_id = useful.id, incorrect.id, foreign.id

    queue = await api.get("memories", params={"card_review": "unreviewed"})
    assert queue.status_code == 200, queue.text
    assert queue.json()["total"] == 2
    assert [item["id"] for item in queue.json()["items"]] == [str(useful_id), str(incorrect_id)]
    assert queue.json()["items"][0]["content"] == "A useful and current memory."
    skill_queue = await api.get(
        "memories", params={"tags": "card:skill", "card_review": "unreviewed"}
    )
    assert [item["id"] for item in skill_queue.json()["items"]] == [str(useful_id)]
    knowledge_queue = await api.get(
        "memories", params={"tags": "card:knowledge", "card_review": "unreviewed"}
    )
    assert knowledge_queue.json()["total"] == 2

    ordinary_feedback = await api.post(
        "memory-feedback", json={"memory_id": str(useful_id), "rating": "important"}
    )
    assert ordinary_feedback.status_code == 201, ordinary_feedback.text
    assert (await api.get("memories", params={"card_review": "unreviewed"})).json()["total"] == 2

    useful_review = await api.post(
        "memory-feedback/card-review",
        json={"memory_id": str(useful_id), "rating": "helpful"},
    )
    assert useful_review.status_code == 201, useful_review.text
    assert useful_review.json()["memory_status"] == "active"
    duplicate = await api.post(
        "memory-feedback/card-review",
        json={"memory_id": str(useful_id), "rating": "wrong"},
    )
    assert duplicate.status_code == 409, duplicate.text
    reviewed = await api.get("memories", params={"card_review": "reviewed"})
    assert [item["id"] for item in reviewed.json()["items"]] == [str(useful_id)]
    knowledge_queue = await api.get(
        "memories", params={"tags": "card:knowledge", "card_review": "unreviewed"}
    )
    assert [item["id"] for item in knowledge_queue.json()["items"]] == [str(incorrect_id)]

    wrong_review = await api.post(
        "memory-feedback/card-review",
        json={"memory_id": str(incorrect_id), "rating": "wrong", "note": "Old address"},
    )
    assert wrong_review.status_code == 201, wrong_review.text
    assert wrong_review.json()["memory_status"] == "pending"
    assert (await api.get("memories", params={"card_review": "unreviewed"})).json()["total"] == 0
    default_list = await api.get("memories")
    assert [item["id"] for item in default_list.json()["items"]] == [str(useful_id)]
    pending = await api.get("memories", params={"status": "pending", "card_review": "reviewed"})
    assert [item["id"] for item in pending.json()["items"]] == [str(incorrect_id)]

    foreign_review = await api.post(
        "memory-feedback/card-review",
        json={"memory_id": str(foreign_id), "rating": "wrong"},
    )
    assert foreign_review.status_code == 404
    async with database() as session:
        assert (await session.get(Memory, incorrect_id)).status == "pending"
        assert (await session.get(Memory, foreign_id)).status == "active"
        card_feedback = (
            (
                await session.execute(
                    select(MemoryFeedback)
                    .where(MemoryFeedback.task_context == CARD_REVIEW_CONTEXT)
                    .order_by(MemoryFeedback.rating)
                )
            )
            .scalars()
            .all()
        )
        assert len(card_feedback) == 2
        assert all(
            item.user_id == test_user_id and item.used_by == "user" for item in card_feedback
        )
        assert any(item.rating == "wrong" and item.note == "Old address" for item in card_feedback)


@pytest.mark.asyncio
async def test_simultaneous_card_reviews_create_one_judgment(api, database, test_user_id):
    async with database() as session:
        memory = Memory(
            user_id=test_user_id,
            title="Double tap",
            content="Only one card judgment should be saved.",
            type="context",
            layer="L2",
        )
        session.add(memory)
        await session.commit()
        memory_id = memory.id

    responses = await asyncio.gather(
        api.post(
            "memory-feedback/card-review",
            json={"memory_id": str(memory_id), "rating": "helpful"},
        ),
        api.post(
            "memory-feedback/card-review",
            json={"memory_id": str(memory_id), "rating": "wrong"},
        ),
    )
    assert sorted(response.status_code for response in responses) == [201, 409]
    async with database() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(MemoryFeedback)
            .where(
                MemoryFeedback.memory_id == memory_id,
                MemoryFeedback.task_context == CARD_REVIEW_CONTEXT,
            )
        )
        assert count == 1
