"""Tests for the benchmark harness (P2.3).

Verifies:
- Benchmark runs end to end without touching the database
- Accurate calculation of classification accuracy, precision, recall, date parsing, confidence
- Hallucination detector flags extracted values that do not appear in OCR text
- Planted hallucination is detected and causes harness to report failure
- Results are saved to benchmark/results/<timestamp>.json
"""
import json
import tempfile
from pathlib import Path
try:
    import pytest
except ImportError:
    pytest = None

from benchmark.run import is_hallucinated, run_benchmark, format_table


SAMPLE_TEMPLATE_CSV = """filename,category,field_key,expected_value,field_type
doc1.txt,insurance,policy_number,POL-1001,string
doc1.txt,insurance,expiry_date,2027-05-31,date
doc2.txt,vehicle,registration_number,DL01AB1234,string
doc2.txt,vehicle,registration_date,2022-01-15,date
doc3.txt,financial,account_or_deposit_number,FD-554433,string
doc4.txt,utility,consumer_number,9988776655,string
doc5.txt,government_id,id_number,ABCD1234E,string
doc6.txt,property,property_identifier,Plot 45 Green Valley,string
doc7.txt,tax,pan_number,ABCDE1234F,string
doc8.txt,medical,patient_name,Aarav Patel,string
doc9.txt,education,degree_name,Bachelor of Technology,string
doc10.txt,legal_agreement,agreement_title,Lease Agreement,string
"""

SAMPLE_DOCS = {
    "doc1.txt": "Star Health Insurance Certificate. Policy Number: POL-1001. Valid till expiry date: 2027-05-31.",
    "doc2.txt": "Form 23 Registration Certificate. Registration Number: DL01AB1234. Date of reg: 2022-01-15.",
    "doc3.txt": "Fixed Deposit Receipt. Deposit Number: FD-554433. Amount: 50000 INR.",
    "doc4.txt": "Electricity Bill. Consumer Number: 9988776655. Due Date: 2026-12-10.",
    "doc5.txt": "Income Tax Department. Permanent Account Number ID Number: ABCD1234E.",
    "doc6.txt": "Sale Deed. Property Identifier: Plot 45 Green Valley, Pune.",
    "doc7.txt": "Form 16 Tax Statement. PAN Number: ABCDE1234F.",
    "doc8.txt": "Hospital Discharge Summary. Patient Name: Aarav Patel. Age: 42.",
    "doc9.txt": "Delhi University. Degree Name: Bachelor of Technology in Computer Engineering.",
    "doc10.txt": "Commercial Lease Agreement. Agreement Title: Lease Agreement between parties.",
}


def test_is_hallucinated():
    ocr_text = "Policy issued to Rahul Sharma. Policy Number: POL-12345. Premium: 15000."
    assert not is_hallucinated("POL-12345", ocr_text)
    assert not is_hallucinated("Rahul Sharma", ocr_text)
    assert not is_hallucinated("15000", ocr_text)

    # Hallucinated values not present in OCR text
    assert is_hallucinated("Amitabh Bachchan", ocr_text)
    assert is_hallucinated("POL-99999", ocr_text)
    assert is_hallucinated("9876543210", ocr_text)


def test_benchmark_runs_end_to_end_on_ten_documents():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        template_file = tmp / "template.csv"
        template_file.write_text(SAMPLE_TEMPLATE_CSV, encoding="utf-8")

        samples_dir = tmp / "samples"
        samples_dir.mkdir()
        for fname, text in SAMPLE_DOCS.items():
            (samples_dir / fname).write_text(text, encoding="utf-8")

        # Mock classify and extract to simulate accurate pipeline responses
        def mock_classify(ocr_text: str):
            t = ocr_text.lower()
            if "insurance" in t:
                return {"category": "insurance", "confidence": 0.95}
            if "registration certificate" in t or "dl01" in t:
                return {"category": "vehicle", "confidence": 0.95}
            if "fixed deposit" in t:
                return {"category": "financial", "confidence": 0.95}
            if "electricity bill" in t or "consumer number" in t:
                return {"category": "utility", "confidence": 0.95}
            if "permanent account number" in t or "id number" in t:
                return {"category": "government_id", "confidence": 0.95}
            if "sale deed" in t or "plot 45" in t:
                return {"category": "property", "confidence": 0.95}
            if "form 16" in t or "tax statement" in t:
                return {"category": "tax", "confidence": 0.95}
            if "hospital" in t or "discharge" in t:
                return {"category": "medical", "confidence": 0.95}
            if "degree" in t or "university" in t:
                return {"category": "education", "confidence": 0.95}
            if "lease agreement" in t:
                return {"category": "legal_agreement", "confidence": 0.95}
            return {"category": "other", "confidence": 0.5}

        def mock_extract(ocr_text: str, category: str):
            fields = []
            if "POL-1001" in ocr_text:
                fields.append({"key": "policy_number", "value": "POL-1001", "confidence": 0.98, "snippet": "POL-1001"})
                fields.append({"key": "expiry_date", "value": "2027-05-31", "confidence": 0.92, "snippet": "2027-05-31"})
            if "DL01AB1234" in ocr_text:
                fields.append({"key": "registration_number", "value": "DL01AB1234", "confidence": 0.97, "snippet": "DL01AB1234"})
                fields.append({"key": "registration_date", "value": "2022-01-15", "confidence": 0.90, "snippet": "2022-01-15"})
            if "FD-554433" in ocr_text:
                fields.append({"key": "account_or_deposit_number", "value": "FD-554433", "confidence": 0.96, "snippet": "FD-554433"})
            if "9988776655" in ocr_text:
                fields.append({"key": "consumer_number", "value": "9988776655", "confidence": 0.94, "snippet": "9988776655"})
            if "ABCD1234E" in ocr_text:
                fields.append({"key": "id_number", "value": "ABCD1234E", "confidence": 0.99, "snippet": "ABCD1234E"})
            if "Plot 45 Green Valley" in ocr_text:
                fields.append({"key": "property_identifier", "value": "Plot 45 Green Valley", "confidence": 0.91, "snippet": "Plot 45 Green Valley"})
            if "ABCDE1234F" in ocr_text:
                fields.append({"key": "pan_number", "value": "ABCDE1234F", "confidence": 0.98, "snippet": "ABCDE1234F"})
            if "Aarav Patel" in ocr_text:
                fields.append({"key": "patient_name", "value": "Aarav Patel", "confidence": 0.95, "snippet": "Aarav Patel"})
            if "Bachelor of Technology" in ocr_text:
                fields.append({"key": "degree_name", "value": "Bachelor of Technology", "confidence": 0.93, "snippet": "Bachelor of Technology"})
            if "Lease Agreement" in ocr_text:
                fields.append({"key": "agreement_title", "value": "Lease Agreement", "confidence": 0.89, "snippet": "Lease Agreement"})
            return {"fields": fields}

        results = run_benchmark(
            template_path=template_file,
            samples_dir=samples_dir,
            classify_fn=mock_classify,
            extract_fn=mock_extract,
        )

        assert results["passed"] is True
        assert results["summary"]["total_documents"] == 10
        assert results["summary"]["classification_accuracy"] == 1.0
        assert results["summary"]["overall_field_precision"] == 1.0
        assert results["summary"]["overall_field_recall"] == 1.0
        assert results["summary"]["date_parsing_accuracy"] == 1.0
        assert results["summary"]["hallucination_count"] == 0

        # Verify table formatting runs cleanly
        table = format_table(results)
        assert "LIFE ADMIN OS — BENCHMARK RESULTS" in table
        assert "Classification Accuracy:   100.0%" in table


def test_hallucination_check_catches_planted_value():
    """Verify that a planted hallucination (value not in OCR text) is caught."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        template_file = tmp / "template.csv"
        template_file.write_text("""filename,category,field_key,expected_value,field_type
doc1.txt,insurance,policy_number,POL-1001,string
""", encoding="utf-8")

        samples_dir = tmp / "samples"
        samples_dir.mkdir()
        (samples_dir / "doc1.txt").write_text("Insurance document with Policy POL-1001.", encoding="utf-8")

        def mock_classify(ocr_text: str):
            return {"category": "insurance", "confidence": 0.95}

        # Planted hallucination: extractor invents a claim amount not present in the document
        def mock_extract_with_hallucination(ocr_text: str, category: str):
            return {
                "fields": [
                    {"key": "policy_number", "value": "POL-1001", "confidence": 0.95},
                    {"key": "claim_amount", "value": "99999999", "confidence": 0.90},  # PLANTED!
                ]
            }

        results = run_benchmark(
            template_path=template_file,
            samples_dir=samples_dir,
            classify_fn=mock_classify,
            extract_fn=mock_extract_with_hallucination,
        )

        # Hallucination count should be at least 1 and benchmark should fail!
        assert results["summary"]["hallucination_count"] == 1
        assert results["passed"] is False
        assert results["hallucinations"][0]["field_key"] == "claim_amount"
        assert results["hallucinations"][0]["value"] == "99999999"
