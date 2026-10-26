'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { api, NodeQuestionItem } from '../api';

interface NodeQuestionsState {
  nodeId: string | null;
  loading: boolean;
  error: string | null;
  questions: NodeQuestionItem[] | null;
}

/**
 * 按节点拉取关联题目（含作答状态）。
 * 
 * 竞态与身份防护：
 * 1. 每次节点切换第一时间递增序号并锁定当前活动节点身份。
 * 2. 缓存命中时同样更新序号，防止飞行的旧慢响应覆盖已缓存节点。
 * 3. 状态携带 nodeId，防止上一个节点的题目在切换间隙闪现。
 * 4. 节点置空或卸载时废弃在途请求。
 */
export function useNodeQuestions(nodeId: string | null) {
  const [state, setState] = useState<NodeQuestionsState>({
    nodeId,
    loading: !!nodeId,
    error: null,
    questions: null,
  });
  const cacheRef = useRef(new Map<string, NodeQuestionItem[]>());
  const seqRef = useRef(0);
  const nodeIdRef = useRef<string | null>(nodeId);

  const fetchQuestions = useCallback((id: string, force = false) => {
    // 关键：在处理任何缓存或发起请求前，第一时间自增序号并确立当前节点身份
    const seq = ++seqRef.current;
    nodeIdRef.current = id;

    const cached = cacheRef.current.get(id);
    if (cached && !force) {
      setState({ nodeId: id, loading: false, error: null, questions: cached });
      return;
    }

    setState(prev => ({
      nodeId: id,
      loading: true,
      error: null,
      questions: prev.nodeId === id ? prev.questions : null,
    }));

    api<{ node_id: string; total: number; questions: NodeQuestionItem[] }>(
      `/knowledge-nodes/${encodeURIComponent(id)}/questions`,
    )
      .then(res => {
        if (seqRef.current !== seq || nodeIdRef.current !== id) return;
        cacheRef.current.set(id, res.questions);
        setState({ nodeId: id, loading: false, error: null, questions: res.questions });
      })
      .catch((err: unknown) => {
        if (seqRef.current !== seq || nodeIdRef.current !== id) return;
        const message = err instanceof Error ? err.message : '题目加载失败';
        setState({ nodeId: id, loading: false, error: message, questions: null });
      });
  }, []);

  useEffect(() => {
    if (!nodeId) {
      seqRef.current += 1;
      nodeIdRef.current = null;
      setState({ nodeId: null, loading: false, error: null, questions: null });
      return;
    }

    fetchQuestions(nodeId);

    return () => {
      seqRef.current += 1;
      nodeIdRef.current = null;
    };
  }, [nodeId, fetchQuestions]);

  const retry = useCallback(() => {
    const currentId = nodeIdRef.current;
    if (currentId) {
      fetchQuestions(currentId, true);
    }
  }, [fetchQuestions]);

  return { ...state, retry };
}
