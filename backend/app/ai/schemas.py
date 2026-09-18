"""Per-category extraction schemas. Extend these instead of editing prompts."""
from __future__ import annotations

FIELD_SCHEMAS: dict[str, dict[str, dict]] = {
    "insurance": {
        "insurer_name":     {"type": "string", "label": "Insurer"},
        "policy_number":    {"type": "string", "label": "Policy number"},
        "policy_type":      {"type": "string", "label": "Policy type"},
        "policyholder_name": {"type": "string", "label": "Policyholder"},
        "nominee_name":     {"type": "string", "label": "Nominee"},
        "sum_assured":      {"type": "amount", "label": "Sum assured"},
        "premium_amount":   {"type": "amount", "label": "Premium"},
        "premium_frequency": {"type": "string", "label": "Premium frequency"},
        "start_date":       {"type": "date", "label": "Start date"},
        "expiry_date":      {"type": "date", "label": "Expiry date", "deadline": True},
        "next_premium_date": {"type": "date", "label": "Next premium due", "deadline": True},
    },
    "property": {
        "document_kind":    {"type": "string", "label": "Document kind"},
        "recorded_holder":  {"type": "string", "label": "Recorded holder"},
        "survey_number":    {"type": "string", "label": "Survey number"},
        "plot_number":      {"type": "string", "label": "Plot number"},
        "khata_number":     {"type": "string", "label": "Khata number"},
        "area_value":       {"type": "number", "label": "Area"},
        "area_unit":        {"type": "string", "label": "Area unit"},
        "village_locality": {"type": "string", "label": "Village or locality"},
        "district":         {"type": "string", "label": "District"},
        "state":            {"type": "string", "label": "State"},
        "registration_date": {"type": "date", "label": "Registration date"},
        "registration_number": {"type": "string", "label": "Registration number"},
        "consideration_amount": {"type": "amount", "label": "Consideration amount"},
    },
    "vehicle": {
        "registration_number": {"type": "string", "label": "Registration number"},
        "owner_name":       {"type": "string", "label": "Owner"},
        "make_model":       {"type": "string", "label": "Make and model"},
        "chassis_number":   {"type": "string", "label": "Chassis number"},
        "engine_number":    {"type": "string", "label": "Engine number"},
        "registration_date": {"type": "date", "label": "Registration date"},
        "fitness_expiry_date": {"type": "date", "label": "Fitness expiry", "deadline": True},
        "insurance_expiry_date": {"type": "date", "label": "Insurance expiry", "deadline": True},
        "puc_expiry_date":  {"type": "date", "label": "PUC expiry", "deadline": True},
    },
    "financial": {
        "institution_name": {"type": "string", "label": "Institution"},
        "account_type":     {"type": "string", "label": "Account type"},
        "account_last4":    {"type": "string", "label": "Account (last 4)"},
        "holder_name":      {"type": "string", "label": "Holder"},
        "nominee_name":     {"type": "string", "label": "Nominee"},
        "balance_or_value": {"type": "amount", "label": "Balance or value"},
        "statement_date":   {"type": "date", "label": "Statement date"},
        "maturity_date":    {"type": "date", "label": "Maturity date", "deadline": True},
    },
    "government_id": {
        "id_type":          {"type": "string", "label": "ID type"},
        "holder_name":      {"type": "string", "label": "Name"},
        "id_last4":         {"type": "string", "label": "ID (last 4)"},
        "date_of_birth":    {"type": "date", "label": "Date of birth"},
        "issue_date":       {"type": "date", "label": "Issue date"},
        "expiry_date":      {"type": "date", "label": "Expiry date", "deadline": True},
    },
    "tax": {
        "assessment_year":  {"type": "string", "label": "Assessment year"},
        "pan_last4":        {"type": "string", "label": "PAN (last 4)"},
        "total_income":     {"type": "amount", "label": "Total income"},
        "tax_paid":         {"type": "amount", "label": "Tax paid"},
        "filing_date":      {"type": "date", "label": "Filing date"},
        "due_date":         {"type": "date", "label": "Due date", "deadline": True},
    },
    "utility": {
        "provider_name":    {"type": "string", "label": "Provider"},
        "consumer_number":  {"type": "string", "label": "Consumer number"},
        "billing_period":   {"type": "string", "label": "Billing period"},
        "amount_due":       {"type": "amount", "label": "Amount due"},
        "due_date":         {"type": "date", "label": "Due date", "deadline": True},
    },
    "legal_agreement": {
        "agreement_type":   {"type": "string", "label": "Agreement type"},
        "parties":          {"type": "string", "label": "Parties"},
        "effective_date":   {"type": "date", "label": "Effective date"},
        "end_date":         {"type": "date", "label": "End date", "deadline": True},
        "renewal_notice_days": {"type": "number", "label": "Renewal notice period"},
    },
}

GENERIC = {
    "document_title": {"type": "string", "label": "Title"},
    "issuer":         {"type": "string", "label": "Issued by"},
    "person_named":   {"type": "string", "label": "Person named"},
    "document_date":  {"type": "date", "label": "Document date"},
    "any_expiry_date": {"type": "date", "label": "Expiry date", "deadline": True},
}


def for_category(category: str) -> dict:
    return FIELD_SCHEMAS.get(category, GENERIC)


def type_of(category: str, key: str) -> str:
    return for_category(category).get(key, {}).get("type", "string")


def label_for(key: str) -> str:
    for schema in (*FIELD_SCHEMAS.values(), GENERIC):
        if key in schema:
            return schema[key]["label"]
    return key.replace("_", " ").capitalize()


def deadline_keys(category: str) -> list[str]:
    return [k for k, v in for_category(category).items() if v.get("deadline")]


# Mappings from extracted_fields keys to Property / Asset model columns (P4.1)
PROPERTY_MAPPINGS: dict[str, str] = {
    "survey_number": "survey_number",
    "plot_number": "plot_number",
    "khata_number": "khata_number",
    "village_locality": "village_locality",
    "district": "district",
    "state": "state",
    "area_value": "area_value",
    "area_unit": "area_unit",
    "recorded_holder": "recorded_holder",
    "consideration_amount": "value_estimate",
    "document_kind": "type",
    "property_identifier": "label",
}

ASSET_MAPPINGS: dict[str, str] = {
    "insurer_name": "institution",
    "policy_number": "identifier_last4",
    "sum_assured": "value_estimate",
    "policyholder_name": "notes",
    "institution_name": "institution",
    "account_last4": "identifier_last4",
    "account_or_deposit_number": "identifier_last4",
    "balance_or_value": "value_estimate",
    "deposit_amount": "value_estimate",
    "registration_number": "identifier_last4",
    "make_model": "name",
    "asset_name": "name",
}


def get_column_mapping(target: str) -> dict[str, str]:
    if target == "property":
        return PROPERTY_MAPPINGS
    elif target == "asset":
        return ASSET_MAPPINGS
    return {}

