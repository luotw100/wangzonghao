import { useState } from 'react';
import { Modal } from './Modal';
import * as api from '../lib/api';
import type { Session } from '../lib/api';

interface EditSessionModalProps {
  open: boolean;
  session: Session | null;
  onClose: () => void;
  onSaved: () => void;
  onError: (msg: string) => void;
}

export function EditSessionModal({ open, session, onClose, onSaved, onError }: EditSessionModalProps) {
  const [title, setTitle] = useState('');
  const [prevSessionId, setPrevSessionId] = useState<string | null>(null);
  const isDeleted = Boolean(session && session.status === 'deleted');

  if (session && session.id !== prevSessionId) {
    setPrevSessionId(session.id);
    setTitle(session.title || '');
  }

  const handleSave = async () => {
    if (!session || !title.trim()) return;
    if (isDeleted) {
      onError('已删除的 Session 不能编辑');
      return;
    }
    try {
      await api.updateSession(session.id, { title: title.trim() });
      onClose();
      onSaved();
    } catch (err: unknown) {
      onError('更新 Session 失败: ' + (err instanceof Error ? err.message : String(err)));
    }
  };

  const handleDelete = async () => {
    if (!session) return;
    try {
      await api.deleteSession(session.id);
      onClose();
      onSaved();
    } catch (err: unknown) {
      onError('删除 Session 失败: ' + (err instanceof Error ? err.message : String(err)));
    }
  };

  const handleRestore = async () => {
    if (!session) return;
    try {
      await api.restoreSession(session.id);
      onClose();
      onSaved();
    } catch (err: unknown) {
      onError('恢复 Session 失败: ' + (err instanceof Error ? err.message : String(err)));
    }
  };

  return (
    <Modal open={open} onClose={onClose}>
      <h3 className="text-lg font-medium mb-4 shrink-0">
        编辑 Session
        {isDeleted && <span className="ml-2 text-sm text-danger">（已删除）</span>}
      </h3>
      <div className="space-y-4 overflow-y-auto flex-1">
        <div>
          <label className="block text-sm font-medium mb-2 text-text-secondary">Session 标题</label>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            disabled={isDeleted}
            type="text"
            className="w-full px-4 py-2.5 bg-bg-tertiary rounded-lg outline-none focus:ring-2 focus:ring-accent disabled:opacity-60"
            onKeyUp={(e) => e.key === 'Enter' && handleSave()}
          />
        </div>
      </div>
      <div className="flex items-center justify-between gap-3 mt-5 shrink-0">
        {isDeleted ? (
          <button onClick={handleRestore} className="px-4 py-2 bg-success text-white rounded-lg hover:opacity-90 transition">
            恢复 Session
          </button>
        ) : (
          <button onClick={handleDelete} className="px-4 py-2 text-danger hover:bg-danger-bg rounded-lg transition">
            删除 Session
          </button>
        )}
        <div className="flex gap-3">
          <button onClick={onClose} className="px-4 py-2 text-text-secondary hover:bg-bg-tertiary rounded-lg transition">
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={isDeleted}
            className="px-4 py-2 bg-accent text-white rounded-lg hover:bg-accent-hover transition disabled:opacity-50"
          >
            保存
          </button>
        </div>
      </div>
    </Modal>
  );
}
