// 工具函数集合

const Utils = {
    /**
     * 格式化日期时间
     * @param {string} dateStr - ISO 格式的日期字符串
     * @returns {string} 格式化后的字符串
     */
    formatDate(dateStr) {
        if (!dateStr) return '';

        const date = new Date(dateStr);
        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const yesterday = new Date(today.getTime() - 24 * 60 * 60 * 1000);

        const targetDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());

        // 今天显示时间
        if (targetDate.getTime() === today.getTime()) {
            return Utils.formatTime(date);
        }

        // 昨天显示 "昨天"
        if (targetDate.getTime() === yesterday.getTime()) {
            return '昨天 ' + Utils.formatTime(date);
        }

        // 今年显示 "月-日"
        if (date.getFullYear() === now.getFullYear()) {
            return `${date.getMonth() + 1}-${date.getDate()} ${this.formatTime(date)}`;
        }

        // 其他显示完整日期
        return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;
    },

    /**
     * 格式化时间 HH:MM
     */
    formatTime(date) {
        const hours = String(date.getHours()).padStart(2, '0');
        const minutes = String(date.getMinutes()).padStart(2, '0');
        return `${hours}:${minutes}`;
    },

    /**
     * 获取相对时间（如 "3分钟前"）
     */
    timeAgo(dateStr) {
        if (!dateStr) return '';

        const date = new Date(dateStr);
        const now = new Date();
        const diff = Math.floor((now - date) / 1000);

        if (diff < 60) return '刚刚';
        if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`;
        if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
        if (diff < 604800) return `${Math.floor(diff / 86400)}天前`;

        return this.formatDate(dateStr);
    },

    /**
     * 生成唯一ID
     */
    generateId() {
        return Date.now().toString(36) + Math.random().toString(36).substr(2);
    },

    /**
     * 文件大小格式化
     */
    formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    },

    /**
     * 获取文件类型
     */
    getFileType(filename) {
        const ext = filename.split('.').pop().toLowerCase();
        const imageExts = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'];
        const audioExts = ['mp3', 'wav', 'ogg', 'm4a', 'aac'];
        const videoExts = ['mp4', 'webm', 'avi', 'mov', 'mkv'];

        if (imageExts.includes(ext)) return 'image';
        if (audioExts.includes(ext)) return 'audio';
        if (videoExts.includes(ext)) return 'video';
        return 'file';
    },

    /**
     * 防抖函数
     */
    debounce(fn, delay = 300) {
        let timer = null;
        return function (...args) {
            if (timer) clearTimeout(timer);
            timer = setTimeout(() => fn.apply(this, args), delay);
        };
    },

    /**
     * 节流函数
     */
    throttle(fn, delay = 300) {
        let last = 0;
        return function (...args) {
            const now = Date.now();
            if (now - last >= delay) {
                last = now;
                fn.apply(this, args);
            }
        };
    },

    /**
     * HTML 转义（防止 XSS）
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};

// 导出给全局使用
window.Utils = Utils;