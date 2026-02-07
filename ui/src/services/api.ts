/**
 * API Service for Campus Store Chatbot
 * Connects React UI to FastAPI backend
 */

// API Configuration
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// Type Definitions
export interface ChatRequest {
  message: string;
  session_id?: string;
}

export interface ChatResponse {
  reply: string;
  source: string;
  article_link: string | null;
  confidence: number;
  recommended_pdfs?: PDFRecommendation[];  // ✨ NEW
  retrieval_time_ms?: number;
  llm_time_ms?: number;
  total_time_ms?: number;
}

export interface PDFRecommendation {
  doc_id: string;
  title: string;
  description: string;
  platform: string;
  public_url: string;
  filename: string;
  pages: number;
  file_size_kb: number;
  relevance?: string;  // "Best Match", "Related", "Relevant"
  priority?: string;   // "high", "medium", "low"
  tags?: string[];
}

export interface SessionStats {
  active_sessions: number;
  sessions: Array<{
    id: string;
    history_length: number;
    awaiting_course_code: boolean;
    last_activity: string;
    age_minutes: number;
  }>;
}

/**
 * Send a chat message to the backend
 */
export async function sendChatMessage(
  message: string,
  sessionId?: string
): Promise<ChatResponse> {
  try {
    const response = await fetch(`${API_BASE_URL}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        message,
        session_id: sessionId,
      }),
    });

    if (!response.ok) {
      throw new Error(`API Error: ${response.status} ${response.statusText}`);
    }

    const data: ChatResponse = await response.json();
    return data;
  } catch (error) {
    console.error('Error sending chat message:', error);
    throw error;
  }
}

/**
 * Get session statistics (for debugging)
 */
export async function getSessionStats(): Promise<SessionStats> {
  try {
    const response = await fetch(`${API_BASE_URL}/sessions/stats`);
    
    if (!response.ok) {
      throw new Error(`API Error: ${response.status}`);
    }

    return await response.json();
  } catch (error) {
    console.error('Error fetching session stats:', error);
    throw error;
  }
}

/**
 * Clear a specific session
 */
export async function clearSession(sessionId: string): Promise<void> {
  try {
    const response = await fetch(`${API_BASE_URL}/sessions/${sessionId}`, {
      method: 'DELETE',
    });

    if (!response.ok) {
      throw new Error(`API Error: ${response.status}`);
    }
  } catch (error) {
    console.error('Error clearing session:', error);
    throw error;
  }
}

/**
 * Check if the API is healthy
 */
export async function checkApiHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/sessions/stats`);
    return response.ok;
  } catch (error) {
    console.error('API health check failed:', error);
    return false;
  }
}