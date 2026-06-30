import React, { useState, useEffect, useRef, useCallback } from 'react';
import { ChatHeader } from './components/ChatHeader';
import { WelcomeState } from './components/WelcomeState';
import { ChatMessage } from './components/ChatMessage';
import { ChatInput } from './components/ChatInput';
import { FAQSidebar } from './components/FAQSidebar';
import { PDFSidebar } from './components/PDFSidebar';
import { API_BASE_URL, STREAM_ENDPOINT, checkApiHealth, getHeaders } from './services/api';
import { PDFRecommendation, Message } from './types';

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [pdfRecommendations, setPdfRecommendations] = useState<PDFRecommendation[]>([]);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [sessionId, setSessionId] = useState<string>('');
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [apiStatus, setApiStatus] = useState<'connected' | 'disconnected' | 'checking'>('checking');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const chatInputRef = useRef<HTMLTextAreaElement>(null);

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

  const resolvePdfUrl = (url: string | undefined): string => {
    if (!url) {
      return '';
    }
    if (/^https?:\/\//i.test(url)) {
      return url;
    }
    return `${API_BASE_URL.replace(/\/$/, '')}/${url.replace(/^\//, '')}`;
  };

  const formatPdfRecommendations = (pdfs: PDFRecommendation[] | any[]): PDFRecommendation[] =>
    pdfs.map(pdf => ({
      doc_id: pdf.doc_id || pdf.filename || pdf.url,
      title: pdf.title || 'Recommended Instructions',
      description: pdf.description || '',
      filename: pdf.filename || '',
      url: resolvePdfUrl(pdf.url || pdf.public_url),
      pages: pdf.pages || 0,
      relevance: pdf.relevance || 'Relevant',
      platform: pdf.platform ? pdf.platform.charAt(0).toUpperCase() + pdf.platform.slice(1) : 'General',
      file_size_kb: pdf.file_size_kb || 0,
      tags: pdf.tags || [],
      created_at: pdf.created_at ?? null,
      updated_at: pdf.updated_at ?? null,
    }));

  const toggleThought = useCallback((messageId: string) => {
    setMessages(prev =>
      prev.map(m =>
        m.id === messageId
          ? { ...m, isThinkingExpanded: !m.isThinkingExpanded }
          : m
      )
    );
  }, []);

  const sendMessageStreaming = async (messageText: string, imageBase64?: string) => {
    const userMessage: Message = {
      id: Date.now().toString(),
      type: 'user',
      content: messageText,
      timestamp: new Date(),
      imagePreviewUrl: imageBase64
        ? `data:image/png;base64,${imageBase64}`
        : undefined,
    };

    const assistantPlaceholder: Message = {
      id: (Date.now() + 1).toString(),
      type: 'assistant',
      content: '',
      timestamp: new Date(),
      isStreaming: true,
      thought: '',
      isThinkingExpanded: false,
    };

    setMessages(prev => [...prev, userMessage, assistantPlaceholder]);
    setPdfRecommendations([]);
    setInputValue('');
    setIsLoading(true);

    try {
      const response = await fetch(STREAM_ENDPOINT, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          message: messageText,
          session_id: sessionId,
          image_base64: imageBase64 ?? null,
        }),
      });

      if (!response.ok) {
        throw new Error(`Stream request failed: ${response.status}`);
      }

      if (!response.body) {
        throw new Error('No response body');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let completed = false;

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) {
            continue;
          }

          const jsonStr = line.slice(6).trim();
          if (!jsonStr) {
            continue;
          }

          try {
            const event = JSON.parse(jsonStr);

            if (event.type === 'thought') {
              setMessages(prev =>
                prev.map(m =>
                  m.id === assistantPlaceholder.id
                    ? {
                        ...m,
                        thought: (m.thought || '') + event.token,
                        debug_mode: true,
                      }
                    : m
                )
              );
              continue;
            }

            if (event.type === 'response' && event.token) {
              setMessages(prev =>
                prev.map(m =>
                  m.id === assistantPlaceholder.id
                    ? {
                        ...m,
                        content: m.content + event.token,
                      }
                    : m
                )
              );
              continue;
            }

            if (event.done) {
              completed = true;
              setMessages(prev =>
                prev.map(m =>
                  m.id === assistantPlaceholder.id
                    ? {
                        ...m,
                        isStreaming: false,
                        source: event.source ?? m.source,
                        confidence: event.confidence ?? m.confidence,
                        debug_mode: event.debug_mode ?? m.debug_mode,
                        thought: event.thought ?? m.thought,
                      }
                    : m
                )
              );

              if (event.recommended_pdfs && event.recommended_pdfs.length > 0) {
                const formattedPDFs = formatPdfRecommendations(event.recommended_pdfs);
                setPdfRecommendations(formattedPDFs);
                console.log('📄 PDF Recommendations loaded:', formattedPDFs.length);
                console.log('📄 First PDF URL:', formattedPDFs[0]?.url);
              } else {
                setPdfRecommendations([]);
              }

              setApiStatus('connected');
              setIsLoading(false);
              return;
            }
          } catch {
            // Ignore malformed SSE fragments
          }
        }
      }

      if (!completed) {
        throw new Error('Stream closed before completion');
      }
    } catch (error) {
      console.error('Stream error:', error);
      setMessages(prev =>
        prev.map(m =>
          m.id === assistantPlaceholder.id
            ? {
                ...m,
                content: 'Something went wrong. Please try again.',
                isStreaming: false,
              }
            : m
        )
      );
      setPdfRecommendations([]);
      setApiStatus('disconnected');
    } finally {
      setIsLoading(false);
    }
  };

  const handleSendMessage = async (content: string, imageBase64?: string) => {
    await sendMessageStreaming(content, imageBase64);
  };

  const handlePromptClick = (prompt: string) => {
    handleSendMessage(prompt);
  };

  const focusChatInput = () => {
    requestAnimationFrame(() => {
      chatInputRef.current?.focus();
      const length = chatInputRef.current?.value.length ?? 0;
      chatInputRef.current?.setSelectionRange(length, length);
      chatInputRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
  };

  const handleOtherSelect = () => {
    focusChatInput();
  };

  const hasStreamingMessage = messages.some(message => message.isStreaming);

  return (
    <div className="flex h-screen bg-white">
      <FAQSidebar
        onSendMessage={(text) => {
          setInputValue(text);
          handleSendMessage(text);
        }}
        onOtherSelect={handleOtherSelect}
      />

      {/* Left Panel - Chat Interface */}
      <div className="flex flex-col flex-1 min-w-0">
        <ChatHeader apiStatus={apiStatus} />
        
        <div className="flex-1 overflow-y-auto px-4 py-6">
          {messages.length === 0 ? (
            <WelcomeState onPromptClick={handlePromptClick} />
          ) : (
            <div className="max-w-4xl mx-auto space-y-4">
              {messages.map((message) => (
                <ChatMessage
                  key={message.id}
                  message={message}
                  onToggleThought={toggleThought}
                />
              ))}
              
              {/* Loading indicator */}
              {isLoading && !hasStreamingMessage && (
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

        <ChatInput
          onSendMessage={handleSendMessage}
          value={inputValue}
          onChange={setInputValue}
          disabled={isLoading}
          inputRef={chatInputRef}
        />
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
