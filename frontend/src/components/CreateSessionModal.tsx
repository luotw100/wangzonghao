import { useState } from 'react';
import { Modal } from './Modal';
import * as api from '../lib/api';
import type { Robot, Contact, ProviderConfig } from '../lib/api';

interface CreateSessionModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: (sessionId: string) => void;
  onError: (msg: string) => void;
  activeRobots: Robot[];
  activeContacts: Contact[];
  providerConfigs: ProviderConfig[];
  defaultRobotId: string | null;
}

export function CreateSessionModal({
  open,
  onClose,
  onCreated,
  onError,
  activeRobots,
  activeContacts,
  providerConfigs,
  defaultRobotId,
}: CreateSessionModalProps) {
  const [robotId, setRobotId] = useState<string>(defaultRobotId || '');
  const [contactId, setContactId] = useState<string>('');
  const [title, setTitle] = useState('');
  const [providerId, setProviderId] = useState<string>(providerConfigs.length > 0 ? providerConfigs[0].id : '');
  const [prevDefault, setPrevDefault] = useState(defaultRobotId);

  // Reset form when modal opens with a new defaultRobotId
  if (prevDefault !== defaultRobotId) {
    setPrevDefault(defaultRobotId);
    setRobotId(defaultRobotId || '');
    setContactId('');
    setTitle('');
    setProviderId(providerConfigs.length > 0 ? providerConfigs[0].id : '');
  }

  const handleCreate = async () => {
    if (!robotId || !contactId) {
      onError('请选择 Robot 和联系人');
      return;
    }
    try {
      const session = await api.createSession({
        robot_id: robotId,
        contact_id: contactId,
        title: title.trim() || null,
        provider_config_id: providerId || null,
      });
      setRobotId('');
      setContactId('');
      setTitle('');
      onClose();
      onCreated(session.id);
    } catch (err: unknown) {
      onError('创建 Session 失败: ' + (err instanceof Error ? err.message : String(err)));
    }
  };

  return (
    <Modal open={open} onClose={onClose}>
      <h3 className="text-lg font-medium mb-4 shrink-0">新建 Session</h3>
      <div className="space-y-4 overflow-y-auto flex-1">
        <div>
          <label className="block text-sm font-medium mb-2 text-text-secondary">选择 Robot</label>
          <select
            value={robotId}
            onChange={(e) => setRobotId(e.target.value)}
            className="w-full px-4 py-2.5 bg-bg-tertiary rounded-lg outline-none focus:ring-2 focus:ring-accent"
          >
            <option value="" disabled>请选择 Robot</option>
            {activeRobots.map((r) => (
              <option key={r.id} value={r.id}>{r.name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium mb-2 text-text-secondary">选择联系人</label>
          <select
            value={contactId}
            onChange={(e) => setContactId(e.target.value)}
            className="w-full px-4 py-2.5 bg-bg-tertiary rounded-lg outline-none focus:ring-2 focus:ring-accent"
          >
            <option value="" disabled>请选择联系人</option>
            {activeContacts.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          {activeContacts.length === 0 && (
            <p className="text-xs text-text-tertiary mt-1">还没有联系人，请先创建一个</p>
          )}
        </div>
        {providerConfigs.length > 0 && (
          <div>
            <label className="block text-sm font-medium mb-2 text-text-secondary">LLM Provider</label>
            <select
              value={providerId}
              onChange={(e) => setProviderId(e.target.value)}
              className="w-full px-4 py-2.5 bg-bg-tertiary rounded-lg outline-none focus:ring-2 focus:ring-accent"
            >
              <option value="">不指定（自动选择）</option>
              {providerConfigs.map((p) => (
                <option key={p.id} value={p.id}>{p.name} — {p.default_model}</option>
              ))}
            </select>
          </div>
        )}
        <div>
          <label className="block text-sm font-medium mb-2 text-text-secondary">Session 标题（可选）</label>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            type="text"
            className="w-full px-4 py-2.5 bg-bg-tertiary rounded-lg outline-none focus:ring-2 focus:ring-accent"
            placeholder="留空则自动生成"
          />
        </div>
      </div>
      <div className="flex justify-end gap-3 mt-6 shrink-0">
        <button onClick={onClose} className="px-4 py-2 text-text-secondary hover:bg-bg-tertiary rounded-lg transition">
          取消
        </button>
        <button onClick={handleCreate} className="px-4 py-2 bg-accent text-white rounded-lg hover:bg-accent-hover transition">
          创建
        </button>
      </div>
    </Modal>
  );
}
