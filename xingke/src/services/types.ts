// ============================================
// 型刻 API — TypeScript 类型定义
// 对应后端 OpenAPI 3.1.0 接口文档
// ============================================

// —— 对话模块 ——

export interface ChatRequest {
  message: string
  session_id?: string | null
  user_id?: string
  user_profile?: Record<string, any> | null
}

export interface ChatResponse {
  session_id: string
  response: string
  user_id: string
}

export interface SessionListResponse {
  sessions: Record<string, any>[]
}

// SSE 流式对话返回的逐 token 数据
export interface ChatStreamToken {
  token: string
}

export interface ChatStreamDone {
  done: true
  session_id: string
}

// —— 工具模块 ——

export interface ToolCallRequest {
  tool_name: string
  args?: Record<string, any>
  user_id?: string
}

export interface ToolCallResponse {
  tool_name: string
  content: string
  metadata: Record<string, any>
}

export interface BMRCalculatorParams {
  gender?: string  // default: male
  age?: number     // default: 25
  weight?: number  // default: 70
  height?: number  // default: 175
}

export interface TDEECalculatorParams {
  bmr: number             // required
  activity_level?: string  // default: moderate
}

export interface BMICalculatorParams {
  weight: number  // required
  height: number  // required
}

export interface DietPlanParams {
  gender?: string
  age?: number
  weight?: number
  height?: number
  activity_level?: string
  target_deficit?: number  // default: 500
  meals_per_day?: number   // default: 3
  preferences?: string
  allergies?: string
  days?: number            // default: 1
  user_id?: string
}

export interface ExercisePlanParams {
  fitness_level?: string    // default: beginner
  available_days?: number   // default: 4
  time_per_session?: number // default: 45
  equipment?: string        // default: none
  target_areas?: string     // default: 全身
  goal?: string             // default: 减脂
  user_id?: string
}

export interface AnalyzeBodyParams {
  goal?: string       // default: 减脂
  target_weight?: number  // default: 0
}

export interface AnalyzeBodyBody {
  weight_records: Record<string, any>[]
  body_fat_records: Record<string, any>[]
}

// —— 图像识别模块 ——

export interface FoodRecognitionRequest {
  image_base64?: string | null
  description?: string | null
  user_id?: string  // default: anonymous
}

// —— 知识库模块 ——

export interface KnowledgeSearchRequest {
  query: string
  top_k?: number    // default: 5
  category?: string | null
}

export interface KnowledgeAddRequest {
  title: string
  content: string
  source?: string   // default: ""
  category?: string // default: user
}

// —— 通用 ——

export interface ApiError {
  detail: {
    loc: (string | number)[]
    msg: string
    type: string
  }[]
}
