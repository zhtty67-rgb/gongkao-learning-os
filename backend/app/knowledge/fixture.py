"""In-memory fixture implementation of KnowledgeProvider for offline and testing use."""
from datetime import datetime, timezone
import re
from typing import Any

from .models import (
    DocumentContext,
    KnowledgeEvidence,
    KnowledgeProviderError,
    ProviderHealth,
    SourceDocument,
    UpstreamAuthError,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
)

BUILTIN_FIXTURES: list[dict[str, Any]] = [
    {
        'evidence_id': 'ev-data-base-share-01',
        'document_id': 'doc-data-analysis-handbook',
        'document_version_id': 'v2026.1',
        'chunk_id': 'chunk-base-period-share-01',
        'document_title': '公考资料分析核心公式手册',
        'namespace': 'gongkao/xingce/data-analysis',
        'text': '基期比重计算公式：若现期部分量为 A，增长率为 a；现期整体量为 B，增长率为 b。则基期比重 = (A / B) × [(1 + b) / (1 + a)]。当 a > b 时，现期比重上升；当 a < b 时，现期比重下降。',
        'page': 14,
        'source_locator': 'sec:base-share',
        'source_reference': '资料分析篇 第2章 比重问题 第3节 基期比重',
        'citation': '《公考资料分析核心公式手册》第14页',
        'keywords': ['基期', '比重', '增长率', '公式', '现期量', '整体量'],
    },
    {
        'evidence_id': 'ev-reasoning-logic-01',
        'document_id': 'doc-formal-logic-guide',
        'document_version_id': 'v2026.1',
        'chunk_id': 'chunk-necessary-sufficient-01',
        'document_title': '判断推理形式逻辑图解指南',
        'namespace': 'gongkao/xingce/reasoning',
        'text': '充分条件假言命题：前推后（如果 A，那么 B => A -> B）。逆否等价命题成立：非 B -> 非 A。肯前必肯后，否后必否前，否前肯后均不能得出确定结论。注意“只有……才……”为后推前（只有 B 才 A => A -> B）。',
        'page': 28,
        'source_locator': 'sec:conditional-logic',
        'source_reference': '判断推理篇 第1章 必然性推理 第2节 假言命题',
        'citation': '《判断推理形式逻辑图解指南》第28页',
        'keywords': ['充分条件', '必要条件', '假言命题', '逆否命题', '前推后', '后推前'],
    },
    {
        'evidence_id': 'ev-verbal-context-01',
        'document_id': 'doc-verbal-comprehension',
        'document_version_id': 'v2026.1',
        'chunk_id': 'chunk-fill-blanks-01',
        'document_title': '言语理解与表达高频考点精析',
        'namespace': 'gongkao/xingce/verbal',
        'text': '逻辑填空中的语境分析法：寻找转折、并列、递进等标点与关联词。转折之后语义相反相对；递进之后程度加深；并列关系词义相近或感情色彩一致。切勿脱离文段主旨单凭语感选词。',
        'page': 45,
        'source_locator': 'sec:context-clues',
        'source_reference': '言语理解篇 第1章 逻辑填空 第1节 语境关联词',
        'citation': '《言语理解与表达高频考点精析》第45页',
        'keywords': ['逻辑填空', '语境', '关联词', '转折', '并列', '递进', '词义色彩'],
    },
    {
        'evidence_id': 'ev-quantitative-work-01',
        'document_id': 'doc-quantitative-methods',
        'document_version_id': 'v2026.1',
        'chunk_id': 'chunk-work-problem-01',
        'document_title': '数量关系高效解题法',
        'namespace': 'gongkao/xingce/quantitative',
        'text': '工程问题赋值法：已知多个人或队伍单独完成的时间时，通常设工作总量为时间的最小公倍数，进而求出各自的工作效率；若已知工作效率之比，可直接根据比例设效率特值。公式：工作总量 = 工作效率 × 工作时间。',
        'page': 33,
        'source_locator': 'sec:work-efficiency',
        'source_reference': '数量关系篇 第3章 工程问题 第1节 赋值法',
        'citation': '《数量关系高效解题法》第33页',
        'keywords': ['工程问题', '工作总量', '工作效率', '赋值法', '最小公倍数', '工作时间'],
    },
    {
        'evidence_id': 'ev-shenlun-extract-01',
        'document_id': 'doc-shenlun-methodology',
        'document_version_id': 'v2026.1',
        'chunk_id': 'chunk-info-extraction-01',
        'document_title': '申论归纳概括作答方法论',
        'namespace': 'gongkao/shenlun',
        'text': '申论材料信息提取三步法：一、分段定位核心句与关键问题；二、合并同类信息，删除细节举例与形容词；三、提炼规范化政治与政策动词，按照“问题-原因-影响-对策”逻辑分条归纳作答。',
        'page': 9,
        'source_locator': 'sec:generalization-steps',
        'source_reference': '申论通论 第2章 归纳概括题作答规范',
        'citation': '《申论归纳概括作答方法论》第9页',
        'keywords': ['申论', '归纳概括', '信息提取', '关键句', '规范词', '合并同类'],
    },
]


class FixtureProvider:
    """Deterministic demo fixture provider conforming to KnowledgeProvider protocol.

    All evidence is explicitly marked as demo data (metadata['source_kind']='demo_fixture',
    '[演示]' citation prefix) so it can never be mistaken for real course material.
    """

    provider_name: str = 'fixture'
    DEMO_CITATION_PREFIX = '[演示数据]'

    def __init__(self, fixtures: list[dict[str, Any]] | None = None, simulated_failure: str | None = None):
        self._fixtures = fixtures if fixtures is not None else list(BUILTIN_FIXTURES)
        self.simulated_failure = simulated_failure

    def _check_simulated_failure(self):
        if self.simulated_failure == 'timeout':
            raise UpstreamTimeoutError('Simulated fixture timeout')
        elif self.simulated_failure == 'auth':
            raise UpstreamAuthError('Simulated fixture 401 Unauthorized')
        elif self.simulated_failure == 'unavailable':
            raise UpstreamUnavailableError('Simulated fixture 503 Service Unavailable')

    async def retrieve(
        self,
        query: str,
        namespace: str,
        filters: dict[str, Any] | None = None,
        limit: int = 5,
    ) -> list[KnowledgeEvidence]:
        self._check_simulated_failure()
        if not query.strip() or limit <= 0:
            return []

        tokens = set(re.findall(r'[\w]+', query.lower()))
        scored: list[tuple[float, dict[str, Any]]] = []

        for item in self._fixtures:
            # Namespace matching
            item_ns = item.get('namespace', '')
            if namespace and item_ns and not (item_ns == namespace or item_ns.startswith(namespace)):
                continue

            # Token / keyword overlap scoring
            item_text = (item['text'] + ' ' + item['document_title']).lower()
            keywords = [k.lower() for k in item.get('keywords', [])]
            
            overlap_count = sum(1 for t in tokens if t in item_text)
            kw_match = sum(2 for k in keywords if any(t in k or k in t for t in tokens))
            total_matches = overlap_count + kw_match
            if total_matches == 0:
                continue

            relevance = min(1.0, 0.4 + 0.1 * total_matches)
            scored.append((relevance, item))

        scored.sort(key=lambda pair: (-pair[0], pair[1]['evidence_id']))
        results: list[KnowledgeEvidence] = []
        for score, item in scored[:limit]:
            citation = item.get('citation')
            if citation:
                citation = f'{self.DEMO_CITATION_PREFIX} {citation}'
            results.append(KnowledgeEvidence(
                evidence_id=item['evidence_id'],
                document_id=item['document_id'],
                document_version_id=item.get('document_version_id'),
                chunk_id=item['chunk_id'],
                document_title=f'{self.DEMO_CITATION_PREFIX} {item["document_title"]}',
                text=item['text'],
                score=round(score, 4),
                page=item.get('page'),
                source_locator=item.get('source_locator'),
                source_reference=item.get('source_reference'),
                citation=citation,
                metadata={**item.get('metadata', {}), 'source_kind': 'demo_fixture'},
            ))
        return results

    async def get_source(
        self,
        document_id: str,
        locator: str | None = None,
    ) -> SourceDocument | None:
        self._check_simulated_failure()
        matches = [f for f in self._fixtures if f['document_id'] == document_id]
        if not matches:
            return None
        first = matches[0]
        full_text = '\n\n'.join(f['text'] for f in matches)
        return SourceDocument(
            document_id=document_id,
            title=first['document_title'],
            version_id=first.get('document_version_id'),
            content_type='text/plain',
            content=full_text,
            metadata={'chunk_count': len(matches)},
        )

    async def get_document_context(
        self,
        document_id: str,
        locator: str | None = None,
    ) -> DocumentContext | None:
        self._check_simulated_failure()
        for f in self._fixtures:
            if f['document_id'] == document_id and (locator is None or f.get('source_locator') == locator):
                return DocumentContext(
                    document_id=document_id,
                    locator=f.get('source_locator'),
                    surrounding_text=f['text'],
                    headings=[f['document_title'], f.get('source_reference', '')],
                    page=f.get('page'),
                )
        return None

    async def health_check(self) -> ProviderHealth:
        self._check_simulated_failure()
        return ProviderHealth(
            status='degraded',
            provider=self.provider_name,
            latency_ms=0.1,
            message='演示数据模式（fixture）：证据来自内置示例，非真实课程资料；仅用于测试或演示',
            checked_at=datetime.now(timezone.utc).isoformat(),
        )
