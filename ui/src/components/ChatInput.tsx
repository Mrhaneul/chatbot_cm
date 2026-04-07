import React from 'react';
import { Send } from 'lucide-react';

interface ChatInputProps {
  onSendMessage: (content: string) => void;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  inputRef?: React.RefObject<HTMLTextAreaElement | null>;
}

export function ChatInput({ onSendMessage, value, onChange, disabled = false, inputRef }: ChatInputProps) {
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (value.trim() && !disabled) {
      onSendMessage(value);
      onChange('');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <div className="border-t border-gray-200 bg-white px-4 py-4">
      <form onSubmit={handleSubmit} className="max-w-4xl mx-auto">
        <div className="flex gap-2 items-end">
          <div className="flex-1 relative">
            <textarea
              ref={inputRef}
              value={value}
              onChange={(e) => onChange(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={disabled}
              placeholder={disabled ? "Waiting for response..." : "Ask about textbook access, platform issues, or Immediate Access..."}
              className="w-full px-4 py-3 border-2 border-[#165FB3] rounded-xl resize-none focus:outline-none focus:border-[#A07400] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              rows={1}
              style={{
                minHeight: '52px',
                maxHeight: '150px',
                overflowY: 'auto',
              }}
            />
          </div>

          <button
            type="submit"
            disabled={!value.trim() || disabled}
            className="p-3 bg-[#A07400] text-white rounded-lg hover:bg-[#002554] disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex-shrink-0"
            aria-label="Send message"
          >
            <Send className="w-5 h-5" />
          </button>
        </div>
      </form>
    </div>
  );
}
