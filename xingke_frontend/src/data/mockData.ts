// 模拟数据

export const mockMessages = [
  {
    id: '1',
    role: 'ai' as const,
    type: 'text' as const,
    content: '早上好，陈晓东！今天感觉怎么样？\n\n根据你最新的身体数据：体重71.5kg，体脂率21.5%，相比上周下降了0.3kg，趋势良好。继续保持当前的饮食和运动节奏，本周有望突破71kg大关！',
    timestamp: '09:00',
  },
  {
    id: '2',
    role: 'user' as const,
    type: 'text' as const,
    content: '今天早餐吃了一碗燕麦粥和一个水煮蛋，热量大概多少？',
    timestamp: '09:15',
  },
  {
    id: '3',
    role: 'ai' as const,
    type: 'card' as const,
    content: '已为你识别并记录今日早餐',
    cardData: {
      title: '今日早餐 · 已记录',
      totalCalories: 320,
      items: [
        { name: '燕麦粥（1碗）', amount: '250g', calories: 152 },
        { name: '水煮蛋（1个）', amount: '50g', calories: 78 },
        { name: '蓝莓（少许）', amount: '30g', calories: 17 },
        { name: '蜂蜜（1勺）', amount: '10g', calories: 73 },
      ],
    },
    timestamp: '09:16',
  },
  {
    id: '4',
    role: 'ai' as const,
    type: 'text' as const,
    content: '这份早餐总计约320千卡，搭配合理！燕麦提供优质碳水，鸡蛋补充蛋白质，蓝莓富含抗氧化物。建议午餐适当增加绿叶蔬菜摄入，保持全天热量均衡。',
    timestamp: '09:16',
  },
  {
    id: '5',
    role: 'user' as const,
    type: 'text' as const,
    content: '帮我生成一份本周的减脂食谱吧',
    timestamp: '14:30',
  },
  {
    id: '6',
    role: 'ai' as const,
    type: 'recipe' as const,
    content: '已根据你的身体数据和目标生成本周减脂食谱',
    cardData: {
      title: '本周减脂食谱 · 周一至周三',
      targetCalories: 1600,
      days: [
        {
          day: '周一',
          meals: [
            { meal: '早餐', desc: '燕麦粥 + 水煮蛋 + 蓝莓', calories: 320 },
            { meal: '午餐', desc: '鸡胸肉沙拉 + 糙米饭', calories: 480 },
            { meal: '晚餐', desc: '清蒸鲈鱼 + 西兰花', calories: 380 },
          ],
        },
        {
          day: '周二',
          meals: [
            { meal: '早餐', desc: '全麦面包 + 牛奶 + 鸡蛋', calories: 350 },
            { meal: '午餐', desc: '牛肉时蔬炒面 + 紫菜汤', calories: 520 },
            { meal: '晚餐', desc: '豆腐蔬菜汤 + 玉米', calories: 360 },
          ],
        },
        {
          day: '周三',
          meals: [
            { meal: '早餐', desc: '杂粮粥 + 茶叶蛋 + 番茄', calories: 300 },
            { meal: '午餐', desc: '虾仁炒饭 + 凉拌黄瓜', calories: 460 },
            { meal: '晚餐', desc: '鸡丝凉面 + 冬瓜汤', calories: 400 },
          ],
        },
      ],
    },
    timestamp: '14:31',
  },
]

export const mockTodayCalories = {
  intake: 1180,
  budget: 1600,
  remaining: 420,
}

export const mockExerciseTask = {
  name: 'HIIT燃脂训练',
  duration: '30分钟',
  completed: false,
}

export const mockGoalProgress = {
  currentWeight: 71.5,
  targetWeight: 68.0,
  startWeight: 75.0,
  percentage: 71,
  weeklyChange: -0.3,
}
