const { createApp, ref, computed, onMounted, onUnmounted, nextTick } = Vue;

const MAX_FILE_SIZE = 5 * 1024 * 1024;

createApp({
    setup() {
        // --- 状态 ---
        const robots = ref([]);
        const conversations = ref([]);
        const activeConvId = ref(null);
        const activeConvTitle = ref("");
        const currentMessages = ref([]);
        const inputText = ref("");
        const errorMessage = ref("");

        // 侧边栏
        const sidebarOpen = ref(false);

        // Robot 管理
        const collapsedRobots = ref({});
        const showCreateRobotModal = ref(false);
        const newRobotName = ref("");
        const newRobotSystemPrompt = ref("");

        // --- 会话编辑弹窗 ---
        const editingConvTitle = ref("");
        const editingConvId = ref(null);

        // 用于判断编辑弹窗是否打开
        const isEditingConv = computed(() => editingConvId.value !== null);

        // 轮询
        let pollAbortController = null;
        let lastMsgId = 0;

        // --- 加载数据 ---
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

        // --- 侧边栏 ---
        const toggleRobot = (robotId) => {
            collapsedRobots.value[robotId] = !collapsedRobots.value[robotId];
        };

        // --- Robot CRUD ---
        const createRobot = async () => {
            const name = newRobotName.value.trim();
            if (!name) return;

            try {
                await API.createRobot({
                    name,
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

        // --- 会话 ---
        const openCreateConversationModal = (robotId) => {
            console.log('[DEBUG] openCreateConversationModal called', robotId);
            createConversation(robotId);
        };

        const createConversation = async (robotId) => {
            console.log('[DEBUG] createConversation called', robotId);
            try {
                const conv = await API.createConversation(robotId);
                console.log('[DEBUG] conv created', conv);
                await loadConversations();
                selectConversation(conv.id);
            } catch (err) {
                console.error('[DEBUG] createConversation error', err);
                errorMessage.value = "创建会话失败: " + err.message;
            }
        };

        const openEditConversationModal = (conv) => {
            console.log('[DEBUG] openEditConversationModal called', conv);
            editingConvId.value = conv.id;
            editingConvTitle.value = conv.title || "";
            console.log('[DEBUG] set editingConvTitle to', editingConvTitle.value);
        };

        const selectConversation = async (convId) => {
            stopPolling();

            activeConvId.value = convId;
            const conv = conversations.value.find(c => c.id === convId);
            activeConvTitle.value = conv ? conv.title : "新对话";
            editingConvTitle.value = "";
            editingConvId.value = null;
            errorMessage.value = "";

            currentMessages.value = [];
            lastMsgId = 0;

            startLongPolling();
        };

        // --- 长轮询 ---
        const stopPolling = () => {
            if (pollAbortController) {
                pollAbortController.abort();
                pollAbortController = null;
            }
        };

        const startLongPolling = () => {
            stopPolling();
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
                    if (!err.message.includes('超时') && !err.message.includes('abort')) {
                        errorMessage.value = "消息同步异常: " + err.message;
                    }
                    await new Promise(r => setTimeout(r, 1500));
                }
            }
        };

        // --- 发送消息 ---
        const sendTextMessage = async () => {
            const text = inputText.value.trim();
            if (!text || !activeConvId.value) return;

            inputText.value = "";
            const textarea = document.querySelector('textarea');
            if (textarea) textarea.style.height = 'auto';

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

        const handleAttachment = () => {
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = 'image/*,audio/*,video/*';
            input.onchange = (e) => handleFileUpload(e);
            input.click();
        };

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
                try {
                    await API.sendMessage({
                        conversation_id: activeConvId.value,
                        role: "user",
                        msg_type: Utils.getFileType(file.name),
                        content: e.target.result
                    });
                } catch (err) {
                    errorMessage.value = "发送文件失败: " + err.message;
                }
            };
            reader.readAsDataURL(file);
            event.target.value = "";
        };

        // --- 标题编辑 ---
        const saveEditConvTitle = async () => {
            console.log('[DEBUG] saveEditConvTitle', editingConvTitle.value, editingConvId.value);
            const title = editingConvTitle.value ? editingConvTitle.value.trim() : "";
            const convId = editingConvId.value;
            if (!title || !convId) {
                editingConvTitle.value = "";
                editingConvId.value = null;
                return;
            }

            try {
                console.log('[DEBUG] API.updateConversation', convId, title);
                await API.updateConversation(convId, title);
                errorMessage.value = "";
                editingConvTitle.value = "";
                editingConvId.value = null;
                await loadConversations();
                if (activeConvId.value === convId) {
                    activeConvTitle.value = title;
                }
            } catch (err) {
                console.error('[DEBUG] saveEditConvTitle error', err);
                editingConvTitle.value = "";
                editingConvId.value = null;
                errorMessage.value = "更新会话失败: " + err.message;
            }
        };

        // --- 辅助 ---
        const scrollToBottom = () => {
            nextTick(() => {
                const box = document.getElementById("chat-box");
                if (box) box.scrollTop = box.scrollHeight;
            });
        };

        const autoResizeTextarea = (e) => {
            const el = e.target;
            el.style.height = 'auto';
            const maxH = window.innerHeight * 0.3;
            el.style.height = Math.min(el.scrollHeight, maxH) + 'px';
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
            sidebarOpen,
            collapsedRobots, toggleRobot,
            showCreateRobotModal, newRobotName, newRobotSystemPrompt, createRobot,
            openCreateConversationModal, createConversation, selectConversation,
            openEditConversationModal,
            sendTextMessage, handleAttachment, handleFileUpload,
            editingConvTitle, editingConvId, isEditingConv, saveEditConvTitle,
            formatDate: Utils.formatDate,
            autoResizeTextarea
        };
    }
}).mount('#app');