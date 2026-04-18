import { useState } from 'react';
import { Modal } from './Modal';
import * as api from '../lib/api';
import type { Contact } from '../lib/api';
import { CONTACT_TEMPLATES } from '../lib/templates';

interface EditContactModalProps {
  open: boolean;
  contact: Contact | null;
  onClose: () => void;
  onSaved: () => void;
  onError: (msg: string) => void;
}

export function EditContactModal({ open, contact, onClose, onSaved, onError }: EditContactModalProps) {
  const [name, setName] = useState('');
  const [profile, setProfile] = useState('');
  const [prevContactId, setPrevContactId] = useState<string | null>(null);
  const isDeleted = Boolean(contact?.is_deleted);

  if (contact && contact.id !== prevContactId) {
    setPrevContactId(contact.id);
    setName(contact.name || '');
    setProfile(contact.profile || '');
  }

  const handleSave = async () => {
    if (!contact || !name.trim()) return;
    if (isDeleted) {
      onError('已删除的联系人不能编辑，请先恢复');
      return;
    }
    try {
      await api.updateContact(contact.id, { name: name.trim(), profile: profile.trim() || null });
      onClose();
      onSaved();
    } catch (err: unknown) {
      onError('更新联系人失败: ' + (err instanceof Error ? err.message : String(err)));
    }
  };

  const handleDelete = async () => {
    if (!contact) return;
    try {
      await api.deleteContact(contact.id);
      onClose();
      onSaved();
    } catch (err: unknown) {
      onError('删除联系人失败: ' + (err instanceof Error ? err.message : String(err)));
    }
  };

  const handleRestore = async () => {
    if (!contact) return;
    try {
      await api.restoreContact(contact.id);
      onClose();
      onSaved();
    } catch (err: unknown) {
      onError('恢复联系人失败: ' + (err instanceof Error ? err.message : String(err)));
    }
  };

  return (
    <Modal open={open} onClose={onClose}>
      <h3 className="text-lg font-medium mb-4 shrink-0">
        编辑联系人
        {isDeleted && <span className="ml-2 text-sm text-danger">（已删除）</span>}
      </h3>
      <div className="space-y-4 overflow-y-auto flex-1">
        <div>
          <label className="block text-sm font-medium mb-2 text-text-secondary">名称</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={isDeleted}
            type="text"
            className="w-full px-4 py-2.5 bg-bg-tertiary rounded-lg outline-none focus:ring-2 focus:ring-accent disabled:opacity-60"
            onKeyUp={(e) => e.key === 'Enter' && handleSave()}
          />
        </div>
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-sm font-medium text-text-secondary">联系人画像 (Contact Profile)</label>
            <select
              onChange={(e) => {
                const idx = parseInt(e.target.value);
                if (!isNaN(idx) && CONTACT_TEMPLATES[idx]) {
                  setProfile(CONTACT_TEMPLATES[idx].profile);
                }
              }}
              disabled={isDeleted}
              defaultValue=""
              className="text-xs px-2 py-1 rounded bg-accent/10 text-accent hover:bg-accent/20 transition cursor-pointer disabled:opacity-50"
            >
              <option value="" disabled>选择模板</option>
              {CONTACT_TEMPLATES.map((t, i) => (
                <option key={i} value={i}>{t.name}</option>
              ))}
            </select>
          </div>
          <textarea
            value={profile}
            onChange={(e) => setProfile(e.target.value)}
            disabled={isDeleted}
            className="w-full px-4 py-2.5 bg-bg-tertiary rounded-lg outline-none focus:ring-2 focus:ring-accent text-sm disabled:opacity-60"
            rows={6}
          />
        </div>
      </div>
      <div className="flex items-center justify-between gap-3 mt-6 shrink-0">
        {isDeleted ? (
          <button onClick={handleRestore} className="px-4 py-2 bg-success text-white rounded-lg hover:opacity-90 transition">
            恢复联系人
          </button>
        ) : (
          <button onClick={handleDelete} className="px-4 py-2 text-danger hover:bg-danger-bg rounded-lg transition">
            删除联系人
          </button>
        )}
        <div className="flex gap-3">
          <button onClick={onClose} className="px-4 py-2 text-text-secondary hover:bg-bg-tertiary rounded-lg transition">
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={isDeleted}
            className="px-4 py-2 bg-accent text-bg-primary font-semibold rounded-lg hover:bg-accent-hover transition disabled:opacity-50 btn-neon"
          >
            保存
          </button>
        </div>
      </div>
    </Modal>
  );
}
