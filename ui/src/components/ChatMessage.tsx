import React from 'react';
import { ChevronRight } from 'lucide-react';
import lanceAvatar from '../assets/lance.png';
import { Message } from '../types';
import { linkify } from '../utils/linkify';

interface ChatMessageProps {
  message: Message;
  onToggleThought?: (id: string) => void;
}

export function ChatMessage({ message, onToggleThought }: ChatMessageProps) {
  const formatContent = (content: string) => {
    const lines = content.split('\n');
    return lines.map((line, index) => {
      // Check for bold text (**text**)
      const boldRegex = /\*\*(.*?)\*\*/g;
      const parts: React.ReactNode[] = [];
      let lastIndex = 0;
      let match;

      while ((match = boldRegex.exec(line)) !== null) {
        if (match.index > lastIndex) {
          // Apply linkify to the plain text segment before the bold match
          const plainText = line.substring(lastIndex, match.index);
          parts.push(...linkify(plainText));
        }
        parts.push(
          <strong key={`bold-${index}-${match.index}`} className="font-bold text-[#002554]">
            {match[1]}
          </strong>
        );
        lastIndex = match.index + match[0].length;
      }

      if (lastIndex < line.length) {
        // Apply linkify to remaining plain text after last bold match
        const remaining = line.substring(lastIndex);
        parts.push(...linkify(remaining));
      }

      if (parts.length === 0 && line.trim() === '') {
        return <br key={index} />;
      }

      // Numbered list item
      if (line.trim().match(/^[\d]+\./)) {
        return (
          <div key={index} className="ml-4">
            {parts.length > 0 ? parts : linkify(line)}
          </div>
        );
      }

      // Bullet list item
      if (line.trim().startsWith('•') || line.trim().startsWith('-')) {
        return (
          <div key={index} className="ml-4">
            {parts.length > 0 ? parts : linkify(line)}
          </div>
        );
      }

      return (
        <div key={index}>
          {parts.length > 0 ? parts : linkify(line)}
        </div>
      );
    });
  };

  if (message.type === 'user') {
    return (
      <div className="flex justify-end mb-4">
        <div className="bg-[#165FB3] text-white px-6 py-3 rounded-2xl rounded-tr-sm max-w-[70%] shadow-sm">
          {/* Screenshot thumbnail — shown only when the user attached an image */}
          {message.imagePreviewUrl && (
            <div className="mb-2">
              <img
                src={message.imagePreviewUrl}
                alt="Attached screenshot"
                className="rounded-lg max-h-48 max-w-full object-contain border border-white/20"
              />
            </div>
          )}
          {message.content && (
            <p className="whitespace-pre-wrap">{message.content}</p>
          )}
        </div>
      </div>
    );
  }

  if (message.type === 'system') {
    return (
      <div className="flex justify-center mb-4">
        <div className="bg-[#5ACBF2]/20 text-[#002554] px-6 py-3 rounded-lg max-w-[80%] text-center">
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>
      </div>
    );
  }

  // Assistant message
  return (
    <div className="flex gap-3 mb-4">
      <div className="flex-shrink-0">
        <div className="w-10 h-10 rounded-full overflow-hidden shadow-sm">
          <img
            src={lanceAvatar}
            alt="Lance Assistant"
            className="w-full h-full object-cover"
          />
        </div>
      </div>
      <div className="flex flex-col gap-1 max-w-[75%]">
        {(message.thought || message.isStreaming) && message.debug_mode && (
          <div style={{ marginBottom: '4px' }}>
            <button
              onClick={() => onToggleThought?.(message.id)}
              className="group flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium text-[#A07400] bg-amber-50 border border-amber-200 hover:bg-amber-100 hover:border-amber-300 transition-all duration-200 cursor-pointer select-none"
            >
              <ChevronRight
                className="w-3 h-3 transition-transform duration-200"
                style={{ transform: message.isThinkingExpanded ? 'rotate(90deg)' : 'rotate(0deg)' }}
              />
              {message.isStreaming && !message.content ? 'Thinking...' : 'Thought process'}
              {message.isStreaming && !message.content && (
                <span className="inline-block w-px h-2.5 bg-[#A07400] ml-0.5 animate-pulse" />
              )}
            </button>

            <div style={{
              display: 'grid',
              gridTemplateRows: message.isThinkingExpanded && message.thought ? '1fr' : '0fr',
              transition: 'grid-template-rows 0.25s ease',
            }}>
              <div style={{ overflow: 'hidden' }}>
                <div style={{
                  marginTop: '6px',
                  padding: '10px 14px',
                  backgroundColor: 'rgba(160, 116, 0, 0.06)',
                  border: '1px solid rgba(160, 116, 0, 0.2)',
                  borderRadius: '8px',
                  fontSize: '12px',
                  color: '#666',
                  fontStyle: 'italic',
                  maxHeight: '200px',
                  overflowY: 'auto',
                  whiteSpace: 'pre-wrap',
                  lineHeight: '1.5',
                }}>
                  {message.thought}
                </div>
              </div>
            </div>
          </div>
        )}

        <div className="bg-[#FFFAEB] border border-[#165FB3]/30 text-[#002554] px-6 py-3 rounded-2xl rounded-tl-sm shadow-sm">
          {message.debug_mode && (
            <span style={{
              fontSize: '10px',
              color: '#A07400',
              border: '1px solid #A07400',
              borderRadius: '4px',
              padding: '1px 4px',
              marginBottom: '6px',
              display: 'inline-block',
            }}>
              LLM
            </span>
          )}
          <div className="whitespace-pre-wrap space-y-2">
            {formatContent(message.content)}
          </div>
          {message.isStreaming && message.content && (
            <span
              style={{
                display: 'inline-block',
                width: '2px',
                height: '1em',
                backgroundColor: '#A07400',
                marginLeft: '2px',
                animation: 'blink 1s step-end infinite',
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
