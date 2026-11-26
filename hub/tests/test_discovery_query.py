"""Automatic topic selection must not remove explicit recall or identifiers."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.discovery_query import discovery_query_tokens, explicit_recall_requested
from app.services.memory_retrieval import retrieve_memories


def test_specific_subject_beats_generic_download_or_schema_words() -> None:
    assert '文献' in discovery_query_tokens('我的文献下载是否正常，另外文献是全文还是摘要')
    assert '下载' not in discovery_query_tokens('我的文献下载是否正常，另外文献是全文还是摘要')
    assert '下载' in discovery_query_tokens('下载')
    terms = discovery_query_tokens('当前 biomed 外显子总数在不同基因组版本的数据库字段怎么设计')
    assert {'biomed', '外显子总数'} <= set(terms)
    assert not {'字段', '设计', '的是', '本的'}.intersection(terms)


def test_long_tasks_keep_short_identifiers_and_multiple_topics() -> None:
    terms = discovery_query_tokens(
        '按 rc.8 为基线测试升级 IGV，把镜像发布到 ACR，更新部署包和 issue。'
        + '注意升级的时候不能影响客户历史数据，检查所有相关代码和当前环境。' * 30
        + '另外修复 FlClash 连接，保留 wg0 配置。'
    )
    assert {'rc.8', 'igv', 'acr', 'flclash', 'wg0'} <= set(terms)
    assert len(terms) <= 64


@pytest.mark.parametrize('query', ['查一下记忆里之前的配置', '搜索记忆', '上次约定的流程', 'look up memories about home networking'])
def test_explicit_recall_remains_broad(query: str) -> None:
    assert explicit_recall_requested(query)


def test_historical_data_does_not_mean_explicit_memory_recall() -> None:
    assert not explicit_recall_requested('测试升级但不要影响客户历史数据')


@pytest.mark.asyncio
async def test_semantic_paraphrase_survives_but_weak_unrelated_vector_does_not(monkeypatch) -> None:
    def memory(title: str):
        return SimpleNamespace(
            id=uuid4(), title=title, content='No literal overlap.', tags=[], priority=5,
            updated_at=datetime.now(timezone.utc),
        )

    useful, unrelated = memory('A stored decision'), memory('Unrelated note')
    count = MagicMock()
    count.scalar_one.return_value = 2
    lexical = MagicMock()
    lexical.scalars.return_value.all.return_value = []
    session = AsyncMock()
    session.execute.side_effect = [count, [(useful, 0.28), (unrelated, 0.48)], lexical]
    monkeypatch.setattr('app.services.memory_retrieval.get_embedding', AsyncMock(return_value=[0.1]))
    result = await retrieve_memories(
        session, user_id='owner', query='寻找同义表达', limit=3, discovery=True,
    )
    assert [item.memory.id for item in result.items] == [useful.id]
    assert result.items[0].reasons == ('vector',)
