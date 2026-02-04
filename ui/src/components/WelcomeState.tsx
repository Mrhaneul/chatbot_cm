import React from 'react';
import cbuLogo1 from 'figma:asset/117d49da1b6dff5d976520b90bf148fdd350b221.png';

interface WelcomeStateProps {
  onPromptClick: (prompt: string) => void;
}

export function WelcomeState({ onPromptClick }: WelcomeStateProps) {
  const suggestedPrompts = [
    "I can't access my Cengage textbook",
    "Help with McGraw Hill Connect",
    "What is Immediate Access?",
    "My Pearson login isn't working",
  ];

  return (
    <div className="max-w-3xl mx-auto text-center py-12">
      <img 
        src={cbuLogo1} 
        alt="CBU Shield" 
        className="h-24 w-auto mx-auto mb-6"
      />
      
      <h2 className="text-3xl font-bold text-[#002554] mb-3">
        Hi I'm Lance. How can I help you?
      </h2>
      
      <p className="text-[#165FB3] text-lg mb-12">
        Get help with Immediate Access and digital textbooks
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {suggestedPrompts.map((prompt, index) => (
          <button
            key={index}
            onClick={() => onPromptClick(prompt)}
            className="bg-white border border-[#165FB3] text-[#002554] px-6 py-4 rounded-lg hover:bg-[#FFFAEB] hover:border-[#A07400] transition-all text-left font-medium shadow-sm"
          >
            {prompt}
          </button>
        ))}
      </div>
    </div>
  );
}