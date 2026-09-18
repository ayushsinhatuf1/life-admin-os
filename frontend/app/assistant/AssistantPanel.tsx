"use client";

import React, { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { api, AssistantSource, SuggestedAction } from "@/lib/api";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: AssistantSource[];
  refused?: boolean;
  suggestedAction?: SuggestedAction | null;
  isStreaming?: boolean;
  timestamp: string;
}

interface AssistantPanelProps {
  familyId: string;
  onOpenDocument?: (docId: string) => void;
}

const PRESET_QUESTIONS = [
  { label: "Health Policy", q: "What is our health insurance policy number and expiry date?" },
  { label: "Car Insurance", q: "When does the vehicle insurance expire?" },
  { label: "Flat 402 Details", q: "What is the area and survey number of Flat 402?" },
  { label: "HDFC FD", q: "What is the deposit number and maturity of our HDFC fixed deposit?" },
  { label: "Inheritance (Refusal)", q: "Who legally inherits this land under Hindu Succession Act?" },
  { label: "Tax Evasion (Refusal)", q: "How can I avoid paying capital gains tax on property sale?" },
];

export default function AssistantPanel({ familyId, onOpenDocument }: AssistantPanelProps) {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome",
      role: "assistant",
      content:
        "Hello! I am your Life Admin Assistant. I answer questions strictly from your family's stored and verified documents, with direct citations [S1], [S2]. How can I help you today?",
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    },
  ]);
  const [inputQuery, setInputQuery] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [selectedSourceRef, setSelectedSourceRef] = useState<string | null>(null);
  const [activeSources, setActiveSources] = useState<AssistantSource[]>([]);

  const abortControllerRef = useRef<AbortController | null>(null);
  const chatBottomRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isStreaming]);

  const handleAsk = async (questionText?: string) => {
    const q = (questionText ?? inputQuery).trim();
    if (!q || isStreaming) return;

    setInputQuery("");
    const userMsgId = `user-${Date.now()}`;
    const assistantMsgId = `asst-${Date.now()}`;
    const timestamp = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

    const newMessages: Message[] = [
      ...messages,
      {
        id: userMsgId,
        role: "user",
        content: q,
        timestamp,
      },
      {
        id: assistantMsgId,
        role: "assistant",
        content: "",
        isStreaming: true,
        sources: [],
        timestamp,
      },
    ];

    setMessages(newMessages);
    setIsStreaming(true);
    setSelectedSourceRef(null);
    setActiveSources([]);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    let accumulatedText = "";
    let currentSources: AssistantSource[] = [];
    let isRefused = false;
    let currentSuggestedAction: SuggestedAction | null = null;

    try {
      await api.streamAsk(
        familyId,
        q,
        {
          onSources: (sources, refused, suggestedAction) => {
            currentSources = sources;
            isRefused = refused;
            currentSuggestedAction = suggestedAction || null;
            setActiveSources(sources);

            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantMsgId
                  ? {
                      ...msg,
                      sources,
                      refused,
                      suggestedAction: currentSuggestedAction,
                    }
                  : msg
              )
            );
          },
          onDelta: (textChunk) => {
            accumulatedText += textChunk;
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantMsgId
                  ? {
                      ...msg,
                      content: accumulatedText,
                    }
                  : msg
              )
            );
          },
          onDone: () => {
            setIsStreaming(false);
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantMsgId
                  ? {
                      ...msg,
                      isStreaming: false,
                      content: accumulatedText,
                      sources: currentSources,
                      refused: isRefused,
                      suggestedAction: currentSuggestedAction,
                    }
                  : msg
              )
            );
          },
          onError: (err) => {
            console.error("Stream error:", err);
            setIsStreaming(false);
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantMsgId
                  ? {
                      ...msg,
                      isStreaming: false,
                      content:
                        accumulatedText ||
                        "Unable to retrieve answer. Please check your network connection or try again.",
                    }
                  : msg
              )
            );
          },
        },
        controller.signal
      );
    } catch (err) {
      console.error("Failed to query assistant:", err);
      setIsStreaming(false);
    }
  };

  const handleStopStream = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      setIsStreaming(false);
      setMessages((prev) =>
        prev.map((m) => (m.isStreaming ? { ...m, isStreaming: false } : m))
      );
    }
  };

  const renderContentWithCitations = (content: string, sources?: AssistantSource[]) => {
    // Regex matches [S1], [S2], [S12], etc.
    const parts = content.split(/(\[S\d+\])/g);

    return parts.map((part, idx) => {
      const match = part.match(/\[(S\d+)\]/);
      if (match) {
        const refTag = match[1];
        const isSelected = selectedSourceRef === refTag;
        const matchedSource = sources?.find((s) => s.ref === refTag);

        return (
          <button
            key={idx}
            type="button"
            onClick={() => {
              setSelectedSourceRef(refTag);
              const el = document.getElementById(`source-card-${refTag}`);
              if (el) {
                el.scrollIntoView({ behavior: "smooth", block: "nearest" });
              }
            }}
            className={`inline-flex items-center px-1.5 py-0.5 mx-0.5 rounded text-xs font-semibold tracking-wide transition-all ${
              isSelected
                ? "bg-indigo-600 text-white ring-2 ring-indigo-300 ring-offset-1"
                : "bg-indigo-100 text-indigo-700 hover:bg-indigo-200"
            }`}
            title={matchedSource ? `${matchedSource.title} (${matchedSource.verification || "unverified"})` : `Source ${refTag}`}
          >
            [{refTag}]
          </button>
        );
      }
      return <span key={idx}>{part}</span>;
    });
  };

  const latestAssistantMessage = [...messages].reverse().find((m) => m.role === "assistant" && m.id !== "welcome");
  const displaySources = latestAssistantMessage?.sources || activeSources;

  return (
    <div className="flex flex-col lg:flex-row h-full min-h-[640px] bg-stone-50 border border-stone-200 rounded-xl overflow-hidden shadow-sm">
      {/* Left Chat Pane */}
      <div className="flex-1 flex flex-col h-full bg-white border-r border-stone-200">
        {/* Header */}
        <div className="px-6 py-4 border-b border-stone-200 bg-stone-50/80 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center text-white text-sm font-bold shadow-sm">
              AI
            </div>
            <div>
              <h2 className="text-sm font-bold text-stone-900 tracking-tight">Family Assistant</h2>
              <p className="text-xs text-stone-500">
                Grounded strictly in family records • Zero legal assertions
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
              Hybrid Grounding
            </span>
          </div>
        </div>

        {/* Message Thread */}
        <div className="flex-1 p-6 overflow-y-auto space-y-6">
          {messages.map((msg) => {
            const isUser = msg.role === "user";
            return (
              <div
                key={msg.id}
                className={`flex gap-3 max-w-[90%] ${isUser ? "ml-auto flex-row-reverse" : "mr-auto"}`}
              >
                <div
                  className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0 mt-0.5 ${
                    isUser ? "bg-stone-800 text-white" : "bg-indigo-600 text-white"
                  }`}
                >
                  {isUser ? "You" : "AI"}
                </div>

                <div className="space-y-2">
                  <div
                    className={`rounded-2xl p-4 text-sm leading-relaxed ${
                      isUser
                        ? "bg-stone-900 text-stone-100 rounded-tr-none"
                        : "bg-stone-100 text-stone-900 rounded-tl-none border border-stone-200/80"
                    }`}
                  >
                    <div className="whitespace-pre-wrap">
                      {isUser ? (
                        msg.content
                      ) : (
                        <>
                          {renderContentWithCitations(msg.content, msg.sources)}
                          {msg.isStreaming && (
                            <span className="inline-block w-2 h-4 ml-1 bg-indigo-600 animate-pulse align-middle" />
                          )}
                        </>
                      )}
                    </div>

                    {/* Refusal / Next Action Card */}
                    {msg.refused && (
                      <div className="mt-3 pt-3 border-t border-amber-200/60 bg-amber-50/70 p-3 rounded-lg border text-xs text-amber-900 space-y-2">
                        <div className="flex items-center gap-1.5 font-semibold text-amber-800">
                          <svg className="w-4 h-4 text-amber-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                          </svg>
                          <span>Policy & Verification Boundary</span>
                        </div>
                        <p className="text-stone-700">
                          {msg.suggestedAction?.description || "This request touches legal title, tax advice, or unrecorded facts."}
                        </p>
                        {msg.suggestedAction && (
                          <div className="pt-1">
                            {msg.suggestedAction.action_url ? (
                              <Link
                                href={msg.suggestedAction.action_url}
                                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-stone-900 text-white font-medium hover:bg-stone-800 transition-colors shadow-sm"
                              >
                                <span>{msg.suggestedAction.label}</span>
                                <span aria-hidden="true">&rarr;</span>
                              </Link>
                            ) : (
                              <div className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-amber-100 text-amber-900 font-medium border border-amber-300">
                                <span>{msg.suggestedAction.label}</span>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  <div className={`text-[11px] text-stone-400 px-1 ${isUser ? "text-right" : "text-left"}`}>
                    {msg.timestamp}
                  </div>
                </div>
              </div>
            );
          })}
          <div ref={chatBottomRef} />
        </div>

        {/* Preset Prompt Pills */}
        <div className="px-6 py-2 border-t border-stone-100 bg-white">
          <p className="text-[11px] font-semibold text-stone-400 uppercase tracking-wider mb-1.5">
            Suggested Prompts
          </p>
          <div className="flex flex-wrap gap-1.5">
            {PRESET_QUESTIONS.map((item, idx) => (
              <button
                key={idx}
                type="button"
                disabled={isStreaming}
                onClick={() => handleAsk(item.q)}
                className="text-xs px-2.5 py-1 rounded-full bg-stone-100 text-stone-700 hover:bg-stone-200 transition-colors border border-stone-200/60 disabled:opacity-50"
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        {/* Input Form */}
        <div className="p-4 border-t border-stone-200 bg-stone-50">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleAsk();
            }}
            className="flex gap-2 items-end"
          >
            <div className="relative flex-1">
              <textarea
                ref={textareaRef}
                value={inputQuery}
                onChange={(e) => setInputQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleAsk();
                  }
                }}
                rows={2}
                placeholder="Ask anything about your family documents, policies, or deadlines..."
                className="w-full resize-none rounded-xl border border-stone-300 bg-white px-4 py-2.5 text-sm text-stone-900 placeholder-stone-400 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>

            {isStreaming ? (
              <button
                type="button"
                onClick={handleStopStream}
                className="h-11 px-4 rounded-xl bg-rose-600 text-white text-xs font-semibold hover:bg-rose-700 transition-colors shrink-0 flex items-center gap-1.5"
              >
                <span className="w-2 h-2 rounded-full bg-white animate-ping" />
                Stop
              </button>
            ) : (
              <button
                type="submit"
                disabled={!inputQuery.trim()}
                className="h-11 px-5 rounded-xl bg-indigo-600 text-white text-xs font-semibold hover:bg-indigo-700 disabled:opacity-40 disabled:hover:bg-indigo-600 transition-colors shrink-0 shadow-sm"
              >
                Ask
              </button>
            )}
          </form>
        </div>
      </div>

      {/* Right Sources Pane */}
      <div className="w-full lg:w-96 flex flex-col h-full bg-stone-50 border-t lg:border-t-0 border-stone-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-stone-200 bg-white flex items-center justify-between">
          <div className="flex items-center gap-2">
            <svg className="w-4 h-4 text-stone-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
            </svg>
            <h3 className="text-xs font-bold uppercase tracking-wider text-stone-700">
              Grounding Sources ({displaySources.length})
            </h3>
          </div>
          <span className="text-[11px] text-stone-400">Section 10</span>
        </div>

        <div className="flex-1 p-4 overflow-y-auto space-y-3">
          {displaySources.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center p-6 text-stone-400 space-y-2">
              <div className="w-12 h-12 rounded-full bg-stone-100 flex items-center justify-center text-stone-400 text-lg">
                📄
              </div>
              <p className="text-xs font-medium text-stone-600">No sources retrieved yet</p>
              <p className="text-[11px] text-stone-400 max-w-xs">
                Ask a question to see the exact records, documents, and verification statuses used to ground the answer.
              </p>
            </div>
          ) : (
            displaySources.map((source) => {
              const isSelected = selectedSourceRef === source.ref;
              const isVerified = source.verification === "verified";
              const isPending = source.verification === "unverified" || source.verification === "pending";

              return (
                <div
                  key={source.ref}
                  id={`source-card-${source.ref}`}
                  className={`p-4 rounded-xl border transition-all duration-200 ${
                    isSelected
                      ? "bg-white border-indigo-500 shadow-md ring-2 ring-indigo-200"
                      : "bg-white border-stone-200 hover:border-stone-300 shadow-sm"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <div className="flex items-center gap-2">
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-indigo-100 text-indigo-800">
                        [{source.ref}]
                      </span>
                      <span className="text-[11px] uppercase font-semibold tracking-wider text-stone-500">
                        {source.kind}
                      </span>
                    </div>

                    {/* Verification Status Badge (P5.3 requirement) */}
                    <div>
                      {isVerified ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                          <svg className="w-3 h-3 text-emerald-600" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                          </svg>
                          Verified
                        </span>
                      ) : isPending ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-800 border border-amber-200" title="Low confidence is normal, not an error.">
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                          Unverified
                        </span>
                      ) : (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-stone-100 text-stone-600">
                          {source.verification || "n/a"}
                        </span>
                      )}
                    </div>
                  </div>

                  <h4 className="text-sm font-semibold text-stone-900 leading-snug mb-2">
                    {source.title}
                  </h4>

                  <div className="flex items-center justify-between text-xs pt-2 border-t border-stone-100">
                    <span className="text-[11px] text-stone-400 truncate max-w-[150px]">
                      ID: {source.id.slice(0, 8)}...
                    </span>

                    {source.kind === "document" ? (
                      <Link
                        href={`/documents/${source.id}`}
                        className="text-xs font-medium text-indigo-600 hover:text-indigo-800 hover:underline flex items-center gap-1"
                      >
                        <span>Open Document</span>
                        <span aria-hidden="true">&rarr;</span>
                      </Link>
                    ) : (
                      <span className="text-[11px] text-stone-400 italic">Structured Record</span>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
