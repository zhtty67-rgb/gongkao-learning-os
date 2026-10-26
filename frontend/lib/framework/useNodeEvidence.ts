'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';

export interface NodeEvidenceItem {
  binding_id: string;
  document_title: string;
  document_version_id: string | null;
  chunk_id: string | null;
  text: string;
  page: number | null;
  source_locator: string | null;
  citation: string | null;
  binding_type: string | null;
  confidence: number | null;
}

export type EvidenceState =
  | { kind: 'idle'; nodeId: null }
  | { kind: 'loading'; nodeId: string }
  | { kind: 'ok'; nodeId: string; count: number; items: NodeEvidenceItem[] }
  | { kind: 'unmapped'; nodeId: string; message: string }
  | { kind: 'unavailable'; nodeId: string; message: string };

/**
 * 按考点拉取知识中心正式绑定的教材片段（只读）。
 *
 * 竞态与身份防护保证：
 * 1. 每次节点变更，第一时间自增序号并更新当前活动节点身份，
 *    使此前飞行中的所有网络请求立即可靠失效。
 * 2. 缓存命中时同样更新序号与身份，防止后到的慢响应覆盖缓存节点。
 * 3. 状态携带 nodeId，面板渲染前可校验当前展示节点与资料身份一致，
 *    彻底消除标题与资料的短暂错配。
 * 4. 节点置空或卸载时主动自增序号并取消活动身份。
 * 5. 失败态不缓存，提供安全的重试入口。
 */
export function useNodeEvidence(nodeId: string | null) {
  const [state, setState] = useState<EvidenceState>(
    nodeId ? { kind: 'loading', nodeId } : { kind: 'idle', nodeId: null },
  );
  const cacheRef = useRef(new Map<string, EvidenceState>());
  const seqRef = useRef(0);
  const nodeIdRef = useRef<string | null>(nodeId);

  const fetchEvidence = useCallback((id: string, force = false) => {
    // 关键：在处理任何缓存或发起请求之前，必须先推进请求序号并确立当前节点身份。
    // 这保证了此前任何在途的旧请求（无论成功还是失败）在返回时均会被身份守卫拦截。
    const seq = ++seqRef.current;
    nodeIdRef.current = id;

    const cached = cacheRef.current.get(id);
    if (cached && !force) {
      setState(cached);
      return;
    }

    setState({ kind: 'loading', nodeId: id });

    api<{ status: string; message?: string; count?: number; items?: NodeEvidenceItem[] }>(
      `/knowledge-nodes/${encodeURIComponent(id)}/evidence`,
    )
      .then(res => {
        // 双重身份与时序校验：序号未变且当前仍驻留在此节点
        if (seqRef.current !== seq || nodeIdRef.current !== id) return;
        const next: EvidenceState =
          res.status === 'unmapped'
            ? { kind: 'unmapped', nodeId: id, message: res.message || '该考点尚未映射到知识中心节点' }
            : { kind: 'ok', nodeId: id, count: res.count || 0, items: res.items || [] };
        cacheRef.current.set(id, next);
        setState(next);
      })
      .catch((err: unknown) => {
        if (seqRef.current !== seq || nodeIdRef.current !== id) return;
        setState({
          kind: 'unavailable',
          nodeId: id,
          message: err instanceof Error ? err.message : '资料服务暂时无法访问',
        });
      });
  }, []);

  useEffect(() => {
    if (!nodeId) {
      seqRef.current += 1;
      nodeIdRef.current = null;
      setState({ kind: 'idle', nodeId: null });
      return;
    }

    fetchEvidence(nodeId);

    return () => {
      // 节点切换或组件卸载时立即废弃当前的在途请求
      seqRef.current += 1;
      nodeIdRef.current = null;
    };
  }, [nodeId, fetchEvidence]);

  const retry = useCallback(() => {
    const currentId = nodeIdRef.current;
    if (currentId) {
      fetchEvidence(currentId, true);
    }
  }, [fetchEvidence]);

  return { state, retry };
}
