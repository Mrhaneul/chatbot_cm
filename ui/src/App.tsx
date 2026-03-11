import React, { useState, useEffect, useRef } from 'react';
import { ChatHeader } from './components/ChatHeader';
import { WelcomeState } from './components/WelcomeState';
import { ChatMessage } from './components/ChatMessage';
import { ChatInput } from './components/ChatInput';
import { PDFSidebar } from './components/PDFSidebar';
import { sendChatMessage, checkApiHealth } from './services/api';
import { PDFRecommendation, Message } from './types';

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [pdfRecommendations, setPdfRecommendations] = useState<PDFRecommendation[]>([]);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
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

      // ✨ PDF recommendations from backend
      if (response.recommended_pdfs && response.recommended_pdfs.length > 0) {
        const formattedPDFs: PDFRecommendation[] = response.recommended_pdfs.map(pdf => ({
          doc_id: pdf.doc_id,
          title: pdf.title,
          description: pdf.description,
          filename: pdf.filename,
          url: pdf.url,
          pages: pdf.pages,
          relevance: pdf.relevance || 'Relevant',
          platform: pdf.platform.charAt(0).toUpperCase() + pdf.platform.slice(1),
          file_size_kb: pdf.file_size_kb,
          tags: pdf.tags || [],
          created_at: pdf.created_at ?? null,
          updated_at: pdf.updated_at ?? null
        }));
        
        setPdfRecommendations(formattedPDFs);
        console.log('📄 PDF Recommendations loaded:', formattedPDFs.length);
        console.log('📄 First PDF URL:', formattedPDFs[0]?.url);
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
