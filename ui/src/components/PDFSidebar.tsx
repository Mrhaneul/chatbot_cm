import React from "react";
import {
  FileText,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { PDFRecommendationCard } from "./PDFRecommendationCard";

interface PDFRecommendation {
  id: string;
  title: string;
  description: string;
  platform: string;
  relevance: "best" | "related" | "relevant";
  lastUpdated: string;
  pageCount: number;
}

interface PDFSidebarProps {
  recommendations: PDFRecommendation[];
  isOpen: boolean;
  onToggle: () => void;
}

export function PDFSidebar({
  recommendations,
  isOpen,
  onToggle,
}: PDFSidebarProps) {
  return (
    <>
      {/* Toggle button for mobile/tablet */}
      <button
        onClick={onToggle}
        className="fixed right-0 top-1/2 -translate-y-1/2 bg-[#A07400] text-white p-2 rounded-l-lg shadow-lg z-50 lg:hidden"
        aria-label={isOpen ? "Close sidebar" : "Open sidebar"}
      >
        {isOpen ? (
          <ChevronRight className="w-5 h-5" />
        ) : (
          <ChevronLeft className="w-5 h-5" />
        )}
      </button>

      {/* Sidebar */}
      <aside
        className={`
          fixed lg:relative right-0 top-0 h-full
          w-full sm:w-96 lg:w-[400px] xl:w-[450px]
          bg-white border-l border-gray-200
          flex flex-col
          transition-transform duration-300 ease-in-out z-40
          ${isOpen ? "translate-x-0" : "translate-x-full lg:translate-x-0"}
        `}
      >
        {/* Header */}
        <div className="bg-[#002554] text-white px-6 py-4 flex items-center gap-3">
          <FileText className="w-6 h-6 text-[#A07400]" />
          <div>
            <h2 className="text-xl font-bold">
              Recommended Instructions
            </h2>
            <p className="text-sm text-white/80">
              PDF Guides & Support Documents
            </p>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          {recommendations.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full px-6 text-center bg-[#FFFAEB]/30">
              <FileText className="w-16 h-16 text-gray-300 mb-4" />
              <p className="text-[#165FB3] text-sm">
                PDF recommendations will appear here based on
                your conversation
              </p>
            </div>
          ) : (
            <div className="p-4 space-y-4">
              {recommendations.map((recommendation) => (
                <PDFRecommendationCard
                  key={recommendation.id}
                  recommendation={recommendation}
                />
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="bg-[#FFFAEB] px-6 py-4 border-t border-gray-200">
          <p className="text-sm text-[#002554] text-center">
            Can't find what you need?{" "}
            <button className="text-[#165FB3] hover:text-[#A07400] font-medium underline">
              Ask in the chat!
            </button>
          </p>
        </div>
      </aside>

      {/* Overlay for mobile */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-30 lg:hidden"
          onClick={onToggle}
        />
      )}
    </>
  );
}