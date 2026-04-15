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

        // Robot 折叠状态
        const collapsedRobots = ref({});

        // 创建 Robot 模态框
        const showCreateRobotModal = ref(false);
        const newRobotName = ref("");
        const newRobotSystemPrompt = ref("");

        // 编辑 Robot 模态框
        const showEditRobotModal = ref(false);
        const editingRobot = ref({ id: null, name: "", system_prompt: "" });

        // 会话标题内联编辑
        const editingConvTitle = ref(null);

        // 轮询控制标志 & 最后一条消息ID
        let pollAbortController = null;
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

        // --- Robot 折叠 ---
        const toggleRobot = (robotId) => {
            collapsedRobots.value[robotId] = !collapsedRobots.value[robotId];
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
                newRobotName.value = "";
                newRobotSystemPrompt.value = "";
                showCreateRobotModal.value = false;
                errorMessage.value = "";
                await loadRobots();
            } catch (err) {
                errorMessage.value = "创建 Robot 失败: " + err.message;
            }
        };

        // --- 编辑 Robot ---
        const openEditRobotModal = (robot) => {
            editingRobot.value = {
                id: robot.id,
                name: robot.name,
                system_prompt: robot.system_prompt || ""
            };
            showEditRobotModal.value = true;
        };

        const saveEditRobot = async () => {
            const name = editingRobot.value.name.trim();
            if (!name) {
                errorMessage.value = "请输入 Robot 名称";
                return;
            }

            try {
                await API.updateRobot(editingRobot.value.id, {
                    name: name,
                    system_prompt: editingRobot.value.system_prompt.trim() || null
                });
                showEditRobotModal.value = false;
                errorMessage.value = "";
                await loadRobots();
            } catch (err) {
                errorMessage.value = "更新 Robot 失败: " + err.message;
            }
        };

        // --- 编辑会话名称（内联编辑） ---
        const startEditConvTitle = () => {
            editingConvTitle.value = activeConvTitle.value;
        };

        const saveEditConvTitle = async () => {
            if (editingConvTitle.value === null) return;

            const title = editingConvTitle.value.trim();
            if (!title) {
                editingConvTitle.value = null;
                return;
            }

            try {
                await API.updateConversation(activeConvId.value, title);
                activeConvTitle.value = title;
                editingConvTitle.value = null;
                errorMessage.value = "";
                await loadConversations();
            } catch (err) {
                errorMessage.value = "更新会话失败: " + err.message;
                editingConvTitle.value = null;
            }
        };

        // --- 创建会话 ---
        const createConversation = async (robotId) => {
            try {
                const conv = await API.createConversation(robotId);
                await loadConversations();
                selectConversation(conv.id);
            } catch (err) {
                errorMessage.value = "创建会话失败: " + err.message;
            }
        };

        // --- 选择会话 & 启动长轮询 ---
        const selectConversation = async (convId) => {
            stopPolling();

            activeConvId.value = convId;
            const conv = conversations.value.find(c => c.id === convId);
            activeConvTitle.value = conv ? conv.title : "聊天";
            editingConvTitle.value = null;
            errorMessage.value = "";

            currentMessages.value = [];
            lastMsgId = 0;

            startLongPolling();
        };

        // --- 长轮询控制 ---
        const stopPolling = () => {
            if (pollAbortController) {
                pollAbortController.abort();
                pollAbortController = null;
            }
        };

        const startLongPolling = () => {
            stopPolling(); // ensure no existing loop before starting
            pollAbortController = new AbortController();
            pollLoop(pollAbortController.signal, activeConvId.value);
        };

        const pollLoop = async (signal, convId) => {
            const renderedIds = new Set(currentMessages.value.map(m => m.id));

            while (!signal.aborted && activeConvId.value === convId) {
                try {
                    const newMsgs = await API.getMessages(convId, lastMsgId, 30, signal);

                    if (signal.aborted || activeConvId.value !== convId) return;

                    const dedupedMsgs = newMsgs.filter(m => !renderedIds.has(m.id));
                    if (dedupedMsgs.length > 0) {
                        dedupedMsgs.forEach(m => renderedIds.add(m.id));
                        currentMessages.value.push(...dedupedMsgs);
                        lastMsgId = dedupedMsgs[dedupedMsgs.length - 1].id;
                        scrollToBottom();
                    }
                } catch (err) {
                    if (signal.aborted) return;
                    console.error("长轮询异常", err);
                    if (!err.message.includes('超时') && !err.message.includes('abort')) {
                        errorMessage.value = "消息同步异常: " + err.message;
                    }
                    // back-off before retry
                    await new Promise(r => setTimeout(r, 1500));
                }
            }
        };

        // --- 发送文本 ---
        const sendTextMessage = async () => {
            const text = inputText.value.trim();
            if (!text || !activeConvId.value) return;

            inputText.value = "";

            try {
                await API.sendMessage({
                    conversation_id: activeConvId.value,
                    role: "user",
                    msg_type: "text",
                    content: text
                });
            } catch (err) {
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

            if (file.size > MAX_FILE_SIZE) {
                errorMessage.value = `文件大小不能超过 ${MAX_FILE_SIZE / 1024 / 1024}MB`;
                event.target.value = "";
                return;
            }

            const reader = new FileReader();
            reader.onload = async (e) => {
                const base64Data = e.target.result;

                try {
                    await API.sendMessage({
                        conversation_id: activeConvId.value,
                        role: "user",
                        msg_type: Utils.getFileType(file.name),
                        content: base64Data
                    });
                } catch (err) {
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

        const getFullUrl = (path) => {
            if (!path) return '';
            if (path.startsWith('http')) return path;
            return path;
        };

        const escapeHtml = (text) => {
            if (!text) return '';
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        };

        onMounted(() => {
            loadRobots();
            loadConversations();
        });

        onUnmounted(() => {
            stopPolling();
        });

        return {
            robots, conversations, activeConvId, activeConvTitle, currentMessages, inputText, errorMessage,
            collapsedRobots, toggleRobot,
            showCreateRobotModal, newRobotName, newRobotSystemPrompt,
            showEditRobotModal, editingRobot,
            editingConvTitle,
            selectConversation, sendTextMessage, handleFileUpload,
            createRobot, createConversation, openEditRobotModal, saveEditRobot,
            startEditConvTitle, saveEditConvTitle,
            formatDate: Utils.formatDate,
            getFullUrl,
            escapeHtml
        };
    }
}).mount('#app');