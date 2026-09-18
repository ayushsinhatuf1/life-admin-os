# Life Admin OS — Access Control Matrix

**Document Version:** 1.0  
**Scope:** Complete HTTP API Surface (`/api/v1/`)  
**Roles & Trust Levels:**
- `anon`: Unauthenticated caller (no Bearer token or invalid token)
- `cross_family`: Authenticated user, but **not** a member of the target `{family_id}`
- `viewer` (Level 0): Read-only member
- `contributor` (Level 1): Can upload documents, verify fields, promote records, and modify deadlines
- `admin` (Level 2): Can manage members, send invitations, and delete records/documents
- `owner` (Level 3): Family creator, full administrative control

> [!IMPORTANT]
> **Tenancy Enumeration Protection Rule:**
> When a caller is authenticated but does not belong to `{family_id}`, every family-scoped endpoint MUST return `404 Not Found`, **never** `403 Forbidden`. This guarantees an attacker cannot discover valid family UUIDs or resource existence.

---

## Access Control Matrix Table

| Endpoint | Method | Min Access | Anonymous (`anon`) | Cross-Family (`other`) | `viewer` | `contributor` | `admin` | `owner` |
|---|---|---|---|---|---|---|---|---|
| `/api/v1/auth/register` | POST | None | 201 | 201 | 201 | 201 | 201 | 201 |
| `/api/v1/auth/login` | POST | None | 200 | 200 | 200 | 200 | 200 | 200 |
| `/api/v1/auth/refresh` | POST | None | 200 | 200 | 200 | 200 | 200 | 200 |
| `/api/v1/auth/logout` | POST | None | 200 | 200 | 200 | 200 | 200 | 200 |
| `/api/v1/invites/{token}/accept` | POST | Authenticated | 401 | 200 | 200 | 200 | 200 | 200 |
| `/api/v1/families/{family_id}/members` | GET | `viewer` | 401 | 404 | 200 | 200 | 200 | 200 |
| `/api/v1/families/{family_id}/members` | POST | `admin` | 401 | 404 | 403 | 403 | 201 | 201 |
| `/api/v1/families/{family_id}/graph` | GET | `viewer` | 401 | 404 | 200 | 200 | 200 | 200 |
| `/api/v1/families/{family_id}/readiness` | GET | `viewer` | 401 | 404 | 200 | 200 | 200 | 200 |
| `/api/v1/families/{family_id}/assets` | GET | `viewer` | 401 | 404 | 200 | 200 | 200 | 200 |
| `/api/v1/families/{family_id}/assets` | POST | `contributor` | 401 | 404 | 403 | 201 | 201 | 201 |
| `/api/v1/families/{family_id}/properties` | GET | `viewer` | 401 | 404 | 200 | 200 | 200 | 200 |
| `/api/v1/families/{family_id}/properties` | POST | `contributor` | 401 | 404 | 403 | 201 | 201 | 201 |
| `/api/v1/families/{family_id}/documents` | GET | `viewer` | 401 | 404 | 200 | 200 | 200 | 200 |
| `/api/v1/families/{family_id}/documents` | POST | `contributor` | 401 | 404 | 403 | 201 | 201 | 201 |
| `/api/v1/families/{family_id}/documents/{id}` | GET | `viewer` | 401 | 404 | 200 | 200 | 200 | 200 |
| `/api/v1/families/{family_id}/documents/{id}` | DELETE | `admin` | 401 | 404 | 403 | 403 | 200 | 200 |
| `/api/v1/families/{family_id}/documents/{id}/file` | GET | `viewer` | 401 | 404 | 200 | 200 | 200 | 200 |
| `/api/v1/families/{family_id}/documents/{id}/pages/{n}` | GET | `viewer` | 401 | 404 | 200 | 200 | 200 | 200 |
| `/api/v1/families/{family_id}/documents/{id}/fields/{fid}/verify` | POST | `contributor` | 401 | 404 | 403 | 200 | 200 | 200 |
| `/api/v1/families/{family_id}/documents/{id}/promote` | POST | `contributor` | 401 | 404 | 403 | 200 | 200 | 200 |
| `/api/v1/families/{family_id}/deadlines` | GET | `viewer` | 401 | 404 | 200 | 200 | 200 | 200 |
| `/api/v1/families/{family_id}/deadlines` | POST | `contributor` | 401 | 404 | 403 | 201 | 201 | 201 |
| `/api/v1/families/{family_id}/deadlines/{id}/complete` | POST | `contributor` | 401 | 404 | 403 | 200 | 200 | 200 |
| `/api/v1/families/{family_id}/deadlines/{id}/snooze` | POST | `contributor` | 401 | 404 | 403 | 200 | 200 | 200 |
| `/api/v1/families/{family_id}/deadlines/preferences` | GET | `viewer` | 401 | 404 | 200 | 200 | 200 | 200 |
| `/api/v1/families/{family_id}/deadlines/preferences` | PUT | `viewer` | 401 | 404 | 200 | 200 | 200 | 200 |
| `/api/v1/families/{family_id}/assistant/ask` | POST | `viewer` | 401 | 404 | 200 | 200 | 200 | 200 |
| `/api/v1/families/{family_id}/assistant/stream` | POST | `viewer` | 401 | 404 | 200 | 200 | 200 | 200 |

---

## Verification & Automated Testing

This matrix is executable and maintained by the automated test suite in [`tests/test_access_control_matrix.py`](file:///c:/Users/ayush/OneDrive/Desktop/life-admin-os/life-admin-os/life-admin-os/tests/test_access_control_matrix.py).

The test suite systematically iterates through each cell of the matrix, confirming:
1. Anonymous requests to protected resources return `401`.
2. Cross-family requests to valid resources return `404` (never leaking `403` or resource existence).
3. In-family requests with insufficient privilege level return `403` with a descriptive message.
4. In-family requests meeting or exceeding `minimum_access` execute with appropriate `200` or `201` status.
