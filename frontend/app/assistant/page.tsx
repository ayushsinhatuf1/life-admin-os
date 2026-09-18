"use client";

import React from "react";
import Link from "next/link";
import AssistantPanel from "./AssistantPanel";

export default function AssistantPage() {
  const defaultFamilyId = "11111111-2222-3333-4444-555555555555";

  return (
    <div className="min-h-screen bg-stone-100 flex flex-col">
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
                href={`/families/${defaultFamilyId}/graph`}
                className="px-3 py-1.5 rounded-lg hover:bg-stone-100 hover:text-stone-900 transition-colors"
              >
                Family Graph
              </Link>
              <Link
                href="/assistant"
                className="px-3 py-1.5 rounded-lg bg-stone-100 text-stone-900 font-semibold"
              >
                Assistant
              </Link>
            </nav>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-xs text-stone-500 font-mono">Demo Workspace</span>
          </div>
        </div>
      </header>

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 flex flex-col">
        <div className="mb-4">
          <h1 className="text-2xl font-bold text-stone-900 tracking-tight">AI Assistant</h1>
          <p className="text-xs text-stone-500 mt-0.5">
            Grounded question answering across family documents, assets, and properties.
          </p>
        </div>

        <div className="flex-1 min-h-[680px]">
          <AssistantPanel familyId={defaultFamilyId} />
        </div>
      </main>
    </div>
  );
}
