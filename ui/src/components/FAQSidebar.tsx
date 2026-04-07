import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, Menu, X } from 'lucide-react';
import { faqConfig } from '../faqConfig';
import { useIsMobile } from './ui/use-mobile';

interface FAQSidebarProps {
  onSendMessage: (text: string) => void;
  onOtherSelect: () => void;
}

const FOCUSABLE_SELECTOR = [
  'button:not([disabled])',
  '[href]',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

export function FAQSidebar({ onSendMessage, onOtherSelect }: FAQSidebarProps) {
  const isMobile = useIsMobile();
  const [isOpen, setIsOpen] = useState(false);
  const [openCategory, setOpenCategory] = useState<string | null>(null);
  const [openSubcategories, setOpenSubcategories] = useState<Record<string, boolean>>({});
  const [activeOption, setActiveOption] = useState<string | null>(null);
  const toggleButtonRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  const sidebarWidth = isMobile ? '85vw' : '280px';
  const sidebarMaxWidth = isMobile ? '320px' : '280px';

  const closeSidebar = useCallback(() => {
    setIsOpen(false);
  }, []);

  const focusDialog = () => {
    const focusableElements = dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
    focusableElements?.[0]?.focus();
  };

  useEffect(() => {
    if (isOpen) {
      requestAnimationFrame(() => {
        focusDialog();
      });
      return;
    }

    toggleButtonRef.current?.focus();
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeSidebar();
        return;
      }

      if (event.key !== 'Tab' || !dialogRef.current) {
        return;
      }

      const focusableElements = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)
      );

      if (focusableElements.length === 0) {
        return;
      }

      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];
      const activeElement = document.activeElement as HTMLElement | null;

      if (event.shiftKey && activeElement === firstElement) {
        event.preventDefault();
        lastElement.focus();
      } else if (!event.shiftKey && activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  const handleCategoryToggle = (category: string) => {
    setOpenCategory((current) => (current === category ? null : category));
  };

  const handleSubcategoryToggle = (key: string) => {
    setOpenSubcategories((prev) => ({
      ...prev,
      [key]: !prev[key],
    }));
  };

  const selectAndClose = (callback: () => void) => {
    closeSidebar();
    window.setTimeout(() => {
      callback();
    }, 260);
  };

  const handleOptionClick = (option: string) => {
    setActiveOption(option);
    window.setTimeout(() => {
      selectAndClose(() => onSendMessage(option));
    }, 120);
  };

  const handleOtherClick = () => {
    setActiveOption(null);
    selectAndClose(onOtherSelect);
  };

  const renderedCategories = useMemo(() => faqConfig, []);

  return (
    <>
      <style>{`
        .faq-sidebar-scrollbar::-webkit-scrollbar {
          width: 6px;
        }

        .faq-sidebar-scrollbar::-webkit-scrollbar-track {
          background: #C8D8EE;
        }

        .faq-sidebar-scrollbar::-webkit-scrollbar-thumb {
          background: #002554;
          border-radius: 999px;
        }
      `}</style>

      <button
        ref={toggleButtonRef}
        type="button"
        onClick={() => setIsOpen(prev => !prev)}
        aria-label={isOpen ? 'Close FAQ menu' : 'Open FAQ menu'}
        style={{
          position: 'fixed',
          left: 0,
          top: '50%',
          transform: 'translateY(-50%)',
          zIndex: 45,
          backgroundColor: '#002554',
          color: '#ffffff',
          border: 'none',
          borderRadius: '0 8px 8px 0',
          width: '28px',
          height: '72px',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: '2px 0 8px rgba(0,37,84,0.25)',
          visibility: isOpen ? 'hidden' : 'visible',
          pointerEvents: isOpen ? 'none' : 'auto',
          transition: 'background-color 160ms ease-out, visibility 220ms',
        }}
        onMouseEnter={(event) => {
          event.currentTarget.style.backgroundColor = '#173c6d';
        }}
        onMouseLeave={(event) => {
          event.currentTarget.style.backgroundColor = '#002554';
        }}
      >
        <Menu size={18} />
      </button>

      <div
        className="fixed inset-0 z-40"
        onClick={closeSidebar}
        aria-hidden="true"
        style={{
          backgroundColor: 'rgba(0, 21, 47, 0.35)',
          opacity: isOpen ? 1 : 0,
          pointerEvents: isOpen ? 'auto' : 'none',
          transition: 'opacity 220ms cubic-bezier(0.4,0,0.2,1)',
        }}
      />

      <aside
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Browse FAQ topics"
        aria-hidden={isOpen ? undefined : true}
        className="fixed left-0 top-0 z-50 border-l-[3px] border-l-[#002554] bg-white"
        style={{
          width: sidebarWidth,
          maxWidth: sidebarMaxWidth,
          height: '100vh',
          transform: isOpen ? 'translateX(0)' : 'translateX(-100%)',
          visibility: isOpen ? 'visible' : 'hidden',
          pointerEvents: isOpen ? 'auto' : 'none',
          boxShadow: '4px 0 16px rgba(0, 37, 84, 0.12)',
          transition: 'transform 220ms cubic-bezier(0.4,0,0.2,1), visibility 220ms',
        }}
      >
        <div className="flex h-full min-h-0 flex-col">
          <div
            className="flex items-start justify-between px-4 py-4"
            style={{ borderBottom: '1px solid #E8EDF5' }}
          >
            <div>
              <h2
                className="font-bold text-[#002554]"
                style={{ fontSize: '16px', lineHeight: '20px' }}
              >
                Quick Help
              </h2>
              <p className="mt-1 text-sm text-[#48698C]">Browse topics and get instant answers</p>
            </div>
            <button
              type="button"
              onClick={closeSidebar}
              className="p-1 text-[#002554] focus:outline-none focus:ring-2 focus:ring-[#A07400]/60"
              aria-label="Close FAQ menu"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="faq-sidebar-scrollbar min-h-0 flex-1 overflow-y-auto">
            <div>
              {renderedCategories.map((category) => {
                const isOther = category.category === 'Other';
                const isCategoryOpen = openCategory === category.category;

                return (
                  <section
                    key={category.category}
                    style={{ borderBottom: '1px solid #F0F4FA' }}
                  >
                    <button
                      type="button"
                      onClick={() => {
                        if (isOther) {
                          handleOtherClick();
                          return;
                        }
                        handleCategoryToggle(category.category);
                      }}
                      className="flex w-full items-center justify-between gap-3 text-left focus:outline-none focus:ring-2 focus:ring-inset focus:ring-[#A07400]/50"
                      style={{
                        minHeight: '48px',
                        paddingLeft: '16px',
                        paddingRight: '12px',
                        backgroundColor: isCategoryOpen ? '#EEF3FB' : '#FFFFFF',
                        transition: 'background-color 160ms ease-out',
                      }}
                      onMouseEnter={(event) => {
                        if (!isCategoryOpen) {
                          event.currentTarget.style.backgroundColor = '#F5F8FF';
                        }
                      }}
                      onMouseLeave={(event) => {
                        event.currentTarget.style.backgroundColor = isCategoryOpen ? '#EEF3FB' : '#FFFFFF';
                      }}
                      aria-expanded={isOther ? undefined : isCategoryOpen}
                    >
                      <span className="flex items-center gap-2">
                        {category.icon ? <span className="text-base">{category.icon}</span> : null}
                        <span
                          className="font-semibold text-[#002554]"
                          style={{ fontSize: '14px', lineHeight: '18px' }}
                        >
                          {category.category}
                        </span>
                      </span>
                      {!isOther ? (
                        <ChevronDown
                          className={`h-4 w-4 text-[#002554] transition-transform ${isCategoryOpen ? 'rotate-180' : ''}`}
                        />
                      ) : null}
                    </button>

                    {!isOther && isCategoryOpen ? (
                      <div style={{ paddingLeft: '16px', backgroundColor: '#FAFBFF' }}>
                        {category.subcategories ? (
                          <div>
                            {category.subcategories.map((subcategory) => {
                              const subKey = `${category.category}:${subcategory.label}`;
                              const isSubOpen = openSubcategories[subKey] ?? false;
                              return (
                                <div key={subKey} style={{ borderBottom: '1px solid #F0F4FA' }}>
                                  <button
                                    type="button"
                                    onClick={() => handleSubcategoryToggle(subKey)}
                                    className="flex w-full items-center justify-between gap-2 text-left focus:outline-none focus:ring-2 focus:ring-inset focus:ring-[#A07400]/40"
                                    style={{
                                      minHeight: '44px',
                                      paddingLeft: '24px',
                                      paddingRight: '12px',
                                      color: '#374F6B',
                                      fontSize: '13px',
                                      fontWeight: 500,
                                      backgroundColor: isSubOpen ? '#EEF3FB' : '#FAFBFF',
                                      transition: 'background-color 160ms ease-out',
                                    }}
                                    onMouseEnter={(event) => {
                                      if (!isSubOpen) {
                                        event.currentTarget.style.backgroundColor = '#EEF3FB';
                                      }
                                    }}
                                    onMouseLeave={(event) => {
                                      event.currentTarget.style.backgroundColor = isSubOpen ? '#EEF3FB' : '#FAFBFF';
                                    }}
                                    aria-expanded={isSubOpen}
                                  >
                                    <span>{subcategory.label}</span>
                                    <ChevronDown
                                      className={`h-4 w-4 transition-transform ${isSubOpen ? 'rotate-180' : ''}`}
                                    />
                                  </button>
                                  {isSubOpen ? (
                                    <div>
                                      {subcategory.options.map((option) => (
                                        <button
                                          key={option}
                                          type="button"
                                          onClick={() => handleOptionClick(option)}
                                          className="w-full text-left transition-colors focus:outline-none focus:ring-2 focus:ring-[#A07400]/50"
                                          style={{
                                            minHeight: '40px',
                                            padding: '10px 16px 10px 32px',
                                            fontSize: '13px',
                                            fontWeight: 400,
                                            color: activeOption === option ? '#002554' : '#2A4665',
                                            backgroundColor: activeOption === option ? '#D4E4F7' : '#FAFBFF',
                                            borderLeft: '2px solid transparent',
                                          }}
                                          onMouseEnter={(event) => {
                                            if (activeOption !== option) {
                                              event.currentTarget.style.backgroundColor = '#E8F0FB';
                                              event.currentTarget.style.borderLeftColor = '#A07400';
                                            }
                                          }}
                                          onMouseLeave={(event) => {
                                            event.currentTarget.style.backgroundColor =
                                              activeOption === option ? '#D4E4F7' : '#FAFBFF';
                                            event.currentTarget.style.borderLeftColor = 'transparent';
                                          }}
                                        >
                                          {option}
                                        </button>
                                      ))}
                                    </div>
                                  ) : null}
                                </div>
                              );
                            })}
                          </div>
                        ) : (
                          <div>
                            {(category.options ?? []).map((option) => (
                              <button
                                key={option}
                                type="button"
                                onClick={() => handleOptionClick(option)}
                                className="w-full text-left transition-colors focus:outline-none focus:ring-2 focus:ring-[#A07400]/50"
                                style={{
                                  minHeight: '40px',
                                  padding: '10px 16px 10px 32px',
                                  fontSize: '13px',
                                  fontWeight: 400,
                                  color: activeOption === option ? '#002554' : '#2A4665',
                                  backgroundColor: activeOption === option ? '#D4E4F7' : '#FAFBFF',
                                  borderLeft: '2px solid transparent',
                                }}
                                onMouseEnter={(event) => {
                                  if (activeOption !== option) {
                                    event.currentTarget.style.backgroundColor = '#E8F0FB';
                                    event.currentTarget.style.borderLeftColor = '#A07400';
                                  }
                                }}
                                onMouseLeave={(event) => {
                                  event.currentTarget.style.backgroundColor =
                                    activeOption === option ? '#D4E4F7' : '#FAFBFF';
                                  event.currentTarget.style.borderLeftColor = 'transparent';
                                }}
                              >
                                {option}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    ) : null}
                  </section>
                );
              })}
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
