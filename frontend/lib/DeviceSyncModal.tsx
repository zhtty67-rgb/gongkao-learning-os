'use client';

import React, { useEffect, useRef, useState } from 'react';
import QRCode from 'qrcode';
import { api } from './api';

interface NetworkInfo {
  lan_ip: string;
  frontend_port: number;
  backend_port: number;
  quiz_url: string;
  home_url: string;
}

interface DeviceSyncModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function DeviceSyncModal({ isOpen, onClose }: DeviceSyncModalProps) {
  const [networkInfo, setNetworkInfo] = useState<NetworkInfo | null>(null);
  const [qrDataUrl, setQrDataUrl] = useState<string>('');
  const [copied, setCopied] = useState(false);
  const [manualCopy, setManualCopy] = useState(false);
  const urlInput = useRef<HTMLInputElement>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!isOpen) return;
    setLoading(true);
    setCopied(false);
    setManualCopy(false);

    api<NetworkInfo>('/network/info')
      .then(async info => {
        setNetworkInfo(info);
        const targetUrl = info.quiz_url || `http://${window.location.hostname}:3000/quiz`;
        const dataUrl = await QRCode.toDataURL(targetUrl, {
          width: 220,
          margin: 1,
          color: {
            dark: '#1e293b',
            light: '#ffffff',
          },
        });
        setQrDataUrl(dataUrl);
      })
      .catch(async () => {
        const fallbackUrl = `http://${window.location.hostname}:3000/quiz`;
        const dataUrl = await QRCode.toDataURL(fallbackUrl, { width: 220, margin: 1 });
        setQrDataUrl(dataUrl);
      })
      .finally(() => setLoading(false));
  }, [isOpen]);

  if (!isOpen) return null;

  const currentUrl = networkInfo?.quiz_url || (typeof window !== 'undefined' ? `http://${window.location.hostname}:3000/quiz` : '');

  const copyUrl = async () => {
    if (!currentUrl) return;
    let success = false;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(currentUrl);
        success = true;
      }
    } catch { /* HTTP origins and denied clipboard permissions use selection. */ }
    if (!success && urlInput.current) {
      urlInput.current.focus({preventScroll:true});
      urlInput.current.select();
      urlInput.current.setSelectionRange(0, currentUrl.length);
      try { success = document.execCommand('copy'); } catch { /* Keep selected URL available for long-press copying. */ }
    }
    setManualCopy(!success);
    if (success) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(15, 23, 42, 0.65)',
        backdropFilter: 'blur(6px)',
        display: 'grid',
        placeItems: 'center',
        zIndex: 9999,
        padding: 16,
      }}
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="手机和平板刷题连接"
        style={{
          background: '#ffffff',
          borderRadius: 16,
          padding: '24px 28px',
          maxWidth: 440,
          width: '100%',
          maxHeight: 'calc(100dvh - 32px)',
          overflowY: 'auto',
          boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1)',
          border: '1px solid #e2e8f0',
          textAlign: 'center',
        }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontSize: 18, color: '#0f172a', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>📱</span> 手机 / 平板局域网刷题
          </h3>
          <button
            type="button"
            aria-label="关闭手机连接"
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              fontSize: 20,
              color: '#94a3b8',
              cursor: 'pointer',
              padding: 4,
              lineHeight: 1,
            }}
          >
            ✕
          </button>
        </div>

        <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 16px', lineHeight: 1.6 }}>
          确保手机/平板与电脑连接在<strong>同一个 Wi-Fi</strong> 下，扫码即刻无缝开练。
        </p>

        {loading ? (
          <div style={{ height: 220, display: 'grid', placeItems: 'center', color: '#64748b' }}>
            <span>正在生成连接二维码…</span>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
            <div
              style={{
                background: '#ffffff',
                padding: 12,
                borderRadius: 12,
                border: '1px solid #e2e8f0',
                display: 'inline-block',
                boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
              }}
            >
              {qrDataUrl && <img src={qrDataUrl} alt="扫码刷题" style={{ width: 200, height: 200, display: 'block' }} />}
            </div>

            <div
              style={{
                width: '100%',
                background: '#f8fafc',
                border: '1px solid #cbd5e1',
                borderRadius: 8,
                padding: '8px 12px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 8,
                marginTop: 4,
              }}
            >
              <input ref={urlInput} aria-label="手机刷题网址" readOnly value={currentUrl} style={{ fontSize: 12, color: '#0f172a', width: '100%', minWidth: 0, border: 0, padding: 0, background: 'transparent' }} />
              <button
                type="button"
                onClick={copyUrl}
                style={{
                  padding: '4px 10px',
                  fontSize: 11,
                  borderRadius: 6,
                  border: '1px solid var(--accent)',
                  background: copied ? 'var(--accent)' : '#ffffff',
                  color: copied ? '#ffffff' : 'var(--accent)',
                  whiteSpace: 'nowrap',
                  cursor: 'pointer',
                }}
              >
                {copied ? '✓ 已复制' : manualCopy ? '长按复制网址' : '复制网址'}
              </button>
            </div>
          </div>
        )}

        <div
          style={{
            marginTop: 18,
            padding: '10px 14px',
            background: '#f0fdf4',
            border: '1px solid #bbf7d0',
            borderRadius: 8,
            fontSize: 12,
            color: '#166534',
            textAlign: 'left',
            lineHeight: 1.6,
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 2 }}>⚡ 数据实时互通特性：</div>
          <div>• 手机/平板提交的每道题作答，直接写入电脑本地 SQLite 数据库。</div>
          <div>• 每日目标进度、错因归因与 FSRS 复习卡片在全设备上完全一致。</div>
        </div>
      </div>
    </div>
  );
}
