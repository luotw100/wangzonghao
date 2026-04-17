const CHAT_BASE = '/api';
const ROBOT_BASE = '/api/robot';

const API = {
    // 通用请求封装，支持超时
    async request(url, options = {}, timeout = 10000) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeout);

        try {
            const res = await fetch(url, {
                ...options,
                signal: controller.signal
            });
            clearTimeout(timeoutId);
            if (!res.ok) {
                let detail = `HTTP ${res.status}`;
                try {
                    const body = await res.json();
                    if (body && body.detail) detail = body.detail;
                } catch (_) { /* ignore */ }
                throw new Error(detail);
            }
            const text = await res.text();
            return text ? JSON.parse(text) : null;
        } catch (err) {
            clearTimeout(timeoutId);
            if (err.name === 'AbortError') {
                throw new Error('请求超时，请检查网络连接');
            }
            throw err;
        }
    },

    // --- Robots ---
    async getRobots(includeDeleted = false) {
        const query = includeDeleted ? '?include_deleted=true' : '';
        return this.request(`${ROBOT_BASE}/robots${query}`);
    },
    async createRobot(data) {
        return this.request(`${ROBOT_BASE}/robots`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
    },
    async updateRobot(robotId, data) {
        return this.request(`${ROBOT_BASE}/robots/${robotId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
    },
    async deleteRobot(robotId) {
        return this.request(`${ROBOT_BASE}/robots/${robotId}`, { method: 'DELETE' });
    },
    async restoreRobot(robotId) {
        return this.request(`${ROBOT_BASE}/robots/${robotId}/restore`, { method: 'POST' });
    },

    // --- Contacts ---
    async getContacts(includeDeleted = false) {
        const query = includeDeleted ? '?include_deleted=true' : '';
        return this.request(`${ROBOT_BASE}/contacts${query}`);
    },
    async createContact(data) {
        return this.request(`${ROBOT_BASE}/contacts`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
    },
    async updateContact(contactId, data) {
        return this.request(`${ROBOT_BASE}/contacts/${contactId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
    },
    async deleteContact(contactId) {
        return this.request(`${ROBOT_BASE}/contacts/${contactId}`, { method: 'DELETE' });
    },
    async restoreContact(contactId) {
        return this.request(`${ROBOT_BASE}/contacts/${contactId}/restore`, { method: 'POST' });
    },

    // --- Provider Configs ---
    async getProviderConfigs() {
        return this.request(`${ROBOT_BASE}/provider-configs`);
    },
    async createProviderConfig(data) {
        return this.request(`${ROBOT_BASE}/provider-configs`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
    },
    async updateProviderConfig(id, data) {
        return this.request(`${ROBOT_BASE}/provider-configs/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
    },
    async deleteProviderConfig(id) {
        return this.request(`${ROBOT_BASE}/provider-configs/${id}`, { method: 'DELETE' });
    },

    // --- Sessions ---
    async getSessions(includeDeleted = false) {
        const query = includeDeleted ? '?include_deleted=true' : '';
        return this.request(`${ROBOT_BASE}/sessions${query}`);
    },
    async createSession(data) {
        return this.request(`${ROBOT_BASE}/sessions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
    },
    async getSession(sessionId) {
        return this.request(`${ROBOT_BASE}/sessions/${sessionId}?include_deleted=true`);
    },
    async updateSession(sessionId, data) {
        return this.request(`${ROBOT_BASE}/sessions/${sessionId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
    },
    async deleteSession(sessionId) {
        return this.request(`${ROBOT_BASE}/sessions/${sessionId}`, { method: 'DELETE' });
    },
    async restoreSession(sessionId) {
        return this.request(`${ROBOT_BASE}/sessions/${sessionId}/restore`, { method: 'POST' });
    },
    async getReplyPlans(sessionId) {
        return this.request(`${ROBOT_BASE}/sessions/${sessionId}/reply-plans`, {}, 5000);
    },

    // --- Messages (direct to Chat API via conversation_id) ---
    async sendMessage(conversationId, payload) {
        return this.request(`${CHAT_BASE}/conversations/${conversationId}/messages`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
    },

    // 消息同步（长轮询）
    async getMessages(conversationId, lastId, serverTimeout = 30, signal) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), serverTimeout > 0 ? 35000 : 10000);

        if (signal) {
            signal.addEventListener('abort', () => controller.abort());
        }

        try {
            const res = await fetch(
                `${CHAT_BASE}/conversations/${conversationId}/messages?last_id=${lastId}&timeout=${serverTimeout}`,
                { signal: controller.signal }
            );
            clearTimeout(timeoutId);
            if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
            const payload = await res.json();
            return payload.messages || [];
        } catch (err) {
            clearTimeout(timeoutId);
            if (err.name === 'AbortError') {
                throw new Error('请求超时，请检查网络连接');
            }
            throw err;
        }
    }
};
