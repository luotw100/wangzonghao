import { useState } from 'react';
import { Modal } from './Modal';
import * as api from '../lib/api';
import { TEMPLATE_SYSTEM_PROMPT } from '../lib/templates';

interface CreateRobotModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
  onError: (msg: string) => void;
}

export function CreateRobotModal({ open, onClose, onCreated, onError }: CreateRobotModalProps) {
  const [name, setName] = useState('');
  const [profile, setProfile] = useState('');

  const handleCreate = async () => {
    if (!name.trim()) return;
    try {
      await api.createRobot({ name: name.trim(), profile: profile.trim() || null });
      setName('');
      setProfile('');
      onClose();
      onCreated();
    } catch (err: unknown) {
      onError('创建 Robot 失败: ' + (err instanceof Error ? err.message : String(err)));
    }
  };

  return (
    <Modal open={open} onClose={onClose} maxWidth="max-w-2xl">
      <h3 className="text-lg font-medium mb-4 shrink-0">新建 Robot</h3>
      <div className="space-y-4 overflow-y-auto flex-1">
        <div>
          <label className="block text-sm font-medium mb-2 text-text-secondary">名称</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            type="text"
            className="w-full px-4 py-2.5 bg-bg-tertiary rounded-lg outline-none focus:ring-2 focus:ring-accent"
            placeholder="输入 Robot 名称"
            onKeyUp={(e) => e.key === 'Enter' && handleCreate()}
          />
        </div>
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-sm font-medium text-text-secondary">系统提示词（Profile / System Prompt）</label>
            <button
              onClick={() => setProfile(TEMPLATE_SYSTEM_PROMPT)}
              className="text-xs px-2 py-1 rounded bg-[#e8f0fe] text-accent hover:bg-[#d2e3fc] transition"
            >
              使用晚晚模板
            </button>
          </div>
          <textarea
            value={profile}
            onChange={(e) => setProfile(e.target.value)}
            className="w-full px-4 py-2.5 bg-bg-tertiary rounded-lg outline-none focus:ring-2 focus:ring-accent font-mono text-xs"
            rows={12}
            placeholder="定义 Robot 的角色、背景和行为规则"
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
