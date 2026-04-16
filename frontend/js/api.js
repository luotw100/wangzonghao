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
    async createConversation(robotId, title, userProfile) {
        return this.request(`${API_BASE}/conversations`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ robot_id: robotId, title: title || null, user_profile: userProfile || null })
        });
    },
    async updateConversation(convId, data) {
        return this.request(`${API_BASE}/conversations/${convId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
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
    // 消息同步（长轮询）
    // serverTimeout=0 时立即返回（短轮询），serverTimeout>0 时等待新消息
    // signal 可选，用于外部中止请求（如切换会话时取消正在进行的请求）
    async getMessages(convId, lastId, serverTimeout = 30, signal) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), serverTimeout > 0 ? 35000 : 10000);

        if (signal) {
            signal.addEventListener('abort', () => controller.abort());
        }

        try {
            const res = await fetch(
                `${API_BASE}/messages?conversation_id=${convId}&last_id=${lastId}&timeout=${serverTimeout}`,
                { signal: controller.signal }
            );
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
    }
    ,
    // --- PlannedReplies ---
    async getPlannedReplies(convId) {
        return this.request(`${API_BASE}/planned_replies?conversation_id=${convId}`, {}, 5000);
    }
};