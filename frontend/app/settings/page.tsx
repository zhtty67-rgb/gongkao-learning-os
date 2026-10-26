'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';

type PolicySnapshot = {
  name: string;
  provider: string;
  model: string;
  base_url: string | null;
  api_key: string | null;
  api_key_set: boolean;
  temperature: number;
  max_tokens: number;
  timeout_seconds: number;
  supports_vision: boolean;
};

type KnowledgeSnapshot = {
  provider: string | null;
  env_provider: string;
  hub_base_url: string;
  hub_api_key_masked: string | null;
  hub_api_key_set: boolean;
  hub_timeout_seconds: number;
  saved: Record<string, unknown> | null;
};

type SettingsSnapshot = {
  ai: { policies: Record<string, PolicySnapshot>; fallback: PolicySnapshot | null };
  knowledge: KnowledgeSnapshot;
  has_saved_settings: boolean;
  settings_file: string;
};

type PolicyForm = {
  provider: string;
  model: string;
  base_url: string;
  api_key: string;
  clear_key: boolean;
  temperature: string;
  max_tokens: string;
  timeout_seconds: string;
  supports_vision: boolean;
  api_key_set: boolean;
  masked: string | null;
};

const POLICY_LABELS: Record<string, string> = {
  FAST: '快速档（提示、轻量任务）',
  BALANCED: '均衡档（讲解、诊断）',
  STRONG: '强力档（申论批改、出题）',
  fallback: '备用模型（主力失败时兜底）',
};

function toForm(p: PolicySnapshot): PolicyForm {
  return {
    provider: p.provider || 'openai_compatible',
    model: p.model || '',
    base_url: p.base_url || '',
    api_key: '',
    clear_key: false,
    temperature: String(p.temperature ?? ''),
    max_tokens: String(p.max_tokens ?? ''),
    timeout_seconds: String(p.timeout_seconds ?? ''),
    supports_vision: !!p.supports_vision,
    api_key_set: !!p.api_key_set,
    masked: p.api_key || null,
  };
}

function policyPayload(form: PolicyForm): Record<string, unknown> {
  const num = (v: string) => {
    const t = v.trim();
    if (!t) return null;
    const n = Number(t);
    return Number.isFinite(n) ? n : null;
  };
  const payload: Record<string, unknown> = {
    provider: form.provider,
    model: form.model.trim(),
    base_url: form.base_url.trim(),
    temperature: num(form.temperature),
    max_tokens: num(form.max_tokens),
    timeout_seconds: num(form.timeout_seconds),
    supports_vision: form.supports_vision,
  };
  if (form.clear_key) payload.api_key = '';
  else if (form.api_key.trim()) payload.api_key = form.api_key.trim();
  return payload;
}

export default function SettingsPage() {
  const [snapshot, setSnapshot] = useState<SettingsSnapshot | null>(null);
  const [forms, setForms] = useState<Record<string, PolicyForm>>({});
  const [fallbackEnabled, setFallbackEnabled] = useState(false);
  const [kbProvider, setKbProvider] = useState<string>('');
  const [kbBaseUrl, setKbBaseUrl] = useState('');
  const [kbApiKey, setKbApiKey] = useState('');
  const [kbClearKey, setKbClearKey] = useState(false);
  const [kbTimeout, setKbTimeout] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [testing, setTesting] = useState<string>('');
  const [testResult, setTestResult] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch('/api/settings', { cache: 'no-store' });
      if (!res.ok) throw new Error(`加载设置失败（HTTP ${res.status}）`);
      const data: SettingsSnapshot = await res.json();
      setSnapshot(data);
      const nextForms: Record<string, PolicyForm> = {};
      for (const [name, cfg] of Object.entries(data.ai.policies)) nextForms[name] = toForm(cfg);
      nextForms.fallback = data.ai.fallback
        ? toForm(data.ai.fallback)
        : {
            provider: 'openai_compatible',
            model: '',
            base_url: '',
            api_key: '',
            clear_key: false,
            temperature: '0.2',
            max_tokens: '4096',
            timeout_seconds: '30',
            supports_vision: false,
            api_key_set: false,
            masked: null,
          };
      setForms(nextForms);
      setFallbackEnabled(!!data.ai.fallback);
      setKbProvider(data.knowledge.provider || '');
      setKbBaseUrl(data.knowledge.hub_base_url || 'http://127.0.0.1:8200');
      setKbTimeout(String(data.knowledge.hub_timeout_seconds ?? 3));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const patchForm = (name: string, patch: Partial<PolicyForm>) => {
    setForms(prev => ({ ...prev, [name]: { ...prev[name], ...patch } }));
  };

  const save = async () => {
    setSaving(true);
    setMessage('');
    setError('');
    try {
      const policies: Record<string, unknown> = {};
      for (const name of ['FAST', 'BALANCED', 'STRONG']) {
        if (forms[name]) policies[name] = policyPayload(forms[name]);
      }
      const body: Record<string, unknown> = {
        ai: {
          policies,
          fallback: fallbackEnabled && forms.fallback ? policyPayload(forms.fallback) : null,
        },
        knowledge: {
          provider: kbProvider || null,
          hub_base_url: kbBaseUrl.trim() || null,
          hub_api_key: kbClearKey ? '' : (kbApiKey.trim() || null),
          hub_timeout_seconds: Number(kbTimeout) > 0 ? Number(kbTimeout) : null,
        },
      };
      const res = await fetch('/api/settings', {
        method: 'PUT',
        cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const value = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(typeof value.detail === 'string' ? value.detail : `保存失败（HTTP ${res.status}）`);
      }
      setMessage('已保存并即时生效（模型与知识检索已热重载，重启后依然生效）。');
      setKbApiKey('');
      setKbClearKey(false);
      setForms(prev => {
        const next = { ...prev };
        for (const key of Object.keys(next)) next[key] = { ...next[key], api_key: '', clear_key: false };
        return next;
      });
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const testPolicy = async (name: string) => {
    const form = forms[name];
    if (!form) return;
    setTesting(name);
    setTestResult(prev => ({ ...prev, [name]: '测试中…' }));
    try {
      const override = policyPayload(form);
      if (form.clear_key) override.api_key = '';
      else if (!form.api_key.trim()) delete override.api_key;
      const res = await fetch('/api/settings/ai/test', {
        method: 'POST',
        cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ policy: name, override }),
      });
      const value = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof value.detail === 'string' ? value.detail : `HTTP ${res.status}`);
      setTestResult(prev => ({
        ...prev,
        [name]: `${value.ok ? '✓ ' : '✗ '}${value.message || (value.ok ? '连接成功' : '连接失败')}`,
      }));
    } catch (e: unknown) {
      setTestResult(prev => ({ ...prev, [name]: `✗ ${e instanceof Error ? e.message : String(e)}` }));
    } finally {
      setTesting('');
    }
  };

  const testKnowledge = async () => {
    setTesting('knowledge');
    setTestResult(prev => ({ ...prev, knowledge: '测试中…' }));
    try {
      const res = await fetch('/api/settings/knowledge/test', {
        method: 'POST',
        cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const value = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof value.detail === 'string' ? value.detail : `HTTP ${res.status}`);
      setTestResult(prev => ({
        ...prev,
        knowledge: `${value.ok ? '✓ ' : '✗ '}${value.message || value.status || ''}`,
      }));
    } catch (e: unknown) {
      setTestResult(prev => ({ ...prev, knowledge: `✗ ${e instanceof Error ? e.message : String(e)}` }));
    } finally {
      setTesting('');
    }
  };

  const renderPolicyCard = (name: string) => {
    const form = forms[name];
    if (!form) return null;
    const isFallback = name === 'fallback';
    return (
      <article className="settings-card" key={name}>
        <div className="settings-card-head">
          <h3>{POLICY_LABELS[name] || name}</h3>
          {isFallback ? (
            <label className="settings-clear">
              <input type="checkbox" checked={fallbackEnabled} onChange={e => setFallbackEnabled(e.target.checked)} />
              启用备用模型
            </label>
          ) : (
            <button type="button" className="settings-test-btn" disabled={testing === name} onClick={() => testPolicy(name)}>
              {testing === name ? '测试中…' : '测试连接'}
            </button>
          )}
        </div>
        {fallbackEnabled || !isFallback ? (
          <>
            {testResult[name] && <p className={testResult[name].startsWith('✓') ? 'settings-ok' : 'settings-fail'}>{testResult[name]}</p>}
            <div className="settings-grid">
              <label>provider
                <select value={form.provider} onChange={e => patchForm(name, { provider: e.target.value })}>
                  <option value="openai_compatible">openai_compatible（通用 OpenAI 兼容接口）</option>
                  <option value="mock">mock（内置演示，不联网）</option>
                </select>
              </label>
              <label>model
                <input value={form.model} onChange={e => patchForm(name, { model: e.target.value })} placeholder="例如 deepseek-chat / gemini-xxx" />
              </label>
              <label className="settings-wide">base_url
                <input value={form.base_url} onChange={e => patchForm(name, { base_url: e.target.value })} placeholder="例如 https://api.deepseek.com/v1" />
              </label>
              <label className="settings-wide">api_key
                <div className="settings-key-row">
                  <input
                    type="password"
                    value={form.api_key}
                    onChange={e => patchForm(name, { api_key: e.target.value })}
                    placeholder={form.api_key_set ? `已配置（${form.masked || '已保存'}），留空保持不变` : '未配置，请输入密钥'}
                    autoComplete="off"
                  />
                  {form.api_key_set && (
                    <label className="settings-clear">
                      <input type="checkbox" checked={form.clear_key} onChange={e => patchForm(name, { clear_key: e.target.checked })} />
                      清除
                    </label>
                  )}
                </div>
              </label>
              <label>temperature
                <input value={form.temperature} onChange={e => patchForm(name, { temperature: e.target.value })} inputMode="decimal" />
              </label>
              <label>max_tokens
                <input value={form.max_tokens} onChange={e => patchForm(name, { max_tokens: e.target.value })} inputMode="numeric" />
              </label>
              <label>timeout_seconds
                <input value={form.timeout_seconds} onChange={e => patchForm(name, { timeout_seconds: e.target.value })} inputMode="decimal" />
              </label>
              <label className="settings-check">
                <input type="checkbox" checked={form.supports_vision} onChange={e => patchForm(name, { supports_vision: e.target.checked })} />
                支持图片（视觉题干）
              </label>
            </div>
          </>
        ) : (
          <p className="settings-hint">备用模型未启用；主力模型请求失败时将直接报错。勾选右上角启用。</p>
        )}
        {isFallback && fallbackEnabled && <p className="settings-hint">备用模型仅在主力模型请求失败时自动接管。</p>}
      </article>
    );
  };

  return <main>
    <header><Link href="/dashboard" className="brand"><span className="brand-icon">学</span>公考 Learning OS</Link><nav><Link href="/dashboard">学习概览</Link><Link href="/framework">知识框架</Link><Link href="/teaching">自适应教学</Link><Link href="/quiz">行测训练</Link><Link href="/review">到期复习</Link><Link href="/notes">我的笔记</Link><Link href="/exam">全真模考</Link><Link href="/shenlun">申论工作台</Link><Link href="/importer">题库导入</Link><Link href="/settings" className="active">系统设置</Link></nav><span className="local">● 本地学习空间</span></header>
    <div className="intro dashboard-intro"><span className="eyebrow">SETTINGS / 系统设置</span><h1>配置你的 AI 与知识检索。</h1><p>密钥只保存在本机 data/settings.json，页面显示永远是掩码；保存后立即生效，无需重启。</p></div>
    {error && <div role="alert" className="error">{error}</div>}
    {message && <div role="status" className="settings-ok">{message}</div>}
    {loading && <p role="status">正在读取当前配置…</p>}
    {!loading && <>
      <section className="dashboard-section">
        <div className="section-heading"><h2>AI 模型网关</h2><span>三档策略 + 备用模型；留空表示保持现值不变</span></div>
        {(['FAST', 'BALANCED', 'STRONG'] as const).map(name => renderPolicyCard(name))}
        {renderPolicyCard('fallback')}
      </section>

      <section className="dashboard-section">
        <div className="section-heading"><h2>知识检索</h2><span>教学讲解的证据来源；Hub 未启动时相关讲解自动降级</span></div>
        <article className="settings-card">
          <div className="settings-card-head">
            <h3>Universal Knowledge Hub</h3>
            <button type="button" className="settings-test-btn" disabled={testing === 'knowledge'} onClick={testKnowledge}>
              {testing === 'knowledge' ? '测试中…' : '测试连接'}
            </button>
          </div>
          {testResult.knowledge && <p className={testResult.knowledge.startsWith('✓') ? 'settings-ok' : 'settings-fail'}>{testResult.knowledge}</p>}
          <div className="settings-grid">
            <label>provider
              <select value={kbProvider} onChange={e => setKbProvider(e.target.value)}>
                <option value="">跟随启动脚本（当前：{snapshot?.knowledge.env_provider || '默认'}）</option>
                <option value="knowledge_hub">knowledge_hub（连接本地 Hub 服务）</option>
                <option value="disabled">disabled（关闭知识检索）</option>
                <option value="fixture">fixture（演示数据，仅供体验）</option>
              </select>
            </label>
            <label>hub 超时（秒）
              <input value={kbTimeout} onChange={e => setKbTimeout(e.target.value)} inputMode="decimal" />
            </label>
            <label className="settings-wide">Hub 地址
              <input value={kbBaseUrl} onChange={e => setKbBaseUrl(e.target.value)} placeholder="http://127.0.0.1:8200" />
            </label>
            <label className="settings-wide">Hub api_key（可选）
              <div className="settings-key-row">
                <input
                  type="password"
                  value={kbApiKey}
                  onChange={e => setKbApiKey(e.target.value)}
                  placeholder={snapshot?.knowledge.hub_api_key_set ? `已配置（${snapshot.knowledge.hub_api_key_masked || '已保存'}），留空保持不变` : '未配置，本地 Hub 一般无需密钥'}
                  autoComplete="off"
                />
                {snapshot?.knowledge.hub_api_key_set && (
                  <label className="settings-clear">
                    <input type="checkbox" checked={kbClearKey} onChange={e => setKbClearKey(e.target.checked)} />
                    清除
                  </label>
                )}
              </div>
            </label>
          </div>
        </article>
      </section>

      <div className="settings-actions">
        <button type="button" className="primary" disabled={saving || loading} onClick={save} style={{ padding: '10px 28px', borderRadius: 8, border: 'none', cursor: 'pointer', fontWeight: 600 }}>
          {saving ? '保存中…' : '保存全部设置'}
        </button>
        <span className="settings-hint">配置文件：{snapshot?.settings_file || 'data/settings.json'}</span>
      </div>
    </>}
  </main>;
}
