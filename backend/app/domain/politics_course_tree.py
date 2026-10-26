"""Read explicit course references attached to the politics learning taxonomy.

This is a local course binding adapter, not a replacement for Knowledge Hub.
"""
import json


def course_evidence(metadata_json: str, node_id: str) -> list[dict]:
    if not node_id.startswith('political_theory'):
        return []
    metadata = json.loads(metadata_json or '{}')
    if metadata.get('source') != 'fengze_politics_course_catalog':
        return []
    items = []
    for index, source in enumerate(metadata.get('course_sources', [])):
        locator = f"第{source['line']}行，字符{source['start_char']}—{source['end_char']}"
        items.append({
            'binding_id': f'{node_id}:course:{index}',
            'document_title': source['source_file'],
            'document_version_id': source['source_sha256'],
            'chunk_id': None,
            'text': source['excerpt'], 'page': None, 'source_locator': locator,
            'citation': f"P 老师政治理论课程（{source['course_period']}），{source['source_file']}，{locator}",
            'binding_type': 'local_course_reference', 'confidence': None,
        })
    return items
