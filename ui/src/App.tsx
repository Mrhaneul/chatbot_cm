import React, { useState, useEffect, useRef } from 'react';
import { ChatHeader } from './components/ChatHeader';
import { WelcomeState } from './components/WelcomeState';
import { ChatMessage } from './components/ChatMessage';
import { ChatInput } from './components/ChatInput';
import { PDFSidebar } from './components/PDFSidebar';
import { sendChatMessage, checkApiHealth } from './services/api';

interface Message {
  id: string;
  type: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  confidence?: number;
  source?: string;
  articleLink?: string | null;
}

interface PDFRecommendation {
  id: string;
  title: string;
  description: string;
  platform: string;
  relevance: 'best' | 'related' | 'relevant';
  lastUpdated: string;
  pageCount: number;
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [pdfRecommendations, setPdfRecommendations] = useState<PDFRecommendation[]>([]);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [sessionId, setSessionId] = useState<string>('');
  const [isLoading, setIsLoading] = useState(false);
  const [apiStatus, setApiStatus] = useState<'connected' | 'disconnected' | 'checking'>('checking');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Generate session ID on mount
  useEffect(() => {
    const newSessionId = `session-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    setSessionId(newSessionId);
    console.log('📱 Session ID:', newSessionId);

    // Check API health
    checkApiHealth().then(isHealthy => {
      setApiStatus(isHealthy ? 'connected' : 'disconnected');
      if (!isHealthy) {
        console.error('⚠️ Backend API is not responding. Make sure the FastAPI server is running on http://localhost:8000');
      }
    });
  }, []);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSendMessage = async (content: string) => {
    // Add user message immediately
    const userMessage: Message = {
      id: Date.now().toString(),
      type: 'user',
      content,
      timestamp: new Date(),
    };

    setMessages(prev => [...prev, userMessage]);
    setIsLoading(true);

    try {
      // Send to backend
      const response = await sendChatMessage(content, sessionId);

      // Add assistant response
      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        type: 'assistant',
        content: response.reply,
        timestamp: new Date(),
        confidence: response.confidence,
        source: response.source,
        articleLink: response.article_link,
      };

      setMessages(prev => [...prev, assistantMessage]);

      // ✨ UPDATE: Use PDF recommendations from backend
      // ✨ UPDATE: Use PDF recommendations from backend
      if (response.recommended_pdfs && response.recommended_pdfs.length > 0) {
        const formattedPDFs: PDFRecommendation[] = response.recommended_pdfs.map(pdf => {
          // Normalize relevance to match our type
          const normalizedRelevance = pdf.relevance?.toLowerCase() || 'relevant';
          const relevance: 'best' | 'related' | 'relevant' = 
            normalizedRelevance === 'best match' ? 'best' :
            normalizedRelevance === 'best' ? 'best' :
            normalizedRelevance === 'related' ? 'related' : 
            'relevant';
          
          return {
            id: pdf.doc_id,
            title: pdf.title,
            description: pdf.description,
            platform: pdf.platform.charAt(0).toUpperCase() + pdf.platform.slice(1),
            relevance,
            lastUpdated: 'Recently',
            pageCount: pdf.pages,
            pdfUrl: pdf.public_url,
          };
        });
        
        setPdfRecommendations(formattedPDFs);
        console.log('📄 PDF Recommendations loaded:', formattedPDFs.length);
      } else {
        setPdfRecommendations([]);
      }


      // Update API status on successful response
      if (apiStatus !== 'connected') {
        setApiStatus('connected');
      }

    } catch (error) {
      console.error('Error sending message:', error);
      
      // Add error message
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        type: 'system',
        content: '⚠️ Sorry, I\'m having trouble connecting to the server. Please try again.',
        timestamp: new Date(),
      };

      setMessages(prev => [...prev, errorMessage]);
      setApiStatus('disconnected');
    } finally {
      setIsLoading(false);
    }
  };

  const updatePDFRecommendations = (query: string, response: any) => {
    const lowerQuery = query.toLowerCase();
    const newRecommendations: PDFRecommendation[] = [];

    // Extract platform from response source
    const source = response.source || '';
    const platform = extractPlatformFromSource(source, lowerQuery);

    // Generate PDF recommendations based on detected platform
    if (platform === 'cengage') {
      newRecommendations.push({
        id: '1',
        title: 'Cengage MindTap Access Guide',
        description: 'Step-by-step instructions for accessing Cengage MindTap through Immediate Access',
        platform: 'Cengage',
        relevance: 'best',
        lastUpdated: 'Jan 27, 2026',
        pageCount: 3,
      });
      if (lowerQuery.includes('textbook')) {
        newRecommendations.push({
          id: '2',
          title: 'Cengage eTextbook Guide',
          description: 'How to access your Cengage eTextbook through VitalSource',
          platform: 'Cengage',
          relevance: 'related',
          lastUpdated: 'Jan 27, 2026',
          pageCount: 2,
        });
      }
    }

    if (platform === 'mcgraw' || platform === 'connect') {
      newRecommendations.push({
        id: '3',
        title: 'McGraw Hill Connect Access',
        description: 'Complete guide to accessing McGraw Hill Connect through Blackboard',
        platform: 'McGraw Hill',
        relevance: 'best',
        lastUpdated: 'Jan 27, 2026',
        pageCount: 4,
      });
      newRecommendations.push({
        id: '4',
        title: 'McGraw Hill Tools Navigation',
        description: 'How to access materials through the Tools menu',
        platform: 'McGraw Hill',
        relevance: 'related',
        lastUpdated: 'Jan 27, 2026',
        pageCount: 3,
      });
    }

    if (platform === 'pearson') {
      newRecommendations.push({
        id: '5',
        title: 'Pearson MyLab & Mastering',
        description: 'Guide for accessing Pearson platforms through Immediate Access',
        platform: 'Pearson',
        relevance: 'best',
        lastUpdated: 'Jan 27, 2026',
        pageCount: 4,
      });
    }

    if (platform === 'simucase') {
      newRecommendations.push({
        id: '6',
        title: 'SimuCase Platform Setup',
        description: 'Complete walkthrough for redeeming your SimuCase access code',
        platform: 'SimuCase',
        relevance: 'best',
        lastUpdated: 'Jan 27, 2026',
        pageCount: 5,
      });
    }

    if (lowerQuery.includes('immediate access')) {
      newRecommendations.push({
        id: '7',
        title: 'Immediate Access Overview',
        description: 'Complete guide to CBU\'s Immediate Access program',
        platform: 'General',
        relevance: 'best',
        lastUpdated: 'Feb 1, 2026',
        pageCount: 6,
      });
    }

    // Add general troubleshooting if we have specific recommendations
    if (newRecommendations.length > 0) {
      newRecommendations.push({
        id: '99',
        title: 'Browser & Cookie Troubleshooting',
        description: 'Common browser issues and how to fix them',
        platform: 'General',
        relevance: 'relevant',
        lastUpdated: 'Jan 27, 2026',
        pageCount: 2,
      });
    }

    setPdfRecommendations(newRecommendations);
  };

  const extractPlatformFromSource = (source: string, query: string): string => {
    const sourceLower = source.toLowerCase();
    const queryLower = query.toLowerCase();

    if (sourceLower.includes('cengage') || queryLower.includes('cengage') || queryLower.includes('mindtap')) {
      return 'cengage';
    }
    if (sourceLower.includes('mcgraw') || queryLower.includes('mcgraw') || queryLower.includes('connect')) {
      return 'mcgraw';
    }
    if (sourceLower.includes('pearson') || queryLower.includes('pearson') || queryLower.includes('mylab')) {
      return 'pearson';
    }
    if (sourceLower.includes('simucase') || queryLower.includes('simucase')) {
      return 'simucase';
    }
    if (sourceLower.includes('bedford') || queryLower.includes('bedford')) {
      return 'bedford';
    }
    if (sourceLower.includes('sage') || queryLower.includes('sage')) {
      return 'sage';
    }
    return 'general';
  };

  const handlePromptClick = (prompt: string) => {
    handleSendMessage(prompt);
  };

  return (
    <div className="flex h-screen bg-white">
      {/* Left Panel - Chat Interface */}
      <div className="flex flex-col flex-1 min-w-0">
        <ChatHeader apiStatus={apiStatus} />
        
        <div className="flex-1 overflow-y-auto px-4 py-6">
          {messages.length === 0 ? (
            <WelcomeState onPromptClick={handlePromptClick} />
          ) : (
            <div className="max-w-4xl mx-auto space-y-4">
              {messages.map((message) => (
                <ChatMessage key={message.id} message={message} />
              ))}
              
              {/* Loading indicator */}
              {isLoading && (
                <div className="flex items-center gap-2 text-gray-500 pl-4">
                  <div className="flex gap-1">
                    <div className="w-2 h-2 bg-[#165FB3] rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                    <div className="w-2 h-2 bg-[#165FB3] rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                    <div className="w-2 h-2 bg-[#165FB3] rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                  </div>
                  <span className="text-sm">Lance is thinking...</span>
                </div>
              )}
              
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        <ChatInput onSendMessage={handleSendMessage} disabled={isLoading} />
      </div>

      {/* Right Panel - PDF Sidebar */}
      <PDFSidebar 
        recommendations={pdfRecommendations}
        isOpen={isSidebarOpen}
        onToggle={() => setIsSidebarOpen(!isSidebarOpen)}
      />
    </div>
  );
}
