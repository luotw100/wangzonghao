const API_BASE = '/api';

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
            if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
            return await res.json();
        } catch (err) {
            clearTimeout(timeoutId);
            if (err.name === 'AbortError') {
                throw new Error('请求超时，请检查网络连接');
            }
            throw err;
        }
    },

    // --- Robots ---
    async getRobots() {
        return this.request(`${API_BASE}/robots`);
    },
    async createRobot(data) {
        return this.request(`${API_BASE}/robots`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
    },
    async updateRobot(robotId, data) {
        return this.request(`${API_BASE}/robots/${robotId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
    },

    // --- Conversations ---
    async getConversations() {
        return this.request(`${API_BASE}/conversations`);
    },
    async createConversation(robotId) {
        return this.request(`${API_BASE}/conversations`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ robot_id: robotId })
        });
    },
    async updateConversation(convId, title) {
        return this.request(`${API_BASE}/conversations/${convId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title })
        });
    },

    // --- Messages ---
    async sendMessage(payload) {
        return this.request(`${API_BASE}/messages`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
    },
    // 短轮询：立即返回现有消息
    async syncMessages(convId, lastId) {
        return this.request(`${API_BASE}/messages?conversation_id=${convId}&last_id=${lastId}`);
    },
    // 长轮询：有新消息立即返回，超时返回空
    // timeout: 客户端超时(毫秒), serverTimeout: 服务端超时(秒)
    async longPollMessages(convId, lastId, timeout = 35000, serverTimeout = 30) {
        return this.request(
            `${API_BASE}/messages/long-poll?conversation_id=${convId}&last_id=${lastId}&timeout=${serverTimeout}`,
            {},
            timeout
        );
    }
};