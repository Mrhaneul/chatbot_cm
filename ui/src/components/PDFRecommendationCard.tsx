import React from 'react';
import { FileText, Download, Calendar, FileStack } from 'lucide-react';

interface PDFRecommendation {
  id: string;
  title: string;
  description: string;
  platform: string;
  relevance: 'best' | 'related' | 'relevant';
  lastUpdated: string;
  pageCount: number;
}

interface PDFRecommendationCardProps {
  recommendation: PDFRecommendation;
}

export function PDFRecommendationCard({ recommendation }: PDFRecommendationCardProps) {
  const getRelevanceBadge = () => {
    const badges = {
      best: {
        text: 'Best Match',
        className: 'bg-[#A07400] text-white',
      },
      related: {
        text: 'Related',
        className: 'bg-[#165FB3] text-white',
      },
      relevant: {
        text: 'Relevant',
        className: 'bg-[#5ACBF2] text-[#002554]',
      },
    };

    const badge = badges[recommendation.relevance];
    
    return (
      <span className={`absolute top-3 right-3 px-3 py-1 rounded-full text-xs font-semibold ${badge.className}`}>
        {badge.text}
      </span>
    );
  };

  const handleViewPDF = () => {
    // Mock PDF viewing
    alert(`Opening: ${recommendation.title}`);
  };

  const handleDownloadPDF = () => {
    // Mock PDF download
    alert(`Downloading: ${recommendation.title}`);
  };

  return (
    <div className="relative bg-white border border-[#165FB3] rounded-xl p-5 shadow-sm hover:shadow-md transition-shadow">
      {getRelevanceBadge()}

      <div className="flex gap-4 mb-4">
        <div className="flex-shrink-0">
          <div className="w-12 h-12 bg-[#002554]/5 rounded-lg flex items-center justify-center">
            <FileText className="w-6 h-6 text-[#002554]" />
          </div>
        </div>

        <div className="flex-1 min-w-0 pr-20">
          <h3 className="font-bold text-[#002554] text-base mb-1">
            {recommendation.title}
          </h3>
          <p className="text-sm text-[#002554]/70 leading-relaxed">
            {recommendation.description}
          </p>
        </div>
      </div>

      {/* Metadata */}
      <div className="flex items-center gap-4 text-xs text-gray-500 mb-4">
        <div className="flex items-center gap-1">
          <Calendar className="w-3.5 h-3.5" />
          <span>{recommendation.lastUpdated}</span>
        </div>
        <div className="flex items-center gap-1">
          <FileStack className="w-3.5 h-3.5" />
          <span>{recommendation.pageCount} pages</span>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="flex gap-2">
        <button
          onClick={handleViewPDF}
          className="flex-1 bg-[#A07400] text-white px-4 py-2.5 rounded-lg font-medium hover:bg-[#002554] transition-colors text-sm"
        >
          View PDF
        </button>
        <button
          onClick={handleDownloadPDF}
          className="px-4 py-2.5 border-2 border-[#165FB3] text-[#165FB3] rounded-lg hover:bg-[#FFFAEB] transition-colors flex items-center justify-center"
          aria-label="Download PDF"
        >
          <Download className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
