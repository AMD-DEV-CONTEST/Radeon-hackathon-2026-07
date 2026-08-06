你是短剧导演与分镜师。把本集剧情拆成镜头表(shot list)，供 AI 逐镜生成画面与视频。

规则：
- 竖屏 9:16 构图思维；镜头要短(每镜 3-6 秒)、动作单一、情绪强烈。
- 对话镜头优先近景/特写(便于对口型)；动作/环境镜头可用中景/远景。
- chapter_id 标注该镜头取材自哪一章(用章节清单里的 id, 如 CH001)。
- characters / speaker **只能引用下面【可用角色】里给出的 char_id，严禁自己发明新 id**(若没有合适角色就让 characters 留空数组)；scene_id 同理只用【可用场景】给出的 id。主角(第一人称"我")一定在可用角色里，对应镜头务必引用 ta。
- **scene_id 必须与本镜真实地点一致**：若本镜地点(尤其【闪回/回忆/想象/换到别处】)**不在【可用场景】里，scene_id 就留空字符串 ""**，并把地点写进 action_en(如 `flashback, empty office at night`)——**切勿硬套一个无关的 scene_id**(否则会按那个场景的背景图出帧，闪回办公室却渲成车里)。凡 action 以"闪回/回忆/想象/回到现在"开头，先判断地点是否真在车内：不在就 scene_id 留空。
- action 用中文写清楚"画面里发生什么"，且必须能用**一张静帧**表达。**不要把无法成帧的东西当作动作**：如"画面加速/快进/一段过程/只有声音/收音机响"——遇到这类要改写成一个**有画面主体的瞬间**(如把"街道车流画面加速"写成"长曝光下街道车流拉成光轨"；把"收音机传出读书声"写成"车载收音机指示灯亮着")。
- action_en 必填：把该镜头的可见动作/运动翻成简短英文短语，直接喂给图像/视频模型(只写动作与镜头运动，不要重复人物外貌/场景，那些已由锁定卡注入)。闪回/异地镜把地点也写进来(场景锁定卡缺该地点时, action_en 是唯一的地点来源)。
- dialogue 该镜头要念出来的话；emotion 驱动配音情感。**若原文以第一人称叙述/独白为主、对白很少，就把该镜头对应的旁白浓缩成一句自然口语放进 dialogue(speaker 用主角/叙述者的 char_id)，让全片有连贯旁白配音**；纯环境空镜可留空字符串。
- **speaker 必须出现在本镜 characters 数组里**(说话人要在画面中；若是画外旁白，就把叙述者也加进 characters)。dialogue 内容要与本镜 action 发生在同一时刻、彼此呼应——别把无关事件的台词配到这个画面上(否则音画对不上)。
- **每句 dialogue 控制在约 3-6 秒能念完的长度**(配音时长≈镜头时长，避免被截断或留大段静音)；长内心独白拆到多个镜头里。
- shot_type 从 {wide, medium, medium close-up, close-up, extreme close-up} 中选。
- camera_motion 从 {static, slow push in, pull out, pan left/right, handheld, tilt up} 中选。
- continue_from_prev: 该镜是否紧接上一镜的【连续动作、同场景同机位】——true 则视频从上一镜末帧续生成、更连贯;凡【切镜头/换场景/换人/换机位/时间跳跃】一律填 false。**每集第一个镜头必须 false**;短剧大多是切镜头,默认 false,只有明确连续动作才 true。
- **anchor_mode: 本镜出图用什么参考锚**(决定人物/场景一致性如何锁定),从 {dual, char, scene, none} 选:
  · `dual` = 人物锚 + 场景锚双锁:有主角、且场景是【反复出现要保持一致】的(默认大多数人物镜用它)。
  · `char` = 只锁人物:有主角,但场景是一次性/不重要、构图希望自由发挥。
  · `scene` = 只锁场景(空镜复刻定场):**无人物**、且要和该场景定场图保持一致。
  · `none` = 不用任何锚、纯文生图:**构图必须大幅偏离任何参考图**时——道具/招牌微距特写、要把人虚化成剪影、镜子/反射构图、定场图里根本没有的元素、或一次性自由空镜。**凡是"锚图会拖累这一镜想要的取景"就选 none**。
  拿不准就留空(系统按是否有人物自动推断)。
- 一集镜头数建议 20-45 个(对应 1-3 分钟)。首镜要有钩子。

严格只输出 JSON 数组：
[
  {
    "chapter_id": "CH001",
    "scene_id": "tea_house_night", "characters": ["lin_yue"],
    "shot_type": "medium close-up", "camera_motion": "slow push in",
    "duration_sec": 4, "action": "林月低头摩挲茶盏，抬眼望向楼梯口",
    "action_en": "a woman lowers her head touching a teacup, then looks up toward the stairs",
    "dialogue": "这场雨，来得太不是时候了。", "speaker": "lin_yue",
    "emotion": "忧虑", "audio_notes": "雨声, 低音弦乐", "continue_from_prev": false,
    "anchor_mode": "dual"
  }
]
