"""REST API provider integrating with Universal Knowledge Hub service."""
from datetime import datetime, timezone
import logging
import os
import time
from typing import Any
import httpx

from .models import (
    DocumentContext,
    KnowledgeEvidence,
    MalformedResponseError,
    ProviderHealth,
    SourceDocument,
    UpstreamAuthError,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
)

logger = logging.getLogger(__name__)


class KnowledgeHubProvider:
    """Production provider connecting to external Universal Knowledge Hub REST API.
    
    Learning OS communicates strictly over this REST interface and never accesses
    the Knowledge Hub database, Qdrant vector index, or document parsers directly.
    """

    provider_name: str = 'knowledge_hub'

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self.base_url = (base_url or os.environ.get('KNOWLEDGE_HUB_BASE_URL', 'http://127.0.0.1:8200')).rstrip('/')
        self.api_key = api_key or os.environ.get('KNOWLEDGE_HUB_API_KEY')
        env_timeout = float(os.environ.get('KNOWLEDGE_HUB_TIMEOUT_SECONDS', '3.0'))
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else env_timeout
        self._custom_client = client

    def _get_headers(self) -> dict[str, str]:
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> httpx.Response:
        url = f'{self.base_url}{path}'
        to = timeout if timeout is not None else self.timeout_seconds
        headers = self._get_headers()
        if files:
            headers.pop('Content-Type', None)

        try:
            if self._custom_client is not None:
                response = await self._custom_client.request(
                    method, url, json=json_body, data=data, files=files, params=params, headers=headers, timeout=to
                )
            else:
                async with httpx.AsyncClient(timeout=to, trust_env=False) as client:
                    response = await client.request(
                        method, url, json=json_body, data=data, files=files, params=params, headers=headers
                    )
        except httpx.TimeoutException as exc:
            raise UpstreamTimeoutError(f'Knowledge Hub request to {path} timed out after {to}s') from exc
        except (httpx.NetworkError, httpx.ConnectError) as exc:
            raise UpstreamUnavailableError(f'Knowledge Hub unreachable at {self.base_url}: {exc}') from exc

        if response.status_code in (401, 403):
            raise UpstreamAuthError(f'Knowledge Hub auth error {response.status_code}: {response.text}')
        if response.status_code >= 500:
            raise UpstreamUnavailableError(f'Knowledge Hub 5xx error {response.status_code}: {response.text}')
        if response.status_code == 404:
            return response
        if response.status_code >= 400:
            raise MalformedResponseError(f'Knowledge Hub client error {response.status_code}: {response.text}')
        return response

    async def retrieve(
        self,
        query: str,
        namespace: str,
        filters: dict[str, Any] | None = None,
        limit: int = 5,
    ) -> list[KnowledgeEvidence]:
        """Query Knowledge Hub for relevant evidence chunks."""
        if not query.strip() or limit <= 0:
            return []

        payload = {
            'query': query,
            'namespace': namespace,
            'filters': filters or {},
            'limit': limit,
        }

        response = await self._request('POST', '/api/v1/retrieve', json_body=payload)
        try:
            data = response.json()
        except Exception as exc:
            raise MalformedResponseError('Invalid JSON returned by Knowledge Hub') from exc

        raw_items = data.get('items', []) if isinstance(data, dict) else data
        if not isinstance(raw_items, list):
            raise MalformedResponseError('Knowledge Hub response items must be a list')

        evidences: list[KnowledgeEvidence] = []
        for raw in raw_items:
            try:
                evidences.append(KnowledgeEvidence(
                    evidence_id=str(raw['evidence_id']),
                    document_id=str(raw['document_id']),
                    document_version_id=raw.get('document_version_id'),
                    chunk_id=str(raw['chunk_id']),
                    document_title=str(raw.get('document_title', '未命名文档')),
                    text=str(raw['text']),
                    score=float(raw.get('score', 0.0)),
                    page=raw.get('page'),
                    source_locator=raw.get('source_locator'),
                    source_reference=raw.get('source_reference'),
                    citation=raw.get('citation'),
                    metadata=raw.get('metadata', {}),
                ))
            except Exception as exc:
                logger.warning('Skipping malformed evidence from Knowledge Hub: %s (%s)', raw, exc)
                continue

        return evidences

    async def safe_retrieve(
        self,
        query: str,
        namespace: str,
        filters: dict[str, Any] | None = None,
        limit: int = 5,
    ) -> list[KnowledgeEvidence]:
        """Safe retrieval wrapper with complete failure isolation.
        
        Guarantees that no upstream exception will escape to break quiz
        or learning flows.
        """
        try:
            return await self.retrieve(query, namespace, filters, limit)
        except Exception as exc:
            logger.error('Knowledge Hub safe_retrieve degraded gracefully: %s', exc)
            return []

    async def get_node_evidence(self, node_code: str) -> dict[str, Any]:
        """Fetch formal node-evidence bindings from the Hub by node code.

        Read-only lookup of the Hub's binding registry (never free-text
        retrieval). Hub 404 means the code has no node on the Hub side,
        i.e. the Learning OS node is not mapped there.
        """
        code = (node_code or '').strip()
        if not code:
            return {'status': 'unmapped', 'count': 0, 'items': [], 'hub_node_id': None}

        response = await self._request('GET', f'/api/v1/knowledge-nodes/{code}/evidence')
        if response.status_code == 404:
            return {'status': 'unmapped', 'count': 0, 'items': [], 'hub_node_id': None}
        try:
            data = response.json()
        except Exception as exc:
            raise MalformedResponseError('Invalid JSON returned by Knowledge Hub evidence endpoint') from exc
        if not isinstance(data, dict):
            raise MalformedResponseError('Knowledge Hub evidence response must be an object')

        items = data.get('items', [])
        if not isinstance(items, list):
            raise MalformedResponseError('Knowledge Hub evidence items must be a list')
        return {
            'status': 'ok',
            'count': int(data.get('count', len(items))),
            'items': items,
            'hub_node_id': data.get('node_id'),
        }

    async def get_source(
        self,
        document_id: str,
        locator: str | None = None,
    ) -> SourceDocument | None:
        params = {'locator': locator} if locator else None
        response = await self._request('GET', f'/api/v1/documents/{document_id}', params=params)
        if response.status_code == 404:
            return None
        try:
            raw = response.json()
            return SourceDocument(
                document_id=str(raw['document_id']),
                title=str(raw['title']),
                version_id=raw.get('version_id'),
                content_type=raw.get('content_type', 'text/plain'),
                content=str(raw['content']),
                metadata=raw.get('metadata', {}),
            )
        except Exception as exc:
            raise MalformedResponseError(f'Failed to parse document response: {exc}') from exc

    async def get_document_context(
        self,
        document_id: str,
        locator: str | None = None,
    ) -> DocumentContext | None:
        params = {'locator': locator} if locator else None
        response = await self._request('GET', f'/api/v1/documents/{document_id}/context', params=params)
        if response.status_code == 404:
            return None
        try:
            raw = response.json()
            return DocumentContext(
                document_id=str(raw['document_id']),
                locator=raw.get('locator'),
                surrounding_text=str(raw['surrounding_text']),
                headings=raw.get('headings', []),
                page=raw.get('page'),
            )
        except Exception as exc:
            raise MalformedResponseError(f'Failed to parse context response: {exc}') from exc

    async def get_parsed_document(self, document_id: str, version_id: str | None = None) -> dict[str, Any]:
        from urllib.parse import quote
        path = f'/api/v1/documents/{quote(document_id, safe="")}'
        if version_id:
            path += f'/versions/{quote(version_id, safe="")}'
        response = await self._request('GET', path + '/parsed')
        if response.status_code != 200:
            raise MalformedResponseError(f'Parsed document unavailable: HTTP {response.status_code}')
        data = response.json()
        if data.get('document_id') != document_id or (version_id and data.get('document_version_id') != version_id):
            raise MalformedResponseError('Parsed document identity does not match import job')
        if data.get('parse_status') != 'ready':
            raise MalformedResponseError('Parsed document is not ready')
        return data

    async def get_framework_tree(self, framework_id: str = "gongkao-core-v1") -> list[dict[str, Any]]:
        from urllib.parse import quote
        path = f'/api/v1/frameworks/{quote(framework_id, safe="")}/tree'
        try:
            response = await self._request('GET', path)
            if response.status_code == 200:
                return response.json()
        except Exception as exc:
            logger.warning("failed_to_fetch_k6_tree: %s", exc)
        return []

    async def import_document(
        self,
        filename: str,
        content: bytes,
        namespace: str = 'gongkao/xingce',
        title: str | None = None,
        wait: bool = True,
    ) -> dict[str, Any]:
        """Uploads document bytes to Knowledge Hub and awaits parse result."""
        files = {'file': (filename, content, 'application/pdf')}
        data = {'namespace': namespace}
        if title:
            data['title'] = title
        response = await self._request(
            'POST',
            '/api/v1/documents/import',
            data=data,
            files=files,
            params={'wait': 'true'} if wait else None,
            timeout=300.0 if wait else 10.0,
        )
        if response.status_code not in (200, 201, 202):
            raise MalformedResponseError(f'Hub import failed: HTTP {response.status_code}')
        return response.json()

    async def health_check(self) -> ProviderHealth:
        start = time.perf_counter()
        now_str = datetime.now(timezone.utc).isoformat()
        try:
            res = await self._request('GET', '/api/v1/health', timeout=1.0)
            latency = (time.perf_counter() - start) * 1000.0
            if res.status_code == 200:
                return ProviderHealth(
                    status='healthy',
                    provider=self.provider_name,
                    latency_ms=round(latency, 2),
                    message='Knowledge Hub connected',
                    checked_at=now_str,
                )
            return ProviderHealth(
                status='degraded',
                provider=self.provider_name,
                latency_ms=round(latency, 2),
                message=f'Knowledge Hub status code {res.status_code}',
                checked_at=now_str,
            )
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000.0
            return ProviderHealth(
                status='unavailable',
                provider=self.provider_name,
                latency_ms=round(latency, 2),
                message=str(exc),
                checked_at=now_str,
            )
