import { useState } from 'react';
import { Modal } from './Modal';
import * as api from '../lib/api';
import type { Robot } from '../lib/api';
import { TEMPLATE_SYSTEM_PROMPT } from '../lib/templates';

interface EditRobotModalProps {
  open: boolean;
  robot: Robot | null;
  onClose: () => void;
  onSaved: () => void;
  onError: (msg: string) => void;
}

export function EditRobotModal({ open, robot, onClose, onSaved, onError }: EditRobotModalProps) {
  const [name, setName] = useState('');
  const [profile, setProfile] = useState('');
  const [prevRobotId, setPrevRobotId] = useState<string | null>(null);
  const isDeleted = Boolean(robot?.is_deleted);

  if (robot && robot.id !== prevRobotId) {
    setPrevRobotId(robot.id);
    setName(robot.name || '');
    setProfile(robot.profile || '');
  }

  const handleSave = async () => {
    if (!robot || !name.trim()) return;
    if (isDeleted) {
      onError('已删除的 Robot 不能编辑，请先恢复');
      return;
    }
    try {
      await api.updateRobot(robot.id, { name: name.trim(), profile: profile.trim() || null });
      onClose();
      onSaved();
    } catch (err: unknown) {
      onError('更新 Robot 失败: ' + (err instanceof Error ? err.message : String(err)));
    }
  };

  const handleDelete = async () => {
    if (!robot) return;
    try {
      await api.deleteRobot(robot.id);
      onClose();
      onSaved();
    } catch (err: unknown) {
      onError('删除 Robot 失败: ' + (err instanceof Error ? err.message : String(err)));
    }
  };

  const handleRestore = async () => {
    if (!robot) return;
    try {
      await api.restoreRobot(robot.id);
      onClose();
      onSaved();
    } catch (err: unknown) {
      onError('恢复 Robot 失败: ' + (err instanceof Error ? err.message : String(err)));
    }
  };

  return (
    <Modal open={open} onClose={onClose} maxWidth="max-w-2xl">
      <h3 className="text-lg font-medium mb-4 shrink-0">
        编辑 Robot
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
            placeholder="输入 Robot 名称"
            onKeyUp={(e) => e.key === 'Enter' && handleSave()}
          />
        </div>
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-sm font-medium text-text-secondary">系统提示词（Profile / System Prompt）</label>
            <button
              onClick={() => setProfile(TEMPLATE_SYSTEM_PROMPT)}
              disabled={isDeleted}
              className="text-xs px-2 py-1 rounded bg-accent/10 text-accent hover:bg-accent/20 transition disabled:opacity-50"
            >
              使用晚晚模板
            </button>
          </div>
          <textarea
            value={profile}
            onChange={(e) => setProfile(e.target.value)}
            disabled={isDeleted}
            className="w-full px-4 py-2.5 bg-bg-tertiary rounded-lg outline-none focus:ring-2 focus:ring-accent font-mono text-xs disabled:opacity-60"
            rows={12}
            placeholder="定义 Robot 的角色、背景和行为规则"
          />
        </div>
      </div>
      <div className="flex items-center justify-between gap-3 mt-6 shrink-0">
        {isDeleted ? (
          <button onClick={handleRestore} className="px-4 py-2 bg-success text-white rounded-lg hover:opacity-90 transition">
            恢复 Robot
          </button>
        ) : (
          <button onClick={handleDelete} className="px-4 py-2 text-danger hover:bg-danger-bg rounded-lg transition">
            删除 Robot
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
