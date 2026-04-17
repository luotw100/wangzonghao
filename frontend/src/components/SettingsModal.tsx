import { useState } from 'react';
import { Modal } from './Modal';
import * as api from '../lib/api';
import type { Robot, Contact, ProviderConfig } from '../lib/api';
import { IconEdit, IconPlus, IconClose, IconChevronRight } from './Icons';
import { cn } from '../lib/utils';

interface SettingsModalProps {
  open: boolean;
  onClose: () => void;
  robots: Robot[];
  contacts: Contact[];
  providerConfigs: ProviderConfig[];
  onEditRobot: (robot: Robot) => void;
  onCreateRobot: () => void;
  onEditContact: (contact: Contact) => void;
  onCreateContact: () => void;
  onRefresh: () => void;
  onError: (msg: string) => void;
}

export function SettingsModal({
  open,
  onClose,
  robots,
  contacts,
  providerConfigs,
  onEditRobot,
  onCreateRobot,
  onEditContact,
  onCreateContact,
  onRefresh,
  onError,
}: SettingsModalProps) {
  const [tab, setTab] = useState<'robots' | 'contacts' | 'providers'>('robots');
  const [showProviderForm, setShowProviderForm] = useState(false);
  const [editingProviderId, setEditingProviderId] = useState<string | null>(null);
  const [providerForm, setProviderForm] = useState({ name: '', base_url: '', api_key: '', default_model: '' });

  const openProviderForm = (provider: ProviderConfig | null) => {
    setShowProviderForm(true);
    if (provider) {
      setEditingProviderId(provider.id);
      setProviderForm({
        name: provider.name || '',
        base_url: provider.base_url || '',
        api_key: '',
        default_model: provider.default_model || '',
      });
    } else {
      setEditingProviderId(null);
      setProviderForm({ name: '', base_url: '', api_key: '', default_model: '' });
    }
  };

  const saveProvider = async () => {
    const f = providerForm;
    if (!f.name.trim() || !f.base_url.trim() || !f.default_model.trim()) {
      onError('Provider 名称、Base URL 和模型不能为空');
      return;
    }
    try {
      if (editingProviderId) {
        const update: Record<string, string> = { name: f.name.trim(), base_url: f.base_url.trim(), default_model: f.default_model.trim() };
        if (f.api_key.trim()) update.api_key = f.api_key.trim();
        await api.updateProviderConfig(editingProviderId, update as { name: string; base_url: string; api_key?: string; default_model: string });
      } else {
        await api.createProviderConfig({
          name: f.name.trim(),
          base_url: f.base_url.trim(),
          api_key: f.api_key.trim() || null,
          default_model: f.default_model.trim(),
        });
      }
      setShowProviderForm(false);
      setEditingProviderId(null);
      setProviderForm({ name: '', base_url: '', api_key: '', default_model: '' });
      onRefresh();
    } catch (err: unknown) {
      onError('保存 Provider 配置失败: ' + (err instanceof Error ? err.message : String(err)));
    }
  };

  const deleteProvider = async () => {
    if (!editingProviderId) return;
    try {
      await api.deleteProviderConfig(editingProviderId);
      setShowProviderForm(false);
      setEditingProviderId(null);
      setProviderForm({ name: '', base_url: '', api_key: '', default_model: '' });
      onRefresh();
    } catch (err: unknown) {
      onError('删除 Provider 配置失败: ' + (err instanceof Error ? err.message : String(err)));
    }
  };

  const tabClass = (t: string) =>
    cn(
      'px-4 py-2.5 text-sm font-medium transition border-b-2 -mb-px',
      tab === t ? 'border-accent text-accent' : 'border-transparent text-text-secondary hover:text-text-primary'
    );

  return (
    <>
      <Modal open={open} onClose={onClose} maxWidth="max-w-2xl">
        <div className="px-0 pt-0 pb-0 shrink-0">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-medium">设置</h3>
            <button onClick={onClose} className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-bg-tertiary">
              <IconClose />
            </button>
          </div>
          <div className="flex border-b border-border">
            <button onClick={() => setTab('robots')} className={tabClass('robots')}>Robot</button>
            <button onClick={() => setTab('contacts')} className={tabClass('contacts')}>联系人</button>
            <button onClick={() => setTab('providers')} className={tabClass('providers')}>Provider</button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto py-4">
          {/* Robots Tab */}
          {tab === 'robots' && (
            <div>
              <div className="space-y-1">
                {robots.map((robot) => (
                  <div key={robot.id} className="flex items-center justify-between px-3 py-2.5 rounded-lg hover:bg-bg-tertiary transition group">
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <span className={cn('text-sm font-medium truncate', robot.is_deleted && 'opacity-60')}>{robot.name}</span>
                      {robot.is_deleted && (
                        <span className="px-2 py-0.5 rounded-full bg-danger-bg text-danger text-[10px] shrink-0">已删除</span>
                      )}
                    </div>
                    <button
                      onClick={() => onEditRobot(robot)}
                      className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-border opacity-40 group-hover:opacity-100 transition shrink-0"
                      title="编辑"
                    >
                      <IconEdit />
                    </button>
                  </div>
                ))}
                {robots.length === 0 && <div className="py-4 text-center text-sm text-text-tertiary">暂无 Robot</div>}
              </div>
              <button
                onClick={onCreateRobot}
                className="mt-3 w-full text-left px-3 py-2.5 rounded-lg text-sm text-accent hover:bg-accent/10 transition flex items-center gap-2"
              >
                <IconPlus size={14} />
                新建 Robot
              </button>
            </div>
          )}

          {/* Contacts Tab */}
          {tab === 'contacts' && (
            <div>
              <div className="space-y-1">
                {contacts.map((contact) => (
                  <div key={contact.id} className="flex items-center justify-between px-3 py-2.5 rounded-lg hover:bg-bg-tertiary transition group">
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <span className={cn('text-sm font-medium truncate', contact.is_deleted && 'opacity-60')}>{contact.name}</span>
                      {contact.is_deleted && (
                        <span className="px-2 py-0.5 rounded-full bg-danger-bg text-danger text-[10px] shrink-0">已删除</span>
                      )}
                    </div>
                    <button
                      onClick={() => onEditContact(contact)}
                      className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-border opacity-40 group-hover:opacity-100 transition shrink-0"
                      title="编辑"
                    >
                      <IconEdit />
                    </button>
                  </div>
                ))}
                {contacts.length === 0 && <div className="py-4 text-center text-sm text-text-tertiary">暂无联系人</div>}
              </div>
              <button
                onClick={onCreateContact}
                className="mt-3 w-full text-left px-3 py-2.5 rounded-lg text-sm text-accent hover:bg-accent/10 transition flex items-center gap-2"
              >
                <IconPlus size={14} />
                新建联系人
              </button>
            </div>
          )}

          {/* Providers Tab */}
          {tab === 'providers' && (
            <div>
              <div className="space-y-1">
                {providerConfigs.map((p) => (
                  <div
                    key={p.id}
                    onClick={() => openProviderForm(p)}
                    className="flex items-center justify-between px-3 py-2.5 rounded-lg hover:bg-bg-tertiary transition group cursor-pointer"
                  >
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <span className="text-sm font-medium truncate">{p.name}</span>
                      <span className="text-xs text-text-tertiary truncate">{p.default_model}</span>
                    </div>
                    <IconChevronRight size={14} />
                  </div>
                ))}
                {providerConfigs.length === 0 && <div className="py-4 text-center text-sm text-text-tertiary">暂无 Provider</div>}
              </div>
              <button
                onClick={() => openProviderForm(null)}
                className="mt-3 w-full text-left px-3 py-2.5 rounded-lg text-sm text-accent hover:bg-accent/10 transition flex items-center gap-2"
              >
                <IconPlus size={14} />
                新建 Provider
              </button>
            </div>
          )}
        </div>
      </Modal>

      {/* Provider Form Sub-Modal */}
      <Modal open={showProviderForm} onClose={() => setShowProviderForm(false)}>
        <h3 className="text-lg font-medium mb-4 shrink-0">
          {editingProviderId ? '编辑 LLM Provider' : '新建 LLM Provider'}
        </h3>
        <div className="space-y-4 overflow-y-auto flex-1">
          <div>
            <label className="block text-sm font-medium mb-2 text-text-secondary">名称</label>
            <input
              value={providerForm.name}
              onChange={(e) => setProviderForm((f) => ({ ...f, name: e.target.value }))}
              type="text"
              className="w-full px-4 py-2.5 bg-bg-tertiary rounded-lg outline-none focus:ring-2 focus:ring-accent"
              placeholder="例如 DeepSeek"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-2 text-text-secondary">Base URL</label>
            <input
              value={providerForm.base_url}
              onChange={(e) => setProviderForm((f) => ({ ...f, base_url: e.target.value }))}
              type="text"
              className="w-full px-4 py-2.5 bg-bg-tertiary rounded-lg outline-none focus:ring-2 focus:ring-accent"
              placeholder="https://api.deepseek.com"
            />
            <p className="text-xs text-text-tertiary mt-1">
              /chat/completions 之前的前缀。DeepSeek: https://api.deepseek.com，OpenAI: https://api.openai.com/v1
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium mb-2 text-text-secondary">API Key</label>
            <input
              value={providerForm.api_key}
              onChange={(e) => setProviderForm((f) => ({ ...f, api_key: e.target.value }))}
              type="password"
              className="w-full px-4 py-2.5 bg-bg-tertiary rounded-lg outline-none focus:ring-2 focus:ring-accent"
              placeholder={editingProviderId ? '留空则保持不变' : '输入 API Key'}
            />
            {editingProviderId && (
              <p className="text-xs text-text-tertiary mt-1">
                当前 Key: {providerConfigs.find((p) => p.id === editingProviderId)?.api_key_preview || '未设置'}
              </p>
            )}
          </div>
          <div>
            <label className="block text-sm font-medium mb-2 text-text-secondary">默认模型</label>
            <input
              value={providerForm.default_model}
              onChange={(e) => setProviderForm((f) => ({ ...f, default_model: e.target.value }))}
              type="text"
              className="w-full px-4 py-2.5 bg-bg-tertiary rounded-lg outline-none focus:ring-2 focus:ring-accent"
              placeholder="例如 deepseek-chat"
            />
          </div>
        </div>
        <div className="flex items-center justify-between gap-3 mt-6 shrink-0">
          {editingProviderId ? (
            <button onClick={deleteProvider} className="px-4 py-2 text-danger hover:bg-danger-bg rounded-lg transition">
              删除
            </button>
          ) : (
            <span />
          )}
          <div className="flex gap-3">
            <button onClick={() => setShowProviderForm(false)} className="px-4 py-2 text-text-secondary hover:bg-bg-tertiary rounded-lg transition">
              取消
            </button>
            <button onClick={saveProvider} className="px-4 py-2 bg-accent text-white rounded-lg hover:bg-accent-hover transition">
              {editingProviderId ? '更新' : '创建'}
            </button>
          </div>
        </div>
      </Modal>
    </>
  );
}
