import React, { useRef, useState } from 'react';
import { Send, ImagePlus, X } from 'lucide-react';

interface ChatInputProps {
  onSendMessage: (content: string, imageBase64?: string) => void;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  inputRef?: React.RefObject<HTMLTextAreaElement | null>;
}

export function ChatInput({ onSendMessage, value, onChange, disabled = false, inputRef }: ChatInputProps) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [imageBase64, setImageBase64] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleImageSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Only accept images
    if (!file.type.startsWith('image/')) return;

    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      // result is "data:image/png;base64,XXXX..." — strip the prefix for the API
      const base64 = result.split(',')[1];
      setImageBase64(base64);
      setPreviewUrl(result); // keep full data URL for the <img> preview
    };
    reader.readAsDataURL(file);

    // Reset file input so the same file can be re-selected if cleared
    e.target.value = '';
  };

  const clearImage = () => {
    setPreviewUrl(null);
    setImageBase64(null);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if ((value.trim() || imageBase64) && !disabled) {
      onSendMessage(value, imageBase64 ?? undefined);
      onChange('');
      clearImage();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const canSend = (value.trim().length > 0 || imageBase64 !== null) && !disabled;

  return (
    <div className="border-t border-gray-200 bg-white px-4 py-4">
      <div className="max-w-4xl mx-auto">

        {/* Screenshot preview pill */}
        {previewUrl && (
          <div className="flex items-center gap-2 mb-2 px-1">
            <div className="relative inline-flex items-center gap-2 bg-gray-100 border border-gray-300 rounded-lg px-3 py-1.5">
              <img
                src={previewUrl}
                alt="Screenshot preview"
                className="h-8 w-8 object-cover rounded"
              />
              <span className="text-xs text-gray-600 max-w-[120px] truncate">Screenshot attached</span>
              <button
                type="button"
                onClick={clearImage}
                className="ml-1 text-gray-400 hover:text-gray-600 transition-colors"
                aria-label="Remove screenshot"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        )}

        <div className="flex gap-2 items-end">
          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            className="hidden"
            style={{ display: 'none' }}
            onChange={handleImageSelect}
            disabled={disabled}
          />

          {/* Screenshot attach button */}
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled}
            className="p-3 text-[#165FB3] hover:text-[#A07400] border-2 border-[#165FB3] hover:border-[#A07400] rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0"
            aria-label="Attach screenshot"
            title="Attach a screenshot for Lance to analyze"
          >
            <ImagePlus className="w-5 h-5" />
          </button>

          <div className="flex-1 relative">
            <textarea
              ref={inputRef}
              value={value}
              onChange={(e) => onChange(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={disabled}
              placeholder={
                disabled
                  ? 'Waiting for response...'
                  : imageBase64
                  ? 'Describe the issue or just press Send...'
                  : 'Ask about textbook access, platform issues, or Immediate Access...'
              }
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
            type="button"
            onClick={handleSubmit}
            disabled={!canSend}
            className="p-3 bg-[#A07400] text-white rounded-lg hover:bg-[#002554] disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex-shrink-0"
            aria-label="Send message"
          >
            <Send className="w-5 h-5" />
          </button>
        </div>
      </div>
    </div>
  );
}
