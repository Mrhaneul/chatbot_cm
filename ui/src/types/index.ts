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
}

export interface Message {
  id: string;
  type: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  confidence?: number;
  source?: string;
  articleLink?: string | null;
}