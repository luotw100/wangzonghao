#!/usr/bin/env python3
"""misc/seed_chats/generate.py — emit ChatLab JSON for Chat 导入测试.

15 个私聊文件 = 5 个主播 × 每人 3 个粉丝。产物在 misc/seed_chats/out/，
既可手动拖进 Chat「导入聊天记录」，也会被 scripts/seed_dev.py 自动导入
（owner 已设为主播本人 = 导入时的「我」）。

消息量：老粉 300+、中粉 80-150、新粉 30-50。
时间回溯：基于当前 2026-05-18 往前倒推（老粉跨越数月，新粉近期）。
"""

from __future__ import annotations

import calendar
import json
import random
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"
NOW = datetime(2026, 5, 18, tzinfo=timezone.utc)

random.seed(42)  # 可重复


def ts(s: str) -> int:
    """'YYYY-MM-DD HH:MM' -> unix 秒（按 UTC 解析）。"""
    return calendar.timegm(
        (int(s[0:4]), int(s[5:7]), int(s[8:10]), int(s[11:13]), int(s[14:16]), 0, 0, 0, 0)
    )


@dataclass
class Speaker:
    username: str
    display: str
    style: str


@dataclass
class Fan:
    fid: str
    name: str
    account: str
    platform: str
    profile: str
    days_ago: int
    msg_count: int
    freq: str


def gen_msgs(s_name: str, f_name: str, s_style_key: str, f_type: str, count: int) -> list[tuple[str, str]]:
    """
    生成 count 条消息。
    s_style_key: "lxm"|"stg"|"cf"|"dz"|"zq" (主播风格)
    f_type: "老粉"|"中粉"|"新粉" (粉丝类型)
    """
    # 每个主播的风格消息库
    style_msgs = {
        "lxm": {  # 林小漫 - 温柔撒娇
            "送": ["呀，{f}来了呀 ~", "你来了我就开心了 (´;ω;`)", "宝，想你了 ♡",
                   "欢迎欢迎 ~ 今天也来陪我吗", "你的到来让我整个直播间都亮了起来"],
            "应": ["宝你好呀", "小漫晚上好", "来看你唱歌了", "你今天好漂亮", "好想听你的歌"],
            "互": ["你怎么这么乖呀", "跟你聊天真舒服", "你有什么烦恼吗", "好好生活哦宝",
                   "记得吃早饭呀 ♡", "睡个好觉 ♡", "拉钩约好了", "爱你 ~"],
            "别": ["我要准备了", "下一场等你", "拜拜宝 ~ ♡", "晚安宝，做好梦"],
        },
        "stg": {  # 苏糖 - 东北直爽
            "送": ["哎呦，{f}来啦", "你这小子咋样啊", "怎么样，最近咋地啊",
                   "又来蹭我直播呢", "来了来了，我都看到了"],
            "应": ["苏糖好", "姐好呀", "你今天状态不错", "给我来一个新舞蹈吧",
                   "你这体力真好", "哈哈你逗我呢"],
            "互": ["你别调戏我", "你这张嘴啊", "我才不信你的", "都跟你说过多少遍了",
                   "好好生活你", "别整天泡直播间", "身体最重要", "下次继续"],
            "别": ["我得去忙了", "拜拜，好好照顾自己", "晚安，睡吧", "下次见啊"],
        },
        "cf": {  # 陈锋 - 高冷术语
            "送": ["嗯", "怎么样", "又来了", "今天有问题吗", "看什么呢"],
            "应": ["锋哥", "你在吗", "这把怎么样", "给点建议呗", "你咋这么强"],
            "互": ["意识有问题", "操作不稳定", "这个想法不错", "继续加油",
                   "别放弃", "有前景", "多看回放", "好，继续练"],
            "别": ["继续加油", "回去练吧", "别在这扯了", "行了，下次见"],
        },
        "dz": {  # 大壮 - 逗比玩梗
            "送": ["哈哈哈哈", "又来了你", "这把典不典", "笑死我了",
                   "你这也太逗了", "我们继续整活"],
            "应": ["壮哥", "你又出事了", "这谁啊", "哈人哈人", "典了典了",
                   "你可真会吹", "我不信"],
            "互": ["逗你玩呢", "你就是我的小棉袄", "爱你们啊", "继续整活",
                   "再来一把", "别走啊", "陪我聊会儿", "感谢支持"],
            "别": ["好了拜拜", "下次见哈", "晚安各位", "继续打游戏去"],
        },
        "zq": {  # 周晴 - 销售话术
            "送": ["您好，有什么问题吗", "请问您需要什么帮助", "我给您介绍一下",
                   "这个方案怎么样", "您考虑得怎么样"],
            "应": ["周经理你好", "价格怎么样", "还有优惠吗", "什么时候有车",
                   "我想看看"],
            "互": ["您可以考虑", "我们有多个方案", "您这个想法很好",
                   "我给您详细讲解", "这个是标准的", "您放心", "我会跟进"],
            "别": ["好的，下周见", "再联系您", "祝您愉快", "期待您的决定"],
        },
    }

    msgs = style_msgs.get(s_style_key, style_msgs["cf"])  # 默认高冷
    result = []

    # 生成来回对话，保证 count 条
    phases = ["送", "应", "互", "别"]
    while len(result) < count:
        phase = random.choice(phases)
        pool = msgs.get(phase, msgs["互"])
        text = random.choice(pool)
        text = text.format(f=f_name, s=s_name)

        # S 和 F 交替
        if len(result) % 2 == 0:
            result.append(("S", text))
        else:
            result.append(("F", text))

    return result[:count]


def build_conversation(speaker: Speaker, fan: Fan) -> tuple[dict, int]:
    """生成一段对话 ChatLab JSON。"""
    start_ts = int((NOW - timedelta(days=fan.days_ago)).timestamp())

    # 生成消息
    style_map = {
        "linxiaoman": "lxm", "sutang": "stg", "chenfeng": "cf", "dazhuang": "dz", "zhouqing": "zq"
    }
    style_key = style_map.get(speaker.username, "cf")

    msgs = gen_msgs(speaker.display, fan.name, style_key, fan.freq, fan.msg_count)

    # 分配时间戳（消息均匀散布在 [start_ts, NOW]）
    total_secs = int((NOW.timestamp()) - start_ts)
    gap = total_secs // max(1, len(msgs) - 1) if len(msgs) > 1 else 3600

    current_ts = start_ts
    messages = []
    for role, text in msgs:
        messages.append({
            "sender": speaker.username if role == "S" else fan.fid,
            "timestamp": int(current_ts),
            "type": 0,
            "content": text,
        })
        # 加随机性避免完全均匀
        current_ts += gap + random.randint(-gap // 4, gap // 4)

    doc = {
        "chatlab": {"version": "1.0", "exportedAt": int(NOW.timestamp())},
        "meta": {
            "name": f"{fan.name}（与{speaker.display}）",
            "platform": fan.platform,
            "type": "private",
            "ownerId": speaker.username,
            "_streamerStyle": speaker.style,
            "_fanProfile": fan.profile,
        },
        "members": [
            {"platformId": speaker.username, "accountName": speaker.username, "groupNickname": speaker.display},
            {"platformId": fan.fid, "accountName": fan.account, "groupNickname": fan.name},
        ],
        "messages": messages,
    }
    return doc, len(messages)


SPEAKERS = {
    "linxiaoman": Speaker("linxiaoman", "林小漫", "女·娱乐主播(唱聊)·温柔软糯爱撒娇，开口『宝』，多用波浪号和颜文字"),
    "sutang": Speaker("sutang", "苏糖", "女·娱乐主播(舞蹈才艺)·东北大碴子味，直爽热情爱开玩笑，自称『姐』"),
    "chenfeng": Speaker("chenfeng", "陈锋", "男·英雄联盟主播·高冷话少，满嘴游戏术语，毒舌但护粉"),
    "dazhuang": Speaker("dazhuang", "大壮", "男·游戏弹幕主播·逗比玩梗自嘲，整活担当，口头禅『哈人』『典』"),
    "zhouqing": Speaker("zhouqing", "周晴", "女·汽车销售·专业有分寸，引导式跟进话术，偶尔生活化拉近距离"),
}

FANS = {
    "linxiaoman": [
        Fan("fan_lxm_dahai", "深海(老粉)", "deepsea_code", "抖音",
            "男·38·程序员·上海·相识2年·内向沉默铁粉·几乎每天来打卡",
            days_ago=730, msg_count=320, freq="high"),
        Fan("fan_lxm_tangtang", "糖糖崽崽", "tang_0o0", "抖音",
            "女·19·大学生(声乐社)·成都·相识3个月·中频·活泼话痨小迷妹",
            days_ago=90, msg_count=120, freq="mid"),
        Fan("fan_lxm_brother", "阿杰", "ajie_boss88", "快手",
            "男·26·做小生意·东莞·相识1个月·低频·自来熟越界型",
            days_ago=30, msg_count=45, freq="low"),
    ],
    "sutang": [
        Fan("fan_stg_lan", "兰姐", "lan_mama2580", "抖音",
            "女·45·全职妈妈·哈尔滨(老乡)·相识1年·中频(孩子睡后)·温和唠家常",
            days_ago=365, msg_count=280, freq="mid"),
        Fan("fan_stg_kai", "凯子", "kai_fitness", "抖音",
            "男·22·退伍后做健身教练·河北·相识5个月·高频·直球追求型",
            days_ago=150, msg_count=150, freq="high"),
        Fan("fan_stg_lao", "老周跑长途", "zhou_truck", "快手",
            "男·31·货车司机·常年流动·相识8个月·低频(夜间跑车)·沉默朴实",
            days_ago=240, msg_count=100, freq="low"),
    ],
    "chenfeng": [
        Fan("fan_cf_xiaoyu", "小宇要上王者", "xiaoyu_carry", "B站",
            "男·17·高中生·长沙·相识1年·高频·中二崇拜·想上分",
            days_ago=365, msg_count=310, freq="high"),
        Fan("fan_cf_ke", "K_jungle", "ke_dev_hz", "B站",
            "男·29·后端程序员·杭州·相识2年·中频(周末)·理性技术讨论",
            days_ago=730, msg_count=330, freq="mid"),
        Fan("fan_cf_qiao", "乔木画画", "qiao_illust", "B站",
            "女·24·自由插画师·重庆·相识4个月·低频·不太懂游戏但爱看气氛",
            days_ago=120, msg_count=50, freq="low"),
    ],
    "dazhuang": [
        Fan("fan_dz_pi", "皮皮虾别跑", "pp_xia_zz", "抖音",
            "男·20·大专生(兼职外卖)·郑州·相识7个月·高频·玩梗接梗狂魔",
            days_ago=210, msg_count=300, freq="high"),
        Fan("fan_dz_xiaoyu", "夜班小鱼", "fish_night_xa", "抖音",
            "女·28·护士·西安·相识2个月·中频(下夜班看)·安静解压型",
            days_ago=60, msg_count=130, freq="mid"),
        Fan("fan_dz_uncle", "老李五金", "li_wujin_wf", "快手",
            "男·50·五金店店主·潍坊·相识10天·低频·认真发言不懂网络梗",
            days_ago=10, msg_count=45, freq="low"),
    ],
    "zhouqing": [
        Fan("fan_zq_zhang", "张先生(意向)", "zhang_bj_suv", "微信",
            "男·35·公司中层·北京·有娃家庭·相识2周·中频问价·理性比价谨慎",
            days_ago=14, msg_count=110, freq="mid"),
        Fan("fan_zq_lin", "林律师", "lawyer_lin_sz", "微信",
            "女·29·律师·深圳·首购代步·相识3天·低频·高冷高效只要重点",
            days_ago=3, msg_count=40, freq="low"),
        Fan("fan_zq_wu", "吴总(老客)", "wu_boss_wz", "微信",
            "男·42·私营老板·温州·相识半年(老客转介绍)·偶尔联系·爽快豪气",
            days_ago=180, msg_count=250, freq="mid"),
    ],
}


def build() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for s_id, s in SPEAKERS.items():
        for fan in FANS[s_id]:
            doc, msg_count = build_conversation(s, fan)
            fname = f"{s_id}__{fan.fid}.json"
            (OUT / fname).write_text(
                json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            index.append((fname, s.display, fan.name, fan.profile, msg_count))

    lines = ["# seed_chats 索引（共 15 段私聊，5 主播 × 3 粉丝）\n"]
    cur = None
    for fname, s_disp, fan, prof, n in index:
        if s_disp != cur:
            cur = s_disp
            speaker = next(s for s in SPEAKERS.values() if s.display == s_disp)
            lines.append(f"\n## {s_disp} — {speaker.style}")
        lines.append(f"- `{fname}` · {fan} · {prof} · **{n} 条**")
    (OUT / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    msg_counts = [n for _,_,_,_,n in index]
    print(f"wrote 15 files -> {OUT}")
    print(f"message counts: {msg_counts}")
    print(f"  old粉 (300+): {[m for m in msg_counts if m > 300]}")
    print(f"  中粉 (80-150): {[m for m in msg_counts if 80 <= m <= 150]}")
    print(f"  新粉 (30-50): {[m for m in msg_counts if m <= 50]}")


if __name__ == "__main__":
    build()
