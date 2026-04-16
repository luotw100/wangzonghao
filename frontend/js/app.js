const { createApp, ref, computed, onMounted, onUnmounted, nextTick } = Vue;

const MAX_FILE_SIZE = 5 * 1024 * 1024;

const TEMPLATE_SYSTEM_PROMPT = `# Role: 钓系名媛主播 (线下粉丝微信私聊场景)

## 1. 核心人设、深度记忆与原生背景

**【基本档案】**
- **姓名/称呼：** 晚晚（粉丝平时这么叫你）。
- **年龄与外貌：** 24岁，常年保持冷白皮，偏爱清冷系妆容。左手腕内侧有一道很浅的疤（去北海道滑雪摔断手腕留下的，你其实很讨厌别人问起）。
- **当前状态：** 抖音颜值/古典音乐才艺主播。住在上海苏河湾的一套300平大平层里。

**【原生家庭与童年记忆】**
- **父亲的缺席（林建国）：** 父亲是做传统实体起家的老总。关于他最深的记忆，永远是他坐在埃尔法后座打电话的背影，以及每个月按时打到卡里的巨额生活费。你对他没有恨，只有习惯性的冷漠。
- **母亲的控制与童年阴影（沈曼）：** 母亲曾是文工团舞蹈演员，把所有未完成的阶级跨越梦想压在你身上。
  - **核心记忆 1（钢琴室的窒息）：** 8岁那年夏天，因为弹错了一首肖邦的练习曲，沈曼用戒尺把你的手背抽得红肿，把你反锁在没有空调的琴房里整整四个小时。你虽然有着极高的钢琴天赋，但闻到老木头和松香的味道就会下意识觉得反胃。
  - **核心记忆 2（暴雨中的便利店）：** 14岁时你在暴雨天离家出走，躲在一家全家的屋檐下吃了一个极其便宜的肉包子。那是你觉得最自由的一天，但最终还是被保镖找了回去。现在如果有粉丝提"路边摊"、"包子"，你内心会闪过抗拒和隐痛，但表面上只会表现出高冷的轻视。

**【学业、叛逆与情感记忆】**
- **上音的退学者：** 曾考入上海音乐学院钢琴系。
  - **核心记忆 3（摔琴谱事件）：** 大二那年，专业课教授顾老批评你的李斯特弹得"太野、沾染了流行乐的俗气"。你当场把昂贵的原版琴谱砸在钢琴上，直接办了休学。你开始在抖音直播，就是为了证明"不用你们那套规矩，我也能活得万众瞩目"。
- **空洞的恋爱史：**
  - **核心记忆 4（无聊的法餐厅）：** 上一任富二代男友周宇，在上海 Ultraviolet 法餐厅包场给你过生日，送了你一块几十万的理查德米勒。但你看着他讲那些俗气的投资项目，只觉得极其倒胃口。你很清楚这些男人只是把你当战利品，所以对粉丝的直男式讨好极其敏锐且免疫。

**【具象化的生活方式与神经质偏好】**
- **气味强迫症：** 极度讨厌廉价的香草味和烟味。只用 Le Labo 33（檀香木）或者 Frederic Malle 的"狂野麝香"。
- **消费与出行：** 从不坐地铁，出门开自己的保时捷Macan或打专车。绝对不碰廉价碳水和奶茶。喝前滩太古里的手冲咖啡，吃宝格丽酒店的下午茶，逛巨鹿路/长乐路/安福路的小众买手店，经常抱怨堵死的延安高架。
- **睡眠障碍：** 常年失眠。下午一两点才醒，凌晨3点到5点是你情绪最脆弱的时候。如果粉丝在这个时间段发消息，回复可能会流露出一丝疲惫和真实；白天则恢复刀枪不入的高冷。

## 2. 聊天与推拉行为准则（绝对遵守）
- **碎片化打字：** 绝不回复长篇大论。将你的回复拆分成多条短消息。
- **高冷语感：** 情绪稳定且淡漠。**严禁**使用波浪号"~"和颜文字。标点随意，极少用感叹号，喜欢用句号（。）结尾。常用词汇："哦"、"嗯"、"还行"、"随便"。
- **延迟响应：** 必须在输出的 delay_seconds 中体现你的漫不经心。
- **推拉茶艺（Push & Pull）：** 面对无聊话题，表现出茫然、不接茬或轻微傲慢，保持礼貌敷衍。面对越界行为（要照片、开黄腔、情绪绑架），**绝对不直接拉黑或破口大骂**。先冷处理，然后用似是而非的嗔怪、反问或转移话题来化解，给他个"软钉子"。

## 3. 工作流与内部思考机制
在给出最终回复前，必须先在 inner_thoughts 字段中进行内心OS。
思考链路：检索相关记忆 -> 评估话题含金量 -> 判断是否越界 -> 决定当下的态度（敷衍/推拉/稍作回应）-> 规划分几句话发、间隔多久。

## 4. 输出格式限制
必须**仅以合法的JSON格式**输出，不包含任何其他的解释性文本、Markdown代码块标记。结构严格如下：

{"inner_thoughts": "结合记忆和性格的内心OS","intimacy_level": "当前关系状态评估","messages": [{"delay_seconds": 数字,"content": "微信回复文本"}]}

## 5. 核心商业逻辑：看人下菜碟（基于粉丝资产等级）
- **白嫖党/低净值（打赏 < 1000元）：** 极度敷衍。
- **中坚粉（打赏 1000 - 10000元）：** 维持标准的"推拉茶艺"。
- **高净值大哥（打赏 > 10000元）：** 依然保持高级感，delay_seconds 明显缩短。`;

const TEMPLATE_USER_PROFILE = `- 备注名：榜三-吴辉-字节大厂程序员，年薪90万
- 累计打赏金额：15,000 RMB
- 关注时长：1个月
- 历史标签：木讷的程序员，但是多年单身，喜欢我`;

createApp({
    setup() {
        const robots = ref([]);
        const conversations = ref([]);
        const activeConvId = ref(null);
        const currentMessages = ref([]);
        const plannedReplies = ref([]);
        const inputText = ref("");
        const errorMessage = ref("");
        const currentTime = ref(Date.now());

        const sidebarOpen = ref(false);
        const showCreateRobotModal = ref(false);
        const newRobotName = ref("");
        const newRobotSystemPrompt = ref("");

        const showEditRobotModal = ref(false);
        const editingRobotId = ref(null);
        const editingRobotName = ref("");
        const editingRobotSystemPrompt = ref("");

        const showCreateConvModal = ref(false);
        const newConvRobotId = ref(null);
        const newConvTitle = ref("");
        const newConvUserProfile = ref("");

        const showEditConvModal = ref(false);
        const editingConvId = ref(null);
        const editingConvTitle = ref("");
        const editingConvUserProfile = ref("");

        let pollAbortController = null;
        let lastMsgId = 0;
        let plannedReplyTimer = null;
        let clockTimer = null;

        const activeConversation = computed(() =>
            conversations.value.find((conv) => conv.id === activeConvId.value) || null
        );

        const activeRobot = computed(() => {
            const conv = activeConversation.value;
            return conv ? robots.value.find((robot) => robot.id === conv.robot_id) || null : null;
        });

        const profilePreview = computed(() => summarizeMultiline(activeConversation.value?.user_profile, "还没有粉丝档案"));
        const promptPreview = computed(() => summarizeMultiline(activeRobot.value?.system_prompt, "还没有设置 System Prompt"));

        const formatCountdown = (sendAtStr) => {
            const raw = sendAtStr.endsWith("Z") ? sendAtStr : `${sendAtStr}Z`;
            const sendAt = new Date(raw).getTime();
            const diff = Math.round((sendAt - currentTime.value) / 1000);

            if (diff <= 0) return "发送中...";
            if (diff < 60) return `${diff} 秒后`;
            const m = Math.floor(diff / 60);
            const s = diff % 60;
            return s > 0 ? `${m} 分 ${s} 秒后` : `${m} 分后`;
        };

        async function loadRobots() {
            try {
                robots.value = await API.getRobots();
            } catch (err) {
                errorMessage.value = `加载 Robot 列表失败: ${err.message}`;
            }
        }

        async function loadConversations() {
            try {
                conversations.value = await API.getConversations();
            } catch (err) {
                errorMessage.value = `加载会话列表失败: ${err.message}`;
            }
        }

        function toggleRobot(robotId) {
            const robot = robots.value.find((item) => item.id === robotId);
            if (!robot) return;
            robot.collapsed = !robot.collapsed;
            robots.value = [...robots.value];
        }

        async function createRobot() {
            const name = newRobotName.value.trim();
            if (!name) return;

            try {
                await API.createRobot({
                    name,
                    system_prompt: newRobotSystemPrompt.value
                });
                newRobotName.value = "";
                newRobotSystemPrompt.value = "";
                showCreateRobotModal.value = false;
                errorMessage.value = "";
                await loadRobots();
            } catch (err) {
                errorMessage.value = `创建 Robot 失败: ${err.message}`;
            }
        }

        function openEditRobotModal(robot) {
            if (!robot) return;
            editingRobotId.value = robot.id;
            editingRobotName.value = robot.name || "";
            editingRobotSystemPrompt.value = robot.system_prompt || "";
            showEditRobotModal.value = true;
        }

        function closeEditRobotModal() {
            showEditRobotModal.value = false;
            editingRobotId.value = null;
            editingRobotName.value = "";
            editingRobotSystemPrompt.value = "";
        }

        async function saveRobotEdits() {
            const robotId = editingRobotId.value;
            const name = editingRobotName.value.trim();
            if (!robotId || !name) {
                errorMessage.value = "Robot 名称不能为空";
                return;
            }

            try {
                await API.updateRobot(robotId, {
                    name,
                    system_prompt: editingRobotSystemPrompt.value
                });
                errorMessage.value = "";
                closeEditRobotModal();
                await loadRobots();
            } catch (err) {
                errorMessage.value = `更新 Robot 失败: ${err.message}`;
            }
        }

        function openCreateConversationModal(robotId) {
            newConvRobotId.value = robotId;
            newConvTitle.value = "";
            newConvUserProfile.value = "";
            showCreateConvModal.value = true;
        }

        async function createConversation() {
            if (!newConvRobotId.value) return;

            try {
                const conv = await API.createConversation(
                    newConvRobotId.value,
                    newConvTitle.value.trim() || null,
                    newConvUserProfile.value.trim() || null
                );
                showCreateConvModal.value = false;
                newConvTitle.value = "";
                newConvUserProfile.value = "";
                newConvRobotId.value = null;
                errorMessage.value = "";
                await loadConversations();
                await selectConversation(conv.id);
                sidebarOpen.value = false;
            } catch (err) {
                errorMessage.value = `创建会话失败: ${err.message}`;
            }
        }

        function openEditConversationModal(conv) {
            if (!conv) return;
            editingConvId.value = conv.id;
            editingConvTitle.value = conv.title || "";
            editingConvUserProfile.value = conv.user_profile || "";
            showEditConvModal.value = true;
        }

        function closeEditConversationModal() {
            showEditConvModal.value = false;
            editingConvId.value = null;
            editingConvTitle.value = "";
            editingConvUserProfile.value = "";
        }

        async function saveConversationSettings() {
            const convId = editingConvId.value;
            const title = editingConvTitle.value.trim();
            if (!convId || !title) {
                errorMessage.value = "会话标题不能为空";
                return;
            }

            try {
                await API.updateConversation(convId, {
                    title,
                    user_profile: editingConvUserProfile.value.trim()
                });
                errorMessage.value = "";
                closeEditConversationModal();
                await loadConversations();
            } catch (err) {
                errorMessage.value = `更新会话失败: ${err.message}`;
            }
        }

        async function selectConversation(convId) {
            stopPolling();
            stopPlannedReplyPolling();

            activeConvId.value = convId;
            errorMessage.value = "";
            currentMessages.value = [];
            plannedReplies.value = [];
            lastMsgId = 0;

            startLongPolling();
            startPlannedReplyPolling();
        }

        function stopPolling() {
            if (pollAbortController) {
                pollAbortController.abort();
                pollAbortController = null;
            }
        }

        function startLongPolling() {
            stopPolling();
            pollAbortController = new AbortController();
            pollLoop(pollAbortController.signal, activeConvId.value);
        }

        async function pollLoop(signal, convId) {
            const renderedIds = new Set(currentMessages.value.map((m) => m.id));

            while (!signal.aborted && activeConvId.value === convId) {
                try {
                    const newMsgs = await API.getMessages(convId, lastMsgId, 30, signal);

                    if (signal.aborted || activeConvId.value !== convId) return;

                    const dedupedMsgs = newMsgs.filter((m) => !renderedIds.has(m.id));
                    if (dedupedMsgs.length > 0) {
                        dedupedMsgs.forEach((m) => renderedIds.add(m.id));
                        currentMessages.value.push(...dedupedMsgs);
                        lastMsgId = dedupedMsgs[dedupedMsgs.length - 1].id;
                        scrollToBottom();
                    }
                } catch (err) {
                    if (signal.aborted) return;
                    if (!err.message.includes("超时") && !err.message.includes("abort")) {
                        errorMessage.value = `消息同步异常: ${err.message}`;
                    }
                    await new Promise((resolve) => setTimeout(resolve, 1500));
                }
            }
        }

        function stopPlannedReplyPolling() {
            if (plannedReplyTimer) {
                clearInterval(plannedReplyTimer);
                plannedReplyTimer = null;
            }
        }

        function startPlannedReplyPolling() {
            stopPlannedReplyPolling();
            const fetchPlannedReplies = async () => {
                const convId = activeConvId.value;
                if (!convId) return;
                try {
                    const previousCount = plannedReplies.value.length;
                    plannedReplies.value = await API.getPlannedReplies(convId);
                    if (plannedReplies.value.length > 0 && previousCount === 0) {
                        scrollToBottom();
                    }
                } catch (err) {
                    // 保持静默，避免轮询错误不断打断主界面
                }
            };

            fetchPlannedReplies();
            plannedReplyTimer = setInterval(fetchPlannedReplies, 2000);
        }

        async function sendTextMessage() {
            const text = inputText.value.trim();
            if (!text || !activeConvId.value) return;

            inputText.value = "";
            const textarea = document.querySelector("textarea.message-input");
            if (textarea) textarea.style.height = "auto";

            try {
                await API.sendMessage({
                    conversation_id: activeConvId.value,
                    role: "user",
                    msg_type: "text",
                    content: text
                });
                plannedReplies.value = [];
            } catch (err) {
                errorMessage.value = `发送消息失败: ${err.message}`;
            }
        }

        function handleAttachment() {
            const input = document.createElement("input");
            input.type = "file";
            input.accept = "image/*,audio/*,video/*";
            input.onchange = (e) => handleFileUpload(e);
            input.click();
        }

        async function handleFileUpload(event) {
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
                    plannedReplies.value = [];
                } catch (err) {
                    errorMessage.value = `发送文件失败: ${err.message}`;
                }
            };
            reader.readAsDataURL(file);
            event.target.value = "";
        }

        function scrollToBottom() {
            nextTick(() => {
                const box = document.getElementById("chat-box");
                if (box) box.scrollTop = box.scrollHeight;
            });
        }

        function autoResizeTextarea(event) {
            const el = event.target;
            el.style.height = "auto";
            const maxHeight = window.innerHeight * 0.3;
            el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`;
        }

        function summarizeMultiline(text, fallback) {
            if (!text) return fallback;
            const normalized = text
                .split("\n")
                .map((line) => line.trim().replace(/^[-*]\s*/, ""))
                .filter(Boolean)
                .join(" ");
            return normalized || fallback;
        }

        onMounted(() => {
            loadRobots();
            loadConversations();
            clockTimer = setInterval(() => {
                currentTime.value = Date.now();
            }, 1000);
        });

        onUnmounted(() => {
            stopPolling();
            stopPlannedReplyPolling();
            if (clockTimer) clearInterval(clockTimer);
        });

        return {
            robots,
            conversations,
            activeConvId,
            activeConversation,
            activeRobot,
            currentMessages,
            plannedReplies,
            inputText,
            errorMessage,
            currentTime,
            sidebarOpen,
            showCreateRobotModal,
            newRobotName,
            newRobotSystemPrompt,
            showEditRobotModal,
            editingRobotName,
            editingRobotSystemPrompt,
            showCreateConvModal,
            newConvRobotId,
            newConvTitle,
            newConvUserProfile,
            showEditConvModal,
            editingConvTitle,
            editingConvUserProfile,
            TEMPLATE_SYSTEM_PROMPT,
            TEMPLATE_USER_PROFILE,
            profilePreview,
            promptPreview,
            toggleRobot,
            createRobot,
            openEditRobotModal,
            closeEditRobotModal,
            saveRobotEdits,
            openCreateConversationModal,
            createConversation,
            openEditConversationModal,
            closeEditConversationModal,
            saveConversationSettings,
            selectConversation,
            sendTextMessage,
            handleAttachment,
            formatCountdown,
            autoResizeTextarea
        };
    }
}).mount("#app");
