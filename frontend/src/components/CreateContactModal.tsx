import { useState } from 'react';
import { Modal } from './Modal';
import * as api from '../lib/api';
import { TEMPLATE_CONTACT_PROFILE } from '../lib/templates';

interface CreateContactModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
  onError: (msg: string) => void;
}

export function CreateContactModal({ open, onClose, onCreated, onError }: CreateContactModalProps) {
  const [name, setName] = useState('');
  const [profile, setProfile] = useState('');

  const handleCreate = async () => {
    if (!name.trim()) return;
    try {
      await api.createContact({ name: name.trim(), profile: profile.trim() || null });
      setName('');
      setProfile('');
      onClose();
      onCreated();
    } catch (err: unknown) {
      onError('创建联系人失败: ' + (err instanceof Error ? err.message : String(err)));
    }
  };

  return (
    <Modal open={open} onClose={onClose}>
      <h3 className="text-lg font-medium mb-4 shrink-0">新建联系人</h3>
      <div className="space-y-4 overflow-y-auto flex-1">
        <div>
          <label className="block text-sm font-medium mb-2 text-text-secondary">名称</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            type="text"
            className="w-full px-4 py-2.5 bg-bg-tertiary rounded-lg outline-none focus:ring-2 focus:ring-accent"
            placeholder="输入联系人名称"
            onKeyUp={(e) => e.key === 'Enter' && handleCreate()}
          />
        </div>
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-sm font-medium text-text-secondary">联系人画像 (Contact Profile)</label>
            <button
              onClick={() => setProfile(TEMPLATE_CONTACT_PROFILE)}
              className="text-xs px-2 py-1 rounded bg-[#e8f0fe] text-accent hover:bg-[#d2e3fc] transition"
            >
              使用示例模板
            </button>
          </div>
          <textarea
            value={profile}
            onChange={(e) => setProfile(e.target.value)}
            className="w-full px-4 py-2.5 bg-bg-tertiary rounded-lg outline-none focus:ring-2 focus:ring-accent text-sm"
            rows={6}
            placeholder={'- 备注名：XXX\n- 累计打赏金额：XXX RMB\n- 关注时长：X个月\n- 历史标签：XXX'}
          />
          <p className="text-xs text-text-tertiary mt-1">
            联系人画像会附加到 System Prompt 末尾，帮助 Robot 了解对话对象
          </p>
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
