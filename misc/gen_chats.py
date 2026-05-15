#!/usr/bin/env python3
"""
gen_chats.py — Generate 10 synthetic chatlab JSON files using DeepSeek API.
Saves to misc/ directory alongside this script.

Usage:
  python3 gen_chats.py              # generate all
  python3 gen_chats.py chat_kk      # generate only matching filename prefix(es)
"""

import json
import os
import sys
import time
import random
from datetime import datetime, timezone, timedelta

from openai import OpenAI

# ── Config ─────────────────────────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))
env = {}
with open(os.path.join(HERE, "..", "scripts", ".env")) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()

client = OpenAI(api_key=env["PROVIDER_API_KEY"], base_url=env["PROVIDER_BASE_URL"])
MODEL = env["PROVIDER_MODEL"]
CST = timezone(timedelta(hours=8))
random.seed(42)


# ── Scenarios ──────────────────────────────────────────────────────────────────
# batches: list of (day_start, day_end, target_msg_count)
SCENARIOS = [
    # 1 ── 女娱乐主播 × 大学生
    dict(
        filename="chat_yanzi_student.json",
        description="女娱乐主播燕子与大学生粉丝小伟的聊天记录",
        anchor=dict(id="wechat_yanzi_001", name="小燕子不打烊", nick="燕子"),
        fan=dict(id="wechat_xiaowei_002", name="小伟爱摸鱼", nick="小伟"),
        anchor_role="女娱乐主播，唱歌跳舞才艺，活泼开朗，22岁，成都人，刚做直播一年",
        fan_role="大学生，大二，计算机专业，内向腼腆，第一次刷礼物给主播，有点社恐",
        story=(
            "小伟第一次刷礼物给燕子，鼓起勇气加了微信。从感谢聊起，逐渐聊到学业压力、"
            "毕业焦虑、追星心理；燕子分享直播背后的辛苦和不容易；小伟慢慢话多起来，"
            "时不时发一些作业相关的事，两人形成奇特姐弟情谊，偶尔互相给对方打气"
        ),
        start_date="2024-09-01",
        end_date="2024-11-30",
        total_msgs=180,
        batches=[(0, 30, 60), (30, 60, 60), (60, 91, 60)],
    ),
    # 2 ── 女娱乐主播 × 生意人
    dict(
        filename="chat_meimei_boss.json",
        description="女娱乐主播美美与餐饮老板赵总的聊天记录",
        anchor=dict(id="wechat_meimei_001", name="美美来了", nick="美美"),
        fan=dict(id="wechat_zhaozong_002", name="老赵做生意", nick="赵总"),
        anchor_role="女娱乐主播，脱口秀+才艺，性格泼辣大方，25岁，重庆人",
        fan_role="餐饮连锁老板，40岁，离异，生意压力大，大手笔打赏主播解压",
        story=(
            "赵总是老粉，私下越聊越多。美美职业性维系，但赵总话里话外想发展更近的关系——"
            "送礼物、约吃饭、夸长相。美美时而配合时而转移话题，也真实吐槽直播的烦恼；"
            "赵总聊生意的孤独和离婚后的寂寞。关系微妙，美美职业边界清晰但不冷漠"
        ),
        start_date="2024-03-15",
        end_date="2024-06-20",
        total_msgs=350,
        batches=[(0, 25, 88), (25, 50, 88), (50, 75, 88), (75, 97, 86)],
    ),
    # 3 ── 女娱乐主播 × 上班族/工人
    dict(
        filename="chat_nuannuan_worker.json",
        description="女娱乐主播暖暖与工厂工人张强的聊天记录",
        anchor=dict(id="wechat_nuannuan_001", name="暖暖小姐姐", nick="暖暖"),
        fan=dict(id="wechat_zhangqiang_002", name="张强搬砖中", nick="张强"),
        anchor_role="女娱乐主播，颜值聊天互动型，23岁，武汉人，做直播两年",
        fan_role="工厂流水线工人，28岁，来自农村进城务工，工资不高但省着刷礼物",
        story=(
            "张强每天下班后看暖暖直播是唯一慰藉。聊工厂三班倒有多累、流水线无聊；"
            "暖暖偶尔给生活建议，也真实吐槽自己的烦恼；张强用朴实的方式表达心意，"
            "暖暖温柔但保持距离。张强说过好几次想回老家，最终因舍不得直播而留下来"
        ),
        start_date="2024-01-10",
        end_date="2024-04-08",
        total_msgs=420,
        batches=[(0, 22, 105), (22, 44, 105), (44, 66, 105), (66, 89, 105)],
    ),
    # 4 ── 女娱乐主播 × 闲杂人等
    dict(
        filename="chat_xixi_idler.json",
        description="女娱乐主播希希与无业游民宇哥的聊天记录",
        anchor=dict(id="wechat_xixi_001", name="希希不睡觉", nick="希希"),
        fan=dict(id="wechat_yuge_002", name="宇哥在线", nick="宇哥"),
        anchor_role="女娱乐主播，游戏才艺混搭，话多讲段子，24岁，南京人",
        fan_role="无业游民，30岁，靠父母养着，每天刷手机，痞气直接，口无遮拦",
        story=(
            "宇哥是直播间老油条，经常和希希杠嘴。加微信后随性聊，时而约打游戏时而消失几天，"
            "希希有时嫌他游手好闲，有时又聊得来。宇哥某次突然消失两周，回来说家里有事，"
            "两人关系短暂变认真了一下，然后又回归痞气吊儿郎当的节奏"
        ),
        start_date="2023-11-01",
        end_date="2024-02-28",
        total_msgs=280,
        batches=[(0, 32, 93), (32, 64, 94), (64, 119, 93)],
    ),
    # 5 ── 女娱乐主播 × 老头
    dict(
        filename="chat_yaoyao_oldman.json",
        description="女娱乐主播瑶瑶与退休老头刘叔的聊天记录",
        anchor=dict(id="wechat_yaoyao_001", name="瑶瑶唱民歌", nick="瑶瑶"),
        fan=dict(id="wechat_liushu_002", name="刘老汉", nick="刘叔"),
        anchor_role="女娱乐主播，专唱民歌，嗓音甜美，21岁，陕西人，刚出道一年",
        fan_role="退休老头，65岁，老伴去世几年，子女不在身边，手机不太熟练，爱听民歌",
        story=(
            "老刘叔摸索着学会打赏，给瑶瑶送礼物，瑶瑶热情回应加了微信。"
            "老头每天早安晚安，时不时问手机怎么操作，聊村里的事和过去的故事。"
            "瑶瑶像对爷爷一样回复，有时直播忙好几天没看消息，老头只说'娃忙着嘞'，"
            "一年里两人形成特殊的跨代情谊，瑶瑶生病时老头急得坐不住"
        ),
        start_date="2024-05-01",
        end_date="2025-01-15",
        total_msgs=600,
        batches=[
            (0, 45, 100),
            (45, 90, 100),
            (90, 135, 100),
            (135, 180, 100),
            (180, 225, 100),
            (225, 260, 100),
        ],
    ),
    # 6 ── 王者荣耀男主播 × 男粉
    dict(
        filename="chat_kk_kog_bro.json",
        description="王者荣耀男主播KK与男粉虎子的聊天记录",
        anchor=dict(id="wechat_kk_001", name="KK上王者", nick="KK"),
        fan=dict(id="wechat_huzi_002", name="虎子打野牛", nick="虎子"),
        anchor_role="王者荣耀男主播，最强王者段位，英雄榜前50，擅长打野，26岁，北京人，说话直接",
        fan_role="男粉，24岁，刚毕业工作，王者钻石段位，想花钱让KK带飞技术",
        story=(
            "虎子买了KK的陪玩套餐，加微信讨论打野英雄选择和版本更新。"
            "KK带他连麦训练，虎子不听指挥被KK骂，委屈但继续学。"
            "慢慢成了固定连麦朋友，从游戏聊到生活，虎子工作不顺时也跟KK倾诉，"
            "KK粗线条的安慰意外管用。两人从付费关系变成了兄弟关系"
        ),
        start_date="2024-04-10",
        end_date="2024-09-30",
        total_msgs=500,
        batches=[(0, 43, 125), (43, 86, 125), (86, 130, 125), (130, 174, 125)],
    ),
    # 7 ── 抖音弹幕游戏男主播 × 女粉
    dict(
        filename="chat_afei_douyin_girl.json",
        description="抖音弹幕游戏男主播阿飞与女粉小鹿的聊天记录",
        anchor=dict(id="wechat_afei_001", name="阿飞弹幕局", nick="阿飞"),
        fan=dict(id="wechat_xiaolu_002", name="小鹿乱撞呢", nick="小鹿"),
        anchor_role="抖音弹幕游戏男主播，专玩挑战类弹幕游戏，幽默搞怪，27岁，广州人",
        fan_role="女粉，22岁，UI设计师，下班爱看直播解压，性格外向爱怼人，颜狗",
        story=(
            "小鹿在弹幕互动多了之后私聊了阿飞。聊设计审美和游戏画面风格，"
            "阿飞偶尔撩，小鹿有时配合有时直接怼回去，互相斗嘴。"
            "小鹿换工作压力大，阿飞用奇怪的方式转移注意力意外有效。"
            "暧昧感若隐若现但双方都没有真正捅破"
        ),
        start_date="2024-07-01",
        end_date="2024-10-15",
        total_msgs=300,
        batches=[(0, 38, 100), (38, 76, 100), (76, 106, 100)],
    ),
    # 8 ── 王者荣耀女主播 × 男粉
    dict(
        filename="chat_lulu_kog_guy.json",
        description="王者荣耀女主播露露与男粉大壮的聊天记录",
        anchor=dict(id="wechat_lulu_001", name="露露上荣耀", nick="露露"),
        fan=dict(id="wechat_dazhuang_002", name="大壮玩游戏", nick="大壮"),
        anchor_role="王者荣耀女主播，颜值+技术双在线，打辅助为主，23岁，上海人",
        fan_role="男粉，35岁，已婚程序员，王者老玩家，崇拜露露颜值和操作，有点爹气",
        story=(
            "大壮是老粉，每次版本更新都来讨论英雄强度，定期刷礼物。"
            "话里偶有越界——过度赞美、问私人问题，露露有时直接说不合适，有时装没看见。"
            "大壮老婆不知道他这爱好，他在家偷偷聊，回消息慢且措辞谨慎，"
            "有一次被老婆看到手机紧急把话题转成问游戏攻略"
        ),
        start_date="2023-10-01",
        end_date="2024-03-31",
        total_msgs=450,
        batches=[(0, 46, 113), (46, 92, 112), (92, 138, 113), (138, 183, 112)],
    ),
    # 9 ── 抖音弹幕游戏女主播 × 女粉
    dict(
        filename="chat_momo_douyin_sis.json",
        description="抖音弹幕游戏女主播莫莫与女粉糖糖的聊天记录",
        anchor=dict(id="wechat_momo_001", name="莫莫弹弹弹", nick="莫莫"),
        fan=dict(id="wechat_tangtang_002", name="糖糖爱吃糖", nick="糖糖"),
        anchor_role="抖音弹幕游戏女主播，休闲弹幕游戏，可爱系风格，22岁，杭州人",
        fan_role="女粉，20岁，高中毕业准备复读，压力大，直播间弹幕活跃",
        story=(
            "糖糖和莫莫因弹幕互动多了成了朋友。私下聊复读的压力、对未来的迷茫；"
            "莫莫分享自己放弃大学选择做直播的过程，两人互相理解各自被人不理解的处境。"
            "有时半夜直播结束后一起聊到凌晨。糖糖备考前很焦虑，莫莫每天打气，"
            "最后糖糖考上了，两人一起庆祝，喝奶茶发消息"
        ),
        start_date="2024-08-15",
        end_date="2024-12-31",
        total_msgs=380,
        batches=[(0, 38, 95), (38, 76, 95), (76, 114, 95), (114, 139, 95)],
    ),
    # 10 ── 保险女销售 × 家庭主妇女客户
    dict(
        filename="chat_insurance_lixiao_wangjie.json",
        description="保险女销售小李与家庭主妇王姐的聊天记录",
        anchor=dict(id="wechat_lixiao_001", name="李晓保险顾问", nick="小李"),
        fan=dict(id="wechat_wangjie_002", name="王姐家常菜", nick="王姐"),
        anchor_role="保险公司销售，28岁，专注家庭保障类产品，认真但有业绩压力",
        fan_role="家庭主妇，42岁，有初中孩子，丈夫做生意，对保险又想买又怕被坑",
        story=(
            "小李通过朋友介绍认识王姐，先是朋友圈互动后私聊。王姐一开始警惕，"
            "反复试探、找借口、去网上比价，小李耐心聊家庭风险、孩子教育、丈夫生意意外。"
            "期间王姐孩子发高烧住院，小李发来关心消息，王姐明显软化。"
            "之后认真问产品细节，中间又犹豫了一段时间，最终买了家庭意外险+重疾险组合"
        ),
        start_date="2024-02-01",
        end_date="2024-05-31",
        total_msgs=250,
        batches=[(0, 30, 83), (30, 60, 84), (60, 120, 83)],
    ),
]


# ── Core functions ─────────────────────────────────────────────────────────────

def make_prompt(scenario, day_start, day_end, target_n, prev_tail=""):
    day_span = day_end - day_start
    ctx = (
        f"之前对话的最后几条（供续写参考，请自然衔接）：\n{prev_tail}"
        if prev_tail
        else "这是双方第一次聊天，从刚加了微信开始。"
    )
    return f"""你是微信对话数据生成专家。请生成真实的私聊记录JSON数组。

【人物】
- anchor：{scenario['anchor']['nick']}，{scenario['anchor_role']}
- fan：{scenario['fan']['nick']}，{scenario['fan_role']}

【故事背景】{scenario['story']}

【上下文】{ctx}

【任务】生成从第{day_start}天到第{day_end}天之间（共约{day_span}天）的约{target_n}条消息。
day字段请用相对第{day_start}天的偏移（0 = 第{day_start}天，{day_span} = 第{day_end}天）。

【必须遵守的规则】
1. 严禁一问一答式。要有：连续发多条消息、长时间不回复、话题自然跳跃、上下文遗忘后又想起
2. 时间间隔真实：
   - 同一人连续发消息：每条间隔5–40秒
   - 对方回复：间隔30秒到数小时不等，有时是第二天才回
3. 长时间没回复时，要有真实理由：「刚看到」「刚才在忙」「手机没电了」「开会」「睡着了」等
4. 时间分布真实：深夜（0–6点）极少；晚上18–24点最多；中间要有完整的几天没消息
5. 语言风格严格贴合人物年龄、职业和地域背景
6. 主播有职业性，但也有真实情绪、烦恼、状态不好的时候
7. 每个batch都要推进故事线，不要原地循环重复相同话题
8. 消息内容要有细节感（具体的事、具体的时间、具体的情绪）

【严格只输出JSON数组，不要任何解释或markdown代码块】：
[{{"day":0,"hour":20,"minute":30,"sender":"anchor","content":"消息内容"}},...]"""


def call_api(prompt, retries=3):
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": "你是专业对话数据生成专家，严格输出合法JSON数组，不要任何其他文字。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.88,
                max_tokens=8192,
            )
            raw = resp.choices[0].message.content.strip()
            s = raw.find("[")
            e = raw.rfind("]") + 1
            if s == -1 or e == 0:
                raise ValueError(f"No JSON array in response (first 300 chars): {raw[:300]}")
            return json.loads(raw[s:e])
        except Exception as exc:
            print(f"  [attempt {attempt + 1}/{retries}] error: {exc}")
            if attempt == retries - 1:
                raise
            time.sleep(3)


def msgs_to_chatlab(raw_msgs, scenario, day_base, prev_last_ts=None):
    start_dt = datetime.strptime(scenario["start_date"], "%Y-%m-%d").replace(tzinfo=CST)
    anchor_id = scenario["anchor"]["id"]
    anchor_name = scenario["anchor"]["name"]
    fan_id = scenario["fan"]["id"]
    fan_name = scenario["fan"]["name"]

    result = []
    last_ts = prev_last_ts or 0

    for m in raw_msgs:
        try:
            day = int(m.get("day", 0)) + day_base
            hour = max(0, min(23, int(m.get("hour", 12))))
            minute = max(0, min(59, int(m.get("minute", 0))))
        except (TypeError, ValueError):
            continue

        ts = int((start_dt + timedelta(days=day, hours=hour, minutes=minute)).timestamp())
        if ts <= last_ts:
            ts = last_ts + random.randint(5, 45)
        last_ts = ts

        sender = str(m.get("sender", "fan")).lower()
        is_anchor = sender == "anchor"
        result.append({
            "sender": anchor_id if is_anchor else fan_id,
            "accountName": anchor_name if is_anchor else fan_name,
            "timestamp": ts,
            "type": 0,
            "content": str(m.get("content", "")).strip(),
        })

    return result, last_ts


def build_chatlab(scenario, all_messages):
    now_ts = int(datetime.now(CST).timestamp())
    return {
        "chatlab": {
            "version": "0.0.2",
            "exportedAt": now_ts,
            "generator": "deepseek-gen",
            "description": scenario["description"],
        },
        "meta": {
            "name": scenario["anchor"]["name"],
            "platform": "wechat",
            "type": "private",
            "ownerId": scenario["anchor"]["id"],
        },
        "members": [
            {
                "platformId": scenario["anchor"]["id"],
                "accountName": scenario["anchor"]["name"],
                "groupNickname": scenario["anchor"]["nick"],
                "aliases": [scenario["anchor"]["nick"]],
            },
            {
                "platformId": scenario["fan"]["id"],
                "accountName": scenario["fan"]["name"],
                "groupNickname": scenario["fan"]["nick"],
                "aliases": [scenario["fan"]["nick"]],
            },
        ],
        "messages": all_messages,
    }


def generate_scenario(scenario):
    print(f"\n{'=' * 62}")
    print(f"  {scenario['filename']}")
    print(f"  {scenario['description']}")
    print(f"  target {scenario['total_msgs']} msgs | {len(scenario['batches'])} batches")

    all_msgs = []
    last_ts = None
    prev_tail = ""

    for idx, (day_start, day_end, target_n) in enumerate(scenario["batches"]):
        print(f"  batch {idx + 1}/{len(scenario['batches'])}: days {day_start}–{day_end}, ~{target_n} msgs ...", end=" ", flush=True)

        prompt = make_prompt(scenario, day_start, day_end, target_n, prev_tail)
        raw = call_api(prompt)

        batch_msgs, last_ts = msgs_to_chatlab(raw, scenario, day_start, last_ts)
        all_msgs.extend(batch_msgs)

        # Build context hint: last 6 messages as plain text
        if batch_msgs:
            anchor_id = scenario["anchor"]["id"]
            anchor_nick = scenario["anchor"]["nick"]
            fan_nick = scenario["fan"]["nick"]
            lines = []
            for msg in batch_msgs[-6:]:
                nick = anchor_nick if msg["sender"] == anchor_id else fan_nick
                lines.append(f"{nick}：{msg['content']}")
            prev_tail = "\n".join(lines)

        print(f"got {len(batch_msgs)} (total {len(all_msgs)})")
        time.sleep(0.5)

    data = build_chatlab(scenario, all_msgs)
    out_path = os.path.join(HERE, scenario["filename"])
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  saved → {out_path}  ({len(all_msgs)} messages)")
    return len(all_msgs)


def main():
    filters = sys.argv[1:]
    grand_total = 0
    for s in SCENARIOS:
        if filters and not any(s["filename"].startswith(f) for f in filters):
            continue
        n = generate_scenario(s)
        grand_total += n

    print(f"\n{'=' * 62}")
    print(f"  All done. Total messages generated: {grand_total}")


if __name__ == "__main__":
    main()
