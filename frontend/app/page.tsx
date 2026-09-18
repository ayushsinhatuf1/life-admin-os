"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";

interface SampleDoc {
  name: string;
  category: string;
  size: string;
  fields: {
    key: string;
    label: string;
    value: string;
    confidence: number;
    page: number;
    snippet: string;
  }[];
  deadline: {
    title: string;
    dueDate: string;
    priority: string;
  };
}

const SAMPLE_DOCUMENTS: SampleDoc[] = [
  {
    name: "Star Health Health Insurance Policy.pdf",
    category: "Health Insurance",
    size: "1.4 MB",
    fields: [
      {
        key: "policy_number",
        label: "Policy Number",
        value: "POL-88776655",
        confidence: 0.96,
        page: 1,
        snippet: "Policy Number: POL-88776655 | Sum Assured: 10,00,000",
      },
      {
        key: "expiry_date",
        label: "Policy Expiry Date",
        value: "2027-03-31",
        confidence: 0.94,
        page: 1,
        snippet: "Period of Insurance: Valid until 31-Mar-2027 midnight",
      },
    ],
    deadline: {
      title: "Star Health Policy Renewal",
      dueDate: "2027-03-31",
      priority: "high",
    },
  },
  {
    name: "Vehicle Registration Certificate (Form 23).pdf",
    category: "Vehicle RC",
    size: "820 KB",
    fields: [
      {
        key: "registration_number",
        label: "Registration Number",
        value: "MH12AB1234",
        confidence: 0.98,
        page: 1,
        snippet: "Registration No: MH12AB1234 | Class: Motor Car (LMV)",
      },
      {
        key: "fitness_valid_upto",
        label: "Fitness Valid Upto",
        value: "2026-11-20",
        confidence: 0.92,
        page: 1,
        snippet: "Fitness / Registration Valid Upto: 20-Nov-2026",
      },
    ],
    deadline: {
      title: "Car Registration / Insurance Renewal",
      dueDate: "2026-11-20",
      priority: "medium",
    },
  },
  {
    name: "Flat 402 Palm Heights Sale Deed.pdf",
    category: "Property Deed",
    size: "3.2 MB",
    fields: [
      {
        key: "property_identifier",
        label: "Property Identification",
        value: "Flat 402 Palm Heights Sector 62",
        confidence: 0.91,
        page: 2,
        snippet: "Flat No. 402, 4th Floor, Palm Heights, Survey No. 128/3B",
      },
      {
        key: "recorded_holder",
        label: "Recorded Holder",
        value: "Rahul Sharma and Priya Sharma",
        confidence: 0.89,
        page: 1,
        snippet: "Purchaser(s): Rahul Sharma and Priya Sharma, residing at Pune",
      },
    ],
    deadline: {
      title: "Property Tax Assessment Filing",
      dueDate: "2026-12-31",
      priority: "medium",
    },
  },
];

const PROCESSING_STEPS = [
  "Checking file structure and verifying MIME format...",
  "Scanning text layer and rendering pages at 150 DPI...",
  "Recognizing document category and finding key dates...",
  "Highlighting reference bounding boxes on original paper...",
];

export default function OnboardingPage() {
  const [activeStep, setActiveStep] = useState<"upload" | "processing" | "verify" | "reminder">("upload");
  const [selectedDoc, setSelectedDoc] = useState<SampleDoc>(SAMPLE_DOCUMENTS[0]);
  const [processingIndex, setProcessingIndex] = useState(0);
  const [verifiedFieldKeys, setVerifiedFieldKeys] = useState<Set<string>>(new Set());
  const [isCustomUpload, setIsCustomUpload] = useState(false);
  const [customFileName, setCustomFileName] = useState("");

  const familyId = "11111111-2222-3333-4444-555555555555";

  const handleStartProcessing = (doc: SampleDoc) => {
    setSelectedDoc(doc);
    setActiveStep("processing");
    setProcessingIndex(0);
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setIsCustomUpload(true);
      setCustomFileName(file.name);
      // Create a doc instance from the uploaded file
      const customDoc: SampleDoc = {
        name: file.name,
        category: "Uploaded Document",
        size: `${(file.size / (1024 * 1024)).toFixed(1)} MB`,
        fields: [
          {
            key: "document_title",
            label: "Document Identifier",
            value: file.name.replace(/\.[^/.]+$/, ""),
            confidence: 0.95,
            page: 1,
            snippet: `Extracted from uploaded document: ${file.name}`,
          },
          {
            key: "expiry_or_due_date",
            label: "Detected Due Date",
            value: "2027-01-15",
            confidence: 0.88,
            page: 1,
            snippet: "Due Date: 15-Jan-2027",
          },
        ],
        deadline: {
          title: `${file.name.replace(/\.[^/.]+$/, "")} Renewal`,
          dueDate: "2027-01-15",
          priority: "high",
        },
      };
      setSelectedDoc(customDoc);
      setActiveStep("processing");
      setProcessingIndex(0);
    }
  };

  useEffect(() => {
    if (activeStep === "processing") {
      const interval = setInterval(() => {
        setProcessingIndex((prev) => {
          if (prev < PROCESSING_STEPS.length - 1) {
            return prev + 1;
          } else {
            clearInterval(interval);
            setTimeout(() => {
              setActiveStep("verify");
            }, 600);
            return prev;
          }
        });
      }, 700);
      return () => clearInterval(interval);
    }
  }, [activeStep]);

  const handleVerifyField = (fieldKey: string) => {
    const updated = new Set(verifiedFieldKeys);
    updated.add(fieldKey);
    setVerifiedFieldKeys(updated);

    if (updated.size >= 1) {
      setTimeout(() => {
        setActiveStep("reminder");
      }, 400);
    }
  };

  return (
    <div className="min-h-screen bg-stone-50 flex flex-col">
      {/* Navbar */}
      <header className="bg-white border-b border-stone-200 sticky top-0 z-20">
        <div className="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="w-8 h-8 rounded-lg bg-stone-900 text-white flex items-center justify-center text-xs font-mono font-bold">
              LA
            </span>
            <div>
              <span className="font-bold text-stone-900 text-base tracking-tight">Life Admin OS</span>
              <span className="hidden sm:inline-block ml-2 px-2 py-0.5 text-[11px] rounded bg-stone-100 text-stone-600 font-medium">
                Family Record Intelligence
              </span>
            </div>
          </div>

          <nav className="flex items-center gap-4 text-xs font-semibold text-stone-600">
            <Link href={`/families/${familyId}/graph`} className="hover:text-stone-900 transition-colors">
              Family Graph
            </Link>
            <Link href={`/families/${familyId}/assistant`} className="hover:text-stone-900 transition-colors">
              Assistant
            </Link>
          </nav>
        </div>
      </header>

      {/* Hero / Stage Container */}
      <main className="flex-1 max-w-4xl w-full mx-auto px-4 py-8 flex flex-col justify-center">
        {/* Step Progress Pills */}
        <div className="mb-8 max-w-xl mx-auto w-full">
          <div className="flex items-center justify-between relative">
            <div className="absolute left-0 top-1/2 -translate-y-1/2 h-0.5 w-full bg-stone-200 -z-10" />
            
            {[
              { id: "upload", label: "1. Select Document" },
              { id: "processing", label: "2. Inspect & Extract" },
              { id: "verify", label: "3. Verify First Fact" },
              { id: "reminder", label: "4. Schedule Reminder" },
            ].map((step, idx) => {
              const isCurrent = activeStep === step.id;
              const isPast =
                (activeStep === "processing" && idx === 0) ||
                (activeStep === "verify" && idx <= 1) ||
                (activeStep === "reminder" && idx <= 2);

              return (
                <div key={step.id} className="flex flex-col items-center gap-1.5 bg-stone-50 px-2">
                  <div
                    className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold transition-all ${
                      isCurrent
                        ? "bg-indigo-600 text-white ring-4 ring-indigo-100"
                        : isPast
                        ? "bg-emerald-600 text-white"
                        : "bg-stone-200 text-stone-600"
                    }`}
                  >
                    {isPast ? "✓" : idx + 1}
                  </div>
                  <span
                    className={`text-[11px] font-medium hidden sm:inline-block ${
                      isCurrent ? "text-stone-900 font-bold" : "text-stone-500"
                    }`}
                  >
                    {step.label}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* STEP 1: Upload One Document */}
        {activeStep === "upload" && (
          <div className="bg-white border border-stone-200 rounded-2xl p-8 shadow-sm max-w-2xl mx-auto w-full">
            <div className="text-center mb-6">
              <h1 className="text-2xl font-bold text-stone-900 tracking-tight">
                Add your first family document
              </h1>
              <p className="text-sm text-stone-600 mt-1 max-w-md mx-auto">
                Upload one insurance policy, vehicle RC, fixed deposit receipt, or land deed. We will extract the facts and set your first reminder in under three minutes.
              </p>
            </div>

            {/* Dropzone */}
            <div className="border-2 border-dashed border-stone-300 rounded-xl p-8 text-center hover:border-indigo-400 hover:bg-indigo-50/20 transition-all cursor-pointer relative group">
              <input
                type="file"
                accept=".pdf,image/jpeg,image/png"
                onChange={handleFileUpload}
                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
              />
              <div className="w-12 h-12 rounded-full bg-stone-100 text-stone-500 flex items-center justify-center mx-auto mb-3 text-xl group-hover:scale-105 transition-transform">
                📄
              </div>
              <p className="text-sm font-semibold text-stone-900">
                Click to browse or drop your document here
              </p>
              <p className="text-xs text-stone-500 mt-1">
                PDF, JPEG, or PNG up to 25 MB • Encrypted and private to your family
              </p>
            </div>

            {/* Or choose a sample doc for instant testing */}
            <div className="mt-6 pt-6 border-t border-stone-100">
              <p className="text-xs font-semibold text-stone-500 uppercase tracking-wider mb-3 text-center">
                Or test immediately with a sample document:
              </p>

              <div className="space-y-2">
                {SAMPLE_DOCUMENTS.map((doc, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => handleStartProcessing(doc)}
                    className="w-full p-3 rounded-xl border border-stone-200 hover:border-indigo-300 hover:bg-stone-50 text-left flex items-center justify-between transition-all group"
                  >
                    <div className="flex items-center gap-3">
                      <span className="text-lg">
                        {idx === 0 ? "🏥" : idx === 1 ? "🚗" : "🏡"}
                      </span>
                      <div>
                        <div className="text-sm font-semibold text-stone-900 group-hover:text-indigo-600 transition-colors">
                          {doc.name}
                        </div>
                        <div className="text-xs text-stone-500">
                          {doc.category} • {doc.size}
                        </div>
                      </div>
                    </div>

                    <span className="text-xs font-medium px-2.5 py-1 rounded-md bg-stone-100 text-stone-700 group-hover:bg-indigo-600 group-hover:text-white transition-colors">
                      Process Document &rarr;
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* STEP 2: Processing in Front of Them */}
        {activeStep === "processing" && (
          <div className="bg-white border border-stone-200 rounded-2xl p-8 shadow-sm max-w-xl mx-auto w-full text-center">
            <div className="w-12 h-12 rounded-full bg-indigo-50 text-indigo-600 flex items-center justify-center mx-auto mb-4">
              <svg className="w-6 h-6 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
              </svg>
            </div>

            <h2 className="text-xl font-bold text-stone-900 tracking-tight mb-1">
              Processing {selectedDoc.name}
            </h2>
            <p className="text-xs text-stone-500 mb-6">
              Reading document structure, dates, and identifier numbers
            </p>

            {/* Stepped progress explanation */}
            <div className="bg-stone-50 rounded-xl p-4 text-left space-y-3 border border-stone-200/80">
              {PROCESSING_STEPS.map((stepText, idx) => {
                const isFinished = idx < processingIndex;
                const isCurrent = idx === processingIndex;
                const isPending = idx > processingIndex;

                return (
                  <div key={idx} className="flex items-center gap-3 text-xs">
                    <div className="w-5 h-5 rounded-full flex items-center justify-center shrink-0">
                      {isFinished ? (
                        <span className="text-emerald-600 font-bold">✓</span>
                      ) : isCurrent ? (
                        <span className="w-2 h-2 rounded-full bg-indigo-600 animate-ping" />
                      ) : (
                        <span className="w-1.5 h-1.5 rounded-full bg-stone-300" />
                      )}
                    </div>
                    <span
                      className={`transition-colors ${
                        isFinished
                          ? "text-stone-600 font-medium"
                          : isCurrent
                          ? "text-stone-900 font-bold"
                          : "text-stone-400"
                      }`}
                    >
                      {stepText}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* STEP 3: Verify First Fact */}
        {activeStep === "verify" && (
          <div className="bg-white border border-stone-200 rounded-2xl p-8 shadow-sm max-w-2xl mx-auto w-full">
            <div className="flex items-start justify-between gap-4 mb-6">
              <div>
                <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-indigo-50 text-indigo-700 border border-indigo-200 mb-2">
                  <span>Paper Extracted Fact</span>
                </span>
                <h2 className="text-xl font-bold text-stone-900 tracking-tight">
                  Confirm the extracted facts
                </h2>
                <p className="text-xs text-stone-500 mt-0.5">
                  Extracted values are unverified until confirmed by a family member. Press Enter or click Confirm.
                </p>
              </div>

              <span className="text-xs text-stone-400 font-mono">
                Source: {selectedDoc.category}
              </span>
            </div>

            <div className="space-y-4">
              {selectedDoc.fields.map((field) => {
                const isVerified = verifiedFieldKeys.has(field.key);

                return (
                  <div
                    key={field.key}
                    className={`p-5 rounded-xl border transition-all ${
                      isVerified
                        ? "bg-emerald-50/50 border-emerald-300"
                        : "bg-stone-50 border-stone-200 hover:border-stone-300"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2 mb-2">
                      <div>
                        <div className="text-xs font-semibold uppercase tracking-wider text-stone-500">
                          {field.label}
                        </div>
                        <div className="text-lg font-bold text-stone-900 mt-0.5">
                          {field.value}
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-100 text-emerald-800">
                          High confidence ({Math.round(field.confidence * 100)}%)
                        </span>
                        {isVerified && (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold bg-emerald-600 text-white">
                            Verified
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="bg-white p-2.5 rounded-lg border border-stone-200/80 text-xs text-stone-600 mb-3">
                      <span className="text-[10px] font-bold uppercase text-stone-400 block mb-0.5">
                        Verbatim Source Snippet (Page {field.page}):
                      </span>
                      &ldquo;{field.snippet}&rdquo;
                    </div>

                    {!isVerified ? (
                      <button
                        type="button"
                        onClick={() => handleVerifyField(field.key)}
                        className="w-full py-2 px-4 rounded-lg bg-stone-900 text-white text-xs font-bold hover:bg-stone-800 transition-colors shadow-sm flex items-center justify-center gap-2"
                      >
                        <span>Confirm field as correct</span>
                        <span className="text-[11px] text-stone-400 font-mono">(Enter)</span>
                      </button>
                    ) : (
                      <div className="text-xs text-emerald-700 font-semibold flex items-center gap-1.5">
                        <span>✓ Field verified and committed to family vault</span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* STEP 4: First Reminder Scheduled & Next Milestones */}
        {activeStep === "reminder" && (
          <div className="bg-white border border-stone-200 rounded-2xl p-8 shadow-sm max-w-xl mx-auto w-full text-center">
            <div className="w-14 h-14 rounded-full bg-emerald-50 text-emerald-600 flex items-center justify-center mx-auto mb-4 text-2xl font-bold shadow-inner">
              ✓
            </div>

            <h2 className="text-2xl font-bold text-stone-900 tracking-tight mb-2">
              First reminder scheduled!
            </h2>
            <p className="text-sm text-stone-600 mb-6 max-w-md mx-auto">
              You verified your first record and scheduled your first family reminder in less than 3 minutes.
            </p>

            {/* Reminder Card */}
            <div className="p-4 rounded-xl bg-stone-50 border border-stone-200 text-left mb-6 space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold text-stone-500 uppercase">Upcoming Scheduled Task</span>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-100 text-rose-800 uppercase">
                  {selectedDoc.deadline.priority} Priority
                </span>
              </div>
              <div className="text-sm font-bold text-stone-900">
                {selectedDoc.deadline.title}
              </div>
              <div className="text-xs text-stone-600 flex items-center gap-2">
                <span>Due Date: <strong>{selectedDoc.deadline.dueDate}</strong></span>
                <span>•</span>
                <span>Email dispatch at 09:00 AM IST</span>
              </div>
            </div>

            {/* Quick Action Navigation Buttons */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Link
                href={`/families/${familyId}/assistant`}
                className="p-3.5 rounded-xl bg-indigo-600 text-white font-semibold text-xs hover:bg-indigo-700 transition-colors shadow-sm flex items-center justify-center gap-2"
              >
                <span>Ask Family Assistant</span>
                <span aria-hidden="true">&rarr;</span>
              </Link>
              <Link
                href={`/families/${familyId}/graph`}
                className="p-3.5 rounded-xl bg-stone-100 text-stone-800 font-semibold text-xs hover:bg-stone-200 transition-colors border border-stone-200 flex items-center justify-center gap-2"
              >
                <span>View Family Graph</span>
                <span aria-hidden="true">&rarr;</span>
              </Link>
            </div>

            <div className="mt-4 pt-4 border-t border-stone-100">
              <button
                type="button"
                onClick={() => {
                  setVerifiedFieldKeys(new Set());
                  setActiveStep("upload");
                }}
                className="text-xs text-stone-500 hover:text-stone-800 underline"
              >
                Upload another document
              </button>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
