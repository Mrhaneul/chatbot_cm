import React from 'react';
import { Wifi, WifiOff } from 'lucide-react';
import cbuLogo2 from 'figma:asset/3171772f7b3aa5db95557b8d856e5c4223642504.png';

interface ChatHeaderProps {
  apiStatus?: 'connected' | 'disconnected' | 'checking';
}

export function ChatHeader({ apiStatus = 'checking' }: ChatHeaderProps) {
  return (
    <div className="bg-[#002554] text-white px-6 py-4 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <img src={cbuLogo2} alt="CBU logo" className="h-10 w-auto object-contain rounded-md" />
        <div>
          <h1 className="font-semibold text-lg">Lance - Campus Store Assistant</h1>
          <p className="text-sm text-blue-200">Ask me about Immediate Access & textbook platforms</p>
        </div>
      </div>

      {/* API Status Indicator */}
      <div className="flex items-center gap-2">
        {apiStatus === 'connected' && (
          <>
            <Wifi className="w-4 h-4 text-green-400" />
            <span className="text-xs text-green-400">Connected</span>
          </>
        )}
        {apiStatus === 'disconnected' && (
          <>
            <WifiOff className="w-4 h-4 text-red-400" />
            <span className="text-xs text-red-400">Offline</span>
          </>
        )}
        {apiStatus === 'checking' && (
          <span className="text-xs text-blue-200">Connecting...</span>
        )}
      </div>
    </div>
  );
}
