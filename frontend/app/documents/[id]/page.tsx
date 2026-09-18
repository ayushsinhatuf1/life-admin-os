"use client";

import { useEffect, useState, useRef } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { api, type DocumentRecord, type ExtractedField } from "@/lib/api";
import { VerifyPanel } from "../VerifyPanel";

export default function DocumentVerificationPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const documentId = params?.id as string;

  const [familyId, setFamilyId] = useState<string>("");
  const [doc, setDoc] = useState<DocumentRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Viewer state
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [pageImageUrl, setPageImageUrl] = useState<string | null>(null);
  const [pageLoading, setPageLoading] = useState(false);
  const [selectedField, setSelectedField] = useState<ExtractedField | null>(null);

  const imageContainerRef = useRef<HTMLDivElement>(null);

  // 1. Resolve familyId from URL search param, sessionStorage, or fallback
  useEffect(() => {
    const qFamily = searchParams?.get("family_id");
    if (qFamily) {
      setFamilyId(qFamily);
      return;
    }
    if (typeof window !== "undefined") {
      const stored = window.sessionStorage.getItem("lao_family_id");
      if (stored) {
        setFamilyId(stored);
      }
    }
  }, [searchParams]);

  // 2. Fetch Document
  useEffect(() => {
    if (!documentId) return;

    // Default fallback family ID if running in preview/standalone
    const activeFamilyId = familyId || "00000000-0000-0000-0000-000000000000";

    async function loadDoc() {
      setLoading(true);
      setError(null);
      try {
        const data = await api.getDocument(activeFamilyId, documentId);
        setDoc(data);

        // Preselect the first unverified field if present
        const firstUnverified = data.fields.find((f) => f.verification === "unverified");
        if (firstUnverified) {
          setSelectedField(firstUnverified);
          if (firstUnverified.source_page) {
            setCurrentPage(firstUnverified.source_page);
          }
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load document.");
      } finally {
        setLoading(false);
      }
    }

    loadDoc();
  }, [documentId, familyId]);

  // 3. Fetch Page Image URL whenever currentPage changes
  useEffect(() => {
    if (!documentId || !doc) return;
    const activeFamilyId = familyId || "00000000-0000-0000-0000-000000000000";

    async function loadPageImage() {
      setPageLoading(true);
      try {
        const res = await api.documentPageUrl(activeFamilyId, documentId, currentPage);
        setPageImageUrl(res.url);
      } catch {
        // If page image endpoint is unavailable or falling back, try direct file url
        try {
          const fileRes = await api.documentFileUrl(activeFamilyId, documentId);
          setPageImageUrl(fileRes.url);
        } catch {
          setPageImageUrl(null);
        }
      } finally {
        setPageLoading(false);
      }
    }

    loadPageImage();
  }, [documentId, familyId, doc?.id, currentPage]);

  // 4. When selected field changes, sync page and scroll to bbox
  function handleSelectField(field: ExtractedField) {
    setSelectedField(field);
    if (field.source_page && field.source_page !== currentPage) {
      setCurrentPage(field.source_page);
    }

    // Scroll to bbox region in viewer
    if (field.source_bbox && imageContainerRef.current) {
      const container = imageContainerRef.current;
      const targetScrollY = field.source_bbox.y * container.scrollHeight - container.clientHeight / 3;
      container.scrollTo({
        top: Math.max(0, targetScrollY),
        behavior: "smooth",
      });
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="flex items-center gap-3 text-stone-500">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-stone-400 border-t-stone-800" />
          <span className="text-sm">Loading document…</span>
        </div>
      </div>
    );
  }

  if (error || !doc) {
    return (
      <div className="mx-auto max-w-lg p-8 text-center">
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-6 text-amber-900">
          <h2 className="text-base font-semibold">Document not found</h2>
          <p className="mt-1 text-sm">{error ?? "Could not locate this record."}</p>
          <a
            href="/vault"
            className="mt-4 inline-block rounded-lg bg-stone-900 px-4 py-2 text-xs font-medium text-white"
          >
            Back to vault
          </a>
        </div>
      </div>
    );
  }

  const totalPages = doc.page_count || 1;
  const currentBBox =
    selectedField?.source_page === currentPage || (!selectedField?.source_page && currentPage === 1)
      ? selectedField?.source_bbox
      : null;

  return (
    <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      {/* Header bar */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4 border-b border-stone-200 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="rounded bg-stone-100 px-2 py-0.5 text-xs uppercase tracking-wider text-stone-600">
              {doc.category || "Document"}
            </span>
            <span className="text-xs text-stone-400">•</span>
            <span className="text-xs text-stone-500">
              Status: <strong className="font-medium text-stone-700">{doc.status}</strong>
            </span>
          </div>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-stone-900">
            {doc.title}
          </h1>
        </div>

        <a
          href="/vault"
          className="rounded-lg border border-stone-300 bg-white px-3 py-1.5 text-sm font-medium text-stone-700 shadow-sm hover:bg-stone-50"
        >
          ← Back to Vault
        </a>
      </div>

      {/* Two panes on desktop (Page image left, Fields right); stacked on mobile */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Left Pane: Page Image Viewer (7 cols desktop) */}
        <section className="flex flex-col rounded-xl border border-stone-200 bg-stone-100/60 p-4 shadow-sm lg:col-span-7">
          {/* Viewer Controls */}
          <div className="mb-3 flex items-center justify-between border-b border-stone-200 pb-3">
            <div className="flex items-center gap-2 text-sm font-medium text-stone-700">
              <span>Page {currentPage} of {totalPages}</span>
            </div>

            {totalPages > 1 && (
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  disabled={currentPage <= 1}
                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                  className="rounded border border-stone-300 bg-white px-2.5 py-1 text-xs font-medium text-stone-700 shadow-sm hover:bg-stone-50 disabled:opacity-40"
                >
                  Previous
                </button>
                <button
                  type="button"
                  disabled={currentPage >= totalPages}
                  onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                  className="rounded border border-stone-300 bg-white px-2.5 py-1 text-xs font-medium text-stone-700 shadow-sm hover:bg-stone-50 disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            )}
          </div>

          {/* Document Canvas with Bounding Box Overlay */}
          <div
            ref={imageContainerRef}
            className="relative min-h-[480px] max-h-[75vh] overflow-auto rounded-lg border border-stone-300 bg-stone-200/50 shadow-inner flex items-start justify-center p-2"
          >
            {pageLoading ? (
              <div className="flex h-64 w-full items-center justify-center text-stone-500">
                <div className="h-6 w-6 animate-spin rounded-full border-2 border-stone-400 border-t-stone-800" />
              </div>
            ) : pageImageUrl ? (
              <div className="relative inline-block w-full max-w-2xl">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={pageImageUrl}
                  alt={`Document Page ${currentPage}`}
                  className="w-full rounded shadow-md bg-white select-none pointer-events-none"
                />

                {/* Highlighted Bounding Box Rectangle */}
                {currentBBox && (
                  <div
                    id="highlight-bbox"
                    className="absolute rounded border-2 border-indigo-600 bg-indigo-500/20 shadow-md ring-2 ring-indigo-400/40 transition-all duration-200 pointer-events-none"
                    style={{
                      left: `${currentBBox.x * 100}%`,
                      top: `${currentBBox.y * 100}%`,
                      width: `${currentBBox.w * 100}%`,
                      height: `${currentBBox.h * 100}%`,
                    }}
                  >
                    <div className="absolute -top-6 left-0 whitespace-nowrap rounded bg-indigo-700 px-2 py-0.5 text-[11px] font-semibold text-white shadow-sm">
                      {selectedField?.label}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex h-64 w-full flex-col items-center justify-center text-stone-500">
                <p className="text-sm">Page preview rendering…</p>
                <p className="mt-1 text-xs text-stone-400">
                  {selectedField?.source_snippet ? `“${selectedField.source_snippet}”` : ""}
                </p>
              </div>
            )}
          </div>

          {selectedField?.source_snippet && (
            <div className="mt-3 rounded-lg border border-stone-200 bg-white p-3 text-xs text-stone-600">
              <span className="font-semibold text-stone-800">Source snippet:</span>{" "}
              “{selectedField.source_snippet}”
            </div>
          )}
        </section>

        {/* Right Pane: Verification Queue (5 cols desktop) */}
        <section className="lg:col-span-5">
          <div className="sticky top-6 rounded-xl border border-stone-200 bg-white p-5 shadow-sm">
            <VerifyPanel
              familyId={familyId}
              document={doc}
              selectedFieldId={selectedField?.id}
              onSelectField={handleSelectField}
              onChange={(updatedFields) => {
                setDoc({ ...doc, fields: updatedFields });
                // If the selected field was just confirmed, pick the next unverified
                const nextUnverified = updatedFields.find((f) => f.verification === "unverified");
                if (nextUnverified) {
                  handleSelectField(nextUnverified);
                } else {
                  setSelectedField(null);
                }
              }}
            />
          </div>
        </section>
      </div>
    </main>
  );
}
