/**
 * FAQ SIDEBAR CONTENT CONFIGURATION
 * ===================================
 * This is the file to edit when you want to:
 *   - Add a new question option
 *   - Remove an existing option
 *   - Add a new category or subcategory
 *   - Change the wording of an existing option
 *
 * HOW TO EDIT:
 *   1. Find the category you want to change
 *   2. Add or remove items from the "options" array
 *   3. Save the file
 *   4. Run: npm run build
 *   5. Deploy to Firebase: firebase deploy --only hosting
 *
 * Do NOT edit FAQSidebar.tsx unless you need to change
 * the sidebar's appearance or behavior.
 */

export interface FAQSubcategory {
  label: string;
  options: string[];
}

export interface FAQCategory {
  category: string;
  icon: string;
  options?: string[];
  subcategories?: FAQSubcategory[];
}

export const faqConfig: FAQCategory[] = [
  {
    category: "Textbooks & Immediate Access",
    icon: "📚",
    subcategories: [
      {
        label: "I can't access my textbook",
        options: [
          "I can't access my Cengage / MindTap textbook",
          "I can't access my McGraw Hill Connect textbook",
          "I can't access my Pearson MyLab / Mastering textbook",
          "I can't access my WileyPlus textbook",
          "I can't access my Bedford Bookshelf textbook",
          "I can't access my Vitalsource",
          "I can't access my ZyBooks textbook",
          "I can't access my Sage Vantage textbook",
          "I can't access my Macmillan Achieve textbook",
          "I can't access my SimuCase textbook",
          "I can't access my Norton / InQuizitive textbook",
          "I can't access my Stukent textbook"
        ]
      },
      {
        label: "My books aren't showing",
        options: [
          "My book is not showing up in Immediate Access",
          "I see '0 Courses, 0 Materials' on VitalSource"
        ]
      },
      {
        label: "General questions",
        options: [
          "What is Immediate Access?",
          "How do I opt out of Immediate Access?",
          "My textbook is missing from my Immediate Access bundle"
        ]
      }
    ]
  },
  {
    category: "Campus Store",
    icon: "🏪",
    options: [
      "What are the Campus Store hours?",
      "Where is the Campus Store located?",
      "What does the Campus Store sell?"
    ]
  },
  {
    category: "Return & Refund Policy",
    icon: "",
    options: [
      "How do I return a textbook?",
      "What is the refund policy for Immediate Access?"
    ]
  },
  {
    category: "Other",
    icon: "💬",
    options: []
  }
];
