"use client";

import React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import AssistantPanel from "@/app/assistant/AssistantPanel";

export default function FamilyAssistantPage() {
  const params = useParams();
  const familyId = (params?.id as string) || "00000000-0000-0000-0000-000000000000";

  return (
    <div className="min-h-screen bg-stone-100 flex flex-col">
      {/* Global Navigation Bar */}
      <header className="bg-white border-b border-stone-200 sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <Link href="/" className="flex items-center gap-2 text-stone-900 font-bold tracking-tight text-lg">
              <span className="w-7 h-7 rounded-lg bg-stone-900 text-white flex items-center justify-center text-xs font-mono">
                LA
              </span>
              Life Admin OS
            </Link>

            <nav className="hidden md:flex items-center gap-1 text-sm font-medium text-stone-600">
              <Link
                href={`/families/${familyId}/graph`}
                className="px-3 py-1.5 rounded-lg hover:bg-stone-100 hover:text-stone-900 transition-colors"
              >
                Family Graph
              </Link>
              <Link
                href={`/families/${familyId}/assistant`}
                className="px-3 py-1.5 rounded-lg bg-stone-100 text-stone-900 font-semibold"
              >
                Assistant
              </Link>
              <Link
                href={`/families/${familyId}/readiness`}
                className="px-3 py-1.5 rounded-lg hover:bg-stone-100 hover:text-stone-900 transition-colors"
              >
                Readiness
              </Link>
            </nav>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-xs text-stone-500 font-mono hidden sm:inline-block">
              Family ID: {familyId.slice(0, 8)}...
            </span>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 flex flex-col">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-stone-900 tracking-tight">AI Assistant</h1>
            <p className="text-xs text-stone-500 mt-0.5">
              Ask questions grounded strictly in family documents, assets, and deadlines.
            </p>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className="px-2.5 py-1 rounded-md bg-stone-200 text-stone-700 font-medium">
              Tenancy Filter: Active
            </span>
          </div>
        </div>

        <div className="flex-1 min-h-[680px]">
          <AssistantPanel familyId={familyId} />
        </div>
      </main>
    </div>
  );
}
