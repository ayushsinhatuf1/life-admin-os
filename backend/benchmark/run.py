"""Benchmark harness for document classification and field extraction (P2.3).

Measures:
- Classification accuracy (target: >= 0.85)
- Per-field precision and recall
- Date-parsing accuracy
- Mean confidence for correct vs incorrect values
- Hallucination count (fields returned with a value not in the OCR text; target: 0)

Runs completely without touching the database.
Exits with status 0 if accuracy >= 0.85 and hallucinations == 0; non-zero otherwise.
Results are saved to benchmark/results/<timestamp>.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Add backend directory to sys.path so app imports work
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))



def _clean(text: str | None) -> str:
    """Normalize text by lowercasing and removing punctuation/whitespace for comparison."""
    if not text:
        return ""
    return re.sub(r"[^\w]", "", text.lower())


def is_hallucinated(value: str | None, ocr_text: str) -> bool:
    """Check if a non-empty extracted value does not appear anywhere in the OCR text.
    
    A hallucination is any extracted value that has no substring match in the text,
    ignoring case and whitespace/punctuation.
    """
    if not value:
        return False
    val_clean = _clean(value)
    if not val_clean:
        return False
    # If the clean value is contained in the clean OCR text, it is grounded.
    ocr_clean = _clean(ocr_text)
    return val_clean not in ocr_clean


def load_benchmark_template(csv_path: Path) -> dict[str, dict[str, Any]]:
    """Load benchmark ground truth template CSV.
    
    Returns:
        Dict mapping filename to:
        {
            "category": str,
            "fields": {
                field_key: {
                    "expected_value": str,
                    "field_type": str,
                }
            }
        }
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"Benchmark template CSV not found at: {csv_path}")

    docs: dict[str, dict[str, Any]] = {}
    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            filename = row["filename"].strip()
            category = row["category"].strip()
            field_key = row["field_key"].strip()
            expected_val = row["expected_value"].strip()
            field_type = row.get("field_type", "string").strip()

            if filename not in docs:
                docs[filename] = {"category": category, "fields": {}}
            docs[filename]["fields"][field_key] = {
                "expected_value": expected_val,
                "field_type": field_type,
            }
    return docs


def extract_document_text(file_path: Path) -> tuple[str, int]:
    """Extract OCR text and page count from a file on disk."""
    if not file_path.exists():
        raise FileNotFoundError(f"Document file not found: {file_path}")

    suffix = file_path.suffix.lower()
    if suffix == ".txt":
        text = file_path.read_text(encoding="utf-8")
        return text, 1

    mime_type, _ = mimetypes.guess_type(str(file_path))
    if suffix == ".pdf":
        mime_type = "application/pdf"
    elif suffix in (".png", ".jpg", ".jpeg"):
        mime_type = mime_type or "image/png"
    else:
        mime_type = mime_type or "application/octet-stream"

    data = file_path.read_bytes()
    from app.ai import pipeline
    return pipeline.extract_text(data, mime_type)


def run_benchmark(
    template_path: Path,
    samples_dir: Path,
    classify_fn: Callable[[str], dict] | None = None,
    extract_fn: Callable[[str, str], dict] | None = None,
) -> dict[str, Any]:
    """Run benchmark over all documents in template and compute evaluation metrics."""
    if classify_fn is None or extract_fn is None:
        from app.ai import pipeline
        classify_func = classify_fn or pipeline.classify
        extract_func = extract_fn or pipeline.extract
    else:
        classify_func = classify_fn
        extract_func = extract_fn

    ground_truth = load_benchmark_template(template_path)
    if not ground_truth:
        raise ValueError(f"No documents defined in {template_path}")

    total_docs = len(ground_truth)
    correct_categories = 0
    hallucinations = []

    # Per field TP / FP / FN
    field_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    correct_confidences: list[float] = []
    incorrect_confidences: list[float] = []

    total_expected_dates = 0
    correct_dates = 0

    doc_results = []

    for filename, gt in ground_truth.items():
        doc_path = samples_dir / filename
        expected_category = gt["category"]
        expected_fields = gt["fields"]

        # If sample document doesn't exist, check for text representation
        if not doc_path.exists():
            txt_path = samples_dir / f"{filename}.txt"
            if txt_path.exists():
                doc_path = txt_path
            else:
                raise FileNotFoundError(f"Sample file {filename} not found in {samples_dir}")

        ocr_text, page_count = extract_document_text(doc_path)

        # 1. Classification
        classification = classify_func(ocr_text)
        predicted_category = classification.get("category")
        category_conf = classification.get("confidence", 0.0)

        is_cat_correct = predicted_category == expected_category
        if is_cat_correct:
            correct_categories += 1

        # 2. Extraction (using predicted category or expected category for schema)
        extraction = extract_func(ocr_text, predicted_category or expected_category)
        extracted_items = extraction.get("fields", [])

        extracted_map: dict[str, dict[str, Any]] = {}
        for item in extracted_items:
            k = item.get("key")
            if k:
                extracted_map[k] = item

        # Evaluate fields
        doc_hallucinations = []
        doc_field_eval = {}

        # Check extracted fields
        for field_key, item in extracted_map.items():
            val = item.get("value")
            conf = item.get("confidence")
            if conf is not None:
                try:
                    conf_val = float(conf)
                except (ValueError, TypeError):
                    conf_val = 0.0
            else:
                conf_val = 0.0

            # Hallucination check against OCR text
            if is_hallucinated(val, ocr_text):
                hallucination_info = {
                    "filename": filename,
                    "field_key": field_key,
                    "value": val,
                    "snippet": item.get("snippet"),
                }
                hallucinations.append(hallucination_info)
                doc_hallucinations.append(hallucination_info)

            # Compare with ground truth
            if field_key in expected_fields:
                exp_val = expected_fields[field_key]["expected_value"]
                exp_type = expected_fields[field_key].get("field_type", "string")

                is_match = _clean(val) == _clean(exp_val)
                if is_match:
                    field_stats[field_key]["tp"] += 1
                    correct_confidences.append(conf_val)

                    if exp_type == "date" or field_key.endswith("_date"):
                        # Check valid date pattern YYYY-MM-DD
                        if val and re.match(r"^\d{4}-\d{2}-\d{2}", val.strip()):
                            correct_dates += 1
                else:
                    field_stats[field_key]["fp"] += 1
                    incorrect_confidences.append(conf_val)

                doc_field_eval[field_key] = {
                    "extracted": val,
                    "expected": exp_val,
                    "match": is_match,
                    "confidence": conf_val,
                }
            else:
                # Spurious field not in ground truth
                field_stats[field_key]["fp"] += 1
                incorrect_confidences.append(conf_val)
                doc_field_eval[field_key] = {
                    "extracted": val,
                    "expected": None,
                    "match": False,
                    "confidence": conf_val,
                }

        # Check for missed fields (False Negatives)
        for exp_key, exp_info in expected_fields.items():
            if exp_info.get("field_type") == "date" or exp_key.endswith("_date"):
                total_expected_dates += 1

            if exp_key not in extracted_map:
                field_stats[exp_key]["fn"] += 1
                doc_field_eval[exp_key] = {
                    "extracted": None,
                    "expected": exp_info["expected_value"],
                    "match": False,
                    "confidence": 0.0,
                }

        doc_results.append({
            "filename": filename,
            "category": {
                "expected": expected_category,
                "predicted": predicted_category,
                "correct": is_cat_correct,
                "confidence": category_conf,
            },
            "fields": doc_field_eval,
            "hallucinations": doc_hallucinations,
        })

    # Aggregate metrics
    cat_accuracy = correct_categories / total_docs if total_docs > 0 else 0.0
    date_accuracy = correct_dates / total_expected_dates if total_expected_dates > 0 else 1.0

    mean_conf_correct = (
        sum(correct_confidences) / len(correct_confidences) if correct_confidences else 0.0
    )
    mean_conf_incorrect = (
        sum(incorrect_confidences) / len(incorrect_confidences) if incorrect_confidences else 0.0
    )

    per_field_metrics = {}
    total_tp = 0
    total_fp = 0
    total_fn = 0

    for f_key, counts in sorted(field_stats.items()):
        tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
        total_tp += tp
        total_fp += fp
        total_fn += fn
        p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * p * r) / (p + r) if (p + r) > 0 else 0.0
        per_field_metrics[f_key] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(f1, 4),
        }

    overall_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    overall_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0

    hallucination_count = len(hallucinations)
    passed = cat_accuracy >= 0.85 and hallucination_count == 0

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "summary": {
            "total_documents": total_docs,
            "classification_accuracy": round(cat_accuracy, 4),
            "target_classification_accuracy": 0.85,
            "overall_field_precision": round(overall_precision, 4),
            "overall_field_recall": round(overall_recall, 4),
            "date_parsing_accuracy": round(date_accuracy, 4),
            "mean_confidence_correct": round(mean_conf_correct, 4),
            "mean_confidence_incorrect": round(mean_conf_incorrect, 4),
            "hallucination_count": hallucination_count,
            "target_hallucination_count": 0,
        },
        "per_field_metrics": per_field_metrics,
        "hallucinations": hallucinations,
        "documents": doc_results,
    }


def format_table(results: dict[str, Any]) -> str:
    """Format benchmark results as a human-readable table."""
    s = results["summary"]
    lines = []
    lines.append("=" * 72)
    lines.append("                   LIFE ADMIN OS — BENCHMARK RESULTS")
    lines.append("=" * 72)
    lines.append(f"Timestamp:                 {results['timestamp']}")
    lines.append(f"Status:                    {'✅ PASSED' if results['passed'] else '❌ FAILED'}")
    lines.append("-" * 72)
    lines.append(f"Total Documents:           {s['total_documents']}")
    cat_status = "✅" if s["classification_accuracy"] >= s["target_classification_accuracy"] else "❌"
    lines.append(f"Classification Accuracy:   {s['classification_accuracy'] * 100:.1f}% (target >= {s['target_classification_accuracy'] * 100:.0f}%) {cat_status}")
    lines.append(f"Overall Field Precision:   {s['overall_field_precision'] * 100:.1f}%")
    lines.append(f"Overall Field Recall:      {s['overall_field_recall'] * 100:.1f}%")
    lines.append(f"Date Parsing Accuracy:     {s['date_parsing_accuracy'] * 100:.1f}%")
    lines.append(f"Mean Conf (Correct):       {s['mean_confidence_correct']:.3f}")
    lines.append(f"Mean Conf (Incorrect):     {s['mean_confidence_incorrect']:.3f}")
    hal_status = "✅" if s["hallucination_count"] == 0 else "❌"
    lines.append(f"Hallucination Count:       {s['hallucination_count']} (target: 0) {hal_status}")
    lines.append("-" * 72)

    lines.append(f"{'Field Key':<28} | {'Prec':<6} | {'Recall':<6} | {'F1':<6} | {'TP/FP/FN'}")
    lines.append("-" * 72)
    for f_key, m in results["per_field_metrics"].items():
        counts = f"{m['tp']}/{m['fp']}/{m['fn']}"
        lines.append(f"{f_key:<28} | {m['precision']*100:>5.1f}% | {m['recall']*100:>5.1f}% | {m['f1']*100:>5.1f}% | {counts}")

    if results["hallucinations"]:
        lines.append("-" * 72)
        lines.append("🚨 HALLUCINATIONS DETECTED:")
        for h in results["hallucinations"]:
            lines.append(f"  • [{h['filename']}] {h['field_key']}: '{h['value']}' not found in OCR text")

    lines.append("=" * 72)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Life Admin OS Document Benchmark Harness")
    parser.add_argument(
        "--template",
        type=Path,
        default=None,
        help="Path to benchmark_template.csv",
    )
    parser.add_argument(
        "--samples-dir",
        type=Path,
        default=None,
        help="Path to directory containing sample documents",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Path to results directory",
    )
    args = parser.parse_args()

    repo_root = backend_dir.parent
    template = args.template
    if template is None:
        cand1 = repo_root / "ai" / "benchmark_template.csv"
        cand2 = backend_dir / "ai" / "benchmark_template.csv"
        template = cand1 if cand1.exists() else cand2

    samples_dir = args.samples_dir
    if samples_dir is None:
        cand1 = repo_root / "ai" / "samples"
        cand2 = backend_dir / "benchmark" / "samples"
        samples_dir = cand1 if cand1.exists() else cand2

    output_dir = args.output_dir
    if output_dir is None:
        output_dir = backend_dir / "benchmark" / "results"

    output_dir.mkdir(parents=True, exist_ok=True)

    results = run_benchmark(template, samples_dir)

    # Print table
    print(format_table(results))

    # Write JSON
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_file = output_dir / f"{ts}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved benchmark results to: {out_file}")

    # Exit non-zero if failed
    if not results["passed"]:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
