export interface PDFRecommendation {
  doc_id: string;
  title: string;
  description: string;
  filename: string;
  url: string;
  pages: number;
  relevance: string;
  platform: string;
  file_size_kb: number;
  tags: string[];
  created_at?: string | null;
  updated_at?: string | null;
}

export interface Message {
  id: string;
  type: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  confidence?: number;
  source?: string;
  articleLink?: string | null;
  debug_mode?: boolean;
  isStreaming?: boolean;
}
