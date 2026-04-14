import React from 'react';
import lanceAvatar from '../assets/lance.png';
import { Message } from '../types';
import { linkify } from '../utils/linkify';

interface ChatMessageProps {
  message: Message;
}

export function ChatMessage({ message }: ChatMessageProps) {
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
          <p className="whitespace-pre-wrap">{message.content}</p>
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
      <div className="bg-[#FFFAEB] border border-[#165FB3]/30 text-[#002554] px-6 py-3 rounded-2xl rounded-tl-sm max-w-[75%] shadow-sm">
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
          {message.isStreaming && (
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
