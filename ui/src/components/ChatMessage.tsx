import React from 'react';
import lanceAvatar from 'figma:asset/e652a3d023b7ebc5964535b039cbdac6622507bd.png';

interface Message {
  id: string;
  type: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
}

interface ChatMessageProps {
  message: Message;
}

export function ChatMessage({ message }: ChatMessageProps) {
  const formatContent = (content: string) => {
    // Split by line breaks and format
    const lines = content.split('\n');
    
    return lines.map((line, index) => {
      // Check for bold text (**text**)
      const boldRegex = /\*\*(.*?)\*\*/g;
      const parts = [];
      let lastIndex = 0;
      let match;

      while ((match = boldRegex.exec(line)) !== null) {
        if (match.index > lastIndex) {
          parts.push(line.substring(lastIndex, match.index));
        }
        parts.push(
          <strong key={`bold-${index}-${match.index}`} className="font-bold text-[#002554]">
            {match[1]}
          </strong>
        );
        lastIndex = match.index + match[0].length;
      }

      if (lastIndex < line.length) {
        parts.push(line.substring(lastIndex));
      }

      if (parts.length === 0 && line.trim() === '') {
        return <br key={index} />;
      }

      // Check if it's a list item
      if (line.trim().match(/^[\d]+\./)) {
        return (
          <div key={index} className="ml-4">
            {parts.length > 0 ? parts : line}
          </div>
        );
      }

      if (line.trim().startsWith('•')) {
        return (
          <div key={index} className="ml-4">
            {parts.length > 0 ? parts : line}
          </div>
        );
      }

      return (
        <div key={index}>
          {parts.length > 0 ? parts : line}
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
        <div className="whitespace-pre-wrap space-y-2">
          {formatContent(message.content)}
        </div>
      </div>
    </div>
  );
}