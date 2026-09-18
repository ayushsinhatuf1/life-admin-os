"use client";

// The verification screen is where the product earns trust: every AI-extracted
// value is shown next to the page and the exact snippet it came from, and
// nothing becomes trusted data until a person confirms it.
import { useState, useRef, useEffect } from "react";
import { api, type DocumentRecord, type ExtractedField, type Band } from "@/lib/api";

const bandConfig: Record<
  Band,
  { label: string; badgeClass: string; cardClass: string; inputBorder: string }
> = {
  high: {
    label: "Confident match",
    badgeClass: "bg-emerald-50 text-emerald-800 border-emerald-200",
    cardClass: "border-stone-200 hover:border-emerald-300",
    inputBorder: "focus:border-emerald-500 focus:ring-emerald-200",
  },
  medium: {
    label: "Check this one",
    badgeClass: "bg-amber-50 text-amber-800 border-amber-200",
    cardClass: "border-amber-200/80 bg-amber-50/20 hover:border-amber-300",
    inputBorder: "focus:border-amber-500 focus:ring-amber-200",
  },
  review: {
    label: "Needs your eyes",
    // Subdued slate/indigo — NOT RED. Low confidence is normal, not an error.
    badgeClass: "bg-indigo-50 text-indigo-800 border-indigo-200",
    cardClass: "border-indigo-200/80 bg-indigo-50/20 hover:border-indigo-300",
    inputBorder: "focus:border-indigo-500 focus:ring-indigo-200",
  },
};

export function VerifyPanel({
  familyId,
  document: doc,
  selectedFieldId,
  onSelectField,
  onChange,
}: {
  familyId: string;
  document: DocumentRecord;
  selectedFieldId?: string | null;
  onSelectField?: (field: ExtractedField) => void;
  onChange: (fields: ExtractedField[]) => void;
}) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Undo state for "Confirm all" action
  const [undoSnapshot, setUndoSnapshot] = useState<ExtractedField[] | null>(null);
  const [undoToastVisible, setUndoToastVisible] = useState(false);

  const inputRefs = useRef<Record<string, HTMLInputElement | null>>({});

  const pending = doc.fields.filter((f) => f.verification === "unverified");
  const allHighBand = pending.length > 0 && pending.every((f) => f.band === "high");

  // Focus the first unverified field on load if none selected
  useEffect(() => {
    if (selectedFieldId && inputRefs.current[selectedFieldId]) {
      inputRefs.current[selectedFieldId]?.focus();
    } else if (pending.length > 0 && pending[0]) {
      onSelectField?.(pending[0]);
    }
  }, [selectedFieldId]);

  async function confirm(field: ExtractedField, nextField?: ExtractedField) {
    setSaving(field.id);
    setError(null);
    try {
      const edited = drafts[field.id];
      const updated = await api.verifyField(
        familyId,
        doc.id,
        field.id,
        edited !== undefined && edited !== field.field_value ? edited : undefined,
      );
      const newFields = doc.fields.map((f) => (f.id === updated.id ? updated : f));
      onChange(newFields);

      // Advance focus to the next field for seamless keyboard flow
      if (nextField) {
        onSelectField?.(nextField);
        inputRefs.current[nextField.id]?.focus();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save that. Try again.");
    } finally {
      setSaving(null);
    }
  }

  async function confirmAllHigh() {
    if (!allHighBand) return;
    setSaving("all");
    setError(null);
    // Save snapshot in memory for undo
    setUndoSnapshot([...doc.fields]);

    try {
      const updatedList = await Promise.all(
        pending.map((field) =>
          api.verifyField(
            familyId,
            doc.id,
            field.id,
            drafts[field.id] !== undefined && drafts[field.id] !== field.field_value
              ? drafts[field.id]
              : undefined,
          ),
        ),
      );
      const updatedMap = new Map(updatedList.map((f) => [f.id, f]));
      onChange(doc.fields.map((f) => updatedMap.get(f.id) ?? f));
      setUndoToastVisible(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't confirm all. Try individual fields.");
      setUndoSnapshot(null);
    } finally {
      setSaving(null);
    }
  }

  function handleUndo() {
    if (undoSnapshot) {
      onChange(undoSnapshot);
      setUndoSnapshot(null);
      setUndoToastVisible(false);
    }
  }

  if (pending.length === 0) {
    return (
      <section className="rounded-xl border border-stone-200 bg-white p-8 text-center shadow-sm">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
          <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h2 className="mt-4 text-lg font-semibold text-stone-900">
          Everything on this document is confirmed
        </h2>
        <p className="mt-2 text-sm text-stone-600">
          All details have been human-verified and now count as trusted family data.
        </p>

        {undoToastVisible && undoSnapshot && (
          <div className="mt-4 inline-flex items-center gap-3 rounded-lg border border-stone-200 bg-stone-50 px-4 py-2 text-sm">
            <span>Confirmed {undoSnapshot.filter((f) => f.verification === "unverified").length} fields.</span>
            <button
              onClick={handleUndo}
              className="font-medium text-indigo-600 hover:text-indigo-800 underline"
            >
              Undo
            </button>
          </div>
        )}

        <div className="mt-6 flex flex-wrap justify-center gap-3">
          <a
            href={`/families/${familyId}/deadlines`}
            className="rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white hover:bg-stone-800"
          >
            Check deadlines
          </a>
          <a
            href={`/families/${familyId}/vault`}
            className="rounded-lg border border-stone-300 bg-white px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50"
          >
            Return to Vault
          </a>
        </div>
      </section>
    );
  }

  return (
    <section className="flex flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-200 pb-4">
        <div>
          <h2 className="text-lg font-semibold text-stone-900">
            {pending.length} {pending.length === 1 ? "detail" : "details"} to confirm
          </h2>
          <p className="mt-0.5 text-xs text-stone-500">
            Press <kbd className="rounded border border-stone-300 bg-stone-100 px-1.5 py-0.5 text-xs">Enter</kbd> to confirm and jump to the next field.
          </p>
        </div>

        {allHighBand && (
          <button
            onClick={confirmAllHigh}
            disabled={saving === "all"}
            className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-emerald-800 disabled:opacity-50"
          >
            {saving === "all" ? "Confirming all…" : "Confirm all (100% match)"}
          </button>
        )}
      </div>

      {undoToastVisible && undoSnapshot && (
        <div className="mt-3 flex items-center justify-between rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-sm text-emerald-900">
          <span>All high-confidence fields confirmed.</span>
          <button
            onClick={handleUndo}
            className="font-medium text-emerald-800 underline hover:text-emerald-950"
          >
            Undo
          </button>
        </div>
      )}

      {error && (
        <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          {error}
        </div>
      )}

      <ul className="mt-4 space-y-3">
        {pending.map((field, idx) => {
          const isSelected = selectedFieldId === field.id;
          const nextField = pending[idx + 1];
          const cfg = bandConfig[field.band];

          return (
            <li
              key={field.id}
              onClick={() => onSelectField?.(field)}
              className={`cursor-pointer rounded-xl border p-4 transition-all duration-150 ${
                cfg.cardClass
              } ${isSelected ? "ring-2 ring-stone-900 border-transparent shadow-md bg-white" : "bg-white/80"}`}
            >
              <div className="flex items-center justify-between gap-3">
                <label
                  htmlFor={field.id}
                  className="font-medium text-stone-900 cursor-pointer"
                >
                  {field.label}
                </label>
                <span
                  className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${cfg.badgeClass}`}
                >
                  {cfg.label}
                  {field.confidence !== null && ` · ${Math.round(field.confidence * 100)}%`}
                </span>
              </div>

              <div className="mt-2.5">
                <input
                  ref={(el) => {
                    inputRefs.current[field.id] = el;
                  }}
                  id={field.id}
                  className={`w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-stone-900 placeholder-stone-400 focus:outline-none focus:ring-2 ${cfg.inputBorder}`}
                  value={drafts[field.id] ?? field.field_value ?? ""}
                  onChange={(e) => setDrafts({ ...drafts, [field.id]: e.target.value })}
                  onFocus={() => onSelectField?.(field)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      confirm(field, nextField);
                    }
                  }}
                />
              </div>

              {field.source_snippet && (
                <p className="mt-2 text-xs text-stone-500">
                  <span className="font-medium text-stone-600">
                    Page {field.source_page ?? 1}:
                  </span>{" "}
                  “{field.source_snippet}”
                </p>
              )}

              <div className="mt-3 flex items-center justify-between">
                <span className="text-[11px] text-stone-400">
                  {field.source_bbox ? "📍 Box highlighted on page" : "Page text"}
                </span>

                <button
                  type="button"
                  className="rounded-lg bg-stone-900 px-3.5 py-1.5 text-xs font-medium text-white transition hover:bg-stone-800 disabled:opacity-50"
                  disabled={saving === field.id}
                  onClick={(e) => {
                    e.stopPropagation();
                    confirm(field, nextField);
                  }}
                >
                  {saving === field.id ? "Saving…" : "Confirm ↵"}
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
