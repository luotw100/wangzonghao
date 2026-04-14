const { createApp, ref, computed, onMounted, onUnmounted, nextTick } = Vue;

// 文件大小限制：5MB
const MAX_FILE_SIZE = 5 * 1024 * 1024;

createApp({
    setup() {
        // --- 响应式状态 ---
        const robots = ref([]);
        const conversations = ref([]);
        const activeConvId = ref(null);
        const activeConvTitle = ref("");
        const currentMessages = ref([]);
        const inputText = ref("");
        const errorMessage = ref("");

        // Robot 模态框
        const showCreateRobotModal = ref(false);
        const newRobotName = ref("");
        const newRobotSystemPrompt = ref("");

        // 轮询控制标志 & 最后一条消息ID
        let isPolling = false;
        let lastMsgId = 0;

        // --- 初始化加载 ---
        const loadRobots = async () => {
            try {
                robots.value = await API.getRobots();
            } catch (err) {
                errorMessage.value = "加载 Robot 列表失败: " + err.message;
            }
        };

        const loadConversations = async () => {
            try {
                conversations.value = await API.getConversations();
            } catch (err) {
                errorMessage.value = "加载会话列表失败: " + err.message;
            }
        };

        // --- 创建 Robot ---
        const createRobot = async () => {
            const name = newRobotName.value.trim();
            if (!name) {
                errorMessage.value = "请输入 Robot 名称";
                return;
            }

            try {
                await API.createRobot({
                    name: name,
                    system_prompt: newRobotSystemPrompt.value.trim() || null
                });
                // 成功后重置表单并关闭弹窗
                newRobotName.value = "";
                newRobotSystemPrompt.value = "";
                showCreateRobotModal.value = false;
                errorMessage.value = "";
                // 重新加载 Robot 列表
                await loadRobots();
            } catch (err) {
                errorMessage.value = "创建 Robot 失败: " + err.message;
            }
        };

        // --- 创建会话 ---
        const createConversation = async (robotId) => {
            try {
                const conv = await API.createConversation(robotId);
                await loadConversations();
                // 自动选中新创建的会话
                selectConversation(conv.id);
            } catch (err) {
                errorMessage.value = "创建会话失败: " + err.message;
            }
        };

        // --- 选择会话 & 启动长轮询 ---
        const selectConversation = async (convId) => {
            // 停止之前的长轮询
            stopPolling();

            activeConvId.value = convId;
            const conv = conversations.value.find(c => c.id === convId);
            activeConvTitle.value = conv ? conv.title : "聊天";
            errorMessage.value = "";

            // 清空当前消息并重置游标
            currentMessages.value = [];
            lastMsgId = 0;

            // 短轮询立即获取历史消息
            await pollNewMessages();
            // 开启长轮询持续监听新消息
            startLongPolling();
        };

        // --- 长轮询控制 ---
        const startLongPolling = () => {
            isPolling = true;
            pollLoop();
        };

        const stopPolling = () => {
            isPolling = false;
        };

        // --- 长轮询循环 ---
        const pollLoop = async () => {
            if (!isPolling || !activeConvId.value) return;

            try {
                const newMsgs = await API.longPollMessages(activeConvId.value, lastMsgId, 30);
                if (!isPolling || !activeConvId.value) return;

                if (newMsgs.length > 0) {
                    currentMessages.value.push(...newMsgs);
                    lastMsgId = newMsgs[newMsgs.length - 1].id;
                    scrollToBottom();
                }

                // 继续下一次长轮询
                pollLoop();
            } catch (err) {
                console.error("长轮询异常", err);
                errorMessage.value = "消息同步异常: " + err.message;
                // 异常后等待一下再重试
                if (isPolling && activeConvId.value) {
                    await new Promise(r => setTimeout(r, 1000));
                    pollLoop();
                }
            }
        };

        // --- 短轮询：立即获取现有消息 ---
        const pollNewMessages = async () => {
            if (!activeConvId.value) return;
            try {
                const newMsgs = await API.syncMessages(activeConvId.value, lastMsgId);
                if (newMsgs.length > 0) {
                    currentMessages.value.push(...newMsgs);
                    lastMsgId = newMsgs[newMsgs.length - 1].id;
                    scrollToBottom();
                }
            } catch (err) {
                console.error("拉取消息失败", err);
            }
        };

        // --- 发送文本 ---
        const sendTextMessage = async () => {
            const text = inputText.value.trim();
            if (!text || !activeConvId.value) return;

            inputText.value = "";

            // 乐观更新：先在本地添加一条临时消息
            const tempId = 'temp-' + Date.now();
            const tempMsg = {
                id: tempId,
                role: 'user',
                msg_type: 'text',
                content: text,
                created_at: new Date().toISOString()
            };
            currentMessages.value.push(tempMsg);
            scrollToBottom();

            try {
                await API.sendMessage({
                    conversation_id: activeConvId.value,
                    role: "user",
                    msg_type: "text",
                    content: text
                });
                // 发送成功后，移除临时消息，用短轮询立即获取真实消息
                currentMessages.value = currentMessages.value.filter(m => m.id !== tempId);
                // 更新 lastMsgId
                lastMsgId = Math.max(lastMsgId, ...currentMessages.value.map(m => m.id || 0));
                // 短轮询立即获取（不等长轮询）
                await pollNewMessages();
            } catch (err) {
                // 发送失败，移除临时消息并显示错误
                currentMessages.value = currentMessages.value.filter(m => m.id !== tempId);
                errorMessage.value = "发送消息失败: " + err.message;
            }
        };

        // --- 发送图片 (转 Base64) ---
        const handleFileUpload = async (event) => {
            const file = event.target.files[0];
            if (!file) return;

            if (!activeConvId.value) {
                errorMessage.value = "请先选择一个会话";
                event.target.value = "";
                return;
            }

            // 文件大小检查
            if (file.size > MAX_FILE_SIZE) {
                errorMessage.value = `文件大小不能超过 ${MAX_FILE_SIZE / 1024 / 1024}MB`;
                event.target.value = "";
                return;
            }

            const reader = new FileReader();
            reader.onload = async (e) => {
                const base64Data = e.target.result;

                // 乐观更新
                const tempId = 'temp-' + Date.now();
                const tempMsg = {
                    id: tempId,
                    role: 'user',
                    msg_type: Utils.getFileType(file.name),
                    content: base64Data,
                    created_at: new Date().toISOString()
                };
                currentMessages.value.push(tempMsg);
                scrollToBottom();

                try {
                    await API.sendMessage({
                        conversation_id: activeConvId.value,
                        role: "user",
                        msg_type: Utils.getFileType(file.name),
                        content: base64Data
                    });
                    currentMessages.value = currentMessages.value.filter(m => m.id !== tempId);
                    lastMsgId = Math.max(lastMsgId, ...currentMessages.value.map(m => m.id || 0));
                    await pollNewMessages();
                } catch (err) {
                    currentMessages.value = currentMessages.value.filter(m => m.id !== tempId);
                    errorMessage.value = "发送文件失败: " + err.message;
                }
            };
            reader.readAsDataURL(file);
            event.target.value = "";
        };

        // --- 辅助方法 ---
        const scrollToBottom = () => {
            nextTick(() => {
                const box = document.getElementById("chat-box");
                if (!box) {
                    console.warn("scrollToBottom: #chat-box not found");
                    return;
                }
                box.scrollTop = box.scrollHeight;
            });
        };

        // 使用相对路径，避免硬编码
        const getFullUrl = (path) => {
            if (!path) return '';
            if (path.startsWith('http')) return path;
            return path;
        };

        // XSS 防护：对文本内容进行转义
        const escapeHtml = (text) => {
            if (!text) return '';
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        };

        // 生命周期挂载
        onMounted(() => {
            loadRobots();
            loadConversations();
        });

        // 页面卸载前清理
        onUnmounted(() => {
            stopPolling();
        });

        return {
            // 状态
            robots, conversations, activeConvId, activeConvTitle, currentMessages, inputText, errorMessage,
            showCreateRobotModal, newRobotName, newRobotSystemPrompt,
            // 方法
            selectConversation, sendTextMessage, handleFileUpload,
            createRobot, createConversation,
            formatDate: Utils.formatDate,
            getFullUrl,
            escapeHtml
        };
    }
}).mount('#app');