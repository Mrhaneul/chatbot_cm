import React from 'react';

/**
 * linkify.tsx
 * -----------
 * Converts plain text containing URLs and email addresses into
 * React elements with clickable <a> tags.
 *
 * Handles:
 *   - https:// and http:// URLs
 *   - Email addresses (e.g. ImmediateAccess@calbaptist.edu)
 *
 * Link color: CBU gold (#A07400)
 * URLs open in a new tab.
 * Emails open the mail client via mailto:.
 */

export function linkify(text: string): React.ReactNode[] {
  const pattern = /(\bhttps?:\/\/[^\s<>"')\]]+|\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})/g;
  const parts = text.split(pattern);

  return parts.map((part, index) => {
    if (/^https?:\/\//i.test(part)) {
      return (
        <a
          key={index}
          href={part}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            color: '#A07400',
            textDecoration: 'underline',
            wordBreak: 'break-all',
          }}
        >
          {part}
        </a>
      );
    }

    if (/^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$/.test(part)) {
      return (
        <a
          key={index}
          href={`mailto:${part}`}
          style={{
            color: '#A07400',
            textDecoration: 'underline',
          }}
        >
          {part}
        </a>
      );
    }

    return part;
  });
}